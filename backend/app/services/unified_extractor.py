"""
Unified Extractor - 统一的 Snippets + Entities + Relations 提取服务

核心改进：
1. 一次 LLM 调用同时提取 snippets + entities + relations
2. 每个 snippet 都有 subject 归属（谁的成就）
3. 每个 entity 都有 identity（身份/title）和与申请人的关系
4. 保留完整文档上下文，避免碎片化

流程：
1. 每个 exhibit 调用一次 LLM 提取
2. 所有 exhibit 完成后进行实体合并
3. 用户确认合并后生成最终关系图
"""

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..core.atomic_io import write_json
from ..core.config import settings
from ..core.prompt_loader import body as _prompt_body
from ..core.prompt_loader import render as _prompt_render
from .llm_client import call_llm
from .snippet_registry import build_registry_from_combined_extraction
from .storage import project_path

logger = logging.getLogger(__name__)

# 数据目录


# ==================== Data Models ====================

@dataclass
class EnhancedSnippet:
    """带有 subject 归属的 snippet"""
    snippet_id: str
    exhibit_id: str
    document_id: str
    text: str
    page: int
    bbox: Optional[Dict]
    block_id: str

    # Subject Attribution
    subject: str                      # 这是谁的成就
    subject_role: str                 # applicant/recommender/colleague/mentor/other
    is_applicant_achievement: bool    # 是否是申请人的成就

    # Evidence Classification
    evidence_type: str                # award/membership/publication/judging/contribution/article/exhibition/leadership/other
    confidence: float
    reasoning: str

    # Metadata
    is_ai_suggested: bool = True
    is_confirmed: bool = False


@dataclass
class Entity:
    """实体：人物、组织、奖项等"""
    id: str
    name: str
    type: str                         # person/organization/award/publication/position/project/event/metric
    identity: str                     # 身份描述，如 "Professor at Stanford"
    relation_to_applicant: str        # self/recommender/mentor/colleague/employer/other

    # References
    snippet_ids: List[str]
    exhibit_ids: List[str]
    mentioned_in_blocks: List[str]

    # For merging
    aliases: List[str] = None
    is_merged: bool = False
    merged_from: List[str] = None


@dataclass
class Relation:
    """实体间的关系"""
    id: str
    from_entity: str                  # entity name
    to_entity: str                    # entity name
    relation_type: str                # recommends/works_at/leads/authored/founded/member_of/received/etc
    context: str                      # 关系上下文
    source_snippet_ids: List[str]
    source_blocks: List[str]


@dataclass
class ExhibitExtraction:
    """单个 exhibit 的提取结果"""
    exhibit_id: str
    extracted_at: str
    applicant_name: str

    # Document summary
    document_type: str
    primary_subject: str
    key_themes: List[str]

    # Extracted data
    snippets: List[Dict]
    entities: List[Dict]
    relations: List[Dict]

    # Stats
    snippet_count: int
    entity_count: int
    relation_count: int


# ==================== LLM Prompts ====================

UNIFIED_EXTRACTION_SYSTEM_PROMPT = _prompt_body("extractor/unified_extraction_system_prompt")

UNIFIED_EXTRACTION_USER_PROMPT = _prompt_body("extractor/unified_extraction_user_prompt")


# ==================== NIW Extraction Prompts ====================

NIW_EXTRACTION_SYSTEM_PROMPT = _prompt_body("extractor/niw_extraction_system_prompt")


NIW_EXTRACTION_USER_PROMPT = _prompt_body("extractor/niw_extraction_user_prompt")


NIW_EXTRACTION_SCHEMA = {
    "type": "object",
    "required": ["document_summary", "snippets", "entities", "relations"],
    "properties": {
        "document_summary": {
            "type": "object",
            "required": ["document_type", "primary_subject", "key_themes"],
            "properties": {
                "document_type": {
                    "type": "string",
                    "description": "Type: resume, recommendation_letter, award_certificate, publication, media_article, research_paper, degree_certificate, other"
                },
                "primary_subject": {
                    "type": "string",
                    "description": "Main person this document is about"
                },
                "key_themes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key themes or topics"
                }
            },
            "additionalProperties": False
        },
        "snippets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["block_id", "text", "subject", "subject_role", "recommender_name", "is_applicant_achievement", "evidence_type", "evidence_purpose", "evidence_layer", "confidence", "reasoning"],
                "properties": {
                    "block_id": {"type": "string"},
                    "text": {"type": "string"},
                    "subject": {"type": "string", "description": "Person whose achievement this is"},
                    "subject_role": {
                        "type": "string",
                        "enum": ["applicant", "recommender", "evaluator", "colleague", "mentor", "peer", "organization", "other"]
                    },
                    "recommender_name": {
                        "type": ["string", "null"],
                        "description": "If from recommendation/evaluation, who is the recommender/evaluator? Use null if not applicable."
                    },
                    "is_applicant_achievement": {"type": "boolean"},
                    "evidence_type": {
                        "type": "string",
                        "description": """Evidence type by Dhanasar prong (use these labels):
Prong 1: endeavor_description, field_impact, national_importance, merit_evidence
Prong 2: education, work_experience, publication, citation_metrics, research_project, recommendation, award, membership, leadership, contribution, quantitative_impact, media_coverage
Prong 3: waiver_justification, national_benefit, beyond_employer, urgency
General: other"""
                    },
                    "evidence_purpose": {
                        "type": "string",
                        "enum": ["direct_proof", "selectivity_proof", "credibility_proof", "impact_proof"],
                        "description": "WHY this evidence matters: direct_proof (applicant qualification), selectivity_proof (proves prestige), credibility_proof (proves source credibility), impact_proof (proves national significance)"
                    },
                    "evidence_layer": {
                        "type": "string",
                        "enum": ["claim", "proof", "significance", "context"],
                        "description": "Evidence pyramid layer: claim (what applicant did), proof (how to prove), significance (why it matters), context (background)"
                    },
                    "confidence": {"type": "number"},
                    "reasoning": {"type": "string"}
                },
                "additionalProperties": False
            }
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "identity", "relation_to_applicant", "mentioned_in_blocks"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["person", "organization", "award", "publication", "position", "project", "event", "metric"]
                    },
                    "identity": {"type": "string", "description": "Role/title/description"},
                    "relation_to_applicant": {
                        "type": "string",
                        "enum": ["self", "recommender", "mentor", "colleague", "employer", "organization", "award_giver", "other"]
                    },
                    "mentioned_in_blocks": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "additionalProperties": False
            }
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["from_entity", "relation_type", "to_entity", "context", "source_blocks"],
                "properties": {
                    "from_entity": {"type": "string"},
                    "relation_type": {"type": "string"},
                    "to_entity": {"type": "string"},
                    "context": {"type": "string"},
                    "source_blocks": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "additionalProperties": False
            }
        }
    },
    "additionalProperties": False
}


