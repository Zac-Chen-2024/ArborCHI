"""
Legal Argument Organizer - LLM + 法律条例驱动的子论点组织器

核心原则：
1. LLM 理解 8 C.F.R. §204.5(h)(3) 各标准的法律要件
2. 智能选择最有说服力的证据组合
3. 自动过滤弱证据（如普通会员资格）
4. 输出数量与律师例文一致（~7-8个子论点）
"""

import asyncio
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from ..core.atomic_io import write_json
from ..core.prompt_loader import body as _prompt_body
from ..core.prompt_loader import load_data as _prompt_data
from ..core.prompt_loader import render as _prompt_render
from .llm_client import call_llm
from .storage import project_path

logger = logging.getLogger(__name__)

# ==================== EB-1A 法律条例定义 ====================

LEGAL_STANDARDS = {
    "awards": {
        "citation": "8 C.F.R. §204.5(h)(3)(i)",
        "name": "Nationally/Internationally Recognized Awards",
        "requirements": _prompt_body("organizer/eb1a_requirements_awards"),
    },
    "membership": {
        "citation": "8 C.F.R. §204.5(h)(3)(ii)",
        "name": "Membership in Associations",
        "requirements": _prompt_body("organizer/eb1a_requirements_membership"),
    },
    "published_material": {
        "citation": "8 C.F.R. §204.5(h)(3)(iii)",
        "name": "Published Material in Major Media",
        "requirements": _prompt_body("organizer/eb1a_requirements_published_material"),
    },
    "judging": {
        "citation": "8 C.F.R. §204.5(h)(3)(iv)",
        "name": "Judging the Work of Others",
        "requirements": _prompt_body("organizer/eb1a_requirements_judging"),
    },
    "original_contribution": {
        "citation": "8 C.F.R. §204.5(h)(3)(v)",
        "name": "Original Contributions of Major Significance",
        "requirements": _prompt_body("organizer/eb1a_requirements_original_contribution"),
    },
    "scholarly_articles": {
        "citation": "8 C.F.R. §204.5(h)(3)(vi)",
        "name": "Authorship of Scholarly Articles",
        "requirements": _prompt_body("organizer/eb1a_requirements_scholarly_articles"),
    },
    "display": {
        "citation": "8 C.F.R. §204.5(h)(3)(vii)",
        "name": "Display of Work at Exhibitions",
        "requirements": _prompt_body("organizer/eb1a_requirements_display"),
    },
    "leading_role": {
        "citation": "8 C.F.R. §204.5(h)(3)(viii)",
        "name": "Leading/Critical Role for Distinguished Organizations",
        "requirements": _prompt_body("organizer/eb1a_requirements_leading_role"),
    },
    "high_salary": {
        "citation": "8 C.F.R. §204.5(h)(3)(ix)",
        "name": "High Salary or Remuneration",
        "requirements": _prompt_body("organizer/eb1a_requirements_high_salary"),
    },
    "commercial_success": {
        "citation": "8 C.F.R. §204.5(h)(3)(x)",
        "name": "Commercial Success in the Performing Arts",
        "requirements": _prompt_body("organizer/eb1a_requirements_commercial_success"),
    },
    "overall_merits": {
        "citation": "8 C.F.R. §204.5(h)(2) & Kazarian v. USCIS, 596 F.3d 1115 (9th Cir. 2010)",
        "name": "Final Merits Determination — Overall Merits",
        "requirements": _prompt_body("organizer/eb1a_requirements_overall_merits"),
    },
}


# ==================== Prompt Templates ====================

# ==================== NIW 法律条例定义 ====================

NIW_LEGAL_STANDARDS = {
    "prong1_merit": {
        "citation": "Matter of Dhanasar, 26 I&N Dec. 884, 889-890 (AAO 2016), Prong 1",
        "name": "Substantial Merit & National Importance",
        "requirements": _prompt_body("organizer/niw_requirements_prong1_merit"),
    },
    "prong2_positioned": {
        "citation": "Matter of Dhanasar, 26 I&N Dec. 884, 890 (AAO 2016), Prong 2",
        "name": "Well Positioned to Advance the Endeavor",
        "requirements": _prompt_body("organizer/niw_requirements_prong2_positioned"),
    },
    "prong3_balance": {
        "citation": "Matter of Dhanasar, 26 I&N Dec. 884, 890-891 (AAO 2016), Prong 3",
        "name": "Balance of Equities Favors Waiver",
        "requirements": _prompt_body("organizer/niw_requirements_prong3_balance"),
    },
}


# ==================== Prompt Templates ====================

ORGANIZE_SYSTEM_PROMPT = _prompt_body("organizer/organize_system_prompt")

ORGANIZE_USER_PROMPT = _prompt_body("organizer/organize_user_prompt")


NIW_ORGANIZE_SYSTEM_PROMPT = _prompt_body("organizer/niw_organize_system_prompt")


NIW_ORGANIZE_USER_PROMPT = _prompt_body("organizer/niw_organize_user_prompt")


# ==================== NIW v2 Prompts ====================

NIW_CLASSIFY_OTHER_SYSTEM_PROMPT = _prompt_body("organizer/niw_classify_other_system_prompt")

NIW_CLASSIFY_OTHER_USER_PROMPT = _prompt_body("organizer/niw_classify_other_user_prompt")

NIW_PRONG_ORGANIZE_SYSTEM_PROMPT = _prompt_body("organizer/niw_prong_organize_system_prompt")

NIW_PRONG_ORGANIZE_USER_PROMPT = _prompt_body("organizer/niw_prong_organize_user_prompt")


# ==================== L-1A 法律条例定义 ====================

L1A_LEGAL_STANDARDS = {
    "qualifying_relationship": {
        "citation": "INA §101(a)(15)(L); 8 CFR §214.2(l)(1)(ii)",
        "name": "Qualifying Corporate Relationship",
        "requirements": _prompt_body("organizer/l1a_requirements_qualifying_relationship"),
    },
    "doing_business": {
        "citation": "8 CFR §214.2(l)(1)(ii)(H)",
        "name": "Active Business Operations",
        "requirements": _prompt_body("organizer/l1a_requirements_doing_business"),
    },
    "executive_capacity": {
        "citation": "INA §101(a)(44); 8 CFR §214.2(l)(1)(ii)(B)-(C)",
        "name": "Executive/Managerial Capacity in the U.S.",
        "requirements": _prompt_body("organizer/l1a_requirements_executive_capacity"),
    },
    "qualifying_employment": {
        "citation": "8 CFR §214.2(l)(1)(ii)(A)",
        "name": "Qualifying Employment Abroad",
        "requirements": _prompt_body("organizer/l1a_requirements_qualifying_employment"),
    },
}


L1A_ORGANIZE_SYSTEM_PROMPT = _prompt_body("organizer/l1a_organize_system_prompt")


L1A_ORGANIZE_USER_PROMPT = _prompt_body("organizer/l1a_organize_user_prompt")


# ==================== L-1A snippet grouping ====================

L1A_EVIDENCE_TYPE_MAPPING = {
    # Qualifying Relationship
    "corporate_structure": "qualifying_relationship",
    "ownership": "qualifying_relationship",
    "share_transfer": "qualifying_relationship",
    "physical_premises": "qualifying_relationship",
    "investment": "qualifying_relationship",
    "incorporation": "qualifying_relationship",
    # Doing Business
    "business_plan": "doing_business",
    "financial_performance": "doing_business",
    "revenue": "doing_business",
    "customer_relationship": "doing_business",
    "transaction_evidence": "doing_business",
    "parent_company_info": "doing_business",
    "partnership": "doing_business",
    # Executive Capacity
    "org_chart": "executive_capacity",
    "executive_duties": "executive_capacity",
    "subordinate_credentials": "executive_capacity",
    "time_allocation": "executive_capacity",
    # Qualifying Employment
    "employment_history": "qualifying_employment",
    "education": "qualifying_employment",
    "achievement": "qualifying_employment",
    "contract_execution": "qualifying_employment",
    # Shared types that may appear
    "leadership": "executive_capacity",
    "recommendation": "qualifying_employment",
    "award": "qualifying_employment",
    "quantitative_impact": "doing_business",
    "media_coverage": "doing_business",
}


# ==================== NIW snippet grouping ====================

