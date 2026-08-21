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

Timing (红线 #4, PR-6). Two segments, and they are timed differently on purpose:

    organisation   hard limit, VISIBLE countdown, soft-locks at the buzzer
                   (+ a grace window so nobody is cut off mid-keystroke)
    verification   timed silently for the moderator, NO lock, no clock in the
                   participant's `state` at all -- not a null, not a zero, the
                   key is structurally absent

The asymmetry is the design. Organisation is bounded so every participant gets
the same budget to structure the argument. Verification is not, because *when a
participant decides they are done checking* is the behaviour being measured --
a lock would replace that decision with the clock's. `hard_cap_seconds` exists
only to tell the MODERATOR when to step in, and never leaves the moderator API.
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from .atomic_io import read_json, update_json, write_json
from .ids import is_safe_id
from .study_config import config_hash, phase_config

# Version of the SESSION RECORD (session.json), not of the event envelope --
# that one lives in study_log.SCHEMA_VERSION and moves independently.
SESSION_SCHEMA_VERSION = 3

logger = logging.getLogger(__name__)

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

# Phases the participant may end themselves by submitting. This is the whole
# point of the verification phase: when they stop checking is the measurement,
# so the software must not decide it for them.
SUBMITTABLE_PHASES = ("verification", "work")

# Which phases show a clock, which are timed silently, and which soft-lock is
# no longer decided here -- it comes from study_config.json, so pilot can change
# the protocol without a code change (PR-6). These helpers just read it.
#
# The shape that matters: organisation is hard-limited WITH a visible countdown;
# verification is timed silently and does NOT lock, because the participant
# declaring themselves finished is the behaviour under study. Locking them out
# would replace the measurement with the clock's decision.


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
    material_id: str = "case_v1",
    practice_material_id: str = "practice_v1",
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

    # A missing or broken bundle must not take the session down: the moderator
    # can still run setup and tutorial while it is fixed, and the empty hashes
    # make those sessions obvious in the data.
    from .materials import MaterialError, manifest_hash, tree_variant_id
    try:
        material_hash = manifest_hash(material_id)
        variant_id = tree_variant_id(material_id)
    except MaterialError as e:
        logger.error("session %s created without a usable material bundle: %s",
                     session_id, e)
        material_hash, variant_id = "", ""
    session = {
        "schema_version": SESSION_SCHEMA_VERSION,
        "session_id": session_id,
        # Pinned at creation so a mid-session config edit cannot retroactively
        # change what this session ran under.
        "config_hash": config_hash(),
        # Bound at creation, not at first use: every event in the session --
        # including the ones before the letter exists -- must say which material
        # it belongs to, and a session that failed early is still a session
        # somebody has to classify.
        "material_id": material_id,
        "material_manifest_hash": material_hash,
        "tree_variant_id": variant_id,
        # A separate, smaller bundle on a different criterion (BE-18). Bound at
        # creation like the real one so a session always knows both.
        "practice_material_id": practice_material_id,
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
        # -1, not 0: this is "nothing acknowledged yet", and find_gaps starts
        # looking from seq_acked + 1. Starting at 0 meant the first expected seq
        # was 1, so a session whose very first client event never arrived showed
        # no gap at all -- the one loss that is invisible is the one at the
        # start, where the join and the first actions are.
        "seq_acked": -1,
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
    """Budget for a timed phase, or None if untimed. Read from study_config.

    `is not None`, not a truthiness test: a configured 0 means "no time at
    all", which is a legitimate (if unusual) setting and must not silently
    become "untimed" -- those two have opposite effects on the soft lock.
    """
    seconds = phase_config(phase).get("duration_seconds")
    return int(seconds) * 1000 if seconds is not None else None


def phase_locks(phase: str) -> bool:
    """Whether running out of budget soft-locks the participant.

    True for organisation only. Verification is timed for the moderator's
    information, not to cut the participant off -- see the note above.
    """
    return bool(phase_config(phase).get("softlock", False))


def phase_shows_clock(phase: str) -> bool:
    """Whether the participant may see a countdown (红线 #4)."""
    return bool(phase_config(phase).get("visible_clock", False))


def phase_hard_cap_ms(phase: str) -> Optional[int]:
    """Point past which the MODERATOR should step in. Never sent to the
    participant and never enforced by the software."""
    seconds = phase_config(phase).get("hard_cap_seconds")
    return int(seconds) * 1000 if seconds is not None else None


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
    """True once a LOCKING phase is past its budget plus grace.

    Returns False for verification however long it runs: that phase ends when
    the participant says it does.
    """
    phase = session["phase"]
    if not phase_locks(phase):
        return False
    deadline = session.get("phase_deadline_ms")
    if deadline is None or session.get("softlock"):
        return False
    grace = int(phase_config(phase).get("softlock_grace_seconds", 0)) * 1000
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
    if phase_shows_clock(session["phase"]) and session.get("phase_deadline_ms"):
        remaining = session["phase_deadline_ms"] - (at_ms if at_ms is not None else now_ms())
        state["remaining_ms"] = max(0, remaining)
    # The verification phase tells the participant they may finish whenever they
    # like. It carries no time whatsoever -- the flag is a boolean, on purpose,
    # so there is nothing here a clock could be reconstructed from.
    state["can_submit"] = session["phase"] in SUBMITTABLE_PHASES and not session["submitted"]
    return state
