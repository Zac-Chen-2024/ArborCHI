"""
Study API (开发手册 §4). Namespace: /api/study/*

Everything the experiment needs that the product line must not grow. The
product routers are untouched -- in particular /api/logs keeps its own schema
and whitelist, and the two lines never share a file on disk (BE-06).

Role gating. The workspace middleware has already resolved the bearer token to
a workspace and stashed the whole token entry; `_require_moderator` and
`_require_participant` read the role off that. A participant token can reach
neither another participant's session (its own session id comes from its own
token entry -- there is no session_id parameter to tamper with) nor any
moderator route.

M0 scope: sessions / state / advance / start / note / monitor. Generation,
chat, logging, confidence and probe arrive with M1-M4; their route stubs are
deliberately absent rather than half-built, so a caller gets a clean 404
instead of a silent no-op.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core import materials, probe, study, study_log, study_snapshots
from app.core.atomic_io import append_jsonl_many
from app.core.config import settings
from app.core.ids import validate_path_params
from app.core.study_events import events_path, write_server_event
from app.core.workspace import (
    current_role,
    current_session_id,
    current_token,
    current_track,
    current_workspace,
    mint_token,
)
from app.services import study_generator

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/study",
    tags=["study"],
    dependencies=[Depends(validate_path_params)],
)


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def _require_moderator() -> None:
    if current_role() != "moderator":
        # 404, not 403: a participant poking at /mod learns nothing about
        # whether the route exists (same rule as ids.validate_id).
        raise HTTPException(status_code=404, detail="Not found")


def _participant_session() -> Dict[str, Any]:
    """The session bound to the caller's own token. There is no way to name a
    different one -- the id is not a parameter."""
    sid = current_session_id()
    if not sid:
        raise HTTPException(status_code=403, detail="Token is not bound to a session")
    session = study.load_session(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    if session["workspace_id"] != current_workspace():
        # Defence in depth: the token said one workspace, the record another.
        logger.error("Session %s workspace mismatch", sid)
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _moderator_session(session_id: str) -> Dict[str, Any]:
    session = study.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class CreateSessionBody(BaseModel):
    condition: str = Field(..., pattern="^(c|b)$")
    participant_code: str = Field(..., min_length=1, max_length=64)
    lang: str = Field("en", pattern="^(en|zh)$")
    track: str = Field("formal", pattern="^(formal|test)$")
    build: str = Field("", max_length=64)
    material_id: str = Field("case_v1", max_length=64)


class AdvanceBody(BaseModel):
    session_id: str
    # Optional explicit target; without it the machine steps one forward.
    # Named so a moderator cannot skip a phase by accident -- it must match
    # what the machine would do next, or the call is refused.
    to: Optional[str] = None


class NoteBody(BaseModel):
    session_id: str
    text: str = Field(..., min_length=1, max_length=4000)


class LogBatchBody(BaseModel):
    events: List[Dict[str, Any]] = Field(..., max_length=study_log.MAX_BATCH)


class GenerateBody(BaseModel):
    """The tree as the participant left it.

    Only what the node IS -- title, parent, evidence. Deliberately no "changed"
    flag: whether a node counts as changed is a statement about the independent
    variable, and the client is the thing being measured. The server decides by
    comparing against tree.frozen.json (see services/study_generator.py).
    """
    node_states: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class SubmitBody(BaseModel):
    """The participant declaring themselves finished.

    `final_text_hash` is the client's sha256 of what it is submitting. The
    server recomputes it and refuses a mismatch: the probe samples sentences
    from the stored final text and asks the participant about them, so the
    bytes on disk must be the bytes they were looking at. A silent divergence
    would have us quizzing them on a version they never saw.
    """
    text: str = Field(..., max_length=200_000)
    final_text_hash: str = Field(..., pattern="^[0-9a-f]{64}$")


class ConfidenceBody(BaseModel):
    likert_1_7: int = Field(..., ge=1, le=7)
    est_problem_count: int = Field(..., ge=0, le=500)


class ProbeAnswerBody(BaseModel):
    probe_index: int = Field(..., ge=0)
    judgment: str = Field(..., pattern="^(supported|not_supported|unsure)$")
    rt_ms: int = Field(..., ge=0)
    source_opened: bool = False


def _live_generator():
    """Live generation is not wired to a provider yet (M5). Returning None makes
    a changed node a loud 503 rather than a quiet substitution of frozen text --
    which would look like success while falsifying `source`."""
    return None


# ---------------------------------------------------------------------------
# Moderator: build a session (BE-01, MOD-02/07)
# ---------------------------------------------------------------------------

@router.post("/sessions")
def create_session(body: CreateSessionBody) -> Dict[str, Any]:
    _require_moderator()

    # One session == one fresh workspace (create_session derives the workspace
    # id from the session id it mints).
    session = study.create_session(
        condition=body.condition,
        participant_code=body.participant_code,
        lang=body.lang,
        track=body.track,
        build=body.build,
        material_id=body.material_id,
    )

    entry = mint_token(
        label=f"{body.participant_code}/{body.condition}",
        workspace_id=session["workspace_id"],
        role="participant",
        track=body.track,
        session_id=session["session_id"],
    )
    write_server_event(session, "session_created", {
        "condition": body.condition,
        "lang": body.lang,
        "track": body.track,
        "participant_code": body.participant_code,
    }, srv_seq=1)

    join_url = f"{settings.study_join_base_url.rstrip('/')}/join?token={entry['token']}"
    return {
        "success": True,
        "session_id": session["session_id"],
        "condition": session["condition"],
        "lang": session["lang"],
        "track": session["track"],
        "join_token": entry["token"],
        "join_url": join_url,
    }


# ---------------------------------------------------------------------------
# Participant: who am I, where am I (BE-05, FS-02)
# ---------------------------------------------------------------------------

@router.get("/state")
def get_state() -> Dict[str, Any]:
    """Polled every 2s. Drops the soft lock when a phase runs out of budget.

    红线 #4: `public_state` omits the time keys entirely outside the
    organisation phase. Do not add a "for debugging" field here.
    """
    session = _participant_session()
    now = study.now_ms()

    if study.softlock_due(session, now):
        def _lock(rec):
            rec["softlock"] = True
            return rec

        session = study.update_session(session["session_id"], _lock)
        write_server_event(session, "phase_softlock", {"phase": session["phase"]})

    # Heartbeat: the moderator panel reads this to colour the liveness light.
    def _seen(rec):
        rec["last_seen_ms"] = now
        return rec

    study.update_session(session["session_id"], _seen)

    return study.public_state(session, now)


@router.post("/log/batch")
async def log_batch(request: Request) -> Dict[str, Any]:
    """Ingest a batch of client events (BE-06).

    Three behaviours worth stating outright, because each is a decision:

    * A malformed event is rejected individually and counted; the rest of the
      batch is still stored. Losing nineteen good events because the twentieth
      had a bad field would be self-inflicted data loss.
    * A gap in `seq` is recorded, not refused. The participant who unplugged
      the network still finishes the session, and the analysis is told exactly
      which stretch is missing rather than being handed a log that looks whole.
    * `phase` is taken from the session record, not from the client. A client
      one poll behind would otherwise file events under the previous phase; its
      own claim is kept as `phase_client` so a disagreement stays visible.

    The response's `acked_seq` is what the client's queue drains against, so it
    must reflect what is actually on disk.
    """
    session = _participant_session()
    if session.get("submitted"):
        # After submit the record is closed (BE-11).
        raise HTTPException(status_code=409, detail="Session already submitted")

    # Read the body raw rather than through a pydantic model: the final flush
    # uses navigator.sendBeacon, which can only send a text/plain Blob, and
    # that flush is the one carrying the last events of the session. Same
    # reasoning as the product's /api/logs endpoint.
    try:
        body = LogBatchBody.model_validate_json(await request.body())
    except Exception:
        raise HTTPException(status_code=400, detail="Malformed batch")

    received_at = study.now_iso()
    path = events_path(session)

    accepted: List[Dict[str, Any]] = []
    rejected: List[Dict[str, str]] = []
    for raw in body.events:
        try:
            accepted.append(study_log.normalise(
                raw, session=session, received_at=received_at))
        except study_log.RejectedEvent as e:
            rejected.append({
                "seq": str(raw.get("seq")) if isinstance(raw, dict) else "?",
                "reason": e.reason,
            })

    previous_max = int(session.get("seq_acked", 0))
    gaps = study_log.find_gaps(previous_max, [r["seq"] for r in accepted])

    append_jsonl_many(path, accepted)

    highest = max([previous_max] + [r["seq"] for r in accepted])

    def _bump(rec):
        rec["seq_acked"] = max(rec.get("seq_acked", 0), highest)
        rec["event_count"] = rec.get("event_count", 0) + len(accepted)
        if gaps:
            # Registered, not fatal -- integrity.json reports these at close.
            rec.setdefault("seq_gaps", []).extend([list(g) for g in gaps])
        return rec

    study.update_session(session["session_id"], _bump)

    if rejected:
        logger.warning("session %s rejected %d event(s): %s",
                       session["session_id"], len(rejected), rejected[:5])

    return {
        "acked_seq": highest,
        "accepted": len(accepted),
        "rejected": len(rejected),
        "rejections": rejected[:20],
        "gaps": [list(g) for g in gaps],
    }


@router.post("/start")
def start_session() -> Dict[str, Any]:
    """The single button on the participant's Start page (FS-12).

    Idempotent: a double click, or a reload mid-session, must not re-stamp
    started_at or write a second session_start.
    """
    session = _participant_session()
    if session.get("started_at"):
        return study.public_state(session)

    def _start(rec):
        rec["started_at"] = study.now_iso()
        return rec

    session = study.update_session(session["session_id"], _start)
    write_server_event(session, "session_start", {
        "participant_code": session["participant_code"],
        "lang": session["lang"],
        # Material hashes join this payload at M5 when the bundle lands (BE-07).
    })
    return study.public_state(session)


@router.get("/material")
def get_material() -> Dict[str, Any]:
    """The tree and the evidence, as the participant may see them (BE-07).

    Everything here goes through `materials.public_*`, which is where the
    answer key is removed. No endpoint may reach into the bundle directly.
    """
    session = _participant_session()
    material_id = session.get("material_id") or "case_v1"
    return {
        "tree": materials.public_tree(material_id),
        "relations": materials.public_relations(material_id),
        **materials.public_snippets(material_id),
    }


@router.post("/generate")
def generate(body: GenerateBody) -> Dict[str, Any]:
    """Assemble the letter and snapshot it (BE-08, 红线 #1).

    **The ordering in this function is the red line.** The snapshot is written
    before the response is returned, therefore before the participant can type
    a single character. That snapshot is the only baseline against which "what
    did the human change" can ever be answered, and unlike almost everything
    else in the system it cannot be reconstructed after the fact -- once the
    text is edited, the pre-edit version is simply gone.

    So: assemble -> write snapshot -> log -> return. Never return early, never
    write the snapshot in a background task, never make it conditional on
    anything. If this endpoint succeeds, the baseline exists.

    The response carries `source: frozen|live` per sentence and NOT
    `planted_id` -- the first is data the analysis needs and the UI must ignore
    (红线 #3), the second is the probe's answer key.
    """
    session = _participant_session()
    if session.get("submitted"):
        raise HTTPException(status_code=409, detail="Session already submitted")

    material_id = session.get("material_id") or "case_v1"
    try:
        built = study_generator.assemble(
            body.node_states,
            material_id=material_id,
            generate_live=_live_generator(),
        )
    except study_generator.GenerationError as e:
        # Surfaced as 503 rather than 500: the request was fine, the capability
        # is missing. A moderator seeing this needs to know it is configuration.
        logger.error("generation failed for %s: %s", session["session_id"], e)
        raise HTTPException(status_code=503, detail="Generation is not available")

    # 红线 #1 -- before the participant can edit anything.
    meta = study_snapshots.write_snapshot(
        session,
        "initial",
        "draft",
        built["text"],
        sentences=built["sentences"],
        extra={"stats": built["stats"], "material_id": material_id},
    )
    write_server_event(session, "draft_snapshot", {
        "snapshot_id": "initial",
        "trigger": "generation",
        **meta,
    })

    def _mark(rec):
        rec["generated_at"] = study.now_iso()
        rec["initial_snapshot_hash"] = meta["sha256"]
        return rec

    study.update_session(session["session_id"], _mark)

    return {
        "text": built["text"],
        "sentences": materials.public_sentences(built["sentences"]),
        "stats": built["stats"],
    }


@router.post("/submit")
def submit(body: SubmitBody) -> Dict[str, Any]:
    """The participant hands in their draft (BE-11, 红线 #1).

    Everything about this endpoint is about the moment being unambiguous:

    * It is only available in a phase the protocol says may be ended by the
      participant. Submitting from the organisation phase is a 409, not an
      early finish.
    * The hash is verified before anything is written. A mismatch means the
      client and server disagree about what is being submitted, and the probe
      would otherwise quiz the participant on text they never saw.
    * `submit_declared` records the moment. In the verification phase there is
      no lock and no buzzer, so this timestamp is the only marker of when they
      decided they had checked enough -- which is the dependent measure (PR-6).
    * The session locks. Every later write is refused, so the final snapshot
      cannot drift from what the probe is built on.
    """
    session = _participant_session()

    if session.get("submitted"):
        raise HTTPException(status_code=409, detail="Already submitted")
    if session["phase"] not in study.SUBMITTABLE_PHASES:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot submit from phase {session['phase']!r}",
        )

    computed = study_snapshots.sha256(body.text)
    if computed != body.final_text_hash:
        # 400, not 409: this is a malformed request, not a state conflict.
        raise HTTPException(status_code=400, detail="final_text_hash does not match text")

    write_server_event(session, "submit_declared", {
        "phase": session["phase"],
        # How long they chose to spend, measured server-side. The participant
        # never saw this number.
        "phase_elapsed_ms": study.now_ms() - int(session.get("phase_entered_ms", 0)),
        "char_count": len(body.text),
    })

    meta = study_snapshots.write_snapshot(
        session, "final", "final", body.text,
        extra={"declared_by": "participant"},
    )

    def _lock(rec):
        rec["submitted"] = True
        rec["submitted_at"] = study.now_iso()
        rec["final_text_hash"] = computed
        return rec

    session = study.update_session(session["session_id"], _lock)
    write_server_event(session, "submit", meta)

    return {"success": True, **study.public_state(session)}


@router.post("/confidence")
def confidence(body: ConfidenceBody) -> Dict[str, Any]:
    """The two confidence questions (BE-12).

    Must come before the probe. Asking someone how confident they are AFTER
    walking them through their own sentences one at a time would measure the
    probe's effect on them, not the interface's -- so the order is enforced
    here rather than trusted to the client (红线 #6).
    """
    session = _participant_session()
    if session.get("confidence"):
        raise HTTPException(status_code=409, detail="Confidence already submitted")

    def _record(rec):
        rec["confidence"] = {
            "likert_1_7": body.likert_1_7,
            "est_problem_count": body.est_problem_count,
            "at": study.now_iso(),
        }
        return rec

    session = study.update_session(session["session_id"], _record)
    write_server_event(session, "confidence_submit", session["confidence"])
    return {"success": True}


@router.post("/probe/start")
def probe_start() -> Dict[str, Any]:
    """Draw this participant's probe items (BE-13, PR-2).

    Three guards, all server-side:

    * confidence must already be in (see above) -- 409 otherwise
    * the session must be submitted, because the items are sampled from the
      FINAL text and there is no final text before that
    * the draw is idempotent: a reload must show the same items, so the sample
      is stored the first time and replayed afterwards

    The stored record keeps `planted_id` on every item; the response does not.
    """
    session = _participant_session()

    if not session.get("submitted"):
        raise HTTPException(status_code=409, detail="Nothing submitted yet")
    if not session.get("confidence"):
        raise HTTPException(status_code=409, detail="Confidence must be submitted first")

    existing = session.get("probe")
    if existing:
        return {
            "items": [probe.public_item(i) for i in existing["items"]],
            "answered": existing.get("answers", {}),
        }

    final = study_snapshots.read_snapshot(session, "final")
    initial = study_snapshots.read_snapshot(session, "initial")
    if final is None:
        raise HTTPException(status_code=409, detail="No final snapshot")

    drawn = probe.select_items(
        final["text"],
        (initial or {}).get("sentences", []),
        token=current_token(),
        session_id=session["session_id"],
    )

    def _store(rec):
        rec["probe"] = {"items": drawn["items"], "stats": drawn["stats"], "answers": {}}
        return rec

    session = study.update_session(session["session_id"], _store)
    # The stats say how the sample was drawn -- which rule fired, how many
    # planted survived, what the final ratio was. Without them a reviewer
    # cannot check the draw against PR-2 without re-running it.
    write_server_event(session, "probe_start", drawn["stats"])

    return {"items": [probe.public_item(i) for i in drawn["items"]], "answered": {}}


@router.post("/probe/answer")
def probe_answer(body: ProbeAnswerBody) -> Dict[str, Any]:
    """One probe judgement. Idempotent per item: a re-answer replaces the
    previous one and both are in the log."""
    session = _participant_session()
    stored = session.get("probe")
    if not stored:
        raise HTTPException(status_code=409, detail="Probe has not started")
    if body.probe_index >= len(stored["items"]):
        raise HTTPException(status_code=404, detail="No such probe item")

    item = stored["items"][body.probe_index]

    def _record(rec):
        rec["probe"]["answers"][str(body.probe_index)] = {
            "judgment": body.judgment,
            "rt_ms": body.rt_ms,
            "source_opened": body.source_opened,
            "at": study.now_iso(),
        }
        return rec

    session = study.update_session(session["session_id"], _record)
    write_server_event(session, "probe_item", {
        "probe_index": body.probe_index,
        "sent_id": item.get("sent_id"),
        "judgment": body.judgment,
        "rt_ms": body.rt_ms,
        "source_opened": body.source_opened,
        # Ground truth goes in the LOG, never in the response.
        "planted_id": item.get("planted_id"),
        "subargument_id": item.get("subargument_id"),
    })
    return {"success": True}


# ---------------------------------------------------------------------------
# Moderator: drive the machine (BE-03, MOD-03)
# ---------------------------------------------------------------------------

@router.post("/advance")
def advance(body: AdvanceBody) -> Dict[str, Any]:
    _require_moderator()
    session = _moderator_session(body.session_id)

    target = study.next_phase(session)
    if target is None:
        raise HTTPException(status_code=409, detail="Session is already done")
    if body.to is not None and body.to != target:
        # The machine is the authority on order; `to` is a confirmation, not
        # a jump instruction.
        raise HTTPException(
            status_code=409,
            detail=f"Next phase is {target!r}, not {body.to!r}",
        )

    left = session["phase"]
    write_server_event(session, "phase_exit", {"phase": left})

    def _advance(rec):
        study.enter_phase(rec, target)
        return rec

    session = study.update_session(session["session_id"], _advance)
    write_server_event(session, "phase_enter", {"phase": target, "from": left})

    return {"success": True, **study.public_state(session)}


@router.post("/note")
def moderator_note(body: NoteBody) -> Dict[str, Any]:
    """Field notes go into the same event stream as everything else (MOD-05)."""
    _require_moderator()
    session = _moderator_session(body.session_id)
    write_server_event(session, "moderator_note", {"text": body.text})
    return {"success": True}


@router.get("/monitor/{session_id}")
def monitor(session_id: str) -> Dict[str, Any]:
    """Liveness for the moderator panel (MOD-04). Moderator-only: it exposes
    the server-side clock, which the participant must never see."""
    _require_moderator()
    session = _moderator_session(session_id)
    now = study.now_ms()

    last_seen = session.get("last_seen_ms")
    deadline = session.get("phase_deadline_ms")
    return {
        "session_id": session["session_id"],
        "condition": session["condition"],
        "participant_code": session["participant_code"],
        "lang": session["lang"],
        "track": session["track"],
        "phase": session["phase"],
        "next_phase": study.next_phase(session),
        "softlock": session["softlock"],
        "submitted": session["submitted"],
        "started": session.get("started_at") is not None,
        "seq_acked": session.get("seq_acked", 0),
        "heartbeat_age_ms": (now - last_seen) if last_seen else None,
        # Moderator-only clock.
        "phase_remaining_ms": (deadline - now) if deadline else None,
    }


@router.get("/sessions")
def list_sessions(track: Optional[str] = None) -> Dict[str, Any]:
    """Index for the moderator panel. `track` filters formal vs test."""
    _require_moderator()
    index = study.load_index()
    rows = [
        {"session_id": sid, **ref}
        for sid, ref in index.items()
        if track is None or ref.get("track") == track
    ]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return {"sessions": rows}


@router.get("/whoami")
def whoami() -> Dict[str, Any]:
    """What a token is good for. The participant app calls this at /join
    before it knows which condition to render (FS-02)."""
    return {
        "role": current_role(),
        "track": current_track(),
        "session_id": current_session_id(),
        "workspace_id": current_workspace(),
    }
