---
id: organizer/niw_organize_user_prompt
version: 1
format: raw
variables: []
---
## EVIDENCE SUMMARY

{standards_with_evidence_count} prongs have supporting evidence:

{evidence_summary}

## Dhanasar Three-Prong Framework

{standards_text}

## Evidence Snippets by Prong

{snippets_by_standard}

## Task

Organize these snippets into powerful legal arguments under the Dhanasar framework.
Aim for 3-6 arguments total, with at least one per prong.
Valid standard keys: {valid_standard_keys}

Return JSON:
{{
  "arguments": [
    {{
      "id": "arg-001",
      "standard": "prong1_merit",
      "title": "Applicant's Research in X Addresses National Need for Y",
      "rationale": "Why this argument is strong",
      "snippet_ids": ["snp-001", "snp-002"],
      "evidence_strength": "strong|medium|weak"
    }}
  ],
  "filtered_out": [
    {{
      "snippet_ids": ["snp-xxx"],
      "reason": "Not relevant to any Dhanasar prong"
    }}
  ],
  "summary": {{
    "total_arguments": 5,
    "by_standard": {{"prong1_merit": 2, "prong2_positioned": 2, "prong3_balance": 1}}
  }}
}}