UNIFIED_EXTRACTION_SCHEMA = {
    "type": "object",
    "required": ["document_summary", "snippets", "entities", "relations"],
    "properties": {
        "document_summary": {
            "type": "object",
            "required": ["document_type", "primary_subject", "key_themes"],
            "properties": {
                "document_type": {
                    "type": "string",
                    "description": "Type: resume, recommendation_letter, award_certificate, publication, media_article, other"
                },
                "primary_subject": {
                    "type": "string",
                    "description": "Main person this document is about"
                },
                "key_themes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key themes or topics"
                }
            },
            "additionalProperties": False
        },
        "snippets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["block_id", "text", "subject", "subject_role", "recommender_name", "is_applicant_achievement", "evidence_type", "evidence_purpose", "evidence_layer", "confidence", "reasoning"],
                "properties": {
                    "block_id": {"type": "string"},
                    "text": {"type": "string"},
                    "subject": {"type": "string", "description": "Person whose achievement this is"},
                    "subject_role": {
                        "type": "string",
                        "enum": ["applicant", "recommender", "evaluator", "colleague", "mentor", "peer", "organization", "other"]
                    },
                    "recommender_name": {
                        "type": ["string", "null"],
                        "description": "If from recommendation/evaluation, who is the recommender/evaluator? Use null if not applicable."
                    },
                    "is_applicant_achievement": {"type": "boolean"},
                    "evidence_type": {
                        "type": "string",
                        "description": """Evidence type by EB-1A criterion (use these labels for consistency):
(i) award: prizes, awards, honors
(ii) membership, membership_criteria, membership_evaluation, peer_achievement
(iii) media_coverage: articles ABOUT applicant; source_credibility: media credentials
(iv) judging: judge/reviewer of others; peer_assessment: invited peer review
(v) contribution: original contributions; quantitative_impact: metrics (NOT salary); recommendation; scientific_research_project
(vi) publication: scholarly articles AUTHORED BY applicant
(vii) exhibition: display of work at exhibitions
(viii) leadership: leading role IN organization; invitation: invited to speak (NOT leadership)
(ix) salary: applicant's pay; compensation: consulting/contract fees; salary_benchmark: industry averages
(x) commercial_success: box office, sales, revenue data
General: other"""
                    },
                    "evidence_purpose": {
                        "type": "string",
                        "enum": ["direct_proof", "selectivity_proof", "credibility_proof", "impact_proof"],
                        "description": "WHY this evidence matters: direct_proof (applicant achievement), selectivity_proof (proves selectivity), credibility_proof (proves source credibility), impact_proof (proves quantitative impact)"
                    },
                    "evidence_layer": {
                        "type": "string",
                        "enum": ["claim", "proof", "significance", "context"],
                        "description": "Evidence pyramid layer: claim (what applicant did), proof (how to prove), significance (why it matters - MOST IMPORTANT), context (background)"
                    },
                    "confidence": {"type": "number"},
                    "reasoning": {"type": "string"}
                },
                "additionalProperties": False
            }
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "identity", "relation_to_applicant", "mentioned_in_blocks"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["person", "organization", "award", "publication", "position", "project", "event", "metric"]
                    },
                    "identity": {"type": "string", "description": "Role/title/description"},
                    "relation_to_applicant": {
                        "type": "string",
                        "enum": ["self", "recommender", "mentor", "colleague", "employer", "organization", "award_giver", "other"]
                    },
                    "mentioned_in_blocks": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "additionalProperties": False
            }
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["from_entity", "relation_type", "to_entity", "context", "source_blocks"],
                "properties": {
                    "from_entity": {"type": "string"},
                    "relation_type": {"type": "string"},
                    "to_entity": {"type": "string"},
                    "context": {"type": "string"},
                    "source_blocks": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "additionalProperties": False
            }
        }
    },
    "additionalProperties": False
}


