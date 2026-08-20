"""
Petition Writer V3 - OCR 回溯写作

核心改进（v3.1 — OCR Traceback）：
1. snippet 是索引指针，写作时回溯 OCR 原文
2. 写作粒度从 per-SubArgument 提升到 per-Argument
3. LLM 看到完整 OCR 页面，从中提取所有细节

数据流：
Argument → SubArgument结构(大纲) + snippet指针
         → 加载所有引用exhibit的OCR完整页面
         → LLM按大纲、看原文、写深度论证

输出：{text, snippet_ids, subargument_id, argument_id, exhibit_refs}[]
"""

import hashlib
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..core.atomic_io import read_json, write_json
from ..core.prompt_loader import body as _prompt_body
from ..core.prompt_loader import render as _prompt_render
from ..core.text import text_similarity as _text_similarity
from .llm_client import call_llm, call_llm_text
from .snippet_registry import load_registry
from .standards_registry import get_standard_name
from .storage import project_path
from .writing_strategies import get_writing_strategy

# Labels that LLMs sometimes leak from the argumentation-method prompt
_LEAKED_LABEL_RE = re.compile(
    r"\s*(?:FACT|LEGAL NEXUS|QUANTIFICATION|CORROBORATION|CONCLUSION)\s*:\s*",
    re.IGNORECASE,
)


def _strip_leaked_labels(text: str) -> str:
    """Remove analytical framework labels that the LLM leaked into prose."""
    return _LEAKED_LABEL_RE.sub(" ", text).strip()

logger = logging.getLogger(__name__)


# ============================================
# Snippet ID 映射工具
# ============================================

def _parse_old_snippet_id(old_id: str) -> Optional[Dict]:
    """
    解析 snippet ID（支持新旧两种格式）

    旧格式: snp_C2_p2_p2_b5_eadb0715 (6+ parts)
    → {exhibit_id: "C2", page: 2, block_full: "p2_b5", hash: "eadb0715", format: "old"}

    新格式: snp_C2_a3f5b1c2 (3 parts)
    → {exhibit_id: "C2", hash: "a3f5b1c2", format: "new"}
    """
    if not old_id or not old_id.startswith("snp_"):
        return None

    parts = old_id.split("_")

    # 新格式: snp_{exhibit}_{hash8} → 3 parts
    if len(parts) == 3:
        return {
            "exhibit_id": parts[1],
            "hash": parts[2],
            "format": "new"
        }

    # 旧格式: snp_{exhibit}_{pX}_{pY}_{bZ}_{hash} → 6+ parts
    if len(parts) >= 6:
        try:
            exhibit_id = parts[1]
            page_part1 = parts[2]
            page_part2 = parts[3]
            block_part = parts[4]
            hash_part = parts[5]

            page = int(page_part1[1:]) if page_part1.startswith("p") else 0
            block_full = f"{page_part2}_{block_part}"

            return {
                "exhibit_id": exhibit_id,
                "page": page,
                "block": block_part,
                "block_full": block_full,
                "hash": hash_part,
                "format": "old"
            }
        except (IndexError, ValueError):
            return None

    return None


def _map_old_snippet_id_to_new(
    old_id: str,
    snippet_registry: List[Dict]
) -> Optional[Dict]:
    """
    将 snippet ID 映射到 registry snippet（支持新旧格式）

    新格式 (snp_{exhibit}_{hash8}): 直接按 snippet_id 查找
    旧格式 (snp_{exhibit}_{pX}_{pY}_{bZ}_{hash}): 按 exhibit + block_full 匹配
    snip_ 格式: 直接按 snippet_id 查找
    """
    # snip_ 格式（snippet_registry 自身的格式）
    if old_id.startswith("snip_"):
        for snip in snippet_registry:
            if snip.get("snippet_id") == old_id:
                return snip
        return None

    parsed = _parse_old_snippet_id(old_id)
    if not parsed:
        return None

    # 新格式: 直接按 snippet_id 查找
    if parsed.get("format") == "new":
        for snip in snippet_registry:
            if snip.get("snippet_id") == old_id:
                return snip
        return None

    # 旧格式: 按 exhibit_id + source_block_ids/block_id 匹配
    for snip in snippet_registry:
        if snip.get("exhibit_id") != parsed["exhibit_id"]:
            continue

        # Check source_block_ids first
        source_blocks = snip.get("source_block_ids", [])
        if parsed.get("block_full") and parsed["block_full"] in source_blocks:
            return snip

        # Fallback: check block_id field directly
        if parsed.get("block_full") and snip.get("block_id") == parsed["block_full"]:
            return snip

    return None


def _build_snippet_lookup(snippet_registry: List[Dict]) -> Dict:
    """
    构建双向查找表

    Returns:
        {
            "by_new_id": {"snip_xxx": snippet_dict},
            "by_exhibit_block": {("C2", "p2_b5"): snippet_dict}
        }
    """
    by_new_id = {}
    by_exhibit_block = {}

    for snip in snippet_registry:
        new_id = snip.get("snippet_id", "")
        by_new_id[new_id] = snip

        exhibit_id = snip.get("exhibit_id", "")
        for block_id in snip.get("source_block_ids", []):
            key = (exhibit_id, block_id)
            by_exhibit_block[key] = snip

    return {
        "by_new_id": by_new_id,
        "by_exhibit_block": by_exhibit_block
    }


# ============================================
# 常量定义
# ============================================



def _load_snippet_source(project_id: str) -> List[Dict]:
    """加载 snippet 数据源，优先 combined_extraction（和前端一致，snp_ 格式）。

    前端始终从 extraction 端点加载 snippet（snp_ 格式 ID），
    所以 writing pipeline 也必须优先使用同一数据源，确保全链路 ID 一致。
    """
    combined_file = project_path(project_id, "extraction", "combined_extraction.json")
    if combined_file.exists():
        with open(combined_file, 'r', encoding='utf-8') as f:
            snippets = json.load(f).get("snippets", [])
        if snippets:
            return snippets
    # Fallback: registry.json（仅当 combined_extraction 不存在时）
    return load_registry(project_id)


def _recover_snippet_ids_by_text(
    removed_ids: List[str],
    snippet_registry: List[Dict],
    valid_snippet_ids: set,
    threshold: float = 0.6
) -> List[str]:
    """
    对被校验删除的 snippet_ids，尝试通过文本相似度在 registry 中找到匹配。
    只匹配 valid_snippet_ids 范围内的 snippet。
    """
    registry_by_id = {s["snippet_id"]: s for s in snippet_registry}
    valid_snippets = [s for s in snippet_registry if s["snippet_id"] in valid_snippet_ids]

    recovered = []
    for old_id in removed_ids:
        old_snip = registry_by_id.get(old_id)
        if not old_snip:
            continue
        old_text = old_snip.get("text", "")
        if not old_text:
            continue

        best_match, best_score = None, 0.0
        for candidate in valid_snippets:
            score = _text_similarity(old_text[:200], candidate.get("text", "")[:200])
            if score > best_score:
                best_score = score
                best_match = candidate

        if best_match and best_score >= threshold:
            recovered.append(best_match["snippet_id"])

    return recovered


async def _recover_snippet_ids_by_llm(
    sentence_text: str,
    candidate_snippets: List[Dict],
    provider: str = "deepseek"
) -> List[str]:
    """
    用 LLM 将句子与候选 snippet 匹配。
    给 LLM 句子文本 + 候选 snippet 列表，让它返回最相关的 snippet_ids。
    """
    if not candidate_snippets:
        return []

    # Limit to 20 candidates to control token usage
    candidates = candidate_snippets[:20]
    candidates_text = "\n".join(
        f'[{s["snippet_id"]}] "{s.get("text", "")[:150]}"'
        for s in candidates
    )

    prompt = _prompt_render("writer/recover_snippet_ids_by_llm_prompt",
        sentence_text=sentence_text,
        candidates_text=candidates_text,
    )

    try:
        result = await call_llm(
            prompt,
            system_prompt="You match sentences to evidence snippets. Return valid JSON only.",
            temperature=0.0,
            max_tokens=2000,
            provider=provider
        )
        valid_candidate_ids = {s["snippet_id"] for s in candidates}
        return [sid for sid in result.get("snippet_ids", []) if sid in valid_candidate_ids]
    except Exception as e:
        logger.warning(f"LLM snippet recovery failed: {e}")
        return []


def _get_standard_display_name(standard_key: str) -> str:
    """Get display name for a standard key via standards registry."""
    for ptype in ("EB-1A", "NIW", "L-1A"):
        name = get_standard_name(ptype, standard_key)
        if name != standard_key:
            return name
    return standard_key


def _build_criteria_summary(project_id: str) -> Optional[str]:
    """
    Build cross-criteria context for Overall Merits (Kazarian Step 2).

    Reads all completed criterion writing outputs and extracts 1-2 key
    achievement sentences per criterion as bullet points for the LLM.

    Returns:
        Formatted summary string, or None if no criteria writing available.
    """
    from .standards_registry import EB1A_LEGAL_STANDARDS

    criteria_summaries = []

    for std_def in EB1A_LEGAL_STANDARDS:
        if std_def.key == "overall_merits":
            continue

        writing = load_latest_writing_v3(project_id, std_def.key)
        if writing and writing.get("sentences"):
            body_sents = [
                s for s in writing["sentences"]
                if s.get("sentence_type") == "body" and s.get("text")
            ]
            if body_sents:
                # Extract first 2 sentences of each sub-argument (max 6 per criterion)
                seen_subargs: Dict[str, int] = {}
                representative = []
                for s in body_sents:
                    sa_id = s.get("subargument_id", "")
                    count = seen_subargs.get(sa_id, 0)
                    if count < 2:
                        seen_subargs[sa_id] = count + 1
                        representative.append(s["text"])
                    if len(representative) >= 6:
                        break
                criteria_summaries.append(
                    f"  {std_def.name} [{std_def.key}]:\n" +
                    "\n".join(f"    - {sent}" for sent in representative)
                )
                continue

        # Fallback: argument/sub-argument titles
        legal_args = load_legal_arguments(project_id)
        if legal_args:
            arguments = legal_args.get("arguments", [])
            sub_arguments = legal_args.get("sub_arguments", [])
            std_args = [
                a for a in arguments
                if a.get("standard_key") == std_def.key or a.get("standard") == std_def.key
            ]
            if std_args:
                lines = []
                for arg in std_args:
                    lines.append(f"    Argument: {arg.get('title', '')}")
                    arg_subargs = [
                        sa for sa in sub_arguments
                        if sa.get("argument_id") == arg.get("id")
                    ]
                    for sa in arg_subargs:
                        lines.append(f"      - {sa.get('title', '')}")
                criteria_summaries.append(
                    f"  {std_def.name} [{std_def.key}] (titles only — writing not yet generated):\n" +
                    "\n".join(lines)
                )

    if not criteria_summaries:
        return None

    return (
        "=== CROSS-CRITERIA CONTEXT (criteria already established in the petition) ===\n"
        "Reference these accomplishments when arguing the TOTALITY of evidence.\n\n"
        + "\n\n".join(criteria_summaries) +
        "\n\n"
        "CROSS-REFERENCE RULES:\n"
        "- When referencing criteria accomplishments, if the SAME exhibit appears in your\n"
        "  SNIPPET INDEX above, cite it normally with [Exhibit X, p.Y] and snippet_ids.\n"
        "- If the exhibit is NOT in your SNIPPET INDEX, restate the fact WITHOUT any\n"
        "  exhibit citation — just write the sentence naturally.\n"
        "- NEVER fabricate citation formats like [Cross-reference Section X] or [See above].\n"
        "=== END CROSS-CRITERIA CONTEXT ==="
    )


