---
id: writer/step2_polish_argument_user_prompt
version: 1
format: python
variables: ["standard_get_name", "input_text", "subarg_ids_0", "second_subarg_id_example", "len_subarg_ids"]
---
Polish the following sub-argument paragraphs for the "{standard_get_name}" section.

CURRENT TEXT (grouped by SubArgument):

{input_text}

INSTRUCTIONS:
1. Add transition phrases BETWEEN SubArgument groups ("Furthermore,", "In addition to the above,", "Moreover,", etc.)
2. PRESERVE all [Exhibit X, p.Y] citations and direct quotes EXACTLY — do not change any facts, dates, names, or numbers
3. MUST keep the same SubArgument grouping — do NOT merge or split SubArguments
4. MUST keep the same number of sentences per SubArgument group
5. Only change: word order, transition words, connective phrases. Do NOT add new facts.
6. 100% English output

Return JSON with the SAME structure:
{{
  "subargument_paragraphs": [
    {{
      "subargument_id": "{subarg_ids_0}",
      "sentences": [
        {{"text": "polished sentence...", "snippet_ids": ["snip_xxx"], "exhibit_refs": ["X-Y"]}}
      ]
    }},
    {{
      "subargument_id": "{second_subarg_id_example}",
      "sentences": [
        {{"text": "Furthermore, polished sentence...", "snippet_ids": ["snip_yyy"], "exhibit_refs": ["X-Y"]}}
      ]
    }}
  ]
}}

CRITICAL: Return ALL {len_subarg_ids} SubArgument groups. Do NOT skip any.
Return ONLY valid JSON.