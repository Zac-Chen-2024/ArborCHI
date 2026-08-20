---
id: writer/step3_generate_section_frame_user_prompt
version: 1
format: python
variables: ["standard_get_name", "standard_get_legal_ref", "summary_text"]
---
Write an opening sentence and a closing sentence for the "{standard_get_name}" ({standard_get_legal_ref}) section of a petition letter.

The section contains these arguments and sub-arguments:
{summary_text}

OPENING SENTENCE:
- MUST explicitly cite the regulation: "{standard_get_legal_ref}"
- Briefly introduce the scope — do NOT include specific facts, dates, or names (the body handles that)
- Keep it to ONE concise sentence

CLOSING SENTENCE:
- Summarize the argument scope in ONE sentence
- Confident, conclusive legal language
- Do NOT introduce any new facts not covered in the body

Return JSON:
{{
  "opening_text": "The Beneficiary satisfies {standard_get_legal_ref} by demonstrating...",
  "closing_text": "In sum, the foregoing evidence clearly establishes..."
}}

100% English. Return ONLY valid JSON.