def _build_cross_prong_summary(project_id: str, standard_key: str) -> Optional[str]:
    """
    Build cross-section context for standards that need it.

    - prong3_balance: references prong1/prong2 writing
    - overall_merits: references all EB-1A criteria writing

    Returns:
        Formatted summary string, or None if no prior data available.
    """
    if standard_key == "overall_merits":
        return _build_criteria_summary(project_id)

    if standard_key != "prong3_balance":
        return None

    prong_summaries = []

    for prong_key, prong_label in [
        ("prong1_merit", "Prong 1 — Substantial Merit & National Importance"),
        ("prong2_positioned", "Prong 2 — Well Positioned to Advance"),
    ]:
        # Primary strategy: load generated writing text
        writing = load_latest_writing_v3(project_id, prong_key)
        if writing and writing.get("sentences"):
            body_sents = [
                s for s in writing["sentences"]
                if s.get("sentence_type") == "body" and s.get("text")
            ]
            if body_sents:
                # Extract first 2 sentences of each sub-argument group (max 20 total)
                seen_subargs: Dict[str, int] = {}
                representative = []
                for s in body_sents:
                    sa_id = s.get("subargument_id", "")
                    count = seen_subargs.get(sa_id, 0)
                    if count < 2:
                        seen_subargs[sa_id] = count + 1
                        representative.append(s["text"])
                    if len(representative) >= 20:
                        break
                prong_summaries.append(
                    f"  {prong_label}:\n" +
                    "\n".join(f"    - {sent}" for sent in representative)
                )
                continue

        # Fallback strategy: use argument/sub-argument titles from legal_arguments
        legal_args = load_legal_arguments(project_id)
        if legal_args:
            arguments = legal_args.get("arguments", [])
            sub_arguments = legal_args.get("sub_arguments", [])
            # Find arguments for this prong
            prong_args = [a for a in arguments if a.get("standard") == prong_key]
            if prong_args:
                lines = []
                for arg in prong_args:
                    lines.append(f"    Argument: {arg.get('title', '')}")
                    arg_subargs = [
                        sa for sa in sub_arguments
                        if sa.get("argument_id") == arg.get("id")
                    ]
                    for sa in arg_subargs:
                        lines.append(f"      - {sa.get('title', '')}")
                prong_summaries.append(
                    f"  {prong_label} (titles only — writing not yet generated):\n" +
                    "\n".join(lines)
                )

    if not prong_summaries:
        return None

    return (
        "=== CROSS-PRONG CONTEXT (accomplishments already established in Prongs 1 & 2) ===\n"
        "Use these accomplishments to STRENGTHEN your Prong 3 waiver arguments.\n\n"
        + "\n\n".join(prong_summaries) +
        "\n\n"
        "CROSS-REFERENCE RULES:\n"
        "- When referencing Prong 1/2 accomplishments, if the SAME exhibit appears in your\n"
        "  SNIPPET INDEX above, cite it normally with [Exhibit X, p.Y] and snippet_ids.\n"
        "- If the exhibit is NOT in your SNIPPET INDEX, restate the fact WITHOUT any\n"
        "  exhibit citation — just write the sentence naturally (e.g., 'The Beneficiary\n"
        "  has demonstrated...' or 'Given the Beneficiary\\'s established contributions...').\n"
        "- NEVER fabricate citation formats like [Cross-reference Prong X] or [See above].\n"
        "=== END CROSS-PRONG CONTEXT ==="
    )


def _load_cross_prong_exhibits(
    project_id: str,
    standard_key: str = "prong3_balance"
) -> Dict[str, str]:
    """
    Load exhibit OCR text referenced by other sections' arguments.

    - prong3_balance: loads exhibits from prong1/prong2
    - overall_merits: loads exhibits from all non-overall_merits EB-1A criteria

    Used to give the writing section access to full source materials from prior sections.
    """
    legal_args = load_legal_arguments(project_id)
    if not legal_args:
        return {}

    arguments = legal_args.get("arguments", [])
    sub_arguments = legal_args.get("sub_arguments", [])

    # Determine which standards to collect exhibits from
    if standard_key == "overall_merits":
        include_standards = None  # include all non-overall_merits
    else:
        include_standards = {"prong1_merit", "prong2_positioned"}

    # Collect exhibit + page refs
    exhibit_pages: Dict[str, set] = defaultdict(set)
    for arg in arguments:
        arg_std = arg.get("standard_key") or arg.get("standard", "")
        if include_standards is not None:
            if arg_std not in include_standards:
                continue
        else:
            # overall_merits mode: skip the section itself
            if arg_std == "overall_merits":
                continue
        arg_subs = [sa for sa in sub_arguments if sa.get("argument_id") == arg["id"]]
        for sa in arg_subs:
            for snip in sa.get("snippets", []):
                exhibit_id = snip.get("exhibit_id", "") or snip.get("exhibit", "")
                page = snip.get("page", 0)
                if exhibit_id and page > 0:
                    exhibit_pages[exhibit_id].add(page)

    # Load OCR for each exhibit
    exhibit_texts = {}
    for exhibit_id, pages in exhibit_pages.items():
        exhibit_data = _load_exhibit_json(project_id, exhibit_id)
        if not exhibit_data:
            continue
        text = _extract_page_text(exhibit_data, pages)
        if text:
            exhibit_texts[exhibit_id] = text

    return exhibit_texts


# ============================================
# Exhibit OCR 缓存和加载
# ============================================

_exhibit_cache: Dict[str, Dict] = {}


def _load_exhibit_json(project_id: str, exhibit_id: str) -> Optional[Dict]:
    """
    加载并缓存 exhibit JSON，避免同一 exhibit 被多个 argument 重复读取。

    Returns:
        exhibit dict with {exhibit_id, pages: [{page_number, text_blocks, markdown_text}], ...}
        or None if file not found
    """
    cache_key = f"{project_id}:{exhibit_id}"
    if cache_key in _exhibit_cache:
        return _exhibit_cache[cache_key]

    path = project_path(project_id, "documents", f"{exhibit_id}.json")
    if not path.exists():
        logger.warning(f"Exhibit file not found: {path}")
        return None

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _exhibit_cache[cache_key] = data
        return data
    except Exception as e:
        logger.warning(f"Failed to load exhibit {exhibit_id}: {e}")
        return None


def _extract_page_text(exhibit_data: Dict, page_numbers: set) -> str:
    """
    从 exhibit JSON 中提取指定页面的文本内容。

    对于每个请求的页面，也包含相邻页（page±1）以提供上下文。

    Returns:
        格式化的页面文本 "[Page N]\n{text_content}\n..."
    """
    if not exhibit_data or not exhibit_data.get("pages"):
        return ""

    # Expand page set to include adjacent pages for context
    expanded_pages = set()
    for p in page_numbers:
        expanded_pages.add(max(1, p - 1))
        expanded_pages.add(p)
        expanded_pages.add(p + 1)

    page_texts = []
    for page in exhibit_data.get("pages", []):
        pn = page.get("page_number", 0)
        if pn not in expanded_pages:
            continue

        # Collect text from all text blocks on this page
        blocks = page.get("text_blocks", [])
        block_texts = []
        for block in blocks:
            text = block.get("text_content", "").strip()
            if text and block.get("block_type") != "image":
                block_texts.append(text)

        if block_texts:
            page_text = "\n".join(block_texts)
            page_texts.append(f"[Page {pn}]\n{page_text}")

    return "\n\n".join(page_texts)


def load_exhibit_pages_for_argument(
    project_id: str,
    argument: Dict,
    all_snippets: Dict
) -> Dict[str, str]:
    """
    收集 argument 引用的所有 exhibit 的 OCR 页面原文。

    Args:
        project_id: 项目 ID
        argument: argument dict with sub_arguments, each with snippets
        all_snippets: snippet_id → snippet dict (from load_subargument_context output)

    Returns:
        {exhibit_id: formatted_text}  按 exhibit 分组的完整页面文本
    """
    # Step 1: Collect all referenced exhibit_ids and their page numbers
    exhibit_pages: Dict[str, set] = defaultdict(set)

    for subarg in argument.get("sub_arguments", []):
        for snip in subarg.get("snippets", []):
            exhibit_id = snip.get("exhibit", "")
            page = snip.get("page", 0)
            if exhibit_id and page > 0:
                exhibit_pages[exhibit_id].add(page)

    # Step 2: Load exhibit JSONs and extract page text
    exhibit_texts: Dict[str, str] = {}
    for exhibit_id, pages in exhibit_pages.items():
        exhibit_data = _load_exhibit_json(project_id, exhibit_id)
        if not exhibit_data:
            continue

        text = _extract_page_text(exhibit_data, pages)
        if text:
            exhibit_texts[exhibit_id] = text
            logger.info(
                f"Loaded OCR for Exhibit {exhibit_id}: "
                f"{len(pages)} referenced pages, {len(text)} chars"
            )

    return exhibit_texts


# ============================================
# 数据加载函数
# ============================================