NIW_EVIDENCE_TYPE_MAPPING = {
    # NIW-specific extraction types (from NIW extraction prompt)
    "endeavor_description": "prong1_merit",
    "field_impact": "prong1_merit",
    "national_importance": "prong1_merit",
    "merit_evidence": "prong1_merit",
    "education": "prong2_positioned",
    "work_experience": "prong2_positioned",
    "citation_metrics": "prong2_positioned",
    "research_project": "prong2_positioned",
    "waiver_justification": "prong3_balance",
    "national_benefit": "prong3_balance",
    "beyond_employer": "prong3_balance",
    "urgency": "prong3_balance",
    # Shared types (from both EB-1A and NIW extraction)
    "contribution": "prong1_merit",
    "quantitative_impact": "prong1_merit",
    "recommendation": "prong2_positioned",
    "leadership": "prong2_positioned",
    "award": "prong2_positioned",
    "membership": "prong2_positioned",
    "publication": "prong2_positioned",
    "media_coverage": "prong1_merit",
    "certification": "prong2_positioned",
    "citation_impact": "prong2_positioned",
}


@dataclass
class LegalArgument:
    """法律论点数据结构"""
    id: str
    standard: str
    title: str
    rationale: str
    snippet_ids: List[str]
    evidence_strength: str
    sub_argument_ids: List[str] = None
    subject: str = "the applicant"
    confidence: float = 0.9
    is_ai_generated: bool = True
    created_at: str = ""

    def __post_init__(self):
        if self.sub_argument_ids is None:
            self.sub_argument_ids = []
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self):
        """转换为前端兼容的字典格式"""
        return {
            "id": self.id,
            "standard": self.standard,
            "standard_key": self.standard,  # 前端需要 standard_key
            "title": self.title,
            "rationale": self.rationale,
            "snippet_ids": self.snippet_ids,
            "evidence_strength": self.evidence_strength,
            "sub_argument_ids": self.sub_argument_ids,
            "subject": self.subject,
            "confidence": self.confidence,
            "is_ai_generated": self.is_ai_generated,
            "created_at": self.created_at,
        }


async def organize_arguments_with_legal_framework(
    snippets: List[Dict],
    applicant_name: str = "the applicant",
    provider: str = "deepseek",
    project_type: str = "EB-1A",
    project_id: str = None
) -> Tuple[List[LegalArgument], List[Dict]]:
    """
    使用 LLM + 法律条例组织子论点

    Args:
        snippets: 所有提取的 snippets
        applicant_name: 申请人姓名
        provider: LLM provider
        project_type: "EB-1A" or "NIW"
        project_id: 项目 ID（用于保存 top-down pickup 中间结果）

    Returns:
        (arguments, filtered_snippets)
    """
    logger.info(f"[LegalOrganizer] Organizing {len(snippets)} snippets with {project_type} legal framework...")
    # Select standards and prompts based on project type
    if project_type == "NIW":
        legal_stds = NIW_LEGAL_STANDARDS
        system_prompt = NIW_ORGANIZE_SYSTEM_PROMPT
        user_prompt_template = NIW_ORGANIZE_USER_PROMPT
        evidence_mapping = NIW_EVIDENCE_TYPE_MAPPING
    elif project_type == "L-1A":
        legal_stds = L1A_LEGAL_STANDARDS
        system_prompt = L1A_ORGANIZE_SYSTEM_PROMPT
        user_prompt_template = L1A_ORGANIZE_USER_PROMPT
        evidence_mapping = L1A_EVIDENCE_TYPE_MAPPING
    else:
        legal_stds = LEGAL_STANDARDS
        system_prompt = ORGANIZE_SYSTEM_PROMPT
        user_prompt_template = ORGANIZE_USER_PROMPT
        evidence_mapping = None  # uses default _group_snippets_by_standard

    # 按 standard 分组 snippets
    if project_type == "EB-1A":
        snippets_by_std = await _group_snippets_by_standard_topdown(
            snippets, legal_stds, provider, project_id=project_id
        )
    else:
        snippets_by_std = _group_snippets_by_standard(snippets, legal_stds, evidence_mapping)

    # 构建 prompt — only include standards that have evidence
    standards_with_evidence = {k: v for k, v in snippets_by_std.items() if v}
    standards_text = _format_standards_text(legal_stds, only_keys=set(standards_with_evidence.keys()))
    snippets_text = _format_snippets_by_standard(snippets_by_std, applicant_name, legal_stds)

    # Build evidence summary (explicit list at top of prompt)
    evidence_summary_lines = []
    for std_key, std_snps in standards_with_evidence.items():
        std_info = legal_stds.get(std_key, {})
        evidence_summary_lines.append(
            f"- **{std_info.get('name', std_key)}** ({std_info.get('citation', '')}) — {len(std_snps)} snippets → standard key: \"{std_key}\""
        )
    evidence_summary = "\n".join(evidence_summary_lines)

    # Build valid standard keys for the prompt
    valid_keys = ", ".join(f'"{k}"' for k in legal_stds.keys())

    user_prompt = user_prompt_template.format(
        standards_text=standards_text,
        snippet_count=len(snippets),
        snippets_by_standard=snippets_text,
        valid_standard_keys=valid_keys,
        standards_with_evidence_count=len(standards_with_evidence),
        evidence_summary=evidence_summary,
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=system_prompt,
            temperature=0.1,
            max_tokens=8000
        )

        raw_arguments = result.get('arguments', [])
        filtered_out = result.get('filtered_out', [])
        summary = result.get('summary', {})

        logger.info(f"[LegalOrganizer] LLM organized into {len(raw_arguments)} arguments")
        logger.info(f"[LegalOrganizer] Summary: {summary}")
        # 转换为 LegalArgument
        arguments = []
        for raw_arg in raw_arguments:
            arg = LegalArgument(
                id=f"arg-{uuid.uuid4().hex[:8]}",  # Always use UUID to prevent ID collisions across standards
                standard=raw_arg.get('standard', ''),
                title=raw_arg.get('title', ''),
                rationale=raw_arg.get('rationale', ''),
                snippet_ids=raw_arg.get('snippet_ids', []),
                evidence_strength=raw_arg.get('evidence_strength', 'medium'),
                subject=applicant_name,
            )
            arguments.append(arg)

        # Post-processing: ensure every standard with evidence gets at least one argument.
        # LLMs often ignore less common standards (judging, scholarly_articles, etc.)
        # Normalize standard keys to handle plural/singular variants
        _STANDARD_ALIASES = {
            "original_contributions": "original_contribution",
            "scholarly_article": "scholarly_articles",
            "high_salaries": "high_salary",
        }
        covered_standards = set()
        for arg in arguments:
            canonical = _STANDARD_ALIASES.get(arg.standard, arg.standard)
            covered_standards.add(canonical)
            covered_standards.add(arg.standard)  # also add the raw form

        logger.info(f"[LegalOrganizer] Covered standards: {covered_standards}")
        stds_with_evidence = [k for k, v in snippets_by_std.items() if v]
        logger.info(f"[LegalOrganizer] Standards with evidence: {stds_with_evidence}")
        arg_counter = len(arguments)
        for std_key, std_snippets in snippets_by_std.items():
            if not std_snippets:
                continue
            if std_key in covered_standards:
                continue
            logger.warning(f"[LegalOrganizer] FALLBACK: '{std_key}' has {len(std_snippets)} snippets but no LLM argument")
            # This standard has evidence but no LLM argument — create a fallback
            arg_counter += 1
            std_info = legal_stds.get(std_key, {})
            snippet_ids = [s.get('snippet_id', s.get('id', '')) for s in std_snippets]
            fallback_arg = LegalArgument(
                id=f"arg-{arg_counter:03d}",
                standard=std_key,
                title=f"{applicant_name}'s {std_info.get('name', std_key)}",
                rationale=f"Auto-generated fallback: LLM did not create an argument for {std_key} despite {len(std_snippets)} supporting snippets",
                snippet_ids=snippet_ids,
                evidence_strength="medium",
                subject=applicant_name,
            )
            arguments.append(fallback_arg)
            logger.warning(f"[LegalOrganizer] Added fallback argument for '{std_key}' with {len(snippet_ids)} snippets")
        return arguments, filtered_out

    except Exception as e:
        logger.warning(f"[LegalOrganizer] Error: {e}")
        raise


