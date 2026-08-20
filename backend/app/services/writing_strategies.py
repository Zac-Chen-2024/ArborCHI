"""
Writing Strategies — per-standard configuration for the petition writing pipeline.

Centralizes all project_type / standard_key branching into a single lookup layer.
petition_writer_v3.py consumes WritingStrategy objects instead of scattering
if/else blocks throughout the code.

Supports: EB-1A (10 criteria), NIW (3 Dhanasar prongs), L-1A (4 standards).
Extensible to EB-2, O-1A, etc. by adding new strategy entries.
"""

from dataclasses import dataclass
from typing import Dict, Tuple

from ..core.prompt_loader import body as _prompt_body
from ..core.prompt_loader import render as _prompt_render


@dataclass(frozen=True)
class WritingStrategy:
    project_type: str
    standard_key: str
    legal_ref: str
    step1_base_system_prompt: str        # shared base system prompt
    step1_argumentation_appendix: str    # per-standard appendix added after base
    step1_instruction_block: str         # user-prompt instruction block
    sentence_range: Tuple[int, int]      # (min, max) sentences per sub-argument
    polish_single_subarg: bool           # Step 2: polish even when only 1 sub-arg?
    frame_system_prompt: str             # Step 3: opening/closing system prompt
    cross_section_context: bool          # build cross-section context (NIW prong3)


# ============================================================
# Base system prompts (defined once, shared across standards)
# ============================================================

_EB1A_BASE_SYSTEM_PROMPT = _prompt_body("writer/eb1a_base_system_prompt")

_NIW_BASE_SYSTEM_PROMPT = _prompt_body("writer/niw_base_system_prompt")


# ============================================================
# Step 3 frame system prompts
# ============================================================

_EB1A_FRAME_SYSTEM_PROMPT = _prompt_body("writer/eb1a_frame_system_prompt")
_NIW_FRAME_SYSTEM_PROMPT = _prompt_body("writer/niw_frame_system_prompt")


# ============================================================
# Shared instruction tail (appended to every step1 instruction block)
# ============================================================

_INSTRUCTION_TAIL = _prompt_body("writer/instruction_tail")


def _eb1a_instruction(chain: str, sentence_range: Tuple[int, int]) -> str:
    lo, hi = sentence_range
    return _prompt_render("writer/eb1a_instruction",
        lo=lo,
        hi=hi,
        chain=chain,
        _INSTRUCTION_TAIL=_INSTRUCTION_TAIL,
    )


def _niw_instruction(chain: str, sentence_range: Tuple[int, int], standard_key: str = "") -> str:
    lo, hi = sentence_range
    prong3_rules = ""
    if standard_key == "prong3_balance":
        prong3_rules = (
            "- CROSS-PRONG REFRAMING (MANDATORY): Reference at least 3 specific\n"
            "  accomplishments from Prongs 1 and 2 in your waiver argument. REFRAME each\n"
            "  as evidence for why labor certification is impractical or contrary to\n"
            "  national interest — do NOT simply restate them.\n"
            "- POLICY ARGUMENT STRUCTURE: Each paragraph must make a legal CONCLUSION\n"
            "  about why waiver is justified, then support it with facts. Do NOT write\n"
            "  a narrative of accomplishments.\n"
            "- BALANCING LANGUAGE (MANDATORY): Include explicit legal balancing phrases:\n"
            "  'on balance', 'the national interest outweighs', etc.\n"
        )
    return _prompt_render("writer/niw_instruction",
        chain=chain,
        lo=lo,
        hi=hi,
        prong3_rules=prong3_rules,
        _INSTRUCTION_TAIL=_INSTRUCTION_TAIL,
    )


# ============================================================
# NIW per-prong argumentation appendices
# ============================================================

_NIW_APPENDICES: Dict[str, str] = {
    k: _prompt_body(f"writer/niw_appendix_{k}")
    for k in ["prong1_merit", "prong2_positioned", "prong3_balance"]
}


# ============================================================
# EB-1A per-criterion argumentation appendices
# ============================================================

_EB1A_APPENDICES: Dict[str, str] = {
    k: _prompt_body(f"writer/eb1a_appendix_{k}")
    for k in ["awards", "membership", "published", "judging", "contribution", "scholarly", "display", "leading", "salary", "commercial", "overall_merits"]
}


# ============================================================
# Strategy registry
# ============================================================