# ==================== L-1A Extraction Prompts ====================

L1A_EXTRACTION_SYSTEM_PROMPT = _prompt_body("extractor/l1a_extraction_system_prompt")


L1A_EXTRACTION_USER_PROMPT = _prompt_body("extractor/l1a_extraction_user_prompt")


L1A_EXTRACTION_SCHEMA = {
    "type": "object",
    "required": ["document_summary", "snippets", "entities", "relations"],
    "properties": {
        "document_summary": {
            "type": "object",
            "required": ["document_type", "primary_subject", "key_themes"],
            "properties": {
                "document_type": {
                    "type": "string",
                    "description": "Type: corporate_formation, ownership_record, lease_agreement, business_plan, tax_return, audit_report, org_chart, company_letter, resume, transaction_document, bank_statement, other"
                },
                "primary_subject": {
                    "type": "string",
                    "description": "Main entity or person this document is about"
                },
                "key_themes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Key themes or topics"
                }
            },
            "additionalProperties": False
        },
        "snippets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["block_id", "text", "subject", "subject_role", "recommender_name", "is_applicant_achievement", "evidence_type", "evidence_purpose", "evidence_layer", "confidence", "reasoning"],
                "properties": {
                    "block_id": {"type": "string"},
                    "text": {"type": "string"},
                    "subject": {"type": "string", "description": "Person or entity whose action/attribute this is"},
                    "subject_role": {
                        "type": "string",
                        "enum": ["applicant", "recommender", "evaluator", "colleague", "mentor", "peer", "organization", "other"]
                    },
                    "recommender_name": {
                        "type": ["string", "null"],
                        "description": "If from recommendation/evaluation, who is the recommender/evaluator? Use null if not applicable."
                    },
                    "is_applicant_achievement": {"type": "boolean"},
                    "evidence_type": {
                        "type": "string",
                        "description": """Evidence type by L-1A standard:
Qualifying Relationship: corporate_structure, ownership, share_transfer, physical_premises, investment, incorporation
Doing Business: business_plan, financial_performance, revenue, customer_relationship, transaction_evidence, parent_company_info, partnership
Executive Capacity: org_chart, executive_duties, subordinate_credentials, time_allocation
Qualifying Employment: employment_history, education, achievement, contract_execution
General: other"""
                    },
                    "evidence_purpose": {
                        "type": "string",
                        "enum": ["direct_proof", "selectivity_proof", "credibility_proof", "impact_proof"],
                        "description": "WHY this evidence matters: direct_proof (proves legal requirement), credibility_proof (proves entity credibility), impact_proof (proves quantitative scale), selectivity_proof (proves qualifications)"
                    },
                    "evidence_layer": {
                        "type": "string",
                        "enum": ["claim", "proof", "significance", "context"],
                        "description": "Evidence pyramid layer: claim (legal point), proof (supporting fact), significance (why it matters), context (background)"
                    },
                    "confidence": {"type": "number"},
                    "reasoning": {"type": "string"}
                },
                "additionalProperties": False
            }
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "type", "identity", "relation_to_applicant", "mentioned_in_blocks"],
                "properties": {
                    "name": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["person", "organization", "award", "publication", "position", "project", "event", "metric"]
                    },
                    "identity": {"type": "string", "description": "Role/title/description"},
                    "relation_to_applicant": {
                        "type": "string",
                        "enum": ["self", "recommender", "mentor", "colleague", "employer", "organization", "award_giver", "other"]
                    },
                    "mentioned_in_blocks": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "additionalProperties": False
            }
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["from_entity", "relation_type", "to_entity", "context", "source_blocks"],
                "properties": {
                    "from_entity": {"type": "string"},
                    "relation_type": {"type": "string"},
                    "to_entity": {"type": "string"},
                    "context": {"type": "string"},
                    "source_blocks": {
                        "type": "array",
                        "items": {"type": "string"}
                    }
                },
                "additionalProperties": False
            }
        }
    },
    "additionalProperties": False
}


# ==================== Helper Functions ====================

def generate_snippet_id(exhibit_id: str, page: int, text: str) -> str:
    """确定性 snippet ID: 同 exhibit + page + text → 同 ID"""
    normalized = text.strip().lower()[:100]
    content = f"{exhibit_id}:{page}:{normalized}"
    hash_str = hashlib.md5(content.encode('utf-8')).hexdigest()[:8]
    return f"snp_{exhibit_id}_{hash_str}"


def generate_entity_id(exhibit_id: str, index: int) -> str:
    """生成唯一 entity ID"""
    return f"ent_{exhibit_id}_{index}"


def generate_relation_id(exhibit_id: str, index: int) -> str:
    """生成唯一 relation ID"""
    return f"rel_{exhibit_id}_{index}"