# Default EB-1A evidence type mapping
# Maps extraction evidence_type → LEGAL_STANDARDS key
_EB1A_EVIDENCE_TYPE_MAPPING = {
    # (i) Awards
    "award": "awards",
    # (ii) Membership
    "membership": "membership",
    "membership_criteria": "membership",
    "membership_evaluation": "membership",
    "peer_achievement": "membership",
    "selectivity_proof": "membership",
    # (iii) Published Material — media/reports ABOUT the alien
    "media_coverage": "published_material",
    "source_credibility": "published_material",
    # (iv) Judging
    "judging": "judging",
    "peer_assessment": "judging",
    "invitation": "judging",
    # (v) Original Contribution
    "contribution": "original_contribution",
    "quantitative_impact": "original_contribution",
    "recommendation": "original_contribution",
    "impact_proof": "original_contribution",
    "scientific_research_project": "original_contribution",
    # (vi) Scholarly Articles — authored BY the alien
    "publication": "scholarly_articles",
    "scholarly_article": "scholarly_articles",
    "authorship": "scholarly_articles",
    # (viii) Leading/Critical Role
    "leadership": "leading_role",
    "organization": "leading_role",
    # (vii) Display/Exhibition
    "exhibition": "display",
    "display": "display",
    # (ix) High Salary
    "salary": "high_salary",
    "compensation": "high_salary",
    "salary_benchmark": "high_salary",
    "high_salary": "high_salary",
    # (x) Commercial Success
    "commercial": "commercial_success",
    "commercial_success": "commercial_success",
    "box_office": "commercial_success",
    "sales": "commercial_success",
}


# Per-standard pickup criteria for top-down evidence selection.
# Structured prompt content: lives in prompts/organizer/*_topdown_pickup_criteria@vN.json
# (versioned + hash-snapshotted like every other prompt); edit there, in a prompt: commit.
_TOPDOWN_PICKUP_CRITERIA = _prompt_data("organizer/eb1a_topdown_pickup_criteria")


# ==================== NIW Top-Down Pickup Criteria ====================

_NIW_TOPDOWN_PICKUP_CRITERIA = _prompt_data("organizer/niw_topdown_pickup_criteria")


async def _topdown_pickup_for_standard(
    standard_key: str,
    standard_info: Dict,
    all_snippets: List[Dict],
    provider: str = "deepseek"
) -> List[Dict]:
    """
    Top-down: LLM 从全量 applicant snippet 中为一个 standard 挑选相关证据。
    返回被选中的 snippet 列表，每个附加 _topdown_chain 字段。
    """
    # Build exhibit-level source context from snippets
    # Aggregates recommender_name, source_credibility subjects, and org names per exhibit
    from collections import defaultdict as _defaultdict
    _exhibit_sources = _defaultdict(set)
    for snp in all_snippets:
        eid = snp.get('exhibit_id', '')
        if not eid:
            continue
        # Recommender name (already extracted by unified_extractor)
        rec = snp.get('recommender_name', '')
        if rec:
            _exhibit_sources[eid].add(rec)
        # Source credibility snippets — the subject is often the authoritative source
        if snp.get('evidence_type') in ('source_credibility', 'membership_criteria') and snp.get('subject_role') in ('organization', 'media', 'event'):
            subj = snp.get('subject', '')
            if subj and len(subj) < 60:
                _exhibit_sources[eid].add(subj)
    # Build compact label per exhibit: "F4(China Weightlifting Association)"
    exhibit_label = {}
    for eid, sources in _exhibit_sources.items():
        # Pick the shortest meaningful source name (avoid overly long ones)
        best = min(sources, key=len) if sources else ''
        if best:
            exhibit_label[eid] = f"{eid}({best})"
        else:
            exhibit_label[eid] = eid

    # 压缩 snippet 表示，减少 token 用量
    compact_lines = []
    snippet_lookup = {}
    for snp in all_snippets:
        sid = snp.get('snippet_id', snp.get('id', ''))
        snippet_lookup[sid] = snp
        exhibit_id = snp.get('exhibit_id', '')
        evidence_type = snp.get('evidence_type', '')
        subject = snp.get('subject', '')
        text = snp.get('text', '')[:150]
        ex_label = exhibit_label.get(exhibit_id, exhibit_id)
        compact_lines.append(
            f"[{sid}] exhibit={ex_label} type={evidence_type} subject={subject} text={text}"
        )

    snippets_text = "\n".join(compact_lines)

    # Per-standard pickup criteria
    pickup_criteria = _TOPDOWN_PICKUP_CRITERIA.get(standard_key, {})
    include_direct = pickup_criteria.get("include_direct", [])
    include_supporting = pickup_criteria.get("include_supporting", [])
    exclude_rules = pickup_criteria.get("exclude", [])
    subject_rule = pickup_criteria.get("subject_rule", "Subject must be the applicant")

    include_text = ""
    if include_direct:
        include_text += "DIRECT evidence (must include):\n"
        for item in include_direct:
            include_text += f"  - {item}\n"
    if include_supporting:
        include_text += "Valid SUPPORTING evidence:\n"
        for item in include_supporting:
            include_text += f"  - {item}\n"

    exclude_text = ""
    if exclude_rules:
        exclude_text = "EXCLUDE (do NOT select):\n"
        for item in exclude_rules:
            exclude_text += f"  - {item}\n"

    system_prompt = _prompt_render("organizer/topdown_pickup_for_standard_system_prompt",
        include_text=include_text,
        exclude_text=exclude_text,
        subject_rule=subject_rule,
    )

    user_prompt = _prompt_render("organizer/topdown_pickup_for_standard_user_prompt",
        standard_info_get_name_standard_key=standard_info.get('name', standard_key),
        standard_info_get_citation=standard_info.get('citation', ''),
        standard_info_get_requirements=standard_info.get('requirements', ''),
        len_all_snippets=len(all_snippets),
        snippets_text=snippets_text,
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=system_prompt,
            temperature=0.1,
            max_tokens=8192
        )

        # Parse new compact format: {chains: {chain_label: [snippet_ids]}}
        chains_data = result.get('chains', {})

        # Fallback: old format {selected: [{snippet_id, chain, ...}]}
        if not chains_data and result.get('selected'):
            for item in result['selected']:
                chain = item.get('chain', 'uncategorized')
                sid = item.get('snippet_id', '')
                chains_data.setdefault(chain, []).append(sid)

        # Fallback: if extract_json failed (truncated response), try to recover
        if not chains_data and 'content' in result and isinstance(result['content'], str):
            raw = result['content']
            try:
                import re
                # Try to find "chain_label": ["id1", "id2", ...] patterns
                for match in re.finditer(r'"([^"]+)"\s*:\s*\[([^\]]*)\]', raw):
                    chain_label = match.group(1)
                    if chain_label == 'chains':
                        continue
                    ids_str = match.group(2)
                    ids = re.findall(r'"(snp_[^"]+)"', ids_str)
                    if ids:
                        chains_data[chain_label] = ids
                if chains_data:
                    logger.info(f"[TopDown] {standard_key}: recovered {len(chains_data)} chains from truncated response")
            except Exception as recover_err:
                logger.warning(f"[TopDown] {standard_key}: recovery failed: {recover_err}")
        selected_snippets = []
        for chain_label, snippet_ids in chains_data.items():
            for sid in snippet_ids:
                if sid in snippet_lookup:
                    snp_copy = dict(snippet_lookup[sid])
                    snp_copy['_topdown_chain'] = chain_label
                    snp_copy['_topdown_relevance'] = 'direct'
                    selected_snippets.append(snp_copy)

        logger.info(f"[TopDown] {standard_key}: selected {len(selected_snippets)}/{len(all_snippets)} snippets, "
              f"{len(chains_data)} chains")
        return selected_snippets

    except Exception as e:
        logger.warning(f"[TopDown] Error for {standard_key}: {e}, falling back to bottom-up mapping")
        return []  # caller handles fallback


