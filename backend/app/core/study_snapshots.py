"""
Snapshot storage (红线 #1, BE-08/BE-11).

A snapshot is the full text of a draft at a moment that matters, written whole
and referenced from the event log by hash. Two of them are load-bearing:

    draft_snapshot / "initial"  the generated letter EXACTLY as the machine
                                produced it, written BEFORE the participant can
                                touch a character. Without it there is no
                                baseline to diff against, and the whole
                                "what did the human change" question is
                                unanswerable. It cannot be reconstructed after
                                the fact -- this is the one thing in the system
                                that is genuinely unrecoverable if missed.

    submit / "final"            what the participant actually handed in. The
                                probe items are sampled from this, so it must
                                be the same bytes the participant saw.

Everything in between is autosave (BE-10), which exists to survive a crash, not
to be analysed.

Files live beside the event log:

    sessions/{sid}/snapshots/{snapshot_id}.json
        {snapshot_id, kind, sha256, char_count, created_at, text, sentences?}

The event log stores the hash and a summary, never the body: an events.jsonl
with three copies of a 20KB letter in it is painful to read and slow to stream.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

from .atomic_io import read_json, write_json
from .ids import is_safe_id
from .sentences import CITE_RE, count_citations, count_sentences
from .study import now_iso, session_dir


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def snapshots_dir(session: Dict[str, Any]):
    return session_dir(
        session["workspace_id"], session["session_id"], session["track"]
    ) / "snapshots"


def write_snapshot(
    session: Dict[str, Any],
    snapshot_id: str,
    kind: str,
    text: str,
    *,
    sentences: Optional[List[Dict[str, Any]]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Write one snapshot whole. Returns the metadata to put in the event."""
    if not is_safe_id(snapshot_id):
        raise ValueError(f"unsafe snapshot_id: {snapshot_id!r}")

    digest = sha256(text)
    body = {
        "snapshot_id": snapshot_id,
        "kind": kind,
        "sha256": digest,
        "char_count": len(text),
        "citation_count": count_citations(text),
        "sentence_count": count_sentences(text),
        "created_at": now_iso(),
        "text": text,
    }
    if sentences is not None:
        # Per-sentence provenance: sent_id, snippet_ids, source frozen|live
        # (红线 #2, #3). Kept with the snapshot rather than in the event so the
        # two can never drift apart.
        body["sentences"] = sentences
    if extra:
        body.update(extra)

    write_json(snapshots_dir(session) / f"{snapshot_id}.json", body)

    # What goes in the event log: everything except the text itself.
    meta = {k: v for k, v in body.items() if k != "text"}
    if sentences is not None:
        meta["sentences"] = len(sentences)
    return meta


def read_snapshot(session: Dict[str, Any], snapshot_id: str) -> Optional[Dict[str, Any]]:
    if not is_safe_id(snapshot_id):
        return None
    return read_json(snapshots_dir(session) / f"{snapshot_id}.json", default=None)


__all__ = [
    "CITE_RE", "sha256", "snapshots_dir", "count_citations", "count_sentences",
    "write_snapshot", "read_snapshot",
]