def _infer_evidence_layer(item: Dict) -> str:
    """根据 evidence_purpose 和 evidence_type 推断证据层级"""
    purpose = item.get("evidence_purpose", "direct_proof")
    etype = item.get("evidence_type", "other")

    # significance 层：selectivity/credibility/impact proof
    if purpose in ["selectivity_proof", "credibility_proof", "impact_proof"]:
        return "significance"

    # significance 层的证据类型
    if etype in ["peer_achievement", "source_credibility", "quantitative_impact",
                  "membership_criteria", "salary_benchmark"]:
        return "significance"

    # proof 层：证明申请人的声明
    if etype in ["award", "membership_evaluation", "peer_assessment", "recommendation"]:
        return "proof"

    # claim 层：直接声明（主要证据类型）
    if etype in ["membership", "media_coverage", "judging", "contribution", "publication",
                  "exhibition", "leadership", "salary", "compensation", "commercial_success",
                  "scientific_research_project"]:
        return "claim"

    # context 层：背景信息
    return "context"


_COVER_PAGE_RE = re.compile(
    r"^#?\s*exhibit\s+[a-z][-–]?\d+\s*$", re.IGNORECASE
)


def _is_cover_page(page_data: Dict) -> bool:
    """Detect exhibit cover pages that contain only a label like 'Exhibit A-1'."""
    md = page_data.get("markdown_text", "").strip()
    if len(md) < 30 and _COVER_PAGE_RE.match(md):
        return True
    blocks = page_data.get("text_blocks", [])
    if len(blocks) <= 1:
        texts = [b.get("text_content", "").strip() for b in blocks]
        combined = " ".join(texts).strip()
        if len(combined) < 30 and _COVER_PAGE_RE.match(combined):
            return True
    return False


async def _llm_match_blocks(
    unmatched_snippets: List[Dict],
    block_map: Dict,
    exhibit_id: str,
    provider: str = "deepseek",
) -> Dict[int, str]:
    """Layer 3: 用 LLM 为无法文本匹配的 snippet 找到正确的 block_id。

    Args:
        unmatched_snippets: [{"idx": int, "text": str}, ...]
        block_map: {composite_id: (page_num, block)}
        exhibit_id: exhibit ID
        provider: LLM provider

    Returns:
        {snippet_idx: matched_composite_id}
    """
    if not unmatched_snippets or not block_map:
        return {}

    # 构建 block 列表（只保留有实际内容的 block，截断过长的 block text）
    block_list = []
    for cid, (pn, blk) in block_map.items():
        text = blk.get("text_content", "").strip()
        if not text:
            continue
        preview = text[:300] + ("..." if len(text) > 300 else "")
        block_list.append(f"[{cid}] (page {pn}, {len(text)} chars) {preview}")

    blocks_text = "\n".join(block_list)

    # 构建 snippet 列表
    snippet_entries = []
    for item in unmatched_snippets:
        idx = item["idx"]
        text = item["text"][:200] + ("..." if len(item["text"]) > 200 else "")
        snippet_entries.append(f"SNIPPET_{idx}: \"{text}\"")

    snippets_text = "\n".join(snippet_entries)

    prompt = _prompt_render("extractor/llm_match_blocks_prompt",
        exhibit_id=exhibit_id,
        blocks_text=blocks_text,
        snippets_text=snippets_text,
    )

    try:
        result = await call_llm(
            prompt=prompt,
            provider=provider,
            system_prompt="You match text snippets to source document blocks. Return only valid JSON.",
            temperature=0.1,
            max_tokens=2000,
        )
        matches_raw = result.get("matches", [])
        matched = {}
        for m in matches_raw:
            snip_key = m.get("snippet", "")
            block_id = m.get("block_id", "")
            # 解析 SNIPPET_{idx}
            if snip_key.startswith("SNIPPET_") and block_id in block_map:
                try:
                    idx = int(snip_key.split("_")[1])
                    matched[idx] = block_id
                except (ValueError, IndexError):
                    pass
        logger.info(f"[BlockVerify] {exhibit_id}: LLM matched {len(matched)}/{len(unmatched_snippets)} snippets")
        return matched
    except Exception as e:
        logger.warning(f"[BlockVerify] {exhibit_id}: LLM matching failed: {e}")
        return {}


def format_blocks_for_llm(pages: List[Dict]) -> Tuple[str, Dict]:
    """将所有页的 blocks 格式化为 LLM 输入格式

    Returns:
        tuple: (blocks_text, block_map)
            - blocks_text: 格式化后的文本
            - block_map: {composite_id -> (page_num, block)} 的映射
    """
    lines = []
    block_map = {}

    for page_data in pages:
        page_num = page_data.get("page_number", 0)

        # Skip exhibit cover pages (e.g. pages containing only "Exhibit A-1")
        if _is_cover_page(page_data):
            continue

        blocks = page_data.get("text_blocks", [])

        for block in blocks:
            block_id = block.get("block_id", "")
            text = block.get("text_content", "").strip()

            # 跳过空文本或太短的文本
            if not text or len(text) < 5:
                continue

            # Use block_id directly if it already encodes page info (e.g. "p2_b0"),
            # otherwise prefix with page number to avoid collisions
            if block_id and re.match(r"p\d+_", block_id):
                composite_id = block_id
            else:
                composite_id = f"p{page_num}_{block_id}"
            block_map[composite_id] = (page_num, block)
            lines.append(f"[{composite_id}] {text}")

    return "\n".join(lines), block_map


