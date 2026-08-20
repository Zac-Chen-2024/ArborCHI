---
id: organizer/organize_user_prompt
version: 1
format: raw
variables: []
---
## EVIDENCE SUMMARY

The following {standards_with_evidence_count} EB-1A criteria have supporting evidence.
You MUST create at least one argument for EACH of them:

{evidence_summary}

## Legal Standards and Requirements (only those with evidence)

{standards_text}

## Evidence Snippets by Standard

{snippets_by_standard}

## Task

Create arguments for ALL {standards_with_evidence_count} standards listed above. Do NOT skip any.

Per-standard rules:
- Awards (i): Combine into ONE argument containing all awards
- Membership (ii): One argument per qualifying association (filter ordinary certifications)
- Published Material (iii): Media ABOUT the alien — one argument per major media outlet
- Judging (iv): Combine all judging roles into ONE argument
- Original Contribution (v): Combine ALL into ONE comprehensive argument
- Scholarly Articles (vi): Combine into ONE argument — articles authored BY the alien
- Leading Role (viii): One argument per distinguished organization (select top 2-3)
- High Salary (ix): ONE argument — only if significantly above field average

The "standard" field MUST exactly match one of: {valid_standard_keys}

Return JSON:
{{
  "arguments": [
    {{
      "id": "arg-001",
      "standard": "membership",
      "title": "[Applicant]'s Membership in [Association Name]",
      "rationale": "Why this argument is strong",
      "snippet_ids": ["snp-001", "snp-002"],
      "evidence_strength": "strong|medium|weak"
    }}
  ],
  "filtered_out": [
    {{
      "snippet_ids": ["snp-xxx"],
      "reason": "Ordinary certification, does not meet membership requirements"
    }}
  ],
  "summary": {{
    "total_arguments": 7,
    "by_standard": {{"membership": 1, "scholarly_articles": 1, "judging": 1}}
  }}
}}