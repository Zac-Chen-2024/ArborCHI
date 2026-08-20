---
id: writer/step2_polish_single_subarg_user_prompt
version: 1
format: python
variables: ["standard_get_name", "len_sentences", "sentences_text"]
---
Revise the following paragraph for the "{standard_get_name}" section.

CURRENT TEXT ({len_sentences} sentences):
{sentences_text}

INSTRUCTIONS:
1. Improve sentence-to-sentence flow: add connective phrases, vary sentence openings
2. Strengthen argumentative language — make legal conclusions more assertive
3. PRESERVE all [Exhibit X, p.Y] citations EXACTLY — do not change, add, or remove any
4. PRESERVE the exact number of sentences ({len_sentences})
5. Do NOT add new facts or remove existing ones
6. 100% English output

Return JSON:
{{
  "sentences": [
    {{"text": "revised sentence...", "snippet_ids": ["..."], "exhibit_refs": ["..."]}}
  ]
}}

CRITICAL: Return EXACTLY {len_sentences} sentences. Return ONLY valid JSON.