def get_extraction_dir(project_id: str) -> Path:
    """获取提取结果目录"""
    extraction_dir = project_path(project_id, "extraction")
    extraction_dir.mkdir(parents=True, exist_ok=True)
    return extraction_dir


def get_entities_dir(project_id: str) -> Path:
    """获取实体目录"""
    entities_dir = project_path(project_id, "entities")
    entities_dir.mkdir(parents=True, exist_ok=True)
    return entities_dir


# ==================== Core Functions ====================

async def extract_exhibit_unified(
    project_id: str,
    exhibit_id: str,
    applicant_name: str,
    provider: str = "deepseek",
    project_type: str = "EB-1A"
) -> Dict:
    """
    统一提取单个 exhibit 的 snippets + entities + relations

    Args:
        project_id: 项目 ID
        exhibit_id: Exhibit ID
        applicant_name: 申请人姓名
        provider: LLM 提供商 ("deepseek" 或 "openai")
        project_type: "EB-1A" or "NIW"

    Returns:
        提取结果 dict
    """
    # 1. 加载文档
    doc_path = project_path(project_id, "documents", f"{exhibit_id}.json")
    if not doc_path.exists():
        raise FileNotFoundError(f"Document not found: {doc_path}")

    with open(doc_path, 'r', encoding='utf-8') as f:
        doc_data = json.load(f)

    pages = doc_data.get("pages", [])
    if not pages:
        return {
            "success": False,
            "error": f"No pages in exhibit {exhibit_id}",
            "exhibit_id": exhibit_id
        }

    logger.info(f"[UnifiedExtractor] Processing exhibit {exhibit_id} ({len(pages)} pages)...")
    # 2. 格式化 blocks
    blocks_text, block_map = format_blocks_for_llm(pages)

    if not blocks_text or len(blocks_text) < 50:
        return {
            "success": False,
            "error": f"Not enough text content in {exhibit_id}",
            "exhibit_id": exhibit_id
        }

    # 3. 构建 prompt — 根据 project_type 选择
    if project_type == "NIW":
        system_prompt = NIW_EXTRACTION_SYSTEM_PROMPT.format(applicant_name=applicant_name)
        user_prompt = NIW_EXTRACTION_USER_PROMPT.format(
            exhibit_id=exhibit_id,
            applicant_name=applicant_name,
            blocks_text=blocks_text
        )
        extraction_schema = NIW_EXTRACTION_SCHEMA
    elif project_type == "L-1A":
        system_prompt = L1A_EXTRACTION_SYSTEM_PROMPT.format(applicant_name=applicant_name)
        user_prompt = L1A_EXTRACTION_USER_PROMPT.format(
            exhibit_id=exhibit_id,
            applicant_name=applicant_name,
            blocks_text=blocks_text
        )
        extraction_schema = L1A_EXTRACTION_SCHEMA
    else:
        system_prompt = UNIFIED_EXTRACTION_SYSTEM_PROMPT.format(applicant_name=applicant_name)
        user_prompt = UNIFIED_EXTRACTION_USER_PROMPT.format(
            exhibit_id=exhibit_id,
            applicant_name=applicant_name,
            blocks_text=blocks_text
        )
        extraction_schema = UNIFIED_EXTRACTION_SCHEMA

    # 4. 调用 LLM
    logger.info(f"[UnifiedExtractor] Calling LLM ({provider}) for {exhibit_id} (project_type={project_type})...")
    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=system_prompt,
            json_schema=extraction_schema,
            temperature=0.2,   # 提高到 0.2：允许更多变化，更好地识别上下文
            max_tokens=8000   # DeepSeek 限制 8192，使用 8000 留余量
        )
    except Exception as e:
        logger.warning(f"[UnifiedExtractor] LLM error for {exhibit_id}: {e}")
        return {
            "success": False,
            "error": str(e),
            "exhibit_id": exhibit_id
        }

    # 5. 处理结果
    document_summary = result.get("document_summary", {})
    raw_snippets = result.get("snippets", [])
    raw_entities = result.get("entities", [])
    raw_relations = result.get("relations", [])

    # 6. 处理 snippets - 添加 ID 和 bbox
    # 使用分层置信度阈值：支持性内容（如 membership_criteria）用更低阈值
    CONFIDENCE_THRESHOLDS = {
        # EB-1A types
        "award": 0.5,
        "membership": 0.4,
        "membership_criteria": 0.3,
        "membership_evaluation": 0.3,
        "peer_assessment": 0.3,
        "media_coverage": 0.4,
        "recommendation": 0.4,
        "contribution": 0.4,
        "leadership": 0.4,
        "judging": 0.4,
        "publication": 0.4,
        "salary": 0.3,
        "compensation": 0.3,
        "salary_benchmark": 0.3,
        "exhibition": 0.4,
        "commercial_success": 0.4,
        # NIW Prong 1 types
        "endeavor_description": 0.3,
        "field_impact": 0.3,
        "national_importance": 0.3,
        "merit_evidence": 0.3,
        # NIW Prong 2 types
        "education": 0.3,
        "work_experience": 0.3,
        "citation_metrics": 0.3,
        "research_project": 0.3,
        "quantitative_impact": 0.3,
        # NIW Prong 3 types
        "waiver_justification": 0.3,
        "national_benefit": 0.3,
        "beyond_employer": 0.3,
        "urgency": 0.3,
    }
    DEFAULT_THRESHOLD = 0.35

    processed_snippets = []
    seen_snippet_ids = set()  # 确定性 ID 去重
    pending_llm_match = []  # Layer 3: 收集需要 LLM 匹配的 snippet

    def _build_snippet_dict(item, composite_id, page_block):
        """从 raw item + 匹配到的 block 构建 processed snippet dict。
        Returns None if duplicate snippet_id (deterministic dedup)."""
        page_num, block = page_block
        original_block_id = block.get("block_id", "")
        snippet_id = generate_snippet_id(exhibit_id, page_num, item.get("text", ""))
        if snippet_id in seen_snippet_ids:
            return None
        seen_snippet_ids.add(snippet_id)
        return {
            "snippet_id": snippet_id,
            "exhibit_id": exhibit_id,
            "document_id": f"doc_{exhibit_id}",
            "text": item.get("text", ""),
            "page": page_num,
            "bbox": block.get("bbox"),
            "block_id": original_block_id,
            "subject": item.get("subject", applicant_name),
            "subject_role": item.get("subject_role", "applicant"),
            "recommender_name": item.get("recommender_name"),
            "is_applicant_achievement": item.get("is_applicant_achievement", True),
            "evidence_type": item.get("evidence_type", "other"),
            "evidence_purpose": item.get("evidence_purpose", "direct_proof"),
            "evidence_layer": item.get("evidence_layer", _infer_evidence_layer(item)),
            "confidence": item.get("confidence", 0.5),
            "reasoning": item.get("reasoning", ""),
            "is_ai_suggested": True,
            "is_confirmed": False
        }

    for item in raw_snippets:
        evidence_type = item.get("evidence_type", "other")
        threshold = CONFIDENCE_THRESHOLDS.get(evidence_type, DEFAULT_THRESHOLD)

        # 处理 confidence - DeepSeek 可能返回 None 或非数字
        confidence = item.get("confidence")
        if confidence is None or not isinstance(confidence, (int, float)):
            confidence = 0.5  # 默认置信度

        if confidence < threshold:
            continue

        composite_id = item.get("block_id", "")
        snippet_text = item.get("text", "")

        # 处理合并的 block_id (如 "p2_p2_b1-p2_p2_b2")
        # 取第一个 block_id
        if composite_id and "-" in composite_id and "_" in composite_id:
            composite_id = composite_id.split("-")[0]

        page_block = block_map.get(composite_id)

        # 如果找不到，尝试模糊匹配
        if not page_block and composite_id:
            for key in block_map.keys():
                if key.endswith(composite_id.split("_")[-1]) or composite_id in key:
                    page_block = block_map[key]
                    composite_id = key
                    break

        # ── 三层 block_id 校验 ──────────────────────────────────
        # Layer 1: 验证 — 即使 block_id 找到了，也检查 snippet 文本是否真的在那个 block 里
        if page_block and snippet_text:
            _, found_block = page_block
            block_text = found_block.get("text_content", "")
            snippet_norm_check = re.sub(r'\s+', ' ', snippet_text.lower().strip())
            block_norm_check = re.sub(r'\s+', ' ', block_text.lower().strip())
            # Check 1: 如果 snippet 远长于 block（2x），说明 block_id 分配错误
            length_mismatch = len(snippet_text) > len(block_text) * 2 and len(snippet_text) > 20
            # Check 2: 如果 snippet 前 50 字符不在 block 中且 block 前 50 字符不在 snippet 中，说明内容不匹配
            content_mismatch = (
                len(snippet_norm_check) > 20 and len(block_norm_check) > 20
                and snippet_norm_check[:50] not in block_norm_check
                and block_norm_check[:50] not in snippet_norm_check
            )
            if length_mismatch or content_mismatch:
                reason = "length" if length_mismatch else "content"
                logger.info(f"[BlockVerify] {exhibit_id}: snippet text ({len(snippet_text)} chars) vs block {composite_id} ({len(block_text)} chars) {reason} mismatch, searching correct block...")
                page_block = None  # 触发 Layer 2

        # Layer 2: 文本匹配 — 在所有 block 中搜索包含 snippet 文本的 block
        if not page_block and snippet_text and len(snippet_text) > 10:
            snippet_norm = re.sub(r'\s+', ' ', snippet_text.lower().strip())
            best_match = None
            best_score = 0
            for cid, (pn, blk) in block_map.items():
                blk_text = blk.get("text_content", "")
                blk_norm = re.sub(r'\s+', ' ', blk_text.lower().strip())
                if not blk_norm:
                    continue
                # 完整子串匹配
                if snippet_norm in blk_norm:
                    score = len(snippet_norm) / max(len(blk_norm), 1)
                    if score > best_score:
                        best_match = cid
                        best_score = score
            # 如果完整匹配没找到，尝试前 80 字符部分匹配
            if not best_match and len(snippet_norm) > 80:
                probe = snippet_norm[:80]
                for cid, (pn, blk) in block_map.items():
                    blk_norm = re.sub(r'\s+', ' ', blk.get("text_content", "").lower().strip())
                    if probe in blk_norm:
                        best_match = cid
                        break
            if best_match:
                page_block = block_map[best_match]
                composite_id = best_match
                logger.info(f"[BlockVerify] {exhibit_id}: text-matched to {best_match}")
        # Layer 3: 收集无法文本匹配的 snippet，等待批量 LLM 匹配
        if not page_block:
            pending_llm_match.append({
                "idx": len(pending_llm_match),
                "text": snippet_text,
                "item": item,  # 保留完整的 raw item 用于后续构建 snippet
            })
            continue

        built = _build_snippet_dict(item, composite_id, page_block)
        if built:
            processed_snippets.append(built)

    # ── Layer 3: 批量 LLM 匹配 ──────────────────────────────────
    if pending_llm_match:
        logger.info(f"[BlockVerify] {exhibit_id}: {len(pending_llm_match)} snippets need LLM matching...")
        llm_results = await _llm_match_blocks(
            pending_llm_match, block_map, exhibit_id, provider
        )
        for pending in pending_llm_match:
            idx = pending["idx"]
            matched_cid = llm_results.get(idx)
            if matched_cid and matched_cid in block_map:
                page_block = block_map[matched_cid]
                built = _build_snippet_dict(pending["item"], matched_cid, page_block)
                if built:
                    processed_snippets.append(built)
            else:
                logger.info(f"[BlockVerify] {exhibit_id}: LLM could not match snippet (text: '{pending['text'][:60]}...'), skipping")
    # 7. 处理 entities - 添加 ID
    processed_entities = []
    for idx, item in enumerate(raw_entities):
        entity_id = generate_entity_id(exhibit_id, idx)
        processed_entities.append({
            "id": entity_id,
            "name": item.get("name", ""),
            "type": item.get("type", "other"),
            "identity": item.get("identity", ""),
            "relation_to_applicant": item.get("relation_to_applicant", "other"),
            "snippet_ids": [],  # 将在后处理中填充
            "exhibit_ids": [exhibit_id],
            "mentioned_in_blocks": item.get("mentioned_in_blocks", []),
            "aliases": [],
            "is_merged": False,
            "merged_from": []
        })

    # 8. 处理 relations - 添加 ID
    processed_relations = []
    for idx, item in enumerate(raw_relations):
        relation_id = generate_relation_id(exhibit_id, idx)
        processed_relations.append({
            "id": relation_id,
            "from_entity": item.get("from_entity", ""),
            "to_entity": item.get("to_entity", ""),
            "relation_type": item.get("relation_type", ""),
            "context": item.get("context", ""),
            "source_snippet_ids": [],  # 将在后处理中填充
            "source_blocks": item.get("source_blocks", [])
        })

    # 9. 保存提取结果
    extraction_result = {
        "version": "4.0",
        "exhibit_id": exhibit_id,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "applicant_name": applicant_name,

        "document_summary": document_summary,

        "snippets": processed_snippets,
        "entities": processed_entities,
        "relations": processed_relations,

        "stats": {
            "snippet_count": len(processed_snippets),
            "entity_count": len(processed_entities),
            "relation_count": len(processed_relations),
            "applicant_snippets": sum(1 for s in processed_snippets if s.get("is_applicant_achievement")),
            "other_snippets": sum(1 for s in processed_snippets if not s.get("is_applicant_achievement"))
        }
    }

    # 保存到文件
    extraction_dir = get_extraction_dir(project_id)
    extraction_file = extraction_dir / f"{exhibit_id}_extraction.json"
    write_json(extraction_file, extraction_result)

    logger.info(f"[UnifiedExtractor] {exhibit_id}: {len(processed_snippets)} snippets, {len(processed_entities)} entities, {len(processed_relations)} relations")
    return {
        "success": True,
        "exhibit_id": exhibit_id,
        **extraction_result["stats"]
    }


