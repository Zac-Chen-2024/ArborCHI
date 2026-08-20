"""
Material bundle: read-only, hashed, and stripped before it reaches a browser
(开发手册 §3, 红线 #5, BE-07).

The bundle holds three things the participant must never see:

    tree.frozen.json   `distractor` on nodes
    planted.json       the planted-error registry
    pregen/*.json      `planted_id` on individual sentences

Those are the answer key. If any of them reached the frontend, the interface
would be marking its own homework: a node the software knows is noise, or a
sentence it knows is wrong, cannot be presented neutrally no matter how careful
the CSS is -- and neutrality is the experiment.

So this module has exactly one shape of public function: `public_*` returns
what may be sent, `load_*` returns everything. The stripping happens here, once,
rather than at each call site, because "remember to delete the field" is not a
guarantee. `tests/test_materials.py` asserts the negative directly.

Hashing. `manifest_hash` covers EVERY file in the bundle, not just manifest.json
-- otherwise editing a pregen sentence would leave the hash untouched and two
sessions with materially different letters would look identical in the log. The
hash goes on the session at creation and rides in every event (schema v3).
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ids import is_safe_id

logger = logging.getLogger(__name__)

# Fields that exist for the analysis and must never leave the server.
SERVER_ONLY_NODE_FIELDS = ("distractor",)
SERVER_ONLY_SENTENCE_FIELDS = ("planted_id",)


class MaterialError(Exception):
    pass


def materials_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "study_materials"


def bundle_dir(material_id: str) -> Path:
    if not is_safe_id(material_id):
        raise MaterialError(f"unsafe material_id: {material_id!r}")
    return materials_root() / material_id


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise MaterialError(f"missing bundle file {path.name}: {e}") from e
    except json.JSONDecodeError as e:
        raise MaterialError(f"corrupt bundle file {path.name}: {e}") from e


@lru_cache(maxsize=4)
def load_bundle(material_id: str = "case_v1") -> Dict[str, Any]:
    """Whole bundle, including the server-only fields. Cached: the bundle is
    frozen for the duration of a study, so re-reading it per request would be
    pure waste. Call `load_bundle.cache_clear()` in tests that write one."""
    root = bundle_dir(material_id)
    if not root.is_dir():
        raise MaterialError(f"no material bundle at {root}")

    manifest = _read(root / "manifest.json")
    tree = _read(root / "tree.frozen.json")
    snippets = _read(root / "snippets.json")
    relations = _read(root / "relations.json")
    planted = _read(root / "planted.json")

    pregen: Dict[str, Any] = {}
    for path in sorted((root / "pregen").glob("*.json")):
        pregen[path.stem] = _read(path)

    bundle = {
        "material_id": material_id,
        "manifest": manifest,
        "tree": tree,
        "snippets": snippets,
        "relations": relations,
        "planted": planted,
        "pregen": pregen,
        "manifest_hash": _bundle_hash(root),
    }
    if manifest.get("placeholder"):
        logger.warning(
            "material bundle %r is a PLACEHOLDER (%s) -- no participant may run "
            "on it", material_id, bundle["manifest_hash"],
        )
    return bundle


def _bundle_hash(root: Path) -> str:
    """sha256 over every file in the bundle, path-ordered.

    Covers content, not just the manifest: an edited pregen sentence changes
    the letter a participant sees, so it must change the hash their log carries.
    """
    h = hashlib.sha256()
    for path in sorted(root.rglob("*.json")):
        h.update(str(path.relative_to(root)).replace("\\", "/").encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
        h.update(b"\0")
    return h.hexdigest()[:16]


def manifest_hash(material_id: str = "case_v1") -> str:
    return load_bundle(material_id)["manifest_hash"]


def tree_variant_id(material_id: str = "case_v1") -> str:
    return load_bundle(material_id)["tree"].get("tree_variant_id", "")


# ---------------------------------------------------------------------------
# Server-side reads
# ---------------------------------------------------------------------------

def frozen_nodes(material_id: str = "case_v1") -> Dict[str, Dict[str, Any]]:
    """node_id -> the frozen definition, for comparing against what the
    participant submitted. Includes the server-only fields."""
    out: Dict[str, Dict[str, Any]] = {}
    for arg in load_bundle(material_id)["tree"]["arguments"]:
        for sub in arg["subs"]:
            out[sub["id"]] = {**sub, "parent_id": arg["id"], "parent_title": arg["title"]}
    return out


def pregen_sentences(node_id: str, material_id: str = "case_v1") -> Optional[List[Dict[str, Any]]]:
    """Pre-generated sentences for one node, with `planted_id` intact.

    DEEP copy, not a slice of the cached list. The caller stamps position and
    parentage onto each sentence dict, and those dicts would otherwise be the
    very objects inside the lru_cached bundle -- a second generation (which is
    a real feature: the participant can regenerate after editing the tree)
    would then read last time's leftovers, and the bundle would drift away from
    the file it was loaded from without anything failing.
    """
    entry = load_bundle(material_id)["pregen"].get(node_id)
    return copy.deepcopy(entry["sentences"]) if entry else None


def planted_index(material_id: str = "case_v1") -> Dict[str, Dict[str, Any]]:
    return {i["planted_id"]: i for i in load_bundle(material_id)["planted"]["items"]}


# ---------------------------------------------------------------------------
# What may be sent to a browser
# ---------------------------------------------------------------------------

def public_tree(material_id: str = "case_v1") -> Dict[str, Any]:
    """The tree as the participant receives it.

    A distractor node is byte-identical to any other node here. That is the
    point: the participant's job is to notice, and an interface that already
    knew would be answering the question for them (红线 #5, C-14).
    """
    tree = load_bundle(material_id)["tree"]
    return {
        "tree_variant_id": tree.get("tree_variant_id", ""),
        "criterion": tree.get("criterion", ""),
        "arguments": [
            {
                "id": arg["id"],
                "index": arg["index"],
                "title": arg["title"],
                "rationale": arg["rationale"],
                "subs": [
                    {k: v for k, v in sub.items() if k not in SERVER_ONLY_NODE_FIELDS}
                    for sub in arg["subs"]
                ],
            }
            for arg in tree["arguments"]
        ],
    }


def public_snippets(material_id: str = "case_v1") -> Dict[str, Any]:
    """Snippets and exhibits. Nothing here is secret -- the participant is
    meant to read all of it -- so this is a straight pass-through."""
    return load_bundle(material_id)["snippets"]


def public_relations(material_id: str = "case_v1") -> Dict[str, Any]:
    """Factual triples for the relations panel (C-07).

    A straight pass-through, and it stays that way: the file has no evaluative
    field to strip because there is nowhere in the schema to put one. That is
    the mechanism -- the panel cannot render a warning it was never given.
    """
    return load_bundle(material_id)["relations"]


def public_sentence(sentence: Dict[str, Any]) -> Dict[str, Any]:
    """One sentence with the answer key removed.

    `source` (frozen|live) SURVIVES: it is data the analysis needs and the UI
    is forbidden from rendering differently (红线 #3). `planted_id` does not.
    """
    return {k: v for k, v in sentence.items() if k not in SERVER_ONLY_SENTENCE_FIELDS}


def public_sentences(sentences: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [public_sentence(s) for s in sentences]


__all__ = [
    "MaterialError", "materials_root", "bundle_dir", "load_bundle",
    "manifest_hash", "tree_variant_id", "frozen_nodes", "pregen_sentences",
    "planted_index", "public_tree", "public_snippets", "public_relations",
    "public_sentence",
    "public_sentences", "SERVER_ONLY_NODE_FIELDS", "SERVER_ONLY_SENTENCE_FIELDS",
]