def load_legal_arguments(project_id: str) -> Optional[Dict]:
    """加载 legal_arguments.json"""
    legal_file = project_path(project_id, "arguments", "legal_arguments.json")
    if legal_file.exists():
        with open(legal_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def load_subargument_context(
    project_id: str,
    standard_key: str,
    argument_ids: List[str] = None,
    subargument_ids: List[str] = None,
    project_type: str = "EB-1A"
) -> Dict:
    """
    加载用于写作的 SubArgument 上下文

    Args:
        project_id: 项目 ID
        standard_key: 标准 key (如 "membership", "leading_role")
        argument_ids: 可选，指定要生成的 Argument IDs
        subargument_ids: 可选，指定要生成的 SubArgument IDs（更细粒度）

    Returns:
        {
            "standard": {"key": str, "name": str, "legal_ref": str},
            "arguments": [
                {
                    "id": str,
                    "title": str,
                    "sub_arguments": [
                        {
                            "id": str,
                            "title": str,
                            "purpose": str,
                            "relationship": str,
                            "snippets": [
                                {"id": str, "exhibit": str, "text": str, "page": int}
                            ]
                        }
                    ]
                }
            ]
        }
    """
    # 加载数据
    legal_args = load_legal_arguments(project_id)
    if not legal_args:
        return {"standard": None, "arguments": []}

    snippet_registry = _load_snippet_source(project_id)

    # 构建双向查找表（支持新旧两种 ID 格式）
    snippet_lookup = _build_snippet_lookup(snippet_registry)
    snippet_map = snippet_lookup["by_new_id"]

    arguments = legal_args.get("arguments", [])
    sub_arguments = legal_args.get("sub_arguments", [])

    # 构建 SubArgument 索引
    subarg_map = {sa["id"]: sa for sa in sub_arguments}

    # 过滤该 Standard 的 Arguments
    filtered_args = [
        a for a in arguments
        if a.get("standard_key") == standard_key
    ]

    # 如果指定了 argument_ids，进一步过滤
    if argument_ids:
        filtered_args = [a for a in filtered_args if a.get("id") in argument_ids]

    # 构建输出结构
    result_arguments = []
    for arg in filtered_args:
        arg_subargs = []
        for subarg_id in arg.get("sub_argument_ids", []):
            # 如果指定了 subargument_ids，只处理指定的
            if subargument_ids and subarg_id not in subargument_ids:
                continue

            subarg = subarg_map.get(subarg_id)
            if not subarg:
                continue

            # 加载该 SubArgument 的 Snippets
            snippets = []
            for snip_id in subarg.get("snippet_ids", []):
                # 支持新旧两种 ID 格式
                snip = snippet_map.get(snip_id)
                if not snip:
                    # 尝试映射旧格式 ID
                    snip = _map_old_snippet_id_to_new(snip_id, snippet_registry)

                if snip:
                    # 使用实际的 registry ID（新格式）供 LLM 引用
                    actual_id = snip.get("snippet_id", snip_id)
                    snippets.append({
                        "id": actual_id,
                        "original_id": snip_id,  # 保留原始 ID 以便调试
                        "exhibit": snip.get("exhibit_id", "Unknown"),
                        "text": snip.get("text", "")[:500],  # 限制长度
                        "page": snip.get("page", 0)
                    })

            arg_subargs.append({
                "id": subarg_id,
                "title": subarg.get("title", ""),
                "purpose": subarg.get("purpose", ""),
                "relationship": subarg.get("relationship", ""),
                "snippets": snippets
            })

        result_arguments.append({
            "id": arg.get("id"),
            "title": arg.get("title", ""),
            "sub_arguments": arg_subargs
        })

    return {
        "standard": {
            "key": standard_key,
            "name": _get_standard_display_name(standard_key),
            "legal_ref": get_writing_strategy(project_type, standard_key).legal_ref
        },
        "arguments": result_arguments
    }


# ============================================
# LLM 生成函数
# ============================================

def _build_writing_prompt(context: Dict) -> str:
    """构建写作 Prompt"""
    arguments = context.get("arguments", [])

    if not arguments:
        return ""

    # 构建 Argument 和 SubArgument 描述
    args_text = []
    for arg in arguments:
        arg_lines = [f"\n## Argument: {arg['title']}"]

        for subarg in arg.get("sub_arguments", []):
            subarg_lines = [
                f"\n### SubArgument [{subarg['id']}]: {subarg['title']}",
                f"Purpose: {subarg['purpose']}",
                f"Relationship: {subarg['relationship']}",
                "Evidence:"
            ]

            for snip in subarg.get("snippets", []):
                subarg_lines.append(
                    f"  - [{snip['id']}] (Exhibit {snip['exhibit']}, p.{snip['page']}): "
                    f'"{snip["text"][:200]}..."' if len(snip["text"]) > 200 else f'"{snip["text"]}"'
                )

            arg_lines.extend(subarg_lines)

        args_text.append("\n".join(arg_lines))

    return "\n".join(args_text)


# ============================================
# 三步流水线：分拆生成 → 润色整合 → 首尾生成
# ============================================

async def _step1_generate_subargument_body(
    standard: Dict,
    argument_title: str,
    subargument: Dict,
    additional_instructions: str = None,
    provider: str = "deepseek"
) -> List[Dict]:
    """
    Step 1: 为单个 SubArgument 生成 3-5 句正文。

    每个 SubArgument 独立调用 LLM，保证 100% 覆盖率。

    Returns:
        [{"text": str, "snippet_ids": [...], "exhibit_refs": [...]}]
    """
    # 构建该 SubArgument 的证据文本（给足内容，不过分截断）
    evidence_lines = []
    snippet_ids_list = []
    for snip in subargument.get("snippets", []):
        text = snip["text"][:600] + "..." if len(snip["text"]) > 600 else snip["text"]
        evidence_lines.append(
            f'  SNIPPET {snip["id"]} (Exhibit {snip["exhibit"]}, p.{snip["page"]}):\n    "{text}"'
        )
        snippet_ids_list.append(snip["id"])
    evidence_text = "\n\n".join(evidence_lines) if evidence_lines else "(no evidence provided)"
    snippet_ids_str = ", ".join(f'"{sid}"' for sid in snippet_ids_list)

    system_prompt = _prompt_body("writer/step1_generate_subargument_body_system_prompt")

    user_prompt = _prompt_render("writer/step1_generate_subargument_body_user_prompt",
        subargument_title=subargument['title'],
        argument_title=argument_title,
        evidence_text=evidence_text,
        additional_instructions_block=f"ADDITIONAL INSTRUCTIONS: {additional_instructions}" if additional_instructions else "",
        snippet_ids_str=snippet_ids_str,
        example_snippet_id=snippet_ids_list[0] if snippet_ids_list else 'snip_xxx',
    )

    result = await call_llm(
        prompt=user_prompt,
        system_prompt=system_prompt,
        json_schema={},
        temperature=0.3,
        max_tokens=4000,
        provider=provider
    )

    if "error" in result:
        return []

    sentences = result.get("sentences", [])

    # 校验 snippet_ids：只保留该 SubArgument 实际有的 snippet
    valid_ids = {s["id"] for s in subargument.get("snippets", [])}
    _logger = logging.getLogger(__name__)
    for sent in sentences:
        raw_ids = sent.get("snippet_ids", [])
        sent["snippet_ids"] = [sid for sid in raw_ids if sid in valid_ids]
        if raw_ids and not sent["snippet_ids"]:
            _logger.warning(f"Step1 snippet_ids ALL invalid: raw={raw_ids}, valid={valid_ids}")
        sent["exhibit_refs"] = sent.get("exhibit_refs", [])

    return sentences


def _build_step1_instructions(project_type: str, standard_key: str) -> str:
    """Build per-standard Step 1 instructions from the strategy registry."""
    strategy = get_writing_strategy(project_type, standard_key)
    return strategy.step1_instruction_block


async def _step1_generate_argument_body(
    project_id: str,
    standard: Dict,
    argument: Dict,
    exhibit_texts: Dict[str, str],
    additional_instructions: str = None,
    provider: str = "deepseek",
    project_type: str = "EB-1A",
    cross_prong_context: str = None
) -> List[Dict]:
    """
    Step 1 (v3.1): 为整个 Argument 生成 body，LLM 看到完整 OCR 原文。

    写作粒度从 per-SubArgument 提升到 per-Argument：
    - SubArgument 结构作为论证大纲
    - snippet 摘要作为"重点标记"
    - 完整 OCR 页面作为原始素材

    Args:
        standard: {key, name, legal_ref}
        argument: argument dict with sub_arguments (each with snippets)
        exhibit_texts: {exhibit_id: formatted OCR text} from load_exhibit_pages_for_argument
        additional_instructions: optional extra instructions

    Returns:
        [{"subargument_id": str, "sentences": [{"text", "snippet_ids", "exhibit_refs"}]}]
    """
    sub_arguments = argument.get("sub_arguments", [])
    if not sub_arguments:
        return []

    # Build sub-argument outline with snippet pointers
    outline_parts = []
    all_snippet_ids = set()
    for i, subarg in enumerate(sub_arguments, 1):
        lines = [
            f"  {i}. [{subarg['id']}] {subarg.get('title', '')}",
            f"     Purpose: {subarg.get('purpose', '')}",
            "     Key evidence pointers:"
        ]
        for snip in subarg.get("snippets", []):
            text_preview = snip["text"][:200] + "..." if len(snip["text"]) > 200 else snip["text"]
            lines.append(
                f'       - [{snip["id"]}] Exhibit {snip["exhibit"]}, p.{snip["page"]}: "{text_preview}"'
            )
            all_snippet_ids.add(snip["id"])
        outline_parts.append("\n".join(lines))

    outline_text = "\n\n".join(outline_parts)

    # Build source materials section
    source_parts = []
    for exhibit_id, text in sorted(exhibit_texts.items()):
        source_parts.append(f"--- Exhibit {exhibit_id} ---\n{text}")
    source_text = "\n\n".join(source_parts)

    # Build snippet index: all snippet blocks on referenced exhibits
    # so the LLM can cite specific block-level snippet_ids
    # Include all exhibits in exhibit_texts (covers cross-prong exhibits too)
    referenced_exhibits = set(exhibit_texts.keys())
    for subarg in sub_arguments:
        for snip in subarg.get("snippets", []):
            referenced_exhibits.add(snip.get("exhibit", ""))

    snippet_registry = _load_snippet_source(project_id)
    snippet_index_lines = []
    all_available_snippet_ids = set(all_snippet_ids)  # start with outline IDs
    for snip in snippet_registry:
        if snip.get("exhibit_id") in referenced_exhibits:
            sid = snip.get("snippet_id", "")
            preview = snip.get("text", "")[:150]
            page = snip.get("page", 0)
            snippet_index_lines.append(
                f'  [{sid}] Exhibit {snip["exhibit_id"]}, p.{page}: "{preview}"'
            )
            all_available_snippet_ids.add(sid)

    snippet_index_text = "\n".join(snippet_index_lines)

    # Build subargument_id list for JSON example
    subarg_ids = [sa["id"] for sa in sub_arguments]
    subarg_json_example = ",\n    ".join(
        f'{{"subargument_id": "{sid}", "sentences": [{{"text": "...", "snippet_ids": ["..."], "exhibit_refs": ["..."]}}]}}'
        for sid in subarg_ids[:2]
    )
    if len(subarg_ids) > 2:
        subarg_json_example += ",\n    ..."

    strategy = get_writing_strategy(project_type, standard.get("key", ""))
    system_prompt = strategy.step1_base_system_prompt
    if strategy.step1_argumentation_appendix:
        system_prompt += "\n" + strategy.step1_argumentation_appendix

    user_prompt = _prompt_render("writer/step1_generate_argument_body_user_prompt",
        standard_get_name=standard.get('name', ''),
        standard_get_legal_ref=standard.get('legal_ref', ''),
        argument_get_title=argument.get('title', ''),
        outline_text=outline_text,
        source_text=source_text,
        snippet_index_text=snippet_index_text,
        cross_prong_context_or=cross_prong_context or "",
        additional_instructions_block=f"ADDITIONAL INSTRUCTIONS: {additional_instructions}" if additional_instructions else "",
        step1_instructions=_build_step1_instructions(project_type, standard.get('key', '')),
        subarg_json_example=subarg_json_example,
        len_subarg_ids=len(subarg_ids),
        subarg_ids=subarg_ids,
    )

    # Token budget: system ~800 + outline ~1500 + source ~15000-20000 + output ~8000 = well within 128K
    result = await call_llm(
        prompt=user_prompt,
        system_prompt=system_prompt,
        json_schema={},
        temperature=0.3,
        max_tokens=8000,
        provider=provider
    )

    if "error" in result:
        logger.error(f"Step1 (argument-level) LLM error: {result['error']}")
        return []

    paragraphs = result.get("sub_argument_paragraphs", [])

    # Validate and normalize output
    valid_subarg_ids = {sa["id"] for sa in sub_arguments}
    # Build per-subarg snippet id sets for validation
    subarg_snippet_map = {}
    for sa in sub_arguments:
        sa_snip_ids = {s["id"] for s in sa.get("snippets", [])}
        subarg_snippet_map[sa["id"]] = sa_snip_ids

    validated_paragraphs = []
    for para in paragraphs:
        subarg_id = para.get("subargument_id", "")
        if subarg_id not in valid_subarg_ids:
            logger.warning(f"Step1 returned unknown subargument_id: {subarg_id}")
            continue

        sentences = para.get("sentences", [])
        for sent in sentences:
            # Keep all snippet_ids from this argument (not just this subargument)
            # since the LLM has visibility of all evidence now
            raw_ids = sent.get("snippet_ids", [])
            sent["snippet_ids"] = [sid for sid in raw_ids if sid in all_available_snippet_ids]
            sent["exhibit_refs"] = sent.get("exhibit_refs", [])

        validated_paragraphs.append({
            "subargument_id": subarg_id,
            "title": next(
                (sa.get("title", "") for sa in sub_arguments if sa["id"] == subarg_id),
                ""
            ),
            "sentences": sentences
        })

    # Check for missing subarguments — warn but don't fail
    returned_ids = {p["subargument_id"] for p in validated_paragraphs}
    missing = valid_subarg_ids - returned_ids
    if missing:
        logger.warning(f"Step1 missing subarguments: {missing}")

    return validated_paragraphs


async def _step2_polish_single_subarg(
    standard: Dict,
    subargument_bodies: List[Dict],
    provider: str = "deepseek"
) -> List[Dict]:
    """
    Lightweight self-revision for a single sub-argument.

    Improves sentence flow and argumentative language without changing
    any citations or snippet_ids.
    """
    if not subargument_bodies:
        return subargument_bodies

    body = subargument_bodies[0]
    sentences = body.get("sentences", [])
    if not sentences:
        return subargument_bodies

    sentences_text = "\n".join(
        f'  {i+1}. "{s["text"]}"' for i, s in enumerate(sentences)
    )

    system_prompt = """You are a Senior Immigration Attorney revising a single paragraph in a petition letter for argumentative strength and sentence flow."""

    user_prompt = _prompt_render("writer/step2_polish_single_subarg_user_prompt",
        standard_get_name=standard.get('name', ''),
        len_sentences=len(sentences),
        sentences_text=sentences_text,
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            system_prompt=system_prompt,
            json_schema={},
            temperature=0.3,
            max_tokens=8000,
            provider=provider
        )

        polished_sents = result.get("sentences", [])

        # Validate: must have same number of sentences
        if len(polished_sents) != len(sentences):
            logger.warning(
                f"Single-subarg polish returned {len(polished_sents)} sentences, "
                f"expected {len(sentences)}. Using originals."
            )
            return subargument_bodies

        # Restore original snippet_ids and exhibit_refs (don't trust LLM)
        for j, psent in enumerate(polished_sents):
            psent["snippet_ids"] = sentences[j].get("snippet_ids", [])
            psent["exhibit_refs"] = sentences[j].get("exhibit_refs", [])

        return [{
            "subargument_id": body["subargument_id"],
            "title": body.get("title", ""),
            "sentences": polished_sents
        }]

    except Exception as e:
        logger.warning(f"Single-subarg polish failed, using originals: {e}")
        return subargument_bodies


async def _step2_polish_argument(
    standard: Dict,
    argument: Dict,
    subargument_bodies: List[Dict],
    provider: str = "deepseek",
    project_type: str = "EB-1A"
) -> List[Dict]:
    """
    Step 2: 将同一 Argument 下多个 SubArgument 的段落润色整合。

    LLM 添加过渡句、调整语序，但必须保持 SubArgument 分组结构和引用。

    Args:
        subargument_bodies: [{"subargument_id": str, "sentences": [...]}]

    Returns:
        润色后的 subargument_bodies（同结构）
    """
    if len(subargument_bodies) <= 1:
        strategy = get_writing_strategy(project_type, standard.get("key", ""))
        if strategy.polish_single_subarg:
            return await _step2_polish_single_subarg(
                standard, subargument_bodies, provider
            )
        return subargument_bodies

    # 构建输入文本（包含 snippet_ids 以便 LLM 知道它们）
    input_blocks = []
    subarg_ids = []
    for body in subargument_bodies:
        subarg_id = body["subargument_id"]
        subarg_ids.append(subarg_id)
        title = body.get("title", "")
        sentences_text = "\n".join(
            f'    - "{s["text"]}"' for s in body["sentences"]
        )
        input_blocks.append(f'  SubArgument [{subarg_id}] "{title}":\n{sentences_text}')

    input_text = "\n\n".join(input_blocks)

    system_prompt = """You are a Senior Immigration Attorney polishing a petition letter section for coherence.
Your task is to add smooth transitions between sub-argument paragraphs while preserving ALL factual content, evidence citations, and direct quotes exactly as written."""

    user_prompt = _prompt_render("writer/step2_polish_argument_user_prompt",
        standard_get_name=standard.get('name', ''),
        input_text=input_text,
        subarg_ids_0=subarg_ids[0],
        second_subarg_id_example=subarg_ids[1] if len(subarg_ids) > 1 else 'subarg-yyy',
        len_subarg_ids=len(subarg_ids),
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            system_prompt=system_prompt,
            json_schema={},
            temperature=0.3,
            max_tokens=8000,
            provider=provider
        )

        polished = result.get("subargument_paragraphs", [])

        # 验证润色结果：如果 SubArgument 数量不对，回退到原始版本
        if len(polished) != len(subargument_bodies):
            import logging
            logging.getLogger(__name__).warning(
                f"Polish returned {len(polished)} subargs, expected {len(subargument_bodies)}. Using originals."
            )
            return subargument_bodies

        # 将原始的 subargument_id、title、snippet_ids、exhibit_refs 覆盖回去（不信任 LLM）
        for i, body in enumerate(polished):
            body["subargument_id"] = subargument_bodies[i]["subargument_id"]
            body["title"] = subargument_bodies[i].get("title", "")
            # 恢复原始 snippet_ids 和 exhibit_refs（按句子索引一一对应）
            original_sents = subargument_bodies[i].get("sentences", [])
            polished_sents = body.get("sentences", [])
            for j, psent in enumerate(polished_sents):
                if j < len(original_sents):
                    psent["snippet_ids"] = original_sents[j].get("snippet_ids", [])
                    psent["exhibit_refs"] = original_sents[j].get("exhibit_refs", [])

        return polished

    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Polish failed, using originals: {e}")
        return subargument_bodies


async def _step3_generate_section_frame(
    standard: Dict,
    arguments: List[Dict],
    provider: str = "deepseek",
    project_type: str = "EB-1A"
) -> Dict:
    """
    Step 3: 生成段落的 opening 和 closing 句子。

    看到所有 Argument + SubArgument 的标题来写全局性的首尾。

    Returns:
        {"opening_text": str, "closing_text": str}
    """
    # 构建 Argument/SubArgument 概要
    summary_lines = []
    for arg in arguments:
        summary_lines.append(f"  Argument: {arg.get('title', '')}")
        for sa in arg.get("sub_arguments", []):
            summary_lines.append(f"    - {sa.get('title', '')}")
    summary_text = "\n".join(summary_lines)

    strategy = get_writing_strategy(project_type, standard.get("key", ""))
    system_prompt = strategy.frame_system_prompt

    user_prompt = _prompt_render("writer/step3_generate_section_frame_user_prompt",
        standard_get_name=standard.get('name', ''),
        standard_get_legal_ref=standard.get('legal_ref', ''),
        summary_text=summary_text,
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            system_prompt=system_prompt,
            json_schema={},
            temperature=0.4,
            max_tokens=1000,
            provider=provider
        )
        return {
            "opening_text": result.get("opening_text", ""),
            "closing_text": result.get("closing_text", "")
        }
    except Exception as e:
        logger.warning(f"Section frame generation failed: {e}")
        legal_ref = standard.get('legal_ref', '')
        name = standard.get('name', '')
        return {
            "opening_text": f"The Beneficiary satisfies {legal_ref} ({name}) as demonstrated by the following evidence.",
            "closing_text": "In sum, the foregoing evidence clearly establishes that the Beneficiary meets this criterion."
        }


def _contains_non_ascii(text: str) -> bool:
    """Check if text contains non-ASCII characters (Chinese, etc.)"""
    if not text:
        return False
    return any(ord(char) > 127 for char in text)


# Note: Removed hardcoded CHINESE_TO_ENGLISH mapping to avoid overfitting.
# The system relies on:
# 1. Prompt Rule 8 requiring 100% English output
# 2. LLM translation as fallback (via _translate_to_english)
# 3. _remove_remaining_chinese() as final safety net


def _remove_remaining_chinese(text: str) -> str:
    """Remove any remaining Chinese characters after known replacements."""
    if not text:
        return text

    # Remove characters that are clearly Chinese (CJK unified ideographs range)
    # Range: \u4e00-\u9fff covers most common Chinese characters
    cleaned = re.sub(r'[\u4e00-\u9fff]+', '', text)

    # Clean up any leftover empty parentheses
    cleaned = re.sub(r'\(\s*\)', '', cleaned)
    cleaned = re.sub(r'\s+', ' ', cleaned)  # Normalize spaces

    return cleaned.strip()


async def _translate_to_english(text: str, provider: str = "deepseek") -> str:
    """
    Translate non-English text to English using LLM.
    Generic solution - no hardcoded mappings.
    """
    if not _contains_non_ascii(text):
        return text

    # Try LLM translation
    try:
        prompt = _prompt_render("writer/translate_to_english_prompt",
            text=text,
        )

        llm_result = await call_llm_text(
            prompt=prompt,
            system_prompt="You are a professional translator. Translate to English while preserving legal document formatting.",
            temperature=0.3,
            max_tokens=2000,
            provider=provider
        )

        if llm_result and not _contains_non_ascii(llm_result):
            return llm_result.strip()
    except Exception as e:
        logger.warning(f"[ensure_english] LLM translation failed: {e}")
    # Fallback: Remove remaining Chinese characters
    return _remove_remaining_chinese(text)


async def ensure_english_output(llm_output: Dict) -> Dict:
    """
    Post-process LLM output to ensure 100% English.
    Translates any remaining non-English text while preserving structure.
    """
    if not llm_output:
        return llm_output

    # Check and translate opening sentence
    if "opening_sentence" in llm_output:
        opening = llm_output["opening_sentence"]
        if isinstance(opening, dict) and "text" in opening:
            if _contains_non_ascii(opening["text"]):
                opening["text"] = await _translate_to_english(opening["text"])

    # Check and translate subargument paragraphs
    if "subargument_paragraphs" in llm_output:
        for para in llm_output["subargument_paragraphs"]:
            if "sentences" in para:
                for sentence in para["sentences"]:
                    if "text" in sentence and _contains_non_ascii(sentence["text"]):
                        sentence["text"] = await _translate_to_english(sentence["text"])

    # Check and translate closing sentence
    if "closing_sentence" in llm_output:
        closing = llm_output["closing_sentence"]
        if isinstance(closing, dict) and "text" in closing:
            if _contains_non_ascii(closing["text"]):
                closing["text"] = await _translate_to_english(closing["text"])

    return llm_output


# ============================================
# 溯源回填：从文本中解析 Exhibit 引用，反查 snippet
# ============================================

# Pattern: matches "Exhibit X, p.Y" anywhere (handles [Exhibit D1, p.1; Exhibit D4, p.1])
_EXHIBIT_REF_PATTERN = re.compile(r'Exhibit\s+([A-Za-z0-9-]+),\s*pp?\.?\s*(\d+)')
_EXHIBIT_REF_RANGE_PATTERN = re.compile(r'Exhibit\s+([A-Za-z0-9-]+),\s*pp\.?\s*(\d+)\s*-\s*(\d+)')


def _backfill_snippet_ids(
    sentences: List[Dict],
    snippet_registry: List[Dict],
    allowed_snippet_ids_by_subarg: Optional[Dict[str, set]] = None
) -> int:
    """
    对 snippet_ids 为空的句子，从文本中解析 [Exhibit X, p.Y] 引用，
    反查 snippet registry 回填 snippet_id。

    这是确定性后处理，不依赖 LLM——溯源链由代码保证。

    Args:
        sentences: [{"text", "snippet_ids", "exhibit_refs", ...}]
        snippet_registry: snippet 列表，每个包含 {snippet_id, exhibit_id, page}
        allowed_snippet_ids_by_subarg: 如果提供，回填时只保留该 subargument 已有的 snippet_ids
            (exploration_writing=False 时使用)

    Returns:
        回填的句子数量

    Mutates sentences in-place.
    """
    if not snippet_registry:
        return 0

    # Build lookup: (exhibit_id, page) -> [snippet_ids]
    exhibit_page_to_snippets: Dict[tuple, List[str]] = defaultdict(list)
    for snip in snippet_registry:
        key = (snip.get("exhibit_id", ""), snip.get("page", 0))
        exhibit_page_to_snippets[key].append(snip.get("snippet_id", ""))

    backfilled = 0
    for sent in sentences:
        if sent.get("sentence_type") in ("opening", "closing"):
            continue  # Opening/closing don't need snippet tracing

        existing_ids = sent.get("snippet_ids", [])
        if existing_ids:
            continue  # LLM 已提供 snippet_ids — 信任 LLM 的选择，不做增补

        text = sent.get("text", "")
        refs = _EXHIBIT_REF_PATTERN.findall(text)

        # Also parse page ranges like "pp.2-3" → expand to individual pages
        for exhibit_id, start_p, end_p in _EXHIBIT_REF_RANGE_PATTERN.findall(text):
            for p in range(int(start_p), int(end_p) + 1):
                pair = (exhibit_id, str(p))
                if pair not in refs:
                    refs.append(pair)

        # Also parse from exhibit_refs field (LLM may fill this even when text lacks inline citations)
        for ref_str in sent.get("exhibit_refs", []):
            extra_refs = _EXHIBIT_REF_PATTERN.findall(ref_str)
            for er in extra_refs:
                if er not in refs:
                    refs.append(er)
            # Handle page ranges in exhibit_refs too
            for exhibit_id, start_p, end_p in _EXHIBIT_REF_RANGE_PATTERN.findall(ref_str):
                for p in range(int(start_p), int(end_p) + 1):
                    pair = (exhibit_id, str(p))
                    if pair not in refs:
                        refs.append(pair)

        if not refs:
            continue

        # Match refs to snippets
        matched_ids = []
        matched_exhibit_refs = []
        for exhibit_id, page_str in refs:
            page = int(page_str)
            key = (exhibit_id, page)
            snip_ids = exhibit_page_to_snippets.get(key, [])
            matched_ids.extend(snip_ids)
            matched_exhibit_refs.append(f"{exhibit_id}-{page}")

        if matched_ids:
            # Deduplicate while preserving order
            seen = set()
            unique_ids = []
            for sid in matched_ids:
                if sid not in seen:
                    seen.add(sid)
                    unique_ids.append(sid)

            # Filter by allowed set when exploration_writing is OFF
            if allowed_snippet_ids_by_subarg is not None:
                subarg_id = sent.get("subargument_id")
                if subarg_id and subarg_id in allowed_snippet_ids_by_subarg:
                    allowed = allowed_snippet_ids_by_subarg[subarg_id]
                    unique_ids = [sid for sid in unique_ids if sid in allowed]
                elif subarg_id:
                    # SubArgument has no snippets at all — skip backfill
                    unique_ids = []

            if not unique_ids:
                continue

            sent["snippet_ids"] = unique_ids
            if not sent.get("exhibit_refs"):
                sent["exhibit_refs"] = matched_exhibit_refs
            backfilled += 1

    return backfilled


def _inject_exhibit_citations(sentences: List[Dict]) -> int:
    """
    对有 exhibit_refs 但文本中缺少 [Exhibit X] 引用的句子，
    将引用追加到句尾。已有引用的句子跳过。

    Returns: 注入的句子数量
    Mutates sentences in-place.
    """
    injected = 0
    for sent in sentences:
        exhibit_refs = sent.get("exhibit_refs", [])
        if not exhibit_refs:
            continue
        text = sent.get("text", "")
        # 已经有 [Exhibit ...] 引用的跳过
        if re.search(r'\[Exhibit\s+[A-Za-z0-9]', text):
            continue
        # 跳过 opening/closing
        if sent.get("sentence_type") in ("opening", "closing"):
            continue

        # 构建引用标记，如 [Exhibit A1, p.2; Exhibit B1, p.3]
        # exhibit_refs 格式可能是 "A1-2", "Exhibit A1, p.2", "A1" 等，统一处理
        formatted = []
        for ref in exhibit_refs:
            ref = ref.strip()
            if ref.startswith("Exhibit "):
                formatted.append(ref)
            elif "-" in ref:
                # "A1-2" -> "Exhibit A1, p.2"
                parts = ref.rsplit("-", 1)
                formatted.append(f"Exhibit {parts[0]}, p.{parts[1]}")
            else:
                formatted.append(f"Exhibit {ref}")
        # 去重保持顺序
        seen = set()
        unique = []
        for f in formatted:
            if f not in seen:
                seen.add(f)
                unique.append(f)

        citation = "[" + "; ".join(unique) + "]"

        # 追加到句尾：句号前插入
        text = text.rstrip()
        if text.endswith("."):
            sent["text"] = text[:-1] + " " + citation + "."
        else:
            sent["text"] = text + " " + citation + "."
        injected += 1

    return injected


# ============================================
# 验证和修正函数
# ============================================

def validate_provenance(
    llm_output: Dict,
    context: Dict
) -> Dict:
    """
    验证 LLM 输出的溯源信息

    Returns:
        {
            "is_valid": bool,
            "errors": [...],
            "warnings": [...],
            "fixed_output": {...}
        }
    """
    errors = []
    warnings = []

    # 构建有效的 snippet_id 集合（支持新旧两种格式）
    valid_snippet_ids = set()
    subarg_snippet_map = {}  # subargument_id -> set of snippet_ids
    original_to_new = {}  # old_id -> new_id 映射

    for arg in context.get("arguments", []):
        for subarg in arg.get("sub_arguments", []):
            subarg_id = subarg["id"]
            snippet_ids = set()
            for s in subarg.get("snippets", []):
                new_id = s["id"]
                snippet_ids.add(new_id)
                # 如果有原始 ID，也添加映射
                if s.get("original_id") and s["original_id"] != new_id:
                    original_to_new[s["original_id"]] = new_id
                    valid_snippet_ids.add(s["original_id"])

            subarg_snippet_map[subarg_id] = snippet_ids
            valid_snippet_ids.update(snippet_ids)

    # 验证 subargument_paragraphs
    fixed_paragraphs = []
    for para in llm_output.get("subargument_paragraphs", []):
        subarg_id = para.get("subargument_id", "")

        # 检查 subargument_id 是否有效
        if subarg_id not in subarg_snippet_map:
            warnings.append(f"Unknown subargument_id: {subarg_id}")
            continue

        valid_for_subarg = subarg_snippet_map.get(subarg_id, set())
        fixed_sentences = []

        for sent in para.get("sentences", []):
            snippet_ids = sent.get("snippet_ids", [])

            # 标准化 snippet_ids（将旧格式转换为新格式）
            normalized_ids = []
            for sid in snippet_ids:
                if sid in original_to_new:
                    normalized_ids.append(original_to_new[sid])
                else:
                    normalized_ids.append(sid)

            # 过滤无效的 snippet_ids
            valid_ids = [sid for sid in normalized_ids if sid in valid_snippet_ids]
            invalid_ids = [sid for sid in normalized_ids if sid not in valid_snippet_ids]

            if invalid_ids:
                warnings.append(f"Removed invalid snippet_ids: {invalid_ids}")

            # 检查 snippet 是否属于该 SubArgument
            out_of_scope = [sid for sid in valid_ids if sid not in valid_for_subarg]
            if out_of_scope:
                warnings.append(
                    f"Snippet {out_of_scope} referenced but not in SubArgument {subarg_id}"
                )

            fixed_sentences.append({
                "text": sent.get("text", ""),
                "snippet_ids": valid_ids,
                "exhibit_refs": sent.get("exhibit_refs", [])
            })

        fixed_paragraphs.append({
            "subargument_id": subarg_id,
            "sentences": fixed_sentences
        })

    # 构建修正后的输出
    fixed_output = {
        "argument_id": llm_output.get("argument_id", ""),
        "opening_sentence": llm_output.get("opening_sentence", {"text": "", "snippet_ids": []}),
        "subargument_paragraphs": fixed_paragraphs,
        "closing_sentence": llm_output.get("closing_sentence", {"text": ""})
    }

    is_valid = len(errors) == 0

    return {
        "is_valid": is_valid,
        "errors": errors,
        "warnings": warnings,
        "fixed_output": fixed_output
    }


def build_provenance_index(
    validated_output: Dict,
    context: Dict
) -> Dict:
    """
    构建溯源索引

    Returns:
        {
            "by_subargument": {"subarg-xxx": [0, 1, 2], ...},
            "by_argument": {"arg-xxx": [0, 1, 2, 3], ...},
            "by_snippet": {"snp_xxx": [0, 2], ...}
        }
    """
    by_subargument = defaultdict(list)
    by_argument = defaultdict(list)
    by_snippet = defaultdict(list)

    argument_id = validated_output.get("argument_id", "")
    sentence_index = 0

    # Opening sentence
    opening = validated_output.get("opening_sentence", {})
    if opening.get("text"):
        by_argument[argument_id].append(sentence_index)
        sentence_index += 1

    # SubArgument paragraphs
    for para in validated_output.get("subargument_paragraphs", []):
        subarg_id = para.get("subargument_id", "")

        for sent in para.get("sentences", []):
            by_subargument[subarg_id].append(sentence_index)
            by_argument[argument_id].append(sentence_index)

            for snip_id in sent.get("snippet_ids", []):
                by_snippet[snip_id].append(sentence_index)

            sentence_index += 1

    # Closing sentence
    closing = validated_output.get("closing_sentence", {})
    if closing.get("text"):
        by_argument[argument_id].append(sentence_index)

    return {
        "by_subargument": dict(by_subargument),
        "by_argument": dict(by_argument),
        "by_snippet": dict(by_snippet)
    }


def flatten_sentences(
    validated_output: Dict,
    context: Dict
) -> List[Dict]:
    """
    将结构化输出扁平化为句子列表

    Returns:
        [
            {
                "text": str,
                "snippet_ids": [...],
                "subargument_id": str,
                "argument_id": str,
                "exhibit_refs": [...],
                "sentence_type": "opening" | "body" | "closing"
            }
        ]
    """
    argument_id = validated_output.get("argument_id", "")
    sentences = []

    # Opening sentence
    opening = validated_output.get("opening_sentence", {})
    if opening.get("text"):
        sentences.append({
            "text": opening.get("text", ""),
            "snippet_ids": opening.get("snippet_ids", []),
            "subargument_id": None,
            "argument_id": argument_id,
            "exhibit_refs": [],
            "sentence_type": "opening"
        })

    # SubArgument paragraphs
    for para in validated_output.get("subargument_paragraphs", []):
        subarg_id = para.get("subargument_id", "")

        for sent in para.get("sentences", []):
            sentences.append({
                "text": sent.get("text", ""),
                "snippet_ids": sent.get("snippet_ids", []),
                "subargument_id": subarg_id,
                "argument_id": argument_id,
                "exhibit_refs": sent.get("exhibit_refs", []),
                "sentence_type": "body"
            })

    # Closing sentence
    closing = validated_output.get("closing_sentence", {})
    if closing.get("text"):
        sentences.append({
            "text": closing.get("text", ""),
            "snippet_ids": [],
            "subargument_id": None,
            "argument_id": argument_id,
            "exhibit_refs": [],
            "sentence_type": "closing"
        })

    return sentences


# ============================================
# 主入口函数
# ============================================

def _build_provenance_from_sentences(sentences: List[Dict]) -> Dict:
    """
    从扁平句子列表构建溯源索引。

    与 build_provenance_index() 不同，此函数直接从句子列表读取
    argument_id（支持多 Argument 场景），不依赖单一顶层 argument_id。
    """
    by_subargument = defaultdict(list)
    by_argument = defaultdict(list)
    by_snippet = defaultdict(list)

    for idx, sent in enumerate(sentences):
        subarg_id = sent.get("subargument_id")
        if subarg_id:
            by_subargument[subarg_id].append(idx)

        arg_id = sent.get("argument_id")
        if arg_id:
            by_argument[arg_id].append(idx)

        for snip_id in sent.get("snippet_ids", []):
            by_snippet[snip_id].append(idx)

    return {
        "by_subargument": dict(by_subargument),
        "by_argument": dict(by_argument),
        "by_snippet": dict(by_snippet)
    }



# ============================================
# Step 1 checkpoints (M10)
# ============================================

def _step1_fingerprint(argument: Dict, provider: str, project_type: str,
                       additional_instructions: Optional[str], cross_prong_context: Optional[str]) -> str:
    """Structural fingerprint of one Argument's Step-1 request."""
    payload = {
        "id": argument.get("id"),
        "title": argument.get("title"),
        "sub_arguments": [
            {"id": sa.get("id"), "title": sa.get("title"), "purpose": sa.get("purpose"),
             "relationship": sa.get("relationship"),
             "snippets": sorted(s.get("id", "") for s in sa.get("snippets", []))}
            for sa in argument.get("sub_arguments", [])
        ],
        "provider": provider, "project_type": project_type,
        "additional_instructions": additional_instructions or "",
        "cross_prong_context": cross_prong_context or "",
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:20]


def _checkpoint_path(project_id: str, standard_key: str, fp: str) -> Path:
    return project_path(project_id, "writing_v3", "checkpoints", f"{standard_key}_{fp}.json")


def _load_step1_checkpoint(project_id: str, standard_key: str, fp: str) -> Optional[List[Dict]]:
    data = read_json(_checkpoint_path(project_id, standard_key, fp))
    if isinstance(data, dict) and isinstance(data.get("bodies"), list) and data["bodies"]:
        return data["bodies"]
    return None


def _save_step1_checkpoint(project_id: str, standard_key: str, fp: str, bodies: List[Dict]) -> None:
    try:
        write_json(_checkpoint_path(project_id, standard_key, fp),
                   {"fingerprint": fp, "saved_at": datetime.now(timezone.utc).isoformat(), "bodies": bodies})
    except Exception as e:  # checkpoints are an optimisation, never fatal
        logger.warning(f"Step1 checkpoint save failed: {e}")


async def write_petition_section_v3(
    project_id: str,
    standard_key: str,
    argument_ids: List[str] = None,
    subargument_ids: List[str] = None,
    additional_instructions: str = None,
    provider: str = "deepseek",
    exploration_writing: bool = False,
    job=None,
    use_checkpoints: bool = True,
) -> Dict:
    """
    V3.1 版本的写作入口 — OCR 回溯三步流水线

    Step 1: 逐 Argument 生成正文（LLM 看到完整 OCR 原文 + SubArgument 大纲）
    Step 2: 逐 Argument 润色整合（加过渡句，保持连贯性）
    Step 3: 生成全局 Opening/Closing（引用法规 + 总结）

    Args:
        project_id: 项目 ID
        standard_key: 标准 key (如 "membership", "leading_role")
        argument_ids: 可选，指定要生成的 Argument IDs
        subargument_ids: 可选，指定要生成的 SubArgument IDs（用于局部重新生成）
        additional_instructions: 可选，额外指令
        job: 可选 JobHandle（M10）——每个 Argument 边界 checkpoint 进度 / 协作式取消
        use_checkpoints: Step 1 每个 Argument 的产出即时落盘为 checkpoint；
            结构指纹相同时直接复用，重试 Step 2/3 不必重烧最贵的 Step 1
    """
    from ..core.jobs import NullJob
    job = job or NullJob()

    # Detect project_type
    try:
        from .storage import get_project_type
        project_type = get_project_type(project_id)
    except Exception:
        project_type = "EB-1A"

    # Resolve strategy once, pass down
    strategy = get_writing_strategy(project_type, standard_key)

    # 0. 加载上下文 (now with project_type for legal_ref resolution)
    context = load_subargument_context(
        project_id, standard_key, argument_ids, subargument_ids,
        project_type=project_type
    )

    if not context.get("arguments"):
        return {
            "success": False,
            "error": f"No arguments found for standard: {standard_key}",
            "section": standard_key,
            "paragraph_text": "",
            "sentences": []
        }

    all_arguments = context["arguments"]
    standard = context["standard"]
    all_warnings = []

    # Build snippet map for OCR loading
    snippet_map = {}
    for arg in all_arguments:
        for sa in arg.get("sub_arguments", []):
            for snip in sa.get("snippets", []):
                snippet_map[snip["id"]] = snip

    # ========== Step 1: 逐 Argument 生成正文（OCR 回溯） ==========
    per_argument_bodies: List[List[Dict]] = []  # [[{subargument_id, title, sentences}]]
    per_argument_refs: List[Dict] = []

    # Cross-section context (e.g. NIW Prong 3 references Prong 1 & 2)
    cross_prong_context = None
    cross_prong_exhibit_texts: Dict[str, str] = {}
    if strategy.cross_section_context:
        cross_prong_context = _build_cross_prong_summary(project_id, standard_key)
        cross_prong_exhibit_texts = _load_cross_prong_exhibits(project_id, standard_key)
        if cross_prong_context:
            logger.info(
                f"Step1: Loaded cross-section context + "
                f"{len(cross_prong_exhibit_texts)} cross-prong exhibits"
            )

    total_args = len(all_arguments)
    for arg_index, argument in enumerate(all_arguments):
        arg_id = argument.get("id", "")
        sub_arguments = argument.get("sub_arguments", [])
        job.checkpoint(step="step1", detail=f"Step 1/3: Argument {arg_index + 1}/{total_args}",
                       progress=0.05 + 0.60 * arg_index / max(total_args, 1))

        if not sub_arguments:
            all_warnings.append(f"Skipped argument {arg_id}: no sub_arguments")
            continue

        # Step 1 checkpoint: keyed by a fingerprint of the argument's structure
        # (ids, titles, snippet ids) + generation params. A hit means the exact
        # same request was already answered -- reuse it instead of paying again.
        ckpt_fp = _step1_fingerprint(argument, provider, project_type, additional_instructions, cross_prong_context)
        cached_bodies = _load_step1_checkpoint(project_id, standard_key, ckpt_fp) if use_checkpoints else None
        if cached_bodies:
            logger.info(f"Step1: checkpoint hit for argument {arg_id} ({ckpt_fp})")
            per_argument_bodies.append(cached_bodies)
            per_argument_refs.append(argument)
            continue

        # Load OCR pages for all exhibits referenced by this argument
        exhibit_texts = load_exhibit_pages_for_argument(project_id, argument, snippet_map)
        # Merge cross-prong exhibits (don't overwrite prong3's own)
        for eid, text in cross_prong_exhibit_texts.items():
            if eid not in exhibit_texts:
                exhibit_texts[eid] = text
        logger.info(
            f"Step1: Generating body for argument {arg_id} "
            f"({len(sub_arguments)} subargs, {len(exhibit_texts)} exhibits loaded)"
        )

        # Generate body at argument level with full OCR context
        arg_bodies = await _step1_generate_argument_body(
            project_id=project_id,
            standard=standard,
            argument=argument,
            exhibit_texts=exhibit_texts,
            additional_instructions=additional_instructions,
            provider=provider,
            project_type=project_type,
            cross_prong_context=cross_prong_context
        )

        if not arg_bodies:
            all_warnings.append(f"No content generated for argument {arg_id}")
            continue

        # 确保英文
        for body in arg_bodies:
            for sent in body.get("sentences", []):
                if _contains_non_ascii(sent.get("text", "")):
                    sent["text"] = await _translate_to_english(sent["text"], provider=provider)
                    if _contains_non_ascii(sent["text"]):
                        sent["text"] = _remove_remaining_chinese(sent["text"])

        if use_checkpoints:
            _save_step1_checkpoint(project_id, standard_key, ckpt_fp, arg_bodies)

        per_argument_bodies.append(arg_bodies)
        per_argument_refs.append(argument)

    if not per_argument_bodies:
        return {
            "success": False,
            "error": f"No content generated for standard: {standard_key}",
            "section": standard_key,
            "paragraph_text": "",
            "sentences": []
        }

    # ========== Step 2: 逐 Argument 润色整合 ==========
    polished_bodies: List[List[Dict]] = []

    for i, arg_bodies in enumerate(per_argument_bodies):
        argument_ref = per_argument_refs[i]
        job.checkpoint(step="step2", detail=f"Step 2/3: Polishing {i + 1}/{len(per_argument_bodies)}",
                       progress=0.65 + 0.20 * i / max(len(per_argument_bodies), 1))
        logger.info(f"Step2: Polishing argument group {i+1}/{len(per_argument_bodies)} ({len(arg_bodies)} subargs, arg={argument_ref.get('id', '')})")

        polished = await _step2_polish_argument(
            standard=standard,
            argument=argument_ref,
            subargument_bodies=arg_bodies,
            provider=provider,
            project_type=project_type
        )

        # 确保润色后的文本也是英文
        for body in polished:
            for sent in body.get("sentences", []):
                if _contains_non_ascii(sent.get("text", "")):
                    sent["text"] = _remove_remaining_chinese(sent["text"])

        polished_bodies.append(polished)

    # ========== Step 3: 生成 Opening/Closing ==========
    job.checkpoint(step="step3", detail="Step 3/3: Opening/closing", progress=0.88)
    logger.info("Step3: Generating opening/closing")
    frame = await _step3_generate_section_frame(
        standard=standard,
        arguments=all_arguments,
        provider=provider,
        project_type=project_type
    )

    # 确保英文
    for key in ("opening_text", "closing_text"):
        if _contains_non_ascii(frame.get(key, "")):
            frame[key] = _remove_remaining_chinese(frame[key])

    # ========== 组装最终句子列表 ==========
    all_sentences = []

    # Opening
    all_sentences.append({
        "text": frame["opening_text"],
        "snippet_ids": [],
        "subargument_id": None,
        "argument_id": all_arguments[0].get("id", ""),
        "exhibit_refs": [],
        "sentence_type": "opening"
    })

    # Body: 按 Argument → SubArgument 顺序
    for arg_idx, arg_polished in enumerate(polished_bodies):
        arg_id = per_argument_refs[arg_idx].get("id", "") if arg_idx < len(per_argument_refs) else ""

        for body in arg_polished:
            subarg_id = body["subargument_id"]
            for sent in body.get("sentences", []):
                all_sentences.append({
                    "text": sent.get("text", ""),
                    "snippet_ids": sent.get("snippet_ids", []),
                    "subargument_id": subarg_id,
                    "argument_id": arg_id,
                    "exhibit_refs": sent.get("exhibit_refs", []),
                    "sentence_type": "body"
                })

    # Closing
    all_sentences.append({
        "text": frame["closing_text"],
        "snippet_ids": [],
        "subargument_id": None,
        "argument_id": all_arguments[-1].get("id", ""),
        "exhibit_refs": [],
        "sentence_type": "closing"
    })

    # Post-process: strip leaked analytical labels from all sentences
    for sent in all_sentences:
        sent["text"] = _strip_leaked_labels(sent.get("text", ""))

    # 溯源校验：重新校验 snippet_ids 合法性
    # Include all snippet IDs from referenced exhibits (not just subargument pointers)
    # since step1 now gives LLM a full snippet index for block-level citation
    valid_snippet_ids = set()
    referenced_exhibits = set()
    for arg in all_arguments:
        for sa in arg.get("sub_arguments", []):
            for snip in sa.get("snippets", []):
                valid_snippet_ids.add(snip["id"])
                referenced_exhibits.add(snip.get("exhibit", ""))
    # Expand with all registry snippets on referenced exhibits
    assembly_registry = _load_snippet_source(project_id)
    for snip in assembly_registry:
        if snip.get("exhibit_id") in referenced_exhibits:
            valid_snippet_ids.add(snip.get("snippet_id", ""))

    for sent in all_sentences:
        original_ids = sent.get("snippet_ids", [])
        valid_ids = [sid for sid in original_ids if sid in valid_snippet_ids]
        removed_ids = [sid for sid in original_ids if sid not in valid_snippet_ids]
        if removed_ids:
            sent["_removed_ids"] = removed_ids
            all_warnings.append(f"Removed {len(removed_ids)} invalid snippet_ids from sentence")
        sent["snippet_ids"] = valid_ids

    # Layer 2: 文本匹配恢复 — 被校验删除的 snippet_ids，尝试通过文本相似度找到有效替代
    snippet_registry = _load_snippet_source(project_id)
    text_recovered_count = 0
    for sent in all_sentences:
        if sent.get("snippet_ids"):
            continue  # 已有有效 ID，跳过
        removed_ids = sent.get("_removed_ids", [])
        if removed_ids:
            recovered = _recover_snippet_ids_by_text(removed_ids, snippet_registry, valid_snippet_ids)
            if recovered:
                sent["snippet_ids"] = recovered
                text_recovered_count += len(recovered)
    if text_recovered_count:
        logger.info(f"Layer 2 text-match: recovered {text_recovered_count} snippet_ids")

    # Layer 3: LLM 匹配恢复 — 仍然为空的证据性句子，调用 LLM 将句子与候选 snippet 配对
    llm_recovered_count = 0
    for sent in all_sentences:
        if sent.get("snippet_ids") or sent.get("sentence_type") in ("opening", "closing"):
            continue
        # Get candidate snippets from referenced exhibits
        exhibit_snippets = [s for s in snippet_registry if s.get("exhibit_id") in referenced_exhibits]
        if not exhibit_snippets:
            continue
        recovered = await _recover_snippet_ids_by_llm(sent["text"], exhibit_snippets, provider)
        if recovered:
            sent["snippet_ids"] = recovered
            llm_recovered_count += len(recovered)
    if llm_recovered_count:
        logger.info(f"Layer 3 LLM-match: recovered {llm_recovered_count} snippet_ids")

    # Clean up temporary _removed_ids
    for sent in all_sentences:
        sent.pop("_removed_ids", None)

    # 溯源回填：对 snippet_ids 为空的句子，从文本中解析 exhibit 引用反查 snippet

    # Build allowed snippet set per subargument (exploration OFF → restrict backfill)
    allowed_snippet_ids_by_subarg = None
    if not exploration_writing:
        allowed_snippet_ids_by_subarg = {}
        for arg in all_arguments:
            for sa in arg.get("sub_arguments", []):
                sa_id = sa.get("id", "")
                sa_snip_ids = set(snip["id"] for snip in sa.get("snippets", []))
                allowed_snippet_ids_by_subarg[sa_id] = sa_snip_ids

    # Snapshot original snippet_ids per subargument (for exploration diff)
    original_subarg_snippets: Dict[str, set] = {}
    if exploration_writing:
        for arg in all_arguments:
            for sa in arg.get("sub_arguments", []):
                sa_id = sa.get("id", "")
                original_subarg_snippets[sa_id] = set(
                    snip["id"] for snip in sa.get("snippets", [])
                )

    backfilled_count = _backfill_snippet_ids(all_sentences, snippet_registry, allowed_snippet_ids_by_subarg)
    if backfilled_count:
        logger.info(f"Backfilled snippet_ids for {backfilled_count} sentences via exhibit ref parsing")

    # Exploration writing: discover new snippets and persist to legal_arguments.json
    # backfill 只对 LLM 没给 snippet_ids 的句子做回填（从文中 [Exhibit X, p.Y] 反查），
    # 不会对已有 snippet_ids 的句子做增补，所以这里读 post-backfill 结果是精确的。
    updated_subargument_snippets = None
    if exploration_writing:
        # Collect all snippet_ids per subargument from generated sentences
        current_subarg_snippets: Dict[str, set] = defaultdict(set)
        for sent in all_sentences:
            sa_id = sent.get("subargument_id")
            if sa_id:
                for sid in sent.get("snippet_ids", []):
                    current_subarg_snippets[sa_id].add(sid)

        # Find newly discovered snippet_ids
        new_snippets_map: Dict[str, List[str]] = {}
        for sa_id, current_ids in current_subarg_snippets.items():
            original_ids = original_subarg_snippets.get(sa_id, set())
            new_ids = current_ids - original_ids
            if new_ids:
                new_snippets_map[sa_id] = sorted(new_ids)

        if new_snippets_map:
            logger.info(f"Exploration writing: discovered new snippets for {len(new_snippets_map)} subarguments")
            # Persist to legal_arguments.json
            try:
                from .snippet_recommender import update_legal_arguments
                def _mutate(legal_data):

                    for sa_data in legal_data.get("sub_arguments", []):
                        sa_id = sa_data.get("id", "")
                        if sa_id in new_snippets_map:
                            existing_ids = set(sa_data.get("snippet_ids", []))
                            for new_sid in new_snippets_map[sa_id]:
                                if new_sid not in existing_ids:
                                    sa_data.setdefault("snippet_ids", []).append(new_sid)

                    return legal_data

                update_legal_arguments(project_id, _mutate)
                logger.info("Persisted new snippet associations to legal_arguments.json")
            except Exception as e:
                logger.warning(f"Failed to persist exploration snippets: {e}")

            # Return the full updated snippet list per subargument (not just new ones)
            updated_subargument_snippets = {}
            for sa_id in new_snippets_map:
                updated_subargument_snippets[sa_id] = sorted(current_subarg_snippets[sa_id])

    # 确保文本中包含 [Exhibit X] 引用：如果 exhibit_refs 有值但文本中没有，追加到句尾
    injected_count = _inject_exhibit_citations(all_sentences)
    if injected_count:
        logger.info(f"Injected exhibit citations into {injected_count} sentences")

    # 构建溯源索引
    provenance_index = _build_provenance_from_sentences(all_sentences)

    # 组装段落文本
    paragraph_text = " ".join(s["text"] for s in all_sentences)
    # Final safety net: strip leaked labels from assembled paragraph
    paragraph_text = _strip_leaked_labels(paragraph_text)

    # 统计
    total_sentences = len(all_sentences)
    traced_sentences = sum(
        1 for s in all_sentences
        if s.get("snippet_ids") or s.get("subargument_id")
    )

    result = {
        "success": True,
        "section": standard_key,
        "paragraph_text": paragraph_text,
        "sentences": all_sentences,
        "provenance_index": provenance_index,
        "validation": {
            "total_sentences": total_sentences,
            "traced_sentences": traced_sentences,
            "warnings": all_warnings
        }
    }
    if updated_subargument_snippets:
        result["updated_subargument_snippets"] = updated_subargument_snippets
    return result


# ============================================
# 存储函数
# ============================================

def save_writing_v3(
    project_id: str,
    section: str,
    result: Dict
) -> str:
    """保存 V3 写作结果"""
    project_dir = project_path(project_id)
    writing_dir = project_dir / "writing_v3"
    writing_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc)
    version_id = timestamp.strftime("%Y%m%d_%H%M%S")

    data = {
        "version_id": version_id,
        "timestamp": timestamp.isoformat(),
        **result
    }

    filename = f"writing_{section}_{version_id}.json"
    write_json(writing_dir / filename, data)

    return version_id