async def extract_all_unified(
    project_id: str,
    applicant_name: str,
    provider: str = "deepseek",
    progress_callback=None,
    project_type: str = "EB-1A",
    job=None,
) -> Dict:
    """
    提取项目中所有 exhibits

    Args:
        project_id: 项目 ID
        applicant_name: 申请人姓名
        provider: LLM 提供商 ("deepseek" 或 "openai")
        progress_callback: 进度回调 (current, total, message)
        project_type: "EB-1A" or "NIW"

    Returns:
        提取结果汇总
    """
    from ..core.jobs import NullJob
    job = job or NullJob()
    if progress_callback is None:
        def progress_callback(current, total, message):  # noqa: E306
            job.checkpoint(step="extract", detail=f"{message} ({current}/{total})",
                           progress=0.05 + 0.9 * (current / max(total, 1)))

    documents_dir = project_path(project_id, "documents")

    if not documents_dir.exists():
        return {
            "success": False,
            "error": "Documents directory not found"
        }

    exhibit_files = list(documents_dir.glob("*.json"))
    total_exhibits = len(exhibit_files)

    logger.info(f"[UnifiedExtractor] Starting extraction for {total_exhibits} exhibits, applicant: {applicant_name}")
    all_snippets = []
    all_entities = []
    all_relations = []

    successful = 0
    failed = 0

    # 并发提取 — 使用 semaphore 限流，避免 API 过载
    CONCURRENCY = 5
    semaphore = asyncio.Semaphore(CONCURRENCY)
    completed_count = 0

    async def _extract_one(exhibit_file):
        nonlocal successful, failed, completed_count
        exhibit_id = exhibit_file.stem

        async with semaphore:
            try:
                result = await extract_exhibit_unified(
                    project_id, exhibit_id, applicant_name,
                    provider=provider, project_type=project_type
                )
                completed_count += 1

                if progress_callback:
                    progress_callback(completed_count, total_exhibits, f"Extracted {exhibit_id}")

                return exhibit_id, result
            except Exception as e:
                completed_count += 1
                logger.info(f"[UnifiedExtractor] Exception extracting {exhibit_id}: {e}")
                return exhibit_id, {"success": False, "error": str(e)}

    logger.info(f"[UnifiedExtractor] Extracting {total_exhibits} exhibits with concurrency={CONCURRENCY}...")
    tasks = [_extract_one(ef) for ef in exhibit_files]
    results = await asyncio.gather(*tasks)

    # 收集结果
    for exhibit_id, result in results:
        if result.get("success"):
            successful += 1
            extraction_file = get_extraction_dir(project_id) / f"{exhibit_id}_extraction.json"
            if extraction_file.exists():
                with open(extraction_file, 'r', encoding='utf-8') as f:
                    extraction_data = json.load(f)
                all_snippets.extend(extraction_data.get("snippets", []))
                all_entities.extend(extraction_data.get("entities", []))
                all_relations.extend(extraction_data.get("relations", []))
        else:
            failed += 1
            logger.warning(f"[UnifiedExtractor] Failed {exhibit_id}: {result.get('error')}")
    if progress_callback:
        progress_callback(total_exhibits, total_exhibits, "Saving combined results...")

    # 保存合并后的结果
    combined_result = {
        "version": "4.0",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "applicant_name": applicant_name,
        "exhibit_count": total_exhibits,
        "successful": successful,
        "failed": failed,

        "snippets": all_snippets,
        "entities": all_entities,
        "relations": all_relations,

        "stats": {
            "total_snippets": len(all_snippets),
            "total_entities": len(all_entities),
            "total_relations": len(all_relations),
            "applicant_snippets": sum(1 for s in all_snippets if s.get("is_applicant_achievement")),
            "other_snippets": sum(1 for s in all_snippets if not s.get("is_applicant_achievement"))
        }
    }

    # 保存合并结果
    extraction_dir = get_extraction_dir(project_id)
    combined_file = extraction_dir / "combined_extraction.json"
    write_json(combined_file, combined_result)

    # 同步到 snippet registry（provenance_engine 等读取）
    build_registry_from_combined_extraction(project_id)

    # 同时保存到 snippets 目录（兼容现有代码）
    snippets_dir = project_path(project_id, "snippets")
    snippets_dir.mkdir(parents=True, exist_ok=True)
    snippets_file = snippets_dir / "extracted_snippets.json"

    snippets_data = {
        "version": "4.0",
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "snippet_count": len(all_snippets),
        "extraction_method": "unified_extraction",
        "model": getattr(settings, 'openai_model', 'gpt-4o'),
        "snippets": all_snippets
    }

    write_json(snippets_file, snippets_data)

    logger.info(f"[UnifiedExtractor] Complete: {successful}/{total_exhibits} exhibits, {len(all_snippets)} snippets, {len(all_entities)} entities")
    return {
        "success": True,
        "exhibit_count": total_exhibits,
        "successful": successful,
        "failed": failed,
        **combined_result["stats"]
    }


