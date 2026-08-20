"""
Study event log -- the append-only record everything downstream is computed
from (日志手册 §2, BE-06).

Every event, whether the client sent it or the server wrote it, lands in the
same file with the same envelope:

    schema_version  int     bumped only additively after the M5 freeze
    seq             int     per-session, monotonically increasing
    ts_wall         str     ISO-8601 UTC, server-stamped on arrival
    ts_mono         int|None  client monotonic clock (ms); server events: None
    phase           str     phase the session was in when the event happened
    practice        bool    true for everything in the practice phase (BE-18)
    cond            str     "c" | "b"
    track           str     "formal" | "test" (schema v2, BE-19)
    build           str     frontend build hash (FS-10)
    source          str     "client" | "server"
    event           str     event name from the dictionary
    payload         dict    event-specific fields

Server events (phase_enter / phase_exit / phase_softlock / session_start) get
their seq from a *separate* counter space than client events would clash with:
client seq numbers are authored by the browser and the server records them
verbatim so gaps are detectable (BE-06); server events carry `seq: null` and
are ordered by `srv_seq` instead. Mixing the two counters would make a client
gap indistinguishable from a server insert.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .atomic_io import append_jsonl
from .study import SCHEMA_VERSION, now_iso, session_dir

# Events the server itself writes. Client events live in the log SDK's
# dictionary (日志手册 §4) and are validated at the /log/batch door in M1.
SERVER_EVENTS = {
    "session_created",
    "session_start",
    "phase_enter",
    "phase_exit",
    "phase_softlock",
    "moderator_note",
    "submit",
}


def events_path(session: Dict):
    return session_dir(
        session["workspace_id"], session["session_id"], session["track"]
    ) / "events.jsonl"


def write_server_event(
    session: Dict,
    event: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    srv_seq: Optional[int] = None,
) -> Dict[str, Any]:
    """Append one server-authored event. Returns the record as written."""
    record = {
        "schema_version": SCHEMA_VERSION,
        "seq": None,
        "srv_seq": srv_seq,
        "ts_wall": now_iso(),
        "ts_mono": None,
        "phase": session.get("phase"),
        "practice": session.get("phase") == "practice",
        "cond": session.get("condition"),
        "track": session.get("track"),
        "build": session.get("build", ""),
        "source": "server",
        "session_id": session.get("session_id"),
        "event": event,
        "payload": payload or {},
    }
    append_jsonl(events_path(session), record)
    return record
