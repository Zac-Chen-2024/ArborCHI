---
id: organizer/topdown_pickup_for_standard_user_prompt
version: 1
format: python
variables: ["standard_info_get_name_standard_key", "standard_info_get_citation", "standard_info_get_requirements", "len_all_snippets", "snippets_text"]
---
## Standard: {standard_info_get_name_standard_key}
**Citation**: {standard_info_get_citation}
**Legal Requirements**:
{standard_info_get_requirements}

## All Available Snippets ({len_all_snippets} total)
{snippets_text}

Select snippets relevant to "{standard_info_get_name_standard_key}" following the selection rules above.