def load_combined_extraction(project_id: str) -> Optional[Dict]:
    """加载合并后的提取结果"""
    combined_file = get_extraction_dir(project_id) / "combined_extraction.json"
    if combined_file.exists():
        with open(combined_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def load_exhibit_extraction(project_id: str, exhibit_id: str) -> Optional[Dict]:
    """加载单个 exhibit 的提取结果"""
    extraction_file = get_extraction_dir(project_id) / f"{exhibit_id}_extraction.json"
    if extraction_file.exists():
        with open(extraction_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def get_extraction_status(project_id: str) -> Dict:
    """获取提取状态"""
    extraction_dir = get_extraction_dir(project_id)
    documents_dir = project_path(project_id, "documents")

    # 统计已提取的 exhibits
    extracted_exhibits = []
    if extraction_dir.exists():
        for f in extraction_dir.glob("*_extraction.json"):
            exhibit_id = f.stem.replace("_extraction", "")
            extracted_exhibits.append(exhibit_id)

    # 统计所有 exhibits
    all_exhibits = []
    if documents_dir.exists():
        all_exhibits = [f.stem for f in documents_dir.glob("*.json")]

    # 检查合并结果
    combined_file = extraction_dir / "combined_extraction.json"
    has_combined = combined_file.exists()

    combined_stats = None
    if has_combined:
        with open(combined_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            combined_stats = data.get("stats")

    return {
        "total_exhibits": len(all_exhibits),
        "extracted_exhibits": len(extracted_exhibits),
        "extracted_exhibit_ids": extracted_exhibits,
        "pending_exhibits": [e for e in all_exhibits if e not in extracted_exhibits],
        "has_combined_extraction": has_combined,
        "combined_stats": combined_stats
    }
