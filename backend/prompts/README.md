# Prompt registry

Every LLM prompt used by the backend lives here as a versioned file, loaded by
`app/core/prompt_loader.py`. Code never contains prompt text longer than a
line or two.

```
prompts/<module>/<name>@v<N>.md      # prompt text
prompts/<module>/<name>@v<N>.json    # structured prompt content (see below)
```

Currently 108 `.md` prompts + 2 `.json` assets.

| module | used by |
|---|---|
| `extractor/`     | `unified_extractor.py` (EB-1A / NIW / L-1A extraction) |
| `organizer/`     | `legal_argument_organizer.py` (argument organisation, top-down pickup, per-standard `*_requirements_*` texts) |
| `subdivider/`    | `subargument_generator.py` (sub-argument subdivision + per-standard guidance) |
| `writer/`        | `petition_writer_v3.py` (step 1/2/3, edit, recover ids) and `writing_strategies.py` (base system prompts, appendices, instructions) |
| `recommender/`   | `snippet_recommender.py` (recommend / infer relationship / infer title / consolidate) |
| `entity_merger/` | `entity_merger.py` |

## File format

```
---
id: writer/step1_generate_subargument_body_user_prompt
version: 1
format: python          # python = str.format() template | raw = used verbatim (may contain single braces)
variables: ["subargument_title", "argument_title", ...]   # must equal the placeholders in the body
---
<body, verbatim>
```

* `format: python` bodies are Python `str.format()` templates: `{name}` placeholders, literal braces as `{{ }}`.
* `format: raw` bodies are returned as-is via `prompt_loader.body(id)`; callers may `.format()` them
  themselves (legacy constants) or concatenate them.

## JSON data assets

Some prompt content is structured rather than prose — the per-standard evidence pickup criteria
(`organizer/eb1a_topdown_pickup_criteria@v1.json`, `organizer/niw_topdown_pickup_criteria@v1.json`) are
lists of include / exclude rules that the organizer formats into its prompt. They live here, under the same
naming and versioning rules, and are loaded with `prompt_loader.load_data("organizer/<name>")`.

They are hashed into the same snapshot as prompt bodies, so editing a criterion is a `prompt:` commit like
any other wording change. Treat them as prompt text that happens to be JSON, not as configuration.

## Rules

1. **Wording changes are `prompt:` commits, nothing else in the diff.**
2. Changing a body (or a `.json` asset) **without** bumping the version fails `tests/test_prompts.py`
   (hash snapshot in `tests/fixtures/prompt_hashes.json`). Either bump to `@v2`
   (new file, old one stays for reproducibility) or, for a deliberate in-place
   fix, refresh the snapshot in the same `prompt:` commit:
   `python -c "from tests.test_prompts import refresh; refresh()"`
3. `validate_all()` runs at startup: every file must parse and its `variables`
   must equal the placeholders it uses.
4. `render()` returns a `str` subclass carrying `prompt_id / version / hash`;
   the LLM client writes those into the trace (M9), so every model output can
   be tied to the exact prompt text that produced it.