def _build_eb1a_strategy(
    standard_key: str,
    legal_ref: str,
    chain: str,
    sentence_range: Tuple[int, int],
) -> WritingStrategy:
    appendix = _EB1A_APPENDICES.get(standard_key, "")
    return WritingStrategy(
        project_type="EB-1A",
        standard_key=standard_key,
        legal_ref=legal_ref,
        step1_base_system_prompt=_EB1A_BASE_SYSTEM_PROMPT,
        step1_argumentation_appendix=appendix,
        step1_instruction_block=_eb1a_instruction(chain, sentence_range),
        sentence_range=sentence_range,
        polish_single_subarg=False,
        frame_system_prompt=_EB1A_FRAME_SYSTEM_PROMPT,
        cross_section_context=False,
    )


def _build_niw_strategy(
    standard_key: str,
    legal_ref: str,
    chain: str,
    sentence_range: Tuple[int, int],
    cross_section_context: bool = False,
) -> WritingStrategy:
    return WritingStrategy(
        project_type="NIW",
        standard_key=standard_key,
        legal_ref=legal_ref,
        step1_base_system_prompt=_NIW_BASE_SYSTEM_PROMPT,
        step1_argumentation_appendix=_NIW_APPENDICES.get(standard_key, ""),
        step1_instruction_block=_niw_instruction(chain, sentence_range, standard_key=standard_key),
        sentence_range=sentence_range,
        polish_single_subarg=True,
        frame_system_prompt=_NIW_FRAME_SYSTEM_PROMPT,
        cross_section_context=cross_section_context,
    )


# ---------- EB-1A strategies ----------

_EB1A_STRATEGIES: Dict[str, WritingStrategy] = {
    "awards": _build_eb1a_strategy(
        "awards",
        "8 C.F.R. §204.5(h)(3)(i)",
        "granting body background → selection criteria (quote charter/rules) → COMPUTE acceptance rate percentage → co-recipient bios (3-5 sentences each) → regulatory tie-back",
        (6, 12),
    ),
    "membership": _build_eb1a_strategy(
        "membership",
        "8 C.F.R. §204.5(h)(3)(ii)",
        "association background → admission requirements (quote charter articles) → expert judgment in selection (named reviewers) → exclusivity + co-member credentials → regulatory tie-back",
        (6, 12),
    ),
    "published": _build_eb1a_strategy(
        "published",
        "8 C.F.R. §204.5(h)(3)(iii)",
        "publication founding + circulation + data source → editorial independence → substantive coverage proving material is ABOUT the Beneficiary → regulatory tie-back",
        (6, 10),
    ),
    "judging": _build_eb1a_strategy(
        "judging",
        "8 C.F.R. §204.5(h)(3)(iv)",
        "organization background + exact role title → selection as judge → scope + scale (quantify cases/submissions) + decision weight → co-judge credentials + impact → regulatory tie-back",
        (6, 12),
    ),
    "contribution": _build_eb1a_strategy(
        "contribution",
        "8 C.F.R. §204.5(h)(3)(v)",
        "technical description → adoption + commercialization data (page views, orders, revenue) → named beneficiaries with specific outcomes → expert endorsement quotes → field-wide significance → regulatory tie-back",
        (8, 15),
    ),
    "scholarly": _build_eb1a_strategy(
        "scholarly",
        "8 C.F.R. §204.5(h)(3)(vi)",
        "journal publisher + IF + ranking → COMPUTE citation percentile against field averages → article impact + recommendation letter quotes → cross-discipline breadth → regulatory tie-back",
        (6, 12),
    ),
    "display": _build_eb1a_strategy(
        "display",
        "8 C.F.R. §204.5(h)(3)(vii)",
        "venue prestige → curatorial selection → audience reach → critical reception",
        (3, 5),
    ),
    "leading": _build_eb1a_strategy(
        "leading",
        "8 C.F.R. §204.5(h)(3)(viii)",
        "institution background (founding + government recognition + credit rating) → role title + enumerated duties → quantified impact (monetary amounts, participant counts, mentee outcomes) → decision-making authority → external validation (government/association endorsement quotes) → regulatory tie-back",
        (8, 15),
    ),
    "salary": _build_eb1a_strategy(
        "salary",
        "8 C.F.R. §204.5(h)(3)(ix)",
        "dual-currency compensation amount → named third-party benchmark source + methodology → COMPUTE salary multiplier → supplemental income line-by-line → regulatory tie-back",
        (5, 10),
    ),
    "commercial": _build_eb1a_strategy(
        "commercial",
        "8 C.F.R. §204.5(h)(3)(x)",
        "revenue/sales → market benchmarks → critical reception → sustained performance",
        (3, 5),
    ),
    "overall_merits": WritingStrategy(
        project_type="EB-1A",
        standard_key="overall_merits",
        legal_ref="8 C.F.R. §204.5(h)(2) & Kazarian v. USCIS, 596 F.3d 1115 (9th Cir. 2010)",
        step1_base_system_prompt=_EB1A_BASE_SYSTEM_PROMPT,
        step1_argumentation_appendix=_EB1A_APPENDICES.get("overall_merits", ""),
        step1_instruction_block=_eb1a_instruction(
            "totality declaration (list all established criteria) → supplemental evidence by theme → "
            "cross-criteria synthesis (connect awards to leadership, publications to contributions, etc.) → "
            "totality conclusion (small percentage at top of field + sustained acclaim)",
            (4, 8),
        ),
        sentence_range=(4, 8),
        polish_single_subarg=False,
        frame_system_prompt=_EB1A_FRAME_SYSTEM_PROMPT,
        cross_section_context=True,
    ),
}


