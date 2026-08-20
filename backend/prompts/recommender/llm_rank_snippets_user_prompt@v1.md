---
id: recommender/llm_rank_snippets_user_prompt
version: 1
format: python
variables: ["standard_key", "argument_title", "title", "description_or_n_a", "chr_10_join_snippets_formatted"]
---
## Context
Standard: {standard_key}
Main Argument: {argument_title}

## Sub-Argument to Support
Title: {title}
Description: {description_or_n_a}

## Candidate Snippets
{chr_10_join_snippets_formatted}

## Task
Rank these snippets by their relevance to the sub-argument "{title}".
Consider how well each snippet supports or provides evidence for this specific sub-argument.