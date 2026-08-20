---
id: entity_merger/merge_suggestion_user_prompt
version: 1
format: python
variables: ["entities_text"]
---
Analyze these entities extracted from EB-1A petition documents and identify which ones refer to the SAME real-world entity.

## Entities (grouped by type)

{entities_text}

## Instructions

For each group of entities that should be merged:
1. Choose the most formal/complete name as the PRIMARY entity
2. List all other names as MERGE targets
3. Explain WHY they are the same entity

Return JSON format:
{{
  "merge_suggestions": [
    {{
      "primary_name": "The most formal name",
      "merge_names": ["alias1", "alias2"],
      "entity_type": "person|organization|...",
      "reason": "Why these are the same",
      "confidence": 0.9
    }}
  ]
}}

If no merges are needed, return {{"merge_suggestions": []}}