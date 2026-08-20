---
id: writer/analyze_change_impact_user_prompt
version: 1
format: python
variables: ["action", "change_type", "indexed_text", "change_type_capitalize", "affected_title", "affected_subargument_id"]
---
A sub-argument was just {action} this petition letter section.

CURRENT TEXT (after mechanical {change_type}):
{indexed_text}

CHANGE DESCRIPTION:
- {change_type_capitalize}d SubArgument: "{affected_title}"
- SubArgument ID: {affected_subargument_id}

TASK: Identify sentences that need adjustment due to this change.
Check for:
1. Opening paragraph references to deleted content (e.g., count changes like "three aspects" → "two aspects")
2. Closing paragraph summaries that reference removed points
3. Transition sentences ("Furthermore...", "In addition...") that now dangle
4. Cross-references to removed exhibits

Return JSON:
{{
  "suggestions": [
    {{
      "sentence_index": 0,
      "original_text": "exact current text",
      "suggested_text": "revised text",
      "reason": "brief explanation"
    }}
  ]
}}
Only return suggestions where changes are actually needed. Return empty array if no changes needed.