def load_latest_writing_v3(
    project_id: str,
    section: str,
    full_only: bool = True,
) -> Optional[Dict]:
    """加载最新的 V3 写作结果

    ``full_only`` (default) skips versions saved by a partial regeneration
    (``subargument_ids`` requests, marked ``partial: true``): those hold only
    the regenerated SubArgument's sentences and are not a complete section.
    The complete section is what the client persists via PUT .../sentences
    once the user accepts the regeneration (M13 diff view).
    """
    writing_dir = project_path(project_id, "writing_v3")
    if not writing_dir.exists():
        return None

    files = sorted(writing_dir.glob(f"writing_{section}_*.json"), reverse=True)
    for path in files:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if full_only and data.get("partial"):
            continue
        return data
    return None


# ============================================
# SubArgument 变更级联函数
# ============================================

def remove_subargument_from_writing(
    project_id: str, subargument_id: str, standard_key: str
) -> Dict:
    """
    从 writing_v3 文件中移除 SubArgument 的句子，重建索引，保存新版本。

    Returns:
        {
          "changed": bool,
          "removed_indices": [int],
          "new_sentences": [...],
          "new_paragraph_text": str
        }
    """
    existing = load_latest_writing_v3(project_id, standard_key)
    if not existing:
        return {"changed": False, "removed_indices": [], "new_sentences": [], "new_paragraph_text": ""}

    sentences = existing.get("sentences", [])
    if not sentences:
        return {"changed": False, "removed_indices": [], "new_sentences": [], "new_paragraph_text": ""}

    # Find indices of sentences belonging to this SubArgument
    removed_indices = [
        i for i, s in enumerate(sentences)
        if s.get("subargument_id") == subargument_id
    ]

    if not removed_indices:
        return {"changed": False, "removed_indices": [], "new_sentences": sentences, "new_paragraph_text": existing.get("paragraph_text", "")}

    # Filter out removed sentences
    new_sentences = [s for i, s in enumerate(sentences) if i not in removed_indices]

    # Rebuild provenance_index
    new_provenance = {"by_subargument": {}, "by_argument": {}, "by_snippet": {}}
    for idx, sent in enumerate(new_sentences):
        subarg_id = sent.get("subargument_id")
        if subarg_id:
            new_provenance["by_subargument"].setdefault(subarg_id, []).append(idx)
        arg_id = sent.get("argument_id")
        if arg_id:
            new_provenance["by_argument"].setdefault(arg_id, []).append(idx)
        for snip_id in sent.get("snippet_ids", []):
            new_provenance["by_snippet"].setdefault(snip_id, []).append(idx)

    # Rebuild paragraph text
    new_paragraph_text = " ".join(s["text"] for s in new_sentences)

    # Rebuild validation
    total = len(new_sentences)
    traced = sum(1 for s in new_sentences if s.get("snippet_ids") or s.get("subargument_id"))

    # Build updated result for saving
    updated_result = {
        "section": standard_key,
        "paragraph_text": new_paragraph_text,
        "sentences": new_sentences,
        "provenance_index": new_provenance,
        "validation": {
            "total_sentences": total,
            "traced_sentences": traced,
            "warnings": []
        }
    }

    # Save new version
    save_writing_v3(project_id, standard_key, updated_result)

    return {
        "changed": True,
        "removed_indices": removed_indices,
        "new_sentences": new_sentences,
        "new_paragraph_text": new_paragraph_text
    }


