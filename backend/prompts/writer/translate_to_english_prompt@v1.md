---
id: writer/translate_to_english_prompt
version: 1
format: python
variables: ["text"]
---
Translate the following text to English.
IMPORTANT:
1. Keep all exhibit citations (e.g., [Exhibit C-2, p.3]) exactly as they are
2. Keep all formatting including block quotes (> "...")
3. Translate ONLY the non-English text to English
4. Do NOT add any explanations, just return the translated text

Text to translate:
{text}