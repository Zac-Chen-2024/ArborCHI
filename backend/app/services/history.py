"""
Structural undo / redo for legal_arguments.json (Doc/01 M13 #4).

Every write through ``update_legal_arguments`` that actually changes the
document snapshots the *previous* document into an undo stack; ``undo``
restores it (pushing the current document onto a redo stack), ``redo``
walks forward again. Whole-document snapshots make every operation exactly
invertible -- create / rename / move / merge / consolidate / delete /
remove-standard / generate -- without per-operation inverse logic.

Layout (per project):
    arguments_history/undo/{seq:06d}.json   {"seq", "label", "ts", "data"}
    arguments_history/redo/{seq:06d}.json

Both stacks are bounded (MAX_ENTRIES); a new write clears the redo stack.
All mutation happens inside the legal_arguments file lock (callers pass
through update_json), so stacks and document stay consistent.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..core.atomic_io import write_json
from .storage import project_path

MAX_ENTRIES = 50


def _dir(project_id: str, stack: str) -> Path:
    return project_path(project_id, "arguments_history") / stack


def _entries(project_id: str, stack: str) -> List[Path]:
    d = _dir(project_id, stack)
    if not d.exists():
        return []
    return sorted(p for p in d.glob("*.json") if p.stem.isdigit())


def _next_seq(project_id: str) -> int:
    seqs = [int(p.stem) for s in ("undo", "redo") for p in _entries(project_id, s)]
    return (max(seqs) + 1) if seqs else 1


def _push(project_id: str, stack: str, label: str, data: Dict[str, Any]) -> Dict[str, Any]:
    d = _dir(project_id, stack)
    d.mkdir(parents=True, exist_ok=True)
    seq = _next_seq(project_id)
    entry = {"seq": seq, "label": label, "ts": datetime.now(timezone.utc).isoformat(), "data": data}
    write_json(d / f"{seq:06d}.json", entry)
    # Bound the stack (drop oldest)
    for old in _entries(project_id, stack)[:-MAX_ENTRIES]:
        old.unlink(missing_ok=True)
    return entry


def _pop(project_id: str, stack: str) -> Optional[Dict[str, Any]]:
    entries = _entries(project_id, stack)
    if not entries:
        return None
    path = entries[-1]
    with open(path, "r", encoding="utf-8") as f:
        entry = json.load(f)
    path.unlink(missing_ok=True)
    return entry


def _clear(project_id: str, stack: str) -> None:
    for p in _entries(project_id, stack):
        p.unlink(missing_ok=True)


def record_change(project_id: str, label: str, before: Dict[str, Any]) -> None:
    """Called (inside the document lock) after a write that changed the document."""
    _push(project_id, "undo", label, before)
    _clear(project_id, "redo")


def peek(project_id: str) -> Dict[str, Any]:
    """Labels of what undo / redo would do next (newest first, bounded)."""
    def _meta(paths: List[Path]) -> List[Dict[str, Any]]:
        out = []
        for p in reversed(paths[-10:]):
            with open(p, "r", encoding="utf-8") as f:
                e = json.load(f)
            out.append({"seq": e["seq"], "label": e["label"], "ts": e["ts"]})
        return out
    return {
        "undo": _meta(_entries(project_id, "undo")),
        "redo": _meta(_entries(project_id, "redo")),
        "undo_depth": len(_entries(project_id, "undo")),
        "redo_depth": len(_entries(project_id, "redo")),
    }


def step(project_id: str, direction: str, current: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Inside the document lock: pop from `direction` stack, push `current` on
    the opposite stack, return the entry to restore (or None if empty)."""
    src, dst = ("undo", "redo") if direction == "undo" else ("redo", "undo")
    entry = _pop(project_id, src)
    if entry is None:
        return None
    _push(project_id, dst, entry["label"], current)
    return entry


def affected_standards(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    """Standard keys whose arguments / sub-arguments differ between two documents."""
    def _by_std(doc: Dict[str, Any]) -> Dict[str, Any]:
        args = {x.get("id"): x for x in doc.get("arguments", []) or []}
        out: Dict[str, Any] = {}
        for arg in args.values():
            out.setdefault(arg.get("standard_key") or "unknown", {"arguments": [], "sub_arguments": []})["arguments"].append(arg)
        for sa in doc.get("sub_arguments", []) or []:
            key = (args.get(sa.get("argument_id")) or {}).get("standard_key") or "unknown"
            out.setdefault(key, {"arguments": [], "sub_arguments": []})["sub_arguments"].append(sa)
        return {k: json.dumps(v, sort_keys=True, ensure_ascii=False, default=str) for k, v in out.items()}
    sa, sb = _by_std(a), _by_std(b)
    return sorted(k for k in set(sa) | set(sb) if sa.get(k) != sb.get(k))
