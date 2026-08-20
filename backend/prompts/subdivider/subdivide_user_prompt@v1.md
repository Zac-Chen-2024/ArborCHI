---
id: subdivider/subdivide_user_prompt
version: 1
format: python
variables: ["argument_title", "standard", "snippet_count", "subdivision_guidance", "snippets_formatted"]
---
Main Argument: {argument_title}
Standard: {standard}
Total Snippets: {snippet_count}

## How to Split Sub-Arguments for This Standard
{subdivision_guidance}

## Snippets
{snippets_formatted}

Organize these snippets into logical sub-groups following the guidance above.

Return JSON:
{{
  "sub_arguments": [
    {{
      "title": "...",
      "purpose": "...",
      "relationship": "...",
      "snippet_ids": ["S1", "S3"]
    }}
  ]
}}

RULES:
1. Follow the standard-specific splitting unit above (per-award, per-publication, per-role, etc.)
2. Each snippet must be assigned to exactly ONE sub-group
3. Use English for all title, purpose, and relationship fields
4. Relationship should be 2-5 words explaining how this supports the main argument
5. If snippets are too few (<=3), create 2 sub-groups
6. Create at least 2 sub-groups