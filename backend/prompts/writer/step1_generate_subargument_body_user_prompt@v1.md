---
id: writer/step1_generate_subargument_body_user_prompt
version: 1
format: python
variables: ["subargument_title", "argument_title", "evidence_text", "additional_instructions_block", "snippet_ids_str", "example_snippet_id"]
---
Draft 2-4 sentences for this sub-argument in a petition letter.

SUB-ARGUMENT: {subargument_title}
PARENT ARGUMENT: {argument_title}

EVIDENCE SNIPPETS:
{evidence_text}

{additional_instructions_block}

WRITING STYLE — Each sentence must follow this pattern:
  [Legal argumentative claim] + [evidence from snippet with Exhibit citation]

  GOOD: "The organization's longstanding commitment to excellence is evidenced by its receipt of [Award Name] on multiple occasions [Exhibit X, p.Y]."
  BAD:  "[Organization] wins [Award]." (raw snippet headline, no argumentation)

  GOOD: "The Beneficiary's formal authority within [Organization] is confirmed by her role as legal representative [Exhibit X, p.Y]."
  BAD:  "I serve as the legal representative of [Organization]." (first person, raw snippet copy)

RULES:
1. Use ONLY facts from the snippets above. Do NOT invent dates, statistics, or names.
2. Each sentence must cite [Exhibit X, p.Y] and reference snippet_id(s). Valid IDs: [{snippet_ids_str}]
3. Embed 1-2 short direct quotes from snippets naturally within sentences (do NOT use block quote format).
4. Professional legal tone, 100% English (translate non-English source text).
5. Write 2-4 sentences — match the evidence available. No filler.

Return JSON:
{{
  "sentences": [
    {{
      "text": "Argumentative sentence with evidence [Exhibit X, p.Y].",
      "snippet_ids": ["{example_snippet_id}"],
      "exhibit_refs": ["X-Y"]
    }}
  ]
}}

Return ONLY valid JSON, no markdown.