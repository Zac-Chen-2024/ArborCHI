---
id: writer/edit_text_with_instruction_user_prompt
version: 1
format: python
variables: ["original_text", "history_block", "instruction"]
---
ORIGINAL TEXT:
"{original_text}"

{history_block}

CURRENT INSTRUCTION: {instruction}

Please revise the text according to the instruction. Return a JSON object:
{{
    "revised_text": "the revised text",
    "explanation": "brief explanation of changes made"
}}

Return ONLY valid JSON, no markdown or extra text.