# ---------- NIW strategies ----------

_NIW_STRATEGIES: Dict[str, WritingStrategy] = {
    "prong1_merit": _build_niw_strategy(
        "prong1_merit",
        "Matter of Dhanasar, 26 I&N Dec. 884 (AAO 2016), Prong 1",
        (
            "ARGUMENTATION CHAIN for Prong 1 (Substantial Merit & National Importance):\n"
            "  endeavor definition → substantive value with concrete evidence → "
            "national-level importance (statistics, policy relevance, broad applicability)"
        ),
        (5, 10),
    ),
    "prong2_positioned": _build_niw_strategy(
        "prong2_positioned",
        "Matter of Dhanasar, 26 I&N Dec. 884 (AAO 2016), Prong 2",
        (
            "ARGUMENTATION CHAIN for Prong 2 (Well Positioned to Advance):\n"
            "  qualifications & expertise → track record of achievements → "
            "progress already made → concrete future plans"
        ),
        (5, 10),
    ),
    "prong3_balance": _build_niw_strategy(
        "prong3_balance",
        "Matter of Dhanasar, 26 I&N Dec. 884 (AAO 2016), Prong 3",
        (
            "ARGUMENTATION CHAIN for Prong 3 (Balance of Equities — Waiver Justification):\n"
            "  impracticality of labor certification → national benefit analysis → "
            "benefits beyond any single employer → urgency (if applicable) → explicit balancing"
        ),
        (6, 12),
        cross_section_context=True,
    ),
}


# ---------- Key aliases (backward compatibility) ----------

_KEY_ALIASES: Dict[str, str] = {
    "press": "published",
    "published_material": "published",
    "original_contribution": "contribution",
    "original_contributions": "contribution",
    "scholarly_articles": "scholarly",
    "exhibitions": "display",
    "leading_role": "leading",
    "high_salary": "salary",
    "commercial_success": "commercial",
}

# Fallback generic EB-1A strategy for unknown keys
_EB1A_GENERIC = WritingStrategy(
    project_type="EB-1A",
    standard_key="_generic",
    legal_ref="",
    step1_base_system_prompt=_EB1A_BASE_SYSTEM_PROMPT,
    step1_argumentation_appendix="",
    step1_instruction_block=_eb1a_instruction(
        "fact → authority → rigor → scale → peer comparison", (3, 6)
    ),
    sentence_range=(3, 6),
    polish_single_subarg=False,
    frame_system_prompt=_EB1A_FRAME_SYSTEM_PROMPT,
    cross_section_context=False,
)

# Fallback generic NIW strategy for unknown keys
_NIW_GENERIC = WritingStrategy(
    project_type="NIW",
    standard_key="_generic",
    legal_ref="",
    step1_base_system_prompt=_NIW_BASE_SYSTEM_PROMPT,
    step1_argumentation_appendix="",
    step1_instruction_block=_niw_instruction(
        "- Build a complete argument chain from the evidence", (3, 6)
    ),
    sentence_range=(3, 6),
    polish_single_subarg=True,
    frame_system_prompt=_NIW_FRAME_SYSTEM_PROMPT,
    cross_section_context=False,
)


# ============================================================
# L-1A base system prompts
# ============================================================

_L1A_BASE_SYSTEM_PROMPT = _prompt_body("writer/l1a_base_system_prompt")

_L1A_FRAME_SYSTEM_PROMPT = _prompt_body("writer/l1a_frame_system_prompt")


