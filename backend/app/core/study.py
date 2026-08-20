"""
Study session store + phase machine (BE-01/03/04/05, 开发手册 §4.1).

One study session == one participant == one workspace == one bearer token.
The moderator creates a session, which mints a participant token bound to a
fresh workspace; the participant joins with that token and can never see or
change their own condition (D2: the condition lives in the session record on
the server, never in the URL).

Storage layout -- the ONLY difference between a formal run and a test run
(BE-19) is which root the session directory hangs off. Everything else -- the
phase machine, seq numbering, heartbeats, snapshots, integrity -- is identical,
so a test run is a full dress rehearsal and its data is field-for-field
comparable with a formal one.

    formal:  data/workspaces/{ws}/sessions/{sid}/
    test:    data/study_test/{ws}/sessions/{sid}/
                 session.json      this record
                 events.jsonl      append-only event log
                 snapshots/        draft + final text (M1)
                 integrity.json    end-of-run report (M4)

A single index at data/study_sessions.json maps session_id -> {workspace_id,
track} so the moderator can reach any session without knowing its workspace.

Timing (红线 #4). The organisation phase has a visible countdown, so `state`
carries the remaining milliseconds. The verification phase is silently timed on
the server: `state` for that phase carries NO time field at all -- not a null,
not a zero, the key is structurally absent -- so a curious participant reading
the network tab has nothing to render.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .atomic_io import read_json, update_json, write_json
from .config import settings
from .ids import is_safe_id

SCHEMA_VERSION = 2  # v2 == study envelope carries `track` (BE-19)

CONDITIONS = ("c", "b")
LANGS = ("en", "zh")

# Phase machines (开发手册 §4.1). C organises, then generates, then verifies;
# B does the whole writing job in one undivided `work` phase.
PHASES: Dict[str, List[str]] = {
    "c": ["setup", "tutorial", "practice", "organization", "generation",
          "verification", "confidence", "probe", "done"],
    "b": ["setup", "tutorial", "practice", "work",
          "confidence", "probe", "done"],
}

# Phases whose clock the participant may see.
VISIBLE_CLOCK_PHASES = ("organization",)
# Phases the server times WITHOUT telling the participant (红线 #4).
SILENT_CLOCK_PHASES = ("verification", "work")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    from ..services.storage import data_dir
    return data_dir()


def index_path() -> Path:
    return _data_dir() / "study_sessions.json"


def track_root(track: str) -> Path:
    """Root under which a track's session data lives. Test data is physically
    elsewhere so analysis scripts pointed at the formal tree cannot reach it
    even by accident (BE-20)."""
    if track == "test":
        return _data_dir() / "study_test"
    return _data_dir() / "workspaces"


def session_dir(workspace_id: str, session_id: str, track: str) -> Path:
    if not is_safe_id(workspace_id) or not is_safe_id(session_id):
        raise ValueError("unsafe workspace_id / session_id")
    return track_root(track) / workspace_id / "sessions" / session_id


# ---------------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------------

def load_index() -> Dict[str, Dict]:
    return read_json(index_path(), default={}) or {}


def index_entry(session_id: str) -> Optional[Dict]:
    if not is_safe_id(session_id):
        return None
    return load_index().get(session_id)


def _index_add(session_id: str, entry: Dict) -> None:
    def _add(table):
        table = table or {}
        table[session_id] = entry
        return table

    update_json(index_path(), _add, default={})


# ---------------------------------------------------------------------------
# Session record
# ---------------------------------------------------------------------------

def new_session_id() -> str:
    """Safe-id shaped (leading alnum, no dots) -- it goes into a path."""
    return "s" + secrets.token_hex(8)


def session_path(session_id: str) -> Optional[Path]:
    ref = index_entry(session_id)
    if not ref:
        return None
    return session_dir(ref["workspace_id"], session_id, ref["track"]) / "session.json"


def load_session(session_id: str) -> Optional[Dict]:
    p = session_path(session_id)
    if p is None:
        return None
    return read_json(p, default=None)


def save_session(session: Dict) -> None:
    p = session_path(session["session_id"])
    if p is None:
        raise ValueError(f"session {session['session_id']} is not in the index")
    write_json(p, session)


def update_session(session_id: str, mutator) -> Dict:
    """Locked read -> mutate -> write on one session record."""
    p = session_path(session_id)
    if p is None:
        raise ValueError(f"session {session_id} is not in the index")
    return update_json(p, mutator, default=None)


def create_session(
    *,
    condition: str,
    participant_code: str,
    lang: str,
    track: str,
    workspace_id: Optional[str] = None,
    build: str = "",
) -> Dict:
    """Create one session and its workspace. The workspace id is derived from
    the session id, not the participant code: two runs of the same participant
    can never collide, and the code never appears in a filesystem path."""
    if condition not in CONDITIONS:
        raise ValueError(f"condition must be one of {CONDITIONS}")
    if lang not in LANGS:
        raise ValueError(f"lang must be one of {LANGS}")

    session_id = new_session_id()
    workspace_id = workspace_id or f"ws{session_id}"
    session = {
        "schema_version": SCHEMA_VERSION,
        "session_id": session_id,
        "condition": condition,
        "participant_code": participant_code,
        "lang": lang,
        "track": track,
        "workspace_id": workspace_id,
        "build": build,
        "created_at": now_iso(),
        "started_at": None,          # set by session_start (FS-12)
        "phase": PHASES[condition][0],
        "phase_entered_ms": now_ms(),
        "phase_deadline_ms": None,   # server-side; only some phases expose it
        "softlock": False,
        "submitted": False,
        "seq_acked": 0,
        "last_seen_ms": None,
    }
    _index_add(session_id, {
        "workspace_id": workspace_id,
        "track": track,
        "condition": condition,
        "participant_code": participant_code,
        "lang": lang,
        "created_at": session["created_at"],
    })
    session_dir(workspace_id, session_id, track).mkdir(parents=True, exist_ok=True)
    save_session(session)
    return session


# ---------------------------------------------------------------------------
# Phase machine
# ---------------------------------------------------------------------------

def phase_list(session: Dict) -> List[str]:
    return PHASES[session["condition"]]


def next_phase(session: Dict) -> Optional[str]:
    phases = phase_list(session)
    i = phases.index(session["phase"])
    return phases[i + 1] if i + 1 < len(phases) else None


def phase_duration_ms(phase: str) -> Optional[int]:
    """Budget for a timed phase, or None if the phase is untimed.

    The numbers come from 实验方案 v2.1 and live in settings so a pilot can be
    re-timed without a code change; they are pinned at the M5 freeze.
    """
    if phase == "organization":
        return settings.study_org_seconds * 1000
    if phase in ("verification", "work"):
        return settings.study_verify_seconds * 1000
    return None


def enter_phase(session: Dict, phase: str) -> Dict:
    """Mutate `session` in place to sit at `phase`. Caller persists and logs."""
    session["phase"] = phase
    session["phase_entered_ms"] = now_ms()
    session["softlock"] = False
    budget = phase_duration_ms(phase)
    session["phase_deadline_ms"] = (
        session["phase_entered_ms"] + budget if budget is not None else None
    )
    return session


def softlock_due(session: Dict, at_ms: Optional[int] = None) -> bool:
    """True once the current phase is past its budget and not already locked.

    Organisation locks on the dot; the silently-timed phases get the grace
    period the protocol specifies, so a participant mid-keystroke at the
    buzzer is not cut off.
    """
    deadline = session.get("phase_deadline_ms")
    if deadline is None or session.get("softlock"):
        return False
    grace = (settings.study_softlock_grace_seconds * 1000
             if session["phase"] in SILENT_CLOCK_PHASES else 0)
    return (at_ms if at_ms is not None else now_ms()) >= deadline + grace


def public_state(session: Dict, at_ms: Optional[int] = None) -> Dict:
    """What the participant's client is allowed to know (GET /state).

    红线 #4: for a silently-timed phase the time keys are *absent*, not null.
    Anything added to this dict is visible in the network tab -- treat every
    new key as a leak until proven otherwise.
    """
    state = {
        "session_id": session["session_id"],
        "condition": session["condition"],
        "lang": session["lang"],
        "track": session["track"],
        "phase": session["phase"],
        "softlock": bool(session["softlock"]),
        "submitted": bool(session["submitted"]),
        "started": session.get("started_at") is not None,
    }
    if session["phase"] in VISIBLE_CLOCK_PHASES and session.get("phase_deadline_ms"):
        remaining = session["phase_deadline_ms"] - (at_ms if at_ms is not None else now_ms())
        state["remaining_ms"] = max(0, remaining)
    return state
