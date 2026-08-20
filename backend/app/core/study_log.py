"""
Event dictionary and envelope validation for the study log (BE-06, 日志手册 §2/§4).

This is the schema everything downstream is computed from. Two rules govern it:

1.  **The dictionary is closed.** An event name not listed here is rejected, not
    stored under some generic bucket. A typo that silently becomes data is worse
    than a rejected batch, because the analysis will never know it is missing.

2.  **Events must be readable without a decoder ring.** Every event that
    describes an action on a named thing carries the *name*, not only the id.
    `{"tree_op": "move", "node_id": "s4"}` is a fact nobody can interpret six
    weeks later without replaying every prior event; `{"tree_op": "move",
    "node_id": "s4", "node_title": "Decision and resource authority",
    "to_parent_title": "The petitioner performs a leading role"}` is a sentence.
    This matters because the post-task interview is planned as half fixed
    questions and half questions sampled from what the participant actually did
    -- "at 12:04 you moved X under Y, why?" -- and that is only possible if the
    log says so in words.

    Concretely: prefer redundancy over normalisation. Disk is free; a study you
    cannot interpret is not.

Envelope. The client authors seq / ts_mono; the server stamps ts_wall on
arrival and never trusts a client clock for ordering across sessions. Gaps in
seq are recorded rather than rejected (BE-06): a participant who loses the
network mid-batch must not have the rest of their session refused.

NOTE: 日志手册 v1 is the authority on this dictionary. It was not in the repo
when this was written, so the names below were recovered from the two design
documents in docs/ (they appear verbatim there) plus the paired counterparts
the interaction model requires -- hover_end for hover_start, lightbox_close for
lightbox_open. Reconcile against the manual when it lands; adding a field is
safe, renaming one after the M5 freeze is not.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# v3 adds the provenance triple (config_hash / material_manifest_hash /
# tree_variant_id) to every event. Without them a log says what happened but
# not what it happened *to*: which parameter set, which frozen material, which
# of the five candidate trees. Those three answer "is this session comparable
# with that one", which is the first question the analysis asks.
SCHEMA_VERSION = 3

# ---------------------------------------------------------------------------
# The dictionary
# ---------------------------------------------------------------------------

# Server-authored. Clients may not send these.
SERVER_EVENTS = frozenset({
    "session_created",
    "session_start",
    "phase_enter",
    "phase_exit",
    "phase_softlock",
    # The moment the participant said they were finished checking. In the
    # verification phase nothing else marks the end -- there is no lock and no
    # buzzer -- so this timestamp IS the dependent measure for "how long did
    # they choose to verify" (PR-6).
    "submit_declared",
    "msg_response",
    "frozen_draft_marked",
    "draft_snapshot",
    "moderator_note",
    "submit",
})

# Client-authored, both conditions.
COMMON_EVENTS = frozenset({
    "heartbeat",          # 30s self-driven; drives the liveness light (MOD-04)
    "panel_focus",        # which of evidence / tree|chat / letter|draft has attention
    "doc_open",           # an exhibit was opened
    "page_change",        # via: click | scroll | linkage
    "zoom",               # evidence viewer zoom level
    "checkpoint_passed",  # practice gate cleared (FS-06)
    "text_edit",          # debounced 2s, carries affected_sent_ids
    "declare_done",       # participant says they are finished
    "confidence_submit",  # likert_1_7 + est_problem_count
    "probe_item",         # one probe answer
})

# Client-authored, condition C only.
C_EVENTS = frozenset({
    "hover_start",        # chip hover begins -- a look
    "hover_end",          # chip hover ends, carries dwell_ms
    "chip_click",         # chip committed -- a choice
    "cite_click",         # citation in the letter clicked
    "bbox_hover",         # pointer over the located passage
    "lightbox_open",
    "lightbox_close",     # carries dwell_ms
    # Scrolling INSIDE the magnifier. Recorded because reading around a cited
    # passage is verification behaviour, and a participant who opened the
    # magnifier and scrolled the page did something different from one who
    # opened it and closed it (日志手册 §1 item 2b).
    "lightbox_scroll",
    "tree_op",            # rename / split / merge / move / promote / remove / create
    "node_state",         # proposed -> accepted / edited / removed
    "assign",             # snippet assigned to a node
    "unassign",
    "pool_drag_out",      # snippet dragged out of the unused pool
    "generate_trigger",   # participant asked for (re)generation
})

# Client-authored, condition B only.
B_EVENTS = frozenset({
    "msg_send",           # participant's chat message
    "copy_to_draft",      # assistant text appended to the draft
})

CLIENT_EVENTS = COMMON_EVENTS | C_EVENTS | B_EVENTS
ALL_EVENTS = CLIENT_EVENTS | SERVER_EVENTS

# Events that only make sense in one condition. A C event arriving from a B
# session is a bug worth seeing, not data worth keeping.
CONDITION_SCOPED = {"c": C_EVENTS, "b": B_EVENTS}

PANELS = frozenset({"evidence", "tree", "letter", "chat", "draft", "topbar", "other"})
PAGE_CHANGE_VIA = frozenset({"click", "scroll", "linkage"})

# Generous on purpose: a truncated payload is a hole in the analysis, and these
# are text fields a human will read. Anything genuinely large (draft full text)
# goes to snapshots/ and is referenced by hash.
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_BATCH = 500

# Envelope keys the client must supply on every event.
REQUIRED_ENVELOPE = ("seq", "ts_mono", "event")


class RejectedEvent(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def normalise(
    raw: Dict[str, Any],
    *,
    session: Dict[str, Any],
    received_at: str,
) -> Dict[str, Any]:
    """Validate one client event and return the record to append.

    Raises RejectedEvent with a reason the caller can count. Rejections are
    tallied and returned to the client rather than failing the whole batch --
    one malformed event must not cost the other nineteen.
    """
    if not isinstance(raw, dict):
        raise RejectedEvent("not an object")

    for key in REQUIRED_ENVELOPE:
        if key not in raw:
            raise RejectedEvent(f"missing {key}")

    event = raw.get("event")
    if event not in CLIENT_EVENTS:
        # Explicitly including server events here: a client claiming to have
        # authored a phase_enter would corrupt the phase reconstruction.
        raise RejectedEvent(f"unknown event {event!r}")

    cond = session["condition"]
    other = CONDITION_SCOPED["b" if cond == "c" else "c"]
    if event in other:
        raise RejectedEvent(f"event {event!r} does not belong to condition {cond}")

    seq = raw.get("seq")
    if not isinstance(seq, int) or seq < 0:
        raise RejectedEvent("seq must be a non-negative integer")

    ts_mono = raw.get("ts_mono")
    if not isinstance(ts_mono, (int, float)):
        raise RejectedEvent("ts_mono must be a number")

    payload = raw.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    import json

    encoded = json.dumps(payload, ensure_ascii=False)
    truncated = False
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        payload = {"_truncated": True, "_bytes": len(encoded.encode("utf-8"))}
        truncated = True

    record = {
        "schema_version": SCHEMA_VERSION,
        "seq": seq,
        "srv_seq": None,
        # The client's own clock, for ordering within a session; the server's,
        # for anchoring to wall time. Both are kept -- neither alone is enough.
        "ts_mono": ts_mono,
        "ts_wall": received_at,
        "ts_client_wall": raw.get("ts_wall"),
        # Phase and practice come off the SESSION, not the client: a client that
        # is a poll behind would otherwise label events with the wrong phase.
        # The client's own view is kept alongside so a disagreement is visible.
        "phase": session.get("phase"),
        "phase_client": raw.get("phase"),
        "practice": session.get("phase") == "practice",
        "cond": cond,
        "track": session.get("track"),
        "build": raw.get("build") or session.get("build", ""),
        # Provenance, all three pinned on the session at creation so a
        # mid-run edit to config or material cannot rewrite history.
        "config_hash": session.get("config_hash", ""),
        "material_manifest_hash": session.get("material_manifest_hash", ""),
        "tree_variant_id": session.get("tree_variant_id", ""),
        "source": "client",
        "session_id": session.get("session_id"),
        "event": event,
        "payload": payload,
    }
    if truncated:
        record["truncated"] = True
    return record


def find_gaps(previous_max: int, seqs: List[int]) -> List[Tuple[int, int]]:
    """Ranges of seq numbers that never arrived, as [start, end] inclusive.

    Called with the highest seq seen so far and the seqs in this batch. A gap is
    registered, not fatal (BE-06): the participant pulled the network cable, the
    session continues, and the analysis needs to know which stretch is missing
    rather than silently treating the log as complete.
    """
    gaps: List[Tuple[int, int]] = []
    expected = previous_max + 1
    for seq in sorted(set(seqs)):
        if seq > expected:
            gaps.append((expected, seq - 1))
        expected = max(expected, seq + 1)
    return gaps


def summarise(record: Dict[str, Any]) -> Optional[str]:
    """One human-readable line for an event, or None if it needs no gloss.

    This exists for the moderator panel and for the post-task interview: the
    point of carrying titles in payloads is that a person can read the log, and
    this is where that promise is cashed. It is deliberately best-effort -- a
    missing field yields a shorter sentence, never an exception.
    """
    p = record.get("payload") or {}
    ev = record.get("event")

    if ev == "tree_op":
        op = p.get("op")
        title = p.get("node_title") or p.get("node_id")
        if op == "move":
            return f"moved “{title}” under “{p.get('to_parent_title') or p.get('to_parent')}”"
        if op == "rename":
            return f"renamed “{p.get('from_title')}” to “{p.get('to_title')}”"
        if op == "split":
            return f"split “{title}” into two"
        if op == "merge_up":
            return f"merged “{title}” into the one above"
        if op == "promote":
            return f"promoted “{title}” to an argument"
        if op == "remove":
            return f"removed “{title}”"
        if op == "create":
            return f"created “{title}”"
        return f"{op} on “{title}”"

    if ev == "node_state":
        return f"marked “{p.get('node_title') or p.get('node_id')}” as {p.get('to')}"
    if ev == "chip_click":
        return f"opened evidence {p.get('exhibit')} p.{p.get('page')} — “{p.get('label')}”"
    if ev == "hover_end":
        return (f"hovered evidence {p.get('exhibit')} p.{p.get('page')} "
                f"for {p.get('dwell_ms')}ms without selecting it")
    if ev == "cite_click":
        return f"traced the citation {p.get('exhibit')} p.{p.get('page')} back to its source"
    if ev == "lightbox_close":
        return f"read {p.get('exhibit')} p.{p.get('page')} magnified for {p.get('dwell_ms')}ms"
    if ev == "page_change":
        return f"turned to {p.get('exhibit')} p.{p.get('page')} (via {p.get('via')})"
    if ev == "assign":
        return f"attached {p.get('exhibit')} p.{p.get('page')} to “{p.get('node_title')}”"
    if ev == "unassign":
        return f"detached {p.get('exhibit')} p.{p.get('page')} from “{p.get('node_title')}”"
    if ev == "text_edit":
        return f"edited {p.get('sentence_count', '?')} sentence(s) in the draft"
    if ev == "copy_to_draft":
        return f"copied {p.get('char_count', '?')} characters from the assistant into the draft"
    if ev == "msg_send":
        return f"asked the assistant: “{(p.get('text') or '')[:80]}”"
    return None


__all__ = [
    "SCHEMA_VERSION", "ALL_EVENTS", "CLIENT_EVENTS", "SERVER_EVENTS",
    "COMMON_EVENTS", "C_EVENTS", "B_EVENTS", "PANELS", "PAGE_CHANGE_VIA",
    "MAX_BATCH", "MAX_PAYLOAD_BYTES", "RejectedEvent", "normalise",
    "find_gaps", "summarise",
]