def _l1a_instruction(chain: str, sentence_range: Tuple[int, int]) -> str:
    lo, hi = sentence_range
    return _prompt_render("writer/l1a_instruction",
        lo=lo,
        hi=hi,
        chain=chain,
        _INSTRUCTION_TAIL=_INSTRUCTION_TAIL,
    )


# ============================================================
# L-1A per-standard argumentation appendices
# ============================================================

_L1A_APPENDICES: Dict[str, str] = {
    k: _prompt_body(f"writer/l1a_appendix_{k}")
    for k in ["qualifying_relationship", "doing_business", "executive_capacity", "qualifying_employment"]
}


# ---------- L-1A strategies ----------

def _build_l1a_strategy(
    standard_key: str,
    legal_ref: str,
    chain: str,
    sentence_range: Tuple[int, int],
) -> WritingStrategy:
    appendix = _L1A_APPENDICES.get(standard_key, "")
    return WritingStrategy(
        project_type="L-1A",
        standard_key=standard_key,
        legal_ref=legal_ref,
        step1_base_system_prompt=_L1A_BASE_SYSTEM_PROMPT,
        step1_argumentation_appendix=appendix,
        step1_instruction_block=_l1a_instruction(chain, sentence_range),
        sentence_range=sentence_range,
        polish_single_subarg=False,
        frame_system_prompt=_L1A_FRAME_SYSTEM_PROMPT,
        cross_section_context=False,
    )


_L1A_STRATEGIES: Dict[str, WritingStrategy] = {
    "qualifying_relationship": _build_l1a_strategy(
        "qualifying_relationship",
        "INA §101(a)(15)(L); 8 CFR §214.2(l)(1)(ii)",
        "U.S. entity formation → ownership chain (shareholding with corporate records) → physical premises (address, sq ft, lease) → parent investment (amount, bank statement) → regulatory tie-back",
        (6, 12),
    ),
    "doing_business": _build_l1a_strategy(
        "doing_business",
        "8 CFR §214.2(l)(1)(ii)(H)",
        "U.S. business description → financial performance (revenue, tax return) → growth plan (hiring, departments) → customer/partner names → parent company operations (revenue, employees, scope) → regulatory tie-back",
        (8, 15),
    ),
    "executive_capacity": _build_l1a_strategy(
        "executive_capacity",
        "INA §101(a)(44); 8 CFR §214.2(l)(1)(ii)(B)-(C)",
        "proposed position + org overview → 5 duty segments with % time allocation → subordinate managers (names, titles, enumerated duties) → day-to-day delegation → regulatory tie-back",
        (10, 20),
    ),
    "qualifying_employment": _build_l1a_strategy(
        "qualifying_employment",
        "8 CFR §214.2(l)(1)(ii)(A)",
        "education + degrees → employment history (dates, titles, 1+ year continuous) → executive duties abroad (% time) → subordinate management abroad → specific achievements (contracts, revenue) → regulatory tie-back",
        (8, 15),
    ),
}

# Fallback generic L-1A strategy for unknown keys
_L1A_GENERIC = WritingStrategy(
    project_type="L-1A",
    standard_key="_generic",
    legal_ref="",
    step1_base_system_prompt=_L1A_BASE_SYSTEM_PROMPT,
    step1_argumentation_appendix="",
    step1_instruction_block=_l1a_instruction(
        "fact → legal nexus → quantification → corroboration → conclusion", (5, 10)
    ),
    sentence_range=(5, 10),
    polish_single_subarg=False,
    frame_system_prompt=_L1A_FRAME_SYSTEM_PROMPT,
    cross_section_context=False,
)


# ============================================================
# Public API
# ============================================================

def get_writing_strategy(project_type: str, standard_key: str) -> WritingStrategy:
    """
    Look up the writing strategy for a given project type and standard key.

    Resolves key aliases (e.g. "press" → "published") and falls back to
    a generic strategy if the exact key is not found.
    """
    canonical = _KEY_ALIASES.get(standard_key, standard_key)

    if project_type == "NIW":
        strategy = _NIW_STRATEGIES.get(canonical)
        if strategy:
            return strategy
        return _NIW_GENERIC

    if project_type == "L-1A":
        strategy = _L1A_STRATEGIES.get(canonical)
        if strategy:
            return strategy
        return _L1A_GENERIC

    # Default: EB-1A
    strategy = _EB1A_STRATEGIES.get(canonical)
    if strategy:
        return strategy
    return _EB1A_GENERIC
