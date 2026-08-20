"""
Prompt registry (Doc/01 M8, plan 1.1).

Prompts are versioned artifacts, not code constants. They live in
backend/prompts/<module>/<name>@v<N>.md:

    ---
    id: writer/step1_subarg_body
    version: 1
    format: python            # python = str.format() template (default) | raw = used verbatim
    variables: [standard_name, subargument_title, ...]
    model: default            # optional hints, consumed by callers / llm_client
    temperature: 0.1
    max_tokens: 4000
    ---
    <template body, verbatim>

The body is a Python str.format() template -- the same convention the code
already used -- so migration is a byte-for-byte move. Literal braces are
written {{ }} exactly as before.

API
    render("writer/step1_subarg_body", **vars) -> RenderedPrompt(text, prompt_id, version, hash, meta)
    body("extractor/eb1a_system")              -> raw template string (for constants)
    validate_all()                              -> raises PromptError on any broken file
                                                   (called at app startup)
    Each render's (prompt_id, version, hash) is what M9 writes into the LLM trace,
    so an output can always be tied to the exact prompt text that produced it.
"""

from __future__ import annotations

import hashlib
import json
import re
import string
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"

_FILE_RE = re.compile(r"^(?P<name>[A-Za-z0-9_\-]+)@v(?P<version>\d+)\.md$")
_FM_DELIM = "---\n"


class PromptError(Exception):
    pass


@dataclass
class Prompt:
    id: str                 # "module/name"
    version: int
    body: str
    meta: Dict[str, Any] = field(default_factory=dict)
    path: Optional[Path] = None

    @property
    def variables(self) -> List[str]:
        return list(self.meta.get("variables") or [])

    @property
    def is_template(self) -> bool:
        return (self.meta.get("format") or "python") == "python"

    def placeholders(self) -> List[str]:
        """Field names referenced by the str.format() template."""
        names: List[str] = []
        for _lit, field_name, _spec, _conv in string.Formatter().parse(self.body):
            if field_name is None:
                continue
            base = field_name.split(".")[0].split("[")[0]
            if base and base not in names:
                names.append(base)
        return names


class RenderedPrompt(str):
    """A rendered prompt IS a str (drops straight into call_llm / json bodies)
    that additionally carries prompt_id / version / hash for tracing (M9)."""

    prompt_id: str
    version: int
    hash: str
    meta: Dict[str, Any]

    def __new__(cls, text: str, prompt_id: str, version: int, hash: str, meta: Optional[Dict[str, Any]] = None):
        obj = str.__new__(cls, text)
        obj.prompt_id = prompt_id
        obj.version = version
        obj.hash = hash
        obj.meta = dict(meta or {})
        return obj

    @property
    def text(self) -> str:
        return str(self)

    def __repr__(self) -> str:
        return f"RenderedPrompt({self.prompt_id}@v{self.version} {self.hash} len={len(self)})"


# ---------------------------------------------------------------------------
# Front-matter (deliberately tiny YAML subset: `key: scalar` / `key: [a, b]`)
# ---------------------------------------------------------------------------

