---
id: organizer/niw_prong_organize_user_prompt
version: 1
format: python
variables: ["prong_name", "prong_citation", "applicant_name", "prong_description", "snippet_count", "snippets_text", "target_subargs"]
---
## Prong: {prong_name}
## Legal Standard: {prong_citation}
## Applicant: {applicant_name}

{prong_description}

## Evidence Snippets ({snippet_count} total)

{snippets_text}

## Task

Organize ALL the above snippets into coherent sub-arguments for this prong.

RULES:
1. Each sub-argument should be a distinct legal point with a clear theme
2. Cross-reference evidence from different exhibits when they support the same point
3. Recommendation letter content should be distributed to the relevant sub-argument topics
   (do NOT create a separate "recommendation letters" sub-argument)
4. EVERY snippet must be assigned to exactly one sub-argument — 100% coverage required
5. Aim for {target_subargs} sub-arguments depending on evidence volume
6. Title should be a concise legal argument heading (e.g., "Applicant's Research Addresses Critical National Need in X")
7. Purpose should explain what legal point this sub-argument establishes
8. Relationship should be 3-8 words explaining how it supports the prong

Return JSON:
{{
  "sub_arguments": [
    {{
      "title": "Applicant's Research Addresses Critical Need in Renewable Energy",
      "claim": "Brief statement of the legal claim this sub-argument makes",
      "purpose": "Establishes that the applicant's proposed endeavor in X has substantial merit because...",
      "relationship": "Demonstrates substantial merit of endeavor",
      "snippet_ids": ["S1", "S3", "S7", "S12"],
      "reasoning": "These snippets collectively show... grouped because..."
    }}
  ]
}}