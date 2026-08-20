---
id: writer/recover_snippet_ids_by_llm_prompt
version: 1
format: python
variables: ["sentence_text", "candidates_text"]
---
Match this sentence to the most relevant evidence snippets.

SENTENCE: "{sentence_text}"

CANDIDATE SNIPPETS:
{candidates_text}

Return JSON: {{"snippet_ids": ["id1", "id2"]}}
Only include snippets that this sentence DIRECTLY references or paraphrases. Return empty if none match.