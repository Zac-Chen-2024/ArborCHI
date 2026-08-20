---
id: extractor/llm_match_blocks_prompt
version: 1
format: python
variables: ["exhibit_id", "blocks_text", "snippets_text"]
---
You are matching extracted text snippets to their source blocks in a document.

Each snippet was extracted from one of the blocks below, but the block_id was lost.
For each snippet, find the block that BEST CONTAINS or MATCHES the snippet text.

## Available Blocks (Exhibit {exhibit_id})
{blocks_text}

## Snippets to Match
{snippets_text}

## Instructions
For each snippet, output the block_id of the block that most likely contains that text.
Look for keyword overlap, topic similarity, or partial text matches.

Return JSON:
{{
  "matches": [
    {{"snippet": "SNIPPET_0", "block_id": "p3_b2", "confidence": 0.9}},
    ...
  ]
}}