async def _group_snippets_by_standard_topdown(
    snippets: List[Dict],
    legal_stds: Dict,
    provider: str = "deepseek",
    project_id: str = None
) -> Dict[str, List[Dict]]:
    """
    Top-down snippet grouping: per-standard LLM 从全量 snippet 中挑选。
    并行调用所有 standard，失败时直接抛出异常。
    输出格式与 _group_snippets_by_standard() 相同。

    如果 project_id 提供，保存中间 pickup 结果到 arguments/topdown_pickup.json。
    """
    # 默认只用 applicant snippet
    applicant_snippets = [
        snp for snp in snippets
        if snp.get('is_applicant_achievement', True)
    ]
    # leading_role / display 需要第三方对组织的描述（is_applicant_achievement=False），
    # 使用全量 snippet
    _STANDARDS_NEED_ALL_SNIPPETS = {"leading_role", "display"}

    logger.info(f"[TopDown] Starting top-down pickup for {len(legal_stds)} standards "
          f"with {len(applicant_snippets)} applicant snippets "
          f"(+{len(snippets) - len(applicant_snippets)} non-applicant for org-reputation standards)")

    # 并行调用所有 standard
    tasks = []
    std_keys = []
    for std_key, std_info in legal_stds.items():
        std_keys.append(std_key)
        pool = snippets if std_key in _STANDARDS_NEED_ALL_SNIPPETS else applicant_snippets
        tasks.append(
            _topdown_pickup_for_standard(std_key, std_info, pool, provider)
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 组装结果，异常时直接报错（不再 fallback 到 bottom-up）
    grouped = {std: [] for std in legal_stds.keys()}

    for std_key, result in zip(std_keys, results):
        if isinstance(result, Exception):
            logger.warning(f"[TopDown] {std_key} FAILED: {result}")
            raise RuntimeError(f"Top-down pickup failed for {std_key}: {result}")
        grouped[std_key] = result

    # Summary + save intermediate results
    pickup_report = {}
    for std_key, snps in grouped.items():
        if snps:
            chains = set(s.get('_topdown_chain', '') for s in snps)
            chains.discard('')
            chain_info = f", chains: {chains}" if chains else ""
            logger.info(f"[TopDown] {std_key}: {len(snps)} snippets{chain_info}")
            pickup_report[std_key] = {
                "count": len(snps),
                "chains": sorted(chains),
                "snippet_ids": [s.get('snippet_id', s.get('id', '')) for s in snps],
                "details": [
                    {
                        "snippet_id": s.get('snippet_id', s.get('id', '')),
                        "exhibit_id": s.get('exhibit_id', ''),
                        "evidence_type": s.get('evidence_type', ''),
                        "chain": s.get('_topdown_chain', ''),
                        "relevance": s.get('_topdown_relevance', ''),
                        "text": s.get('text', '')[:150],
                    }
                    for s in snps
                ],
            }

    # Save intermediate pickup results for evaluation
    if project_id:
        try:
            args_dir = project_path(project_id, "arguments")
            args_dir.mkdir(parents=True, exist_ok=True)
            pickup_file = args_dir / "topdown_pickup.json"
            write_json(pickup_file, {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_applicant_snippets": len(applicant_snippets),
                "standards_count": len(legal_stds),
                "pickup_by_standard": pickup_report,
            })
            logger.info(f"[TopDown] Saved pickup results to {pickup_file}")
        except Exception as e:
            logger.warning(f"[TopDown] Warning: could not save pickup results: {e}")
    return grouped


# ==================== NIW Top-Down Pickup ====================

async def _niw_topdown_pickup_for_prong(
    prong_key: str,
    prong_info: Dict,
    all_snippets: List[Dict],
    provider: str = "deepseek",
    cross_prong_context: str = ""
) -> List[Dict]:
    """
    NIW top-down: LLM selects snippets relevant to a specific Dhanasar prong.
    For Prong 3, cross_prong_context provides Prong 1/2 pickup summary.
    Returns selected snippets, each with _topdown_chain field.
    """
    from collections import defaultdict as _defaultdict

    # Build exhibit-level source context
    _exhibit_sources = _defaultdict(set)
    for snp in all_snippets:
        eid = snp.get('exhibit_id', '')
        if not eid:
            continue
        rec = snp.get('recommender_name', '')
        if rec:
            _exhibit_sources[eid].add(rec)
        if snp.get('evidence_type') in ('source_credibility', 'recommendation') and snp.get('subject_role') in ('organization', 'media', 'event', 'recommender'):
            subj = snp.get('subject', '')
            if subj and len(subj) < 60:
                _exhibit_sources[eid].add(subj)

    exhibit_label = {}
    for eid, sources in _exhibit_sources.items():
        best = min(sources, key=len) if sources else ''
        exhibit_label[eid] = f"{eid}({best})" if best else eid

    # Compress snippets
    compact_lines = []
    snippet_lookup = {}
    for snp in all_snippets:
        sid = snp.get('snippet_id', snp.get('id', ''))
        snippet_lookup[sid] = snp
        exhibit_id = snp.get('exhibit_id', '')
        evidence_type = snp.get('evidence_type', '')
        subject = snp.get('subject', '')
        text = snp.get('text', '')[:150]
        ex_label = exhibit_label.get(exhibit_id, exhibit_id)
        compact_lines.append(
            f"[{sid}] exhibit={ex_label} type={evidence_type} subject={subject} text={text}"
        )

    snippets_text = "\n".join(compact_lines)

    # Per-prong pickup criteria
    pickup_criteria = _NIW_TOPDOWN_PICKUP_CRITERIA.get(prong_key, {})
    include_direct = pickup_criteria.get("include_direct", [])
    include_supporting = pickup_criteria.get("include_supporting", [])
    exclude_rules = pickup_criteria.get("exclude", [])
    subject_rule = pickup_criteria.get("subject_rule", "Subject must be the applicant")

    include_text = ""
    if include_direct:
        include_text += "DIRECT evidence (must include):\n"
        for item in include_direct:
            include_text += f"  - {item}\n"
    if include_supporting:
        include_text += "Valid SUPPORTING evidence:\n"
        for item in include_supporting:
            include_text += f"  - {item}\n"

    exclude_text = ""
    if exclude_rules:
        exclude_text = "EXCLUDE (do NOT select):\n"
        for item in exclude_rules:
            exclude_text += f"  - {item}\n"

    cross_prong_section = ""
    if cross_prong_context:
        cross_prong_section = _prompt_render("organizer/niw_topdown_pickup_for_prong_cross_prong_section",
            cross_prong_context=cross_prong_context,
        )

    system_prompt = _prompt_render("organizer/niw_topdown_pickup_for_prong_system_prompt",
        include_text=include_text,
        exclude_text=exclude_text,
        subject_rule=subject_rule,
        cross_prong_section=cross_prong_section,
    )

    user_prompt = _prompt_render("organizer/niw_topdown_pickup_for_prong_user_prompt",
        prong_info_get_name_prong_key=prong_info.get('name', prong_key),
        prong_info_get_citation=prong_info.get('citation', ''),
        prong_info_get_requirements=prong_info.get('requirements', ''),
        len_all_snippets=len(all_snippets),
        snippets_text=snippets_text,
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=system_prompt,
            temperature=0.1,
            max_tokens=8192
        )

        chains_data = result.get('chains', {})

        # Fallback: old format
        if not chains_data and result.get('selected'):
            for item in result['selected']:
                chain = item.get('chain', 'uncategorized')
                sid = item.get('snippet_id', '')
                chains_data.setdefault(chain, []).append(sid)

        # Fallback: truncated response recovery
        if not chains_data and 'content' in result and isinstance(result['content'], str):
            raw = result['content']
            try:
                import re
                for match in re.finditer(r'"([^"]+)"\s*:\s*\[([^\]]*)\]', raw):
                    chain_label = match.group(1)
                    if chain_label == 'chains':
                        continue
                    ids_str = match.group(2)
                    ids = re.findall(r'"(snp_[^"]+)"', ids_str)
                    if ids:
                        chains_data[chain_label] = ids
                if chains_data:
                    logger.info(f"[NIW-TopDown] {prong_key}: recovered {len(chains_data)} chains from truncated response")
            except Exception as recover_err:
                logger.warning(f"[NIW-TopDown] {prong_key}: recovery failed: {recover_err}")
        selected_snippets = []
        for chain_label, snippet_ids in chains_data.items():
            for sid in snippet_ids:
                if sid in snippet_lookup:
                    snp_copy = dict(snippet_lookup[sid])
                    snp_copy['_topdown_chain'] = chain_label
                    snp_copy['_topdown_relevance'] = 'direct'
                    selected_snippets.append(snp_copy)

        logger.info(f"[NIW-TopDown] {prong_key}: selected {len(selected_snippets)}/{len(all_snippets)} snippets, "
              f"{len(chains_data)} chains")
        return selected_snippets

    except Exception as e:
        logger.warning(f"[NIW-TopDown] Error for {prong_key}: {e}")
        return []  # caller handles fallback


async def _niw_group_snippets_by_prong_topdown(
    snippets: List[Dict],
    provider: str = "deepseek",
    project_id: str = None
) -> Dict[str, List[Dict]]:
    """
    NIW top-down snippet grouping: per-prong LLM selects from full snippet pool.

    Flow: Prong 1 & 2 in parallel → build cross-prong context → Prong 3 with context.
    This mirrors Dhanasar's structure: Prong 3 (waiver) reframes Prong 1/2 evidence.

    Returns {prong_key: [selected_snippets]}.
    """
    logger.info(f"[NIW-TopDown] Starting top-down pickup for 3 Dhanasar prongs "
          f"with {len(snippets)} total snippets")

    grouped = {prong: [] for prong in NIW_LEGAL_STANDARDS.keys()}

    # Phase 1: Prong 1 & Prong 2 in parallel
    logger.info("[NIW-TopDown] Phase 1: Prong 1 & 2 in parallel...")
    p1_info = NIW_LEGAL_STANDARDS["prong1_merit"]
    p2_info = NIW_LEGAL_STANDARDS["prong2_positioned"]
    p1_task = _niw_topdown_pickup_for_prong("prong1_merit", p1_info, snippets, provider)
    p2_task = _niw_topdown_pickup_for_prong("prong2_positioned", p2_info, snippets, provider)

    results_12 = await asyncio.gather(p1_task, p2_task, return_exceptions=True)

    for prong_key, result in zip(["prong1_merit", "prong2_positioned"], results_12):
        if isinstance(result, Exception):
            logger.warning(f"[NIW-TopDown] {prong_key} FAILED: {result}")
            raise RuntimeError(f"NIW top-down pickup failed for {prong_key}: {result}")
        grouped[prong_key] = result

    # Phase 2: Build cross-prong context from Prong 1/2 results for Prong 3
    logger.info("[NIW-TopDown] Phase 2: Prong 3 with Prong 1/2 context...")
    cross_prong_lines = []
    for pk in ["prong1_merit", "prong2_positioned"]:
        snps = grouped[pk]
        if not snps:
            continue
        chains = {}
        for s in snps:
            chain = s.get('_topdown_chain', 'other')
            chains.setdefault(chain, []).append(s)
        chain_summaries = []
        for chain_label, chain_snps in chains.items():
            sids = [s.get('snippet_id', s.get('id', '')) for s in chain_snps]
            sample_text = chain_snps[0].get('text', '')[:100] if chain_snps else ''
            chain_summaries.append(f"  - {chain_label} ({len(sids)} snippets): {sample_text}...")
        pk_name = NIW_LEGAL_STANDARDS[pk].get('name', pk)
        cross_prong_lines.append(f"\n{pk_name} ({len(snps)} snippets selected):")
        cross_prong_lines.extend(chain_summaries)

    cross_prong_context = "\n".join(cross_prong_lines) if cross_prong_lines else ""

    p3_info = NIW_LEGAL_STANDARDS["prong3_balance"]
    p3_result = await _niw_topdown_pickup_for_prong(
        "prong3_balance", p3_info, snippets, provider,
        cross_prong_context=cross_prong_context
    )
    if isinstance(p3_result, Exception):
        raise RuntimeError(f"NIW top-down pickup failed for prong3_balance: {p3_result}")
    grouped["prong3_balance"] = p3_result

    # Summary + save intermediate results
    pickup_report = {}
    for prong_key, snps in grouped.items():
        if snps:
            chains = set(s.get('_topdown_chain', '') for s in snps)
            chains.discard('')
            chain_info = f", chains: {sorted(chains)}" if chains else ""
            logger.info(f"[NIW-TopDown] {prong_key}: {len(snps)} snippets{chain_info}")
            pickup_report[prong_key] = {
                "count": len(snps),
                "chains": sorted(chains),
                "snippet_ids": [s.get('snippet_id', s.get('id', '')) for s in snps],
            }

    if project_id:
        try:
            args_dir = project_path(project_id, "arguments")
            args_dir.mkdir(parents=True, exist_ok=True)
            pickup_file = args_dir / "niw_topdown_pickup.json"
            write_json(pickup_file, {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_snippets": len(snippets),
                "prongs_count": len(NIW_LEGAL_STANDARDS),
                "pickup_by_prong": pickup_report,
            })
            logger.info(f"[NIW-TopDown] Saved pickup results to {pickup_file}")
        except Exception as e:
            logger.warning(f"[NIW-TopDown] Warning: could not save pickup results: {e}")
    return grouped


def _group_snippets_by_standard(
    snippets: List[Dict],
    legal_stds: Dict = None,
    evidence_mapping: Dict = None
) -> Dict[str, List[Dict]]:
    """按 standard 分组"""
    if legal_stds is None:
        legal_stds = LEGAL_STANDARDS
    if evidence_mapping is None:
        evidence_mapping = _EB1A_EVIDENCE_TYPE_MAPPING

    grouped = {std: [] for std in legal_stds.keys()}

    for snp in snippets:
        if not snp.get('is_applicant_achievement', True):
            continue
        etype = snp.get('evidence_type', '').lower()
        standard = evidence_mapping.get(etype)
        if standard and standard in grouped:
            grouped[standard].append(snp)

    return grouped


def _format_standards_text(legal_stds: Dict = None, only_keys: set = None) -> str:
    """Format legal standards text, optionally filtered to only standards with evidence."""
    if legal_stds is None:
        legal_stds = LEGAL_STANDARDS
    lines = []
    for std_key, std_info in legal_stds.items():
        if only_keys and std_key not in only_keys:
            continue
        lines.append(f"### {std_info['name']} ({std_info['citation']}) [key: {std_key}]")
        lines.append(std_info['requirements'])
        lines.append("")
    return "\n".join(lines)


def _format_snippets_by_standard(grouped: Dict[str, List[Dict]], applicant_name: str, legal_stds: Dict = None) -> str:
    """格式化 snippets 按标准分组"""
    if legal_stds is None:
        legal_stds = LEGAL_STANDARDS
    lines = []

    for std_key, snps in grouped.items():
        if not snps:
            continue
        std_info = legal_stds.get(std_key, {})
        lines.append(f"### {std_info.get('name', std_key)} ({len(snps)} snippets)")

        for i, snp in enumerate(snps[:30], 1):  # Limit to 30 per standard
            sid = snp.get('snippet_id', snp.get('id', ''))
            text = snp.get('text', '')[:200]
            exhibit = snp.get('exhibit_id', '')
            subject = snp.get('subject', '')
            chain_label = snp.get('_topdown_chain', '')
            chain_str = f" [chain: {chain_label}]" if chain_label else ""
            lines.append(f"[{sid}] (Exhibit {exhibit}{chain_str}, subject: {subject}) {text}...")

        if len(snps) > 30:
            lines.append(f"... and {len(snps) - 30} more snippets")
        lines.append("")

    return "\n".join(lines)


# ==================== NIW v2 Functions ====================

async def niw_classify_other_snippets(
    other_snippets: List[Dict], provider: str = "deepseek"
) -> Dict[str, str]:
    """
    将 'other' 类型 snippet 分类到 prong，返回 {snippet_id: prong_key}。
    批量发送（每批 50 条）。
    """
    if not other_snippets:
        return {}

    result_map = {}
    batch_size = 50

    for batch_start in range(0, len(other_snippets), batch_size):
        batch = other_snippets[batch_start:batch_start + batch_size]

        # Format snippets for prompt
        lines = []
        for snp in batch:
            sid = snp.get('snippet_id', snp.get('id', ''))
            text = snp.get('text', '')[:200]
            exhibit = snp.get('exhibit_id', '')
            lines.append(f"[{sid}] (Exhibit {exhibit}) {text}")

        snippets_text = "\n".join(lines)

        try:
            result = await call_llm(
                prompt=NIW_CLASSIFY_OTHER_USER_PROMPT.format(snippets_text=snippets_text),
                provider=provider,
                system_prompt=NIW_CLASSIFY_OTHER_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=4000
            )

            classifications = result.get('classifications', [])
            for item in classifications:
                sid = item.get('snippet_id', '')
                prong = item.get('prong', 'skip')
                if prong in ('prong1_merit', 'prong2_positioned', 'prong3_balance', 'skip'):
                    result_map[sid] = prong
                else:
                    result_map[sid] = 'prong2_positioned'  # default fallback

            logger.info(f"[NIW-v2] Classified batch {batch_start//batch_size + 1}: "
                  f"{len(classifications)} snippets")

        except Exception as e:
            logger.warning(f"[NIW-v2] Error classifying other snippets batch: {e}")
            # Fallback: assign all to prong2
            for snp in batch:
                sid = snp.get('snippet_id', snp.get('id', ''))
                result_map[sid] = 'prong2_positioned'

        if batch_start + batch_size < len(other_snippets):
            await asyncio.sleep(0.3)

    # Summary
    prong_counts = {}
    for prong in result_map.values():
        prong_counts[prong] = prong_counts.get(prong, 0) + 1
    logger.info(f"[NIW-v2] Other snippet classification: {prong_counts}")
    return result_map


async def niw_organize_per_prong(
    prong_key: str, prong_snippets: List[Dict],
    applicant_name: str, provider: str = "deepseek"
) -> Tuple[LegalArgument, List[Dict]]:
    """
    对单个 prong 的所有 snippet 调用 LLM 组织成 sub-arguments。

    Returns:
        (LegalArgument for this prong, list of sub_argument dicts)
    """
    prong_info = NIW_LEGAL_STANDARDS.get(prong_key, {})
    prong_name = prong_info.get('name', prong_key)
    prong_citation = prong_info.get('citation', '')
    prong_description = prong_info.get('requirements', '')

    # Create simplified ID mapping for the prompt
    id_mapping = {}  # simple_id -> real_snippet_id
    lines = []
    truncate_text = len(prong_snippets) > 50

    for i, snp in enumerate(prong_snippets, 1):
        real_id = snp.get('snippet_id', snp.get('id', ''))
        simple_id = f"S{i}"
        id_mapping[simple_id] = real_id

        text = snp.get('text', '')
        if truncate_text:
            text = text[:150]
        else:
            text = text[:300]
        exhibit = snp.get('exhibit_id', '')
        etype = snp.get('evidence_type', '')
        lines.append(f"[{simple_id}] (Exhibit {exhibit}, type: {etype}) {text}")

    snippets_text = "\n".join(lines)

    # Prong 3 with very few snippets: generate template sub-arguments
    # by legal component (policy argument, not evidence-grouping)
    all_real_ids = list(id_mapping.values())
    if prong_key == "prong3_balance" and len(prong_snippets) <= 3:
        arg_id = f"arg-{uuid.uuid4().hex[:8]}"
        template_components = [
            ("Impracticality of Labor Certification",
             "Why the PERM process is unsuitable for this beneficiary's work",
             "Demonstrates PERM impracticality"),
            ("National Benefit Analysis",
             "Concrete national benefits from the beneficiary's contributions",
             "Establishes national interest"),
            ("Benefits Beyond Single Employer",
             "Work transcends any single employer's interests",
             "Proves cross-employer impact"),
            ("Explicit Balancing — Waiver Justification",
             "Weighing national interest against labor market protection",
             "Concludes waiver justification"),
        ]
        sub_arguments = []
        for title, purpose, relationship in template_components:
            sa_dict = {
                "id": f"subarg-{uuid.uuid4().hex[:8]}",
                "argument_id": arg_id,
                "title": title,
                "purpose": purpose,
                "relationship": relationship,
                "snippet_ids": all_real_ids,  # all snippets shared
                "is_ai_generated": True,
                "status": "draft",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            sub_arguments.append(sa_dict)

        argument = LegalArgument(
            id=arg_id,
            standard=prong_key,
            title=f"{applicant_name}'s {prong_name}",
            rationale=f"Template-based: {len(template_components)} legal components, "
                      f"{len(prong_snippets)} snippets shared across all",
            snippet_ids=all_real_ids,
            evidence_strength="medium",
            sub_argument_ids=[sa["id"] for sa in sub_arguments],
            subject=applicant_name,
        )
        logger.info(f"[NIW-v2] Prong3 template: {len(sub_arguments)} sub-args "
              f"(snippet count {len(prong_snippets)} <= 3, using legal components)")
        return argument, sub_arguments

    # Determine target sub-argument count
    n = len(prong_snippets)
    if n <= 5:
        target = "2-3"
    elif n <= 10:
        target = "3-5"
    elif n <= 30:
        target = "4-6"
    else:
        target = "5-8"

    # Prong-specific organization hints
    prong_hint = ""
    if prong_key == "prong1_merit":
        prong_hint = (
            "\n\nIMPORTANT for Prong 1: You MUST create SEPARATE sub-arguments for "
            "'Substantial Merit' and 'National Importance' — these are two distinct legal "
            "elements. Do NOT merge them into one sub-argument."
        )
    elif prong_key == "prong2_positioned":
        prong_hint = (
            "\n\nIMPORTANT for Prong 2: Create separate sub-arguments for distinct "
            "dimensions (e.g., education, track record, awards, publications, expert "
            "endorsements, future plans). Do NOT collapse all evidence into one group."
        )

    user_prompt = NIW_PRONG_ORGANIZE_USER_PROMPT.format(
        prong_name=prong_name,
        prong_citation=prong_citation,
        applicant_name=applicant_name,
        prong_description=prong_description,
        snippet_count=len(prong_snippets),
        snippets_text=snippets_text,
        target_subargs=target,
    ) + prong_hint

    arg_id = f"arg-{uuid.uuid4().hex[:8]}"

    try:
        result = await call_llm(
            prompt=user_prompt,
            provider=provider,
            system_prompt=NIW_PRONG_ORGANIZE_SYSTEM_PROMPT,
            temperature=0.1,
            max_tokens=8000
        )

        raw_sub_args = result.get('sub_arguments', [])
        logger.info(f"[NIW-v2] Prong {prong_key}: LLM returned {len(raw_sub_args)} sub-arguments")
        if not raw_sub_args:
            # Fallback: single sub-argument with all snippets
            raw_sub_args = [{
                "title": f"{applicant_name}'s Evidence for {prong_name}",
                "purpose": f"All evidence supporting {prong_name}",
                "relationship": f"Supports {prong_name}",
                "snippet_ids": [f"S{i}" for i in range(1, len(prong_snippets) + 1)],
            }]

        # Minimum floor: if LLM collapsed to 1 sub-arg with >5 snippets, force split
        if len(raw_sub_args) == 1 and len(prong_snippets) > 5:
            single = raw_sub_args[0]
            all_sids = single.get('snippet_ids', [])
            mid = len(all_sids) // 2
            if prong_key == "prong1_merit":
                # P1 natural split: substantial merit vs national importance
                raw_sub_args = [
                    {"title": f"Substantial Merit of {applicant_name}'s Proposed Endeavor",
                     "purpose": "Establishes the endeavor has substantial merit",
                     "relationship": "Demonstrates substantial merit",
                     "snippet_ids": all_sids[:mid]},
                    {"title": f"National Importance of {applicant_name}'s Endeavor",
                     "purpose": "Establishes the endeavor has national-level importance",
                     "relationship": "Demonstrates national importance",
                     "snippet_ids": all_sids[mid:]},
                ]
            else:
                # Generic split by halves
                raw_sub_args = [
                    {"title": single.get('title', 'Evidence Group') + " (Part 1)",
                     "purpose": single.get('purpose', ''),
                     "relationship": single.get('relationship', f'Supports {prong_name}'),
                     "snippet_ids": all_sids[:mid]},
                    {"title": single.get('title', 'Evidence Group') + " (Part 2)",
                     "purpose": single.get('purpose', ''),
                     "relationship": single.get('relationship', f'Supports {prong_name}'),
                     "snippet_ids": all_sids[mid:]},
                ]
            logger.info(f"[NIW-v2] Prong {prong_key}: forced split from 1 → {len(raw_sub_args)} sub-args (minimum floor)")
        # Convert sub-arguments, mapping simple IDs back to real IDs
        sub_arguments = []
        all_assigned_real_ids = set()

        for raw_sa in raw_sub_args:
            simple_ids = raw_sa.get('snippet_ids', [])
            real_ids = []
            for sid in simple_ids:
                normalized = sid.upper() if isinstance(sid, str) else str(sid)
                if not normalized.startswith('S'):
                    normalized = f"S{normalized}"
                if normalized in id_mapping:
                    real_ids.append(id_mapping[normalized])

            if not real_ids:
                continue

            all_assigned_real_ids.update(real_ids)

            sa_dict = {
                "id": f"subarg-{uuid.uuid4().hex[:8]}",
                "argument_id": arg_id,
                "title": raw_sa.get('title', 'Evidence Group'),
                "purpose": raw_sa.get('purpose', ''),
                "relationship": raw_sa.get('relationship', f'Supports {prong_name}'),
                "snippet_ids": real_ids,
                "is_ai_generated": True,
                "status": "draft",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            sub_arguments.append(sa_dict)

        # Catch unassigned snippets
        all_real_ids = set(id_mapping.values())
        unassigned = all_real_ids - all_assigned_real_ids
        if unassigned:
            logger.info(f"[NIW-v2] Prong {prong_key}: {len(unassigned)} unassigned snippets, adding catch-all")
            catch_all = {
                "id": f"subarg-{uuid.uuid4().hex[:8]}",
                "argument_id": arg_id,
                "title": "Additional Supporting Evidence",
                "purpose": "Supplementary evidence for this prong",
                "relationship": f"Additional support for {prong_name}",
                "snippet_ids": list(unassigned),
                "is_ai_generated": True,
                "status": "draft",
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            sub_arguments.append(catch_all)
            all_assigned_real_ids.update(unassigned)

        # Build the LegalArgument
        all_snippet_ids = list(all_assigned_real_ids)
        sub_arg_ids = [sa["id"] for sa in sub_arguments]

        argument = LegalArgument(
            id=arg_id,
            standard=prong_key,
            title=f"{applicant_name}'s {prong_name}",
            rationale=f"Organized {len(prong_snippets)} evidence snippets into {len(sub_arguments)} sub-arguments for {prong_name}",
            snippet_ids=all_snippet_ids,
            evidence_strength="strong" if len(prong_snippets) >= 10 else "medium",
            sub_argument_ids=sub_arg_ids,
            subject=applicant_name,
        )

        logger.info(f"[NIW-v2] Prong {prong_key}: {len(sub_arguments)} sub-args, "
              f"{len(all_snippet_ids)} snippets assigned")
        return argument, sub_arguments

    except Exception as e:
        logger.warning(f"[NIW-v2] Error organizing prong {prong_key}: {e}")
        # Fallback: single sub-argument
        all_ids = [snp.get('snippet_id', snp.get('id', '')) for snp in prong_snippets]
        sa_id = f"subarg-{uuid.uuid4().hex[:8]}"
        fallback_sa = {
            "id": sa_id,
            "argument_id": arg_id,
            "title": f"Evidence for {prong_name}",
            "purpose": f"All evidence supporting {prong_name}",
            "relationship": f"Supports {prong_name}",
            "snippet_ids": all_ids,
            "is_ai_generated": True,
            "status": "draft",
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        argument = LegalArgument(
            id=arg_id,
            standard=prong_key,
            title=f"{applicant_name}'s {prong_name}",
            rationale=f"Fallback: all {len(prong_snippets)} snippets in one group",
            snippet_ids=all_ids,
            evidence_strength="medium",
            sub_argument_ids=[sa_id],
            subject=applicant_name,
        )
        return argument, [fallback_sa]


async def niw_organize_arguments_v2(
    snippets: List[Dict], applicant_name: str, provider: str = "deepseek",
    project_id: str = None
) -> Tuple[List[LegalArgument], List[Dict], List[Dict]]:
    """
    NIW v2: Top-down Dhanasar pickup + per-prong LLM organization.

    Two-step flow:
    1. Top-down pickup: LLM selects snippets for each Dhanasar prong (parallel, 3 prongs)
    2. Per-prong organization: parallel LLM calls organize each prong's snippets

    Returns:
        (arguments, sub_arguments, filtered_out)
    """
    logger.info(f"[NIW-v2] Starting with {len(snippets)} total snippets")
    # Step 1: Top-down pickup — LLM selects per prong from full snippet pool
    logger.info("[NIW-v2] Step 1: Top-down Dhanasar pickup...")
    try:
        prong_buckets = await _niw_group_snippets_by_prong_topdown(
            snippets, provider, project_id=project_id
        )
    except RuntimeError as e:
        # Fallback to rule-based if top-down fails completely
        logger.warning(f"[NIW-v2] Top-down pickup failed ({e}), falling back to rule-based mapping")
        prong_buckets = {
            "prong1_merit": [],
            "prong2_positioned": [],
            "prong3_balance": [],
        }
        for snp in snippets:
            if not snp.get('is_applicant_achievement', True):
                continue
            etype = snp.get('evidence_type', '').lower()
            mapped_prong = NIW_EVIDENCE_TYPE_MAPPING.get(etype)
            if mapped_prong and mapped_prong in prong_buckets:
                prong_buckets[mapped_prong].append(snp)
            else:
                prong_buckets['prong2_positioned'].append(snp)

    prong_counts = {k: len(v) for k, v in prong_buckets.items()}
    logger.info(f"[NIW-v2] After pickup: {prong_counts}")
    # Step 2: Per-prong organization (parallel)
    logger.info("[NIW-v2] Step 2: Organizing per prong...")
    filtered_out = []
    tasks = []
    active_prongs = []
    for prong_key, prong_snps in prong_buckets.items():
        if prong_snps:
            active_prongs.append(prong_key)
            tasks.append(niw_organize_per_prong(prong_key, prong_snps, applicant_name, provider))

    if not tasks:
        logger.info("[NIW-v2] No snippets to organize!")
        return [], [], filtered_out

    results = await asyncio.gather(*tasks, return_exceptions=True)

    arguments = []
    all_sub_arguments = []

    for prong_key, result in zip(active_prongs, results):
        if isinstance(result, Exception):
            logger.warning(f"[NIW-v2] Prong {prong_key} failed: {result}")
            continue
        arg, sub_args = result
        arguments.append(arg)
        all_sub_arguments.extend(sub_args)

    # Coverage stats — count unique snippets across all prongs
    all_assigned_ids = set()
    for a in arguments:
        all_assigned_ids.update(a.snippet_ids)
    total_input = len(snippets)
    coverage = (len(all_assigned_ids) / total_input * 100) if total_input > 0 else 0
    logger.info(f"[NIW-v2] Final: {len(arguments)} arguments, {len(all_sub_arguments)} sub-arguments")
    logger.info(f"[NIW-v2] Coverage: {len(all_assigned_ids)}/{total_input} unique snippets ({coverage:.1f}%)")
    return arguments, all_sub_arguments, filtered_out



async def full_legal_pipeline(
    project_id: str,
    applicant_name: str = "the Applicant",
    provider: str = "deepseek",
    project_type: str = "EB-1A",
    job=None,
) -> Dict[str, Any]:
    """
    完整的法律论点组织流程

    Step 1: LLM + 法律条例 → 组织子论点
    Step 2: LLM → 划分次级子论点

    Returns:
        {
            "arguments": [...],
            "sub_arguments": [...],
            "filtered": [...],
            "stats": {...}
        }
    """

    # 加载 snippets
    project_dir = project_path(project_id)

    combined_file = project_dir / "extraction" / "combined_extraction.json"
    enriched_file = project_dir / "enriched" / "enriched_snippets.json"
    if combined_file.exists():
        # Prefer combined extraction (same source as frontend API, consistent IDs)
        with open(combined_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        snippets = data.get('snippets', [])
    elif enriched_file.exists():
        with open(enriched_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        snippets = data.get('snippets', [])
    else:
        # Fallback to per-exhibit extraction files
        snippets = []
        extraction_dir = project_dir / "extraction"
        if extraction_dir.exists():
            for f in extraction_dir.glob("*_extraction.json"):
                if f.name == "combined_extraction.json":
                    continue
                with open(f, 'r', encoding='utf-8') as fp:
                    d = json.load(fp)
                    snippets.extend(d.get("snippets", []))

    logger.info(f"[LegalPipeline] Loaded {len(snippets)} snippets")
    # Resolve project_type from storage if not provided
    if not project_type or project_type == "EB-1A":
        try:
            from .storage import get_project_type
            project_type = get_project_type(project_id)
        except Exception:
            project_type = "EB-1A"

    from ..core.jobs import NullJob
    job = job or NullJob()

    if project_type == "NIW":
        # NIW v2: top-down Dhanasar pickup + per-prong organize (one-step, no separate subdivide)
        job.checkpoint(step="organize", detail="Organizing NIW prongs", progress=0.1)
        logger.info("\n[NIW-v2] Running NIW v2 pipeline...")
        arguments, all_sub_arguments, filtered = await niw_organize_arguments_v2(
            snippets, applicant_name, provider, project_id=project_id
        )
        logger.info(f"[NIW-v2] Done: {len(arguments)} arguments, {len(all_sub_arguments)} sub-arguments")
    else:
        # EB-1A: original two-step flow
        # Step 1: 组织子论点
        job.checkpoint(step="organize", detail="Step 1/2: Organizing arguments", progress=0.1)
        logger.info(f"\n[Step 1] Organizing arguments with {project_type} legal framework...")
        arguments, filtered = await organize_arguments_with_legal_framework(
            snippets, applicant_name, provider, project_type, project_id=project_id
        )

        logger.info(f"[Step 1] Generated {len(arguments)} arguments")
        # Build snippet lookup
        snippet_map = {s.get('snippet_id', s.get('id', '')): s for s in snippets}

        # Step 2: 划分次级子论点
        logger.info("\n[Step 2] Subdividing into sub-arguments...")
        all_sub_arguments = []

        from .subargument_generator import subdivide_argument

        for arg_i, arg in enumerate(arguments):
            job.checkpoint(step="subdivide", detail=f"Step 2/2: SubArguments {arg_i + 1}/{len(arguments)}",
                           progress=0.5 + 0.45 * arg_i / max(len(arguments), 1))
            # Get snippets for this argument
            arg_snippets = [snippet_map[sid] for sid in arg.snippet_ids if sid in snippet_map]

            if not arg_snippets:
                continue

            sub_args = await subdivide_argument(
                argument={'id': arg.id, 'title': arg.title, 'standard': arg.standard},
                snippets=arg_snippets,
                provider=provider
            )

            arg.sub_argument_ids = [sa.id for sa in sub_args]
            all_sub_arguments.extend([asdict(sa) for sa in sub_args])

            await asyncio.sleep(0.2)

        logger.info(f"[Step 2] Generated {len(all_sub_arguments)} sub-arguments")
    # 统计
    by_standard = {}
    for arg in arguments:
        std = arg.standard
        by_standard[std] = by_standard.get(std, 0) + 1

    result = {
        "arguments": [a.to_dict() for a in arguments],
        "sub_arguments": all_sub_arguments,
        "filtered": filtered,
        "main_subject": applicant_name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "argument_count": len(arguments),
            "sub_argument_count": len(all_sub_arguments),
            "by_standard": by_standard,
            "avg_subargs_per_arg": len(all_sub_arguments) / len(arguments) if arguments else 0
        }
    }

    # 保存结果
    output_file = project_dir / "arguments" / "legal_arguments.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_file, result)

    logger.info(f"\n[LegalPipeline] Results saved to {output_file}")
    return result


async def regenerate_standard_pipeline(
    project_id: str,
    standard_key: str,
    applicant_name: str = "the Applicant",
    provider: str = "deepseek",
    project_type: str = "EB-1A"
) -> Dict[str, Any]:
    """
    按单个 standard 重新生成 Arguments + SubArguments，
    只替换该 standard 下的数据，其余保持不动。
    """
    from .snippet_recommender import update_legal_arguments
    from .subargument_generator import subdivide_argument

    # --- 加载 snippets (复用 full_legal_pipeline 的逻辑) ---
    project_dir = project_path(project_id)

    combined_file = project_dir / "extraction" / "combined_extraction.json"
    enriched_file = project_dir / "enriched" / "enriched_snippets.json"
    if combined_file.exists():
        with open(combined_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        snippets = data.get('snippets', [])
    elif enriched_file.exists():
        with open(enriched_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        snippets = data.get('snippets', [])
    else:
        snippets = []
        extraction_dir = project_dir / "extraction"
        if extraction_dir.exists():
            for f in extraction_dir.glob("*_extraction.json"):
                if f.name == "combined_extraction.json":
                    continue
                with open(f, 'r', encoding='utf-8') as fp:
                    d = json.load(fp)
                    snippets.extend(d.get("snippets", []))

    logger.info(f"[RegenerateStandard] Loaded {len(snippets)} snippets, target standard: {standard_key}")
    # --- Resolve project_type ---
    if not project_type or project_type == "EB-1A":
        try:
            from .storage import get_project_type
            project_type = get_project_type(project_id)
        except Exception:
            project_type = "EB-1A"

    # --- 选择法律标准 ---
    if project_type == "NIW":
        legal_stds = NIW_LEGAL_STANDARDS
        evidence_mapping = NIW_EVIDENCE_TYPE_MAPPING
    elif project_type == "L-1A":
        legal_stds = L1A_LEGAL_STANDARDS
        evidence_mapping = L1A_EVIDENCE_TYPE_MAPPING
    else:
        legal_stds = LEGAL_STANDARDS
        evidence_mapping = None

    if standard_key not in legal_stds:
        return {
            "success": False,
            "error": f"Unknown standard_key '{standard_key}' for project_type '{project_type}'. "
                     f"Valid keys: {list(legal_stds.keys())}"
        }

    # --- 按 standard 分组，只取目标 standard ---
    if project_type == "EB-1A":
        # EB-1A: top-down pickup（单个 standard）
        std_info = legal_stds[standard_key]
        # leading_role/display 需要全量 snippet（含第三方对组织的描述）
        if standard_key in ("leading_role", "display"):
            pool = snippets
        else:
            pool = [s for s in snippets if s.get('is_applicant_achievement', True)]
        target_snippets = await _topdown_pickup_for_standard(
            standard_key, std_info, pool, provider
        )
    else:
        # NIW / L-1A: bottom-up 映射
        snippets_by_std = _group_snippets_by_standard(snippets, legal_stds, evidence_mapping)
        target_snippets = snippets_by_std.get(standard_key, [])

    if not target_snippets:
        return {
            "success": False,
            "error": f"No snippets found for standard '{standard_key}'. "
                     f"Check that snippets have matching evidence_type."
        }

    logger.info(f"[RegenerateStandard] Found {len(target_snippets)} snippets for '{standard_key}'")
    if project_type == "NIW":
        # NIW v2: use per-prong organizer directly (includes sub-argument generation)
        argument, all_sub_arguments = await niw_organize_per_prong(
            standard_key, target_snippets, applicant_name, provider
        )
        arguments = [argument]
        logger.info(f"[RegenerateStandard] NIW v2: {len(all_sub_arguments)} sub-arguments")
    else:
        # EB-1A: original two-step flow
        # --- Step 1: organize arguments (仅含该 standard 的 snippets) ---
        arguments, filtered = await organize_arguments_with_legal_framework(
            target_snippets, applicant_name, provider, project_type
        )
        logger.info(f"[RegenerateStandard] Step 1: generated {len(arguments)} arguments")
        # --- Step 2: subdivide into sub-arguments ---
        snippet_map = {s.get('snippet_id', s.get('id', '')): s for s in snippets}
        all_sub_arguments = []

        for arg in arguments:
            arg_snippets = [snippet_map[sid] for sid in arg.snippet_ids if sid in snippet_map]
            if not arg_snippets:
                continue

            sub_args = await subdivide_argument(
                argument={'id': arg.id, 'title': arg.title, 'standard': arg.standard},
                snippets=arg_snippets,
                provider=provider
            )

            arg.sub_argument_ids = [sa.id for sa in sub_args]
            all_sub_arguments.extend([asdict(sa) for sa in sub_args])
            await asyncio.sleep(0.2)

        logger.info(f"[RegenerateStandard] Step 2: generated {len(all_sub_arguments)} sub-arguments")
    new_arguments = [a.to_dict() for a in arguments]

    # --- 合并到现有 legal_arguments.json ---
    by_standard = None
    old_arg_ids = None
    def _mutate(existing):
        nonlocal by_standard, old_arg_ids

        # 删除旧的该 standard 下的 arguments 和关联的 sub_arguments
        old_arg_ids = {
            a["id"] for a in existing.get("arguments", [])
            if (a.get("standard_key") or a.get("standard")) == standard_key
        }
        existing["arguments"] = [
            a for a in existing.get("arguments", [])
            if a["id"] not in old_arg_ids
        ]
        existing["sub_arguments"] = [
            sa for sa in existing.get("sub_arguments", [])
            if sa.get("argument_id") not in old_arg_ids
        ]

        # 插入新的
        existing["arguments"].extend(new_arguments)
        existing["sub_arguments"].extend(all_sub_arguments)

        # 更新 stats
        by_standard = {}
        for a in existing["arguments"]:
            std = a.get("standard_key") or a.get("standard", "")
            by_standard[std] = by_standard.get(std, 0) + 1
        existing.setdefault("stats", {})["by_standard"] = by_standard
        existing["stats"]["argument_count"] = len(existing["arguments"])
        existing["stats"]["sub_argument_count"] = len(existing["sub_arguments"])

        return existing

    existing = update_legal_arguments(project_id, _mutate)
    logger.info(f"[RegenerateStandard] Merged and saved. Removed {len(old_arg_ids)} old args, added {len(new_arguments)} new args.")
    return {
        "success": True,
        "standard_key": standard_key,
        "old_argument_ids": list(old_arg_ids),
        "new_arguments": new_arguments,
        "new_sub_arguments": all_sub_arguments,
        "stats": {
            "old_count": len(old_arg_ids),
            "new_argument_count": len(new_arguments),
            "new_sub_argument_count": len(all_sub_arguments),
            "total_arguments": len(existing["arguments"]),
            "by_standard": by_standard,
        }
    }