async def analyze_change_impact(
    project_id: str, standard_key: str,
    change_type: str,  # "deletion" | "addition"
    affected_subargument_id: str,
    affected_title: str = "",
    provider: str = "deepseek"
) -> Dict:
    """
    分析 SubArgument 变更对整段文章的间接影响。

    调用 LLM，传入当前文章全文 + 变更描述，
    让 LLM 识别哪些句子需要调整。

    Returns:
        {
          "suggestions": [
            {
              "sentence_index": 0,
              "original_text": "...",
              "suggested_text": "...",
              "reason": "..."
            }
          ]
        }
    """
    existing = load_latest_writing_v3(project_id, standard_key)
    if not existing:
        return {"suggestions": []}

    sentences = existing.get("sentences", [])
    if not sentences:
        return {"suggestions": []}

    # Build indexed text for LLM
    indexed_lines = []
    for i, s in enumerate(sentences):
        stype = s.get("sentence_type", "body")
        indexed_lines.append(f"[{i}] ({stype}) {s['text']}")
    indexed_text = "\n".join(indexed_lines)

    action = "deleted from" if change_type == "deletion" else "added to"

    system_prompt = """You are a legal document editor. Analyze how a structural change to a petition letter section affects the remaining text. Return ONLY valid JSON."""

    user_prompt = _prompt_render("writer/analyze_change_impact_user_prompt",
        action=action,
        change_type=change_type,
        indexed_text=indexed_text,
        change_type_capitalize=change_type.capitalize(),
        affected_title=affected_title,
        affected_subargument_id=affected_subargument_id,
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            system_prompt=system_prompt,
            json_schema={},
            temperature=0.3,
            max_tokens=2000,
            provider=provider
        )

        suggestions = result.get("suggestions", [])

        # Validate suggestion indices
        valid_suggestions = []
        for s in suggestions:
            idx = s.get("sentence_index")
            if isinstance(idx, int) and 0 <= idx < len(sentences):
                valid_suggestions.append(s)

        return {"suggestions": valid_suggestions}

    except Exception as e:
        logger.warning(f"analyze_change_impact failed: {e}")
        return {"suggestions": []}


