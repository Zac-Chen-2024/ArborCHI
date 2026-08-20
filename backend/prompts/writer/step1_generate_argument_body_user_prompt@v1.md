---
id: writer/step1_generate_argument_body_user_prompt
version: 1
format: python
variables: ["standard_get_name", "standard_get_legal_ref", "argument_get_title", "outline_text", "source_text", "snippet_index_text", "cross_prong_context_or", "additional_instructions_block", "step1_instructions", "subarg_json_example", "len_subarg_ids", "subarg_ids"]
---
Draft the body paragraphs for this argument in a petition letter.

STANDARD: {standard_get_name} ({standard_get_legal_ref})
ARGUMENT: {argument_get_title}

SUB-ARGUMENTS (use as structural outline — write one paragraph per sub-argument):
{outline_text}

=== SOURCE MATERIALS (full text — extract ALL relevant details) ===

{source_text}

=== END SOURCE MATERIALS ===

=== SNIPPET INDEX (all evidence blocks on cited exhibits — use these IDs in snippet_ids) ===
{snippet_index_text}
=== END SNIPPET INDEX ===

{cross_prong_context_or}

{additional_instructions_block}

{step1_instructions}

Return JSON:
{{
  "sub_argument_paragraphs": [
    {subarg_json_example}
  ]
}}

CRITICAL: Return ALL {len_subarg_ids} sub-argument paragraphs. subargument_id values MUST be exactly: {subarg_ids}
Return ONLY valid JSON, no markdown.