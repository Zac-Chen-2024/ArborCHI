---
id: organizer/niw_topdown_pickup_for_prong_user_prompt
version: 1
format: python
variables: ["prong_info_get_name_prong_key", "prong_info_get_citation", "prong_info_get_requirements", "len_all_snippets", "snippets_text"]
---
## Dhanasar Prong: {prong_info_get_name_prong_key}
**Citation**: {prong_info_get_citation}
**Legal Requirements**:
{prong_info_get_requirements}

## All Available Snippets ({len_all_snippets} total)
{snippets_text}

Select snippets relevant to "{prong_info_get_name_prong_key}" following the selection rules above.
