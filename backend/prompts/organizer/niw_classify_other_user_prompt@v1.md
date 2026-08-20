---
id: organizer/niw_classify_other_user_prompt
version: 1
format: python
variables: ["snippets_text"]
---
Classify each of the following evidence snippets into the most appropriate
Dhanasar prong for an NIW petition.

Prong definitions:
- prong1_merit: The proposed endeavor has substantial merit and national importance
  (e.g., endeavor descriptions, field impact, national importance evidence, contributions)
- prong2_positioned: The applicant is well positioned to advance the endeavor
  (e.g., education, work experience, publications, awards, certifications, expert endorsements)
- prong3_balance: On balance, waiving labor certification benefits the US
  (e.g., national benefit arguments, beyond-employer impact, urgency)
- skip: Not relevant to any prong (e.g., pure formatting, boilerplate, table of contents)

## Snippets to classify

{snippets_text}

Return JSON:
{{
  "classifications": [
    {{"snippet_id": "snp-xxx", "prong": "prong1_merit"}},
    {{"snippet_id": "snp-yyy", "prong": "prong2_positioned"}},
    {{"snippet_id": "snp-zzz", "prong": "skip"}}
  ]
}}

RULES:
1. Every snippet MUST appear exactly once in the output
2. Prefer prong1_merit or prong2_positioned over skip — only skip truly irrelevant content
3. Recommendation letters discussing the applicant's qualifications → prong2_positioned
4. Recommendation letters discussing the endeavor's importance → prong1_merit
5. General professional achievements without clear prong fit → prong2_positioned