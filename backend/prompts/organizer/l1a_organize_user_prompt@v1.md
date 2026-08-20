---
id: organizer/l1a_organize_user_prompt
version: 1
format: raw
variables: []
---
## EVIDENCE SUMMARY

The following {standards_with_evidence_count} L-1A standards have supporting evidence.
You MUST create at least one argument for EACH of them:

{evidence_summary}

## Legal Standards and Requirements (only those with evidence)

{standards_text}

## Evidence Snippets by Standard

{snippets_by_standard}

## Task

Create arguments for ALL {standards_with_evidence_count} standards listed above. Do NOT skip any.

Per-standard rules:
- Qualifying Relationship: ONE unified argument covering ownership, premises, and investment
- Doing Business: ONE argument covering both U.S. and foreign entity operations
- Executive Capacity: ONE argument with org chart, duties, and subordinate management
- Qualifying Employment: ONE argument covering background, employment history, and achievements

The "standard" field MUST exactly match one of: {valid_standard_keys}

Return JSON:
{{
  "arguments": [
    {{
      "id": "arg-001",
      "standard": "qualifying_relationship",
      "title": "Qualifying Relationship Between [Foreign Co.] and [U.S. Co.]",
      "rationale": "Why this argument is strong",
      "snippet_ids": ["snp-001", "snp-002"],
      "evidence_strength": "strong|medium|weak"
    }}
  ],
  "filtered_out": [
    {{
      "snippet_ids": ["snp-xxx"],
      "reason": "Not relevant to any L-1A standard"
    }}
  ],
  "summary": {{
    "total_arguments": 4,
    "by_standard": {{"qualifying_relationship": 1, "doing_business": 1, "executive_capacity": 1, "qualifying_employment": 1}}
  }}
}}