def _parse_scalar(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith("[") or raw.startswith("{") or raw.startswith('"'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # tolerate unquoted list items: [a, b_c]
            if raw.startswith("[") and raw.endswith("]"):
                return [x.strip().strip("'\"") for x in raw[1:-1].split(",") if x.strip()]
            raise
    low = raw.lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("null", "none", "~"):
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw.strip("'\"")


def _split_front_matter(text: str, path: Path) -> tuple[Dict[str, Any], str]:
    if not text.startswith(_FM_DELIM):
        raise PromptError(f"{path}: missing front-matter (file must start with '---')")
    end = text.find("\n" + _FM_DELIM, len(_FM_DELIM) - 1)
    if end == -1:
        raise PromptError(f"{path}: unterminated front-matter")
    fm_text = text[len(_FM_DELIM):end + 1]
    body = text[end + 1 + len(_FM_DELIM):]
    meta: Dict[str, Any] = {}
    for line in fm_text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise PromptError(f"{path}: bad front-matter line {line!r}")
        k, v = line.split(":", 1)
        meta[k.strip()] = _parse_scalar(v)
    return meta, body


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _candidates(prompt_id: str) -> List[Path]:
    module, _, name = prompt_id.rpartition("/")
    if not module or not name:
        raise PromptError(f"prompt id must look like 'module/name', got {prompt_id!r}")
    d = PROMPTS_DIR / module
    if not d.is_dir():
        return []
    return [p for p in d.iterdir() if (m := _FILE_RE.match(p.name)) and m.group("name") == name]


@lru_cache(maxsize=None)
def load(prompt_id: str, version: Optional[int] = None) -> Prompt:
    """Load prompt `module/name` (latest version unless `version` given)."""
    files = _candidates(prompt_id)
    if not files:
        raise PromptError(f"prompt not found: {prompt_id!r} (looked in {PROMPTS_DIR})")
    by_ver = {int(_FILE_RE.match(p.name).group("version")): p for p in files}
    ver = version if version is not None else max(by_ver)
    if ver not in by_ver:
        raise PromptError(f"prompt {prompt_id!r} has no version {ver}; available: {sorted(by_ver)}")
    path = by_ver[ver]
    meta, body = _split_front_matter(path.read_text(encoding="utf-8"), path)
    if meta.get("id") not in (None, prompt_id):
        raise PromptError(f"{path}: front-matter id {meta.get('id')!r} != {prompt_id!r}")
    if meta.get("version") not in (None, ver):
        raise PromptError(f"{path}: front-matter version {meta.get('version')!r} != filename v{ver}")
    return Prompt(id=prompt_id, version=ver, body=body, meta=meta, path=path)


_DATA_RE = re.compile(r"^(?P<name>[A-Za-z0-9_\-]+)@v(?P<version>\d+)\.json$")


@lru_cache(maxsize=None)
def load_data(data_id: str, version: Optional[int] = None) -> Any:
    """Load a versioned JSON asset `module/name` (e.g. structured pickup criteria)
    that is prompt content in all but shape. Same naming/versioning rules as
    prompts; hashed into the snapshot test like any prompt body."""
    module, _, name = data_id.rpartition("/")
    if not module or not name:
        raise PromptError(f"data id must look like 'module/name', got {data_id!r}")
    d = PROMPTS_DIR / module
    files = [p for p in d.iterdir() if (m := _DATA_RE.match(p.name)) and m.group("name") == name] if d.is_dir() else []
    if not files:
        raise PromptError(f"data asset not found: {data_id!r} (looked in {PROMPTS_DIR})")
    by_ver = {int(_DATA_RE.match(p.name).group("version")): p for p in files}
    ver = version if version is not None else max(by_ver)
    if ver not in by_ver:
        raise PromptError(f"data asset {data_id!r} has no version {ver}; available: {sorted(by_ver)}")
    return json.loads(by_ver[ver].read_text(encoding="utf-8"))


def list_data_assets() -> List[tuple]:
    """(id, version, raw_text) for every JSON asset -- for the hash snapshot."""
    out = []
    if not PROMPTS_DIR.is_dir():
        return out
    for module_dir in sorted(PROMPTS_DIR.iterdir()):
        if not module_dir.is_dir():
            continue
        for f in sorted(module_dir.iterdir()):
            m = _DATA_RE.match(f.name)
            if m:
                out.append((f"{module_dir.name}/{m.group('name')}", int(m.group("version")), f.read_text(encoding="utf-8")))
    return out


def body(prompt_id: str, version: Optional[int] = None) -> str:
    """Raw template text (for module-level constants that are formatted later)."""
    return load(prompt_id, version).body


def render(prompt_id: str, version: Optional[int] = None, **variables: Any) -> RenderedPrompt:
    """str.format() the template with `variables`. Missing variables raise PromptError."""
    p = load(prompt_id, version)
    if not p.is_template:
        raise PromptError(f"prompt {prompt_id}@v{p.version} is format: raw; use body() instead of render()")
    try:
        text = p.body.format(**variables)
    except KeyError as e:
        raise PromptError(f"prompt {prompt_id}@v{p.version}: missing variable {e.args[0]!r}") from e
    except (IndexError, ValueError) as e:
        raise PromptError(f"prompt {prompt_id}@v{p.version}: bad template: {e}") from e
    return RenderedPrompt(
        text=text,
        prompt_id=prompt_id,
        version=p.version,
        hash=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        meta=p.meta,
    )


def list_prompts() -> List[Prompt]:
    out: List[Prompt] = []
    if not PROMPTS_DIR.is_dir():
        return out
    for module_dir in sorted(PROMPTS_DIR.iterdir()):
        if not module_dir.is_dir():
            continue
        seen = set()
        for f in sorted(module_dir.iterdir()):
            m = _FILE_RE.match(f.name)
            if not m:
                continue
            pid = f"{module_dir.name}/{m.group('name')}"
            if pid in seen:
                continue
            seen.add(pid)
            out.append(load(pid))
    return out


def validate_all() -> List[Prompt]:
    """Parse every prompt file and check declared variables == placeholders.

    Called at startup so a broken template fails fast instead of at the first
    LLM call two minutes into a pipeline.
    """
    prompts = list_prompts()
    problems: List[str] = []
    for p in prompts:
        if not p.is_template:
            continue
        declared = set(p.variables)
        try:
            used = set(p.placeholders())
        except ValueError as e:
            problems.append(f"{p.id}@v{p.version}: not a valid format string ({e})")
            continue
        if declared != used:
            problems.append(
                f"{p.id}@v{p.version}: variables mismatch -- declared {sorted(declared)} vs used {sorted(used)}"
            )
    if problems:
        raise PromptError("prompt validation failed:\n  " + "\n  ".join(problems))
    return prompts


__all__ = ["Prompt", "RenderedPrompt", "PromptError", "PROMPTS_DIR", "load", "body", "render", "list_prompts", "validate_all"]