# ============================================
# AI 辅助编辑函数
# ============================================

async def edit_text_with_instruction(
    project_id: str,
    original_text: str,
    instruction: str,
    conversation_history: List[Dict] = None,
    provider: str = "deepseek"
) -> Dict:
    """
    使用 AI 根据指令编辑文本

    支持多轮对话，根据用户指令修改选中的文本。

    Args:
        project_id: 项目 ID
        original_text: 原始文本
        instruction: 用户编辑指令
        conversation_history: 对话历史 [{"role": str, "content": str}]

    Returns:
        {
            "revised_text": str,
            "explanation": str
        }
    """
    # 构建对话上下文
    history_text = ""
    if conversation_history:
        for msg in conversation_history:
            role = "用户" if msg["role"] == "user" else "助手"
            history_text += f"\n{role}: {msg['content']}"

    system_prompt = _prompt_body("writer/edit_text_with_instruction_system_prompt")

    user_prompt = _prompt_render("writer/edit_text_with_instruction_user_prompt",
        original_text=original_text,
        history_block=f"CONVERSATION HISTORY:{history_text}" if history_text else "",
        instruction=instruction,
    )

    result = await call_llm(
        prompt=user_prompt,
        system_prompt=system_prompt,
        json_schema={},
        temperature=0.3,
        max_tokens=2000,
        provider=provider
    )

    if "error" in result:
        return {
            "revised_text": original_text,
            "explanation": f"Error: {result.get('error')}"
        }

    return {
        "revised_text": result.get("revised_text", original_text),
        "explanation": result.get("explanation", "")
    }
