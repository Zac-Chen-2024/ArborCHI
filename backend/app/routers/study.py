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

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core import integrity, materials, probe, study, study_log, study_snapshots
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


class CheckpointBody(BaseModel):
    """One practice gate cleared. `gate` names which."""
    gate: str = Field(..., pattern="^[a-z_]{1,32}$")


class TreeStateBody(BaseModel):
    """The participant's working tree, verbatim.

    Opaque to the server on purpose. This is a resume point, not a measurement:
    what a node IS for the purposes of frozen-vs-live is decided from the
    `node_states` that /generate receives and checked against tree.frozen.json,
    and nothing here is allowed to influence that. Storing the client's own
    structure means a restored session is byte-identical to the one that was
    interrupted, rather than a reconstruction that has to be trusted.
    """
    tree: Any
    material_id: str = ""


class ConfidenceBody(BaseModel):
    likert_1_7: int = Field(..., ge=1, le=7)
    est_problem_count: int = Field(..., ge=0, le=500)


class ProbeAnswerBody(BaseModel):
    probe_index: int = Field(..., ge=0)
    judgment: str = Field(..., pattern="^(supported|not_supported|unsure)$")
    rt_ms: int = Field(..., ge=0)
    source_opened: bool = False


async def _precompute_live(
    node_states: Dict[str, Any], material_id: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """Generate every changed node's text, on the request's own event loop.

    assemble() is deliberately synchronous -- it is a pure function of the tree
    and the bundle, which is what lets the frozen/live decision be tested
    without a network. So the I/O happens here, first, and assemble is handed a
    callback that only looks up what was already produced.

    An earlier version bridged the other way, driving the coroutine with
    `asyncio.run` inside a worker thread. It worked once per process and then
    failed with "Event loop is closed": the provider caches one
    httpx.AsyncClient, that client binds to the loop that created it, and
    `asyncio.run` closes its loop on the way out. The first participant to
    press Regenerate got live text; every request after that -- in that server
    process, for every session -- got a 503. A single call in a fresh process
    looks perfectly healthy, which is why it survived a direct test and was
    caught by the deployment rehearsal instead.
    """
    frozen = materials.frozen_nodes(material_id)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for node_id, submitted in node_states.items():
        if (submitted or {}).get("state") == "removed":
            continue
        changed, _reason = study_generator.node_is_changed(node_id, submitted, frozen)
        if changed:
            out[node_id] = await study_generator.generate_live_sentences(
                node_id, submitted, material_id=material_id,
            )
    return out


def _live_generator(precomputed: Dict[str, List[Dict[str, Any]]]):
    """Hands assemble() the text produced above.

    Raises rather than falling back if assemble asks for a node that was not
    precomputed: a quiet substitution of frozen text would look like success
    while falsifying `source`, which is the independent variable.
    """
    def lookup(node_id: str, _submitted: Dict[str, Any]) -> List[Dict[str, Any]]:
        if node_id not in precomputed:
            raise study_generator.GenerationError(
                f"no live text was generated for {node_id}")
        return precomputed[node_id]

    return lookup


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

    previous_max = int(session.get("seq_acked", -1))
    gaps = study_log.find_gaps(previous_max, [r["seq"] for r in accepted])

    append_jsonl_many(path, accepted)

    highest = max([previous_max] + [r["seq"] for r in accepted])

    def _bump(rec):
        rec["seq_acked"] = max(rec.get("seq_acked", -1), highest)
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
    material_id = _material_for_phase(session)
    # criterion / cfr / case come from the bundle, not from the interface's
    # translation file. They were fixed strings there, so the practice phase --
    # which is a different criterion on purpose, to teach the interface without
    # teaching the case -- displayed the real case's criterion and statute
    # above the practice material.
    manifest = materials.load_bundle(material_id)["manifest"]
    return {
        "material_id": material_id,
        "practice": session["phase"] == "practice",
        "criterion": manifest.get("criterion") or "",
        "cfr": manifest.get("cfr") or "",
        "case_label": manifest.get("case_label") or "",
        "tree": materials.public_tree(material_id),
        "relations": materials.public_relations(material_id),
        **materials.public_snippets(material_id),
    }


def _material_for_phase(session: Dict[str, Any]) -> str:
    """Which bundle this request gets.

    Decided by the SERVER from the phase, never by a query parameter. If the
    client could name the bundle, a participant in the practice phase could ask
    for the real case and arrive at the measured task having already read the
    exhibits -- which is precisely the part of the session the two conditions
    are being compared on.
    """
    # setup and tutorial are before the practice phase: the moderator is
    # briefing, and there is nothing the participant is meant to be reading.
    # The real bundle was served in those phases, so anyone whose client
    # rendered the workspace could read the case they were about to be measured
    # on, unobserved and untimed. The practice bundle is the right answer here
    # for the same reason it is the right answer during practice.
    if session["phase"] in ("setup", "tutorial", "practice"):
        return session.get("practice_material_id") or "practice_v1"
    return session.get("material_id") or "case_v1"


@router.post("/generate")
async def generate(body: GenerateBody) -> Dict[str, Any]:
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

    # A generate with no nodes assembles an empty letter, and an empty letter
    # written over the baseline destroys it without anything looking wrong --
    # 200, no sentences, `initial.json` now the sha256 of "". No client sends
    # this (a participant who deletes every sub-argument still reports them as
    # `removed`), so it is a malformed request, and the baseline is worth more
    # than the tolerance.
    if not body.node_states:
        raise HTTPException(status_code=400, detail="node_states must not be empty")

    material_id = _material_for_phase(session)
    try:
        live = await _precompute_live(body.node_states, material_id)
        built = study_generator.assemble(
            body.node_states,
            material_id=material_id,
            generate_live=_live_generator(live),
        )
    except study_generator.GenerationError as e:
        # Surfaced as 503 rather than 500: the request was fine, the capability
        # is missing. A moderator seeing this needs to know it is configuration.
        logger.error("generation failed for %s: %s", session["session_id"], e)
        raise HTTPException(status_code=503, detail="Generation is not available")

    # 红线 #1 -- before the participant can edit anything.
    #
    # The FIRST generation is the baseline and is written once, under the id
    # `initial`. Later regenerations get ids of their own.
    #
    # This used to write `initial` every time. Nothing about that looked wrong:
    # the ordering inside the request was still assemble -> snapshot -> log, the
    # event log still recorded a sha256 per generation, and the integrity check
    # still reported "initial and final present, hashes match". But `initial` on
    # disk was whatever the participant last pressed Regenerate on -- and every
    # measure that asks "what did the letter say before they touched it" is
    # computed against that file. Regenerating is normal use, and entering the
    # verification phase regenerates automatically, so the baseline was
    # routinely gone before the phase that needs it even started.
    generation_index = int(session.get("generation_count") or 0)
    snapshot_id = "initial" if generation_index == 0 else f"draft_{generation_index}"

    meta = study_snapshots.write_snapshot(
        session,
        snapshot_id,
        "draft",
        built["text"],
        sentences=built["sentences"],
        extra={
            "stats": built["stats"],
            "material_id": material_id,
            "generation_index": generation_index,
        },
    )
    write_server_event(session, "draft_snapshot", {
        "snapshot_id": snapshot_id,
        "generation_index": generation_index,
        "trigger": "generation",
        **meta,
    })

    def _mark(rec):
        rec["generated_at"] = study.now_iso()
        rec["generation_count"] = generation_index + 1
        # Set once, by the same rule that decides the snapshot id: the hash the
        # analysis compares against must name the baseline, not the latest draft.
        if generation_index == 0:
            rec["initial_snapshot_hash"] = meta["sha256"]
        rec["latest_snapshot_hash"] = meta["sha256"]
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


# The practice gates each condition must clear before the measured task
# (FS-06). C has to have used the two things that distinguish it -- the
# magnifier and a linkage jump -- at least once, because a participant who
# never discovers them is not in condition C in any meaningful sense. B has to
# have navigated by hand, which is its only route to the evidence.
PRACTICE_GATES = {
    "c": ("lightbox", "linkage"),
    "b": ("manual_page",),
}


@router.put("/tree")
def save_tree(body: TreeStateBody) -> Dict[str, Any]:
    """Persist the working tree so a reload does not erase the organisation phase.

    The tree lived only in the browser. A refresh -- or a crash, or a stray
    Back -- reset all of it to the machine's original proposal, and the next
    generation ran against that pristine tree. Nothing surfaced: the letter
    still appeared, the phase still advanced, the log still held every
    `tree_op` the participant had performed. The session looked complete and
    would have been analysed as one, while the structure it was built on was
    not the participant's.

    No event is written here. Every mutation is already logged at the moment it
    happens (lib/treeStore.ts); this is the same state reaching durable storage,
    not a new action by the participant, and the event dictionary stays closed.
    """
    session = _participant_session()
    if session.get("submitted"):
        raise HTTPException(status_code=409, detail="Session already submitted")

    # Bounded so a malformed client cannot grow the session record without
    # limit. A real tree is a few kilobytes.
    if len(json.dumps(body.tree, ensure_ascii=False)) > 256_000:
        raise HTTPException(status_code=413, detail="Tree state too large")

    saved_at = study.now_iso()

    # Stamped with the bundle it belongs to. The practice phase serves a
    # different bundle, and a practice tree restored over the real material
    # would be a wrong tree that looks like a right one.
    material_id = body.material_id or _material_for_phase(session)

    def _store(rec):
        rec["tree_state"] = {
            "tree": body.tree, "material_id": material_id, "saved_at": saved_at,
        }
        return rec

    study.update_session(session["session_id"], _store)
    return {"success": True, "saved_at": saved_at}


@router.get("/tree")
def load_tree() -> Dict[str, Any]:
    """The stored tree, or null when the participant has not changed anything.

    Null rather than 404: "nothing saved yet" is the normal state at the start
    of the organisation phase, and a client that treats an error and an empty
    result differently would have two paths through the same situation.
    """
    session = _participant_session()
    stored = session.get("tree_state") or {}
    # Only hand back a tree that belongs to the bundle this phase serves.
    if stored and stored.get("material_id") != _material_for_phase(session):
        return {"tree": None, "saved_at": None, "material_id": None}
    return {
        "tree": stored.get("tree"),
        "material_id": stored.get("material_id"),
        "saved_at": stored.get("saved_at"),
    }


@router.post("/checkpoint")
def checkpoint(body: CheckpointBody) -> Dict[str, Any]:
    """Record a cleared practice gate (FS-06, BE-18).

    Kept on the SERVER rather than in client state: the gate decides whether
    someone may start the measured task, and a client-side flag is a flag a
    reload clears. The response says what is still outstanding so the practice
    screen can show it without keeping its own tally.
    """
    session = _participant_session()
    required = PRACTICE_GATES.get(session["condition"], ())
    if body.gate not in required:
        raise HTTPException(status_code=400, detail="Unknown gate for this condition")

    already = set(session.get("checkpoints") or [])
    if body.gate not in already:
        def _record(rec):
            rec.setdefault("checkpoints", [])
            if body.gate not in rec["checkpoints"]:
                rec["checkpoints"].append(body.gate)
            return rec

        session = study.update_session(session["session_id"], _record)
        write_server_event(session, "checkpoint_passed", {
            "gate": body.gate,
            "cleared": list(session["checkpoints"]),
            "remaining": [g for g in required if g not in session["checkpoints"]],
        })

    cleared = set(session.get("checkpoints") or [])
    return {
        "cleared": sorted(cleared),
        "remaining": [g for g in required if g not in cleared],
        "complete": all(g in cleared for g in required),
    }


@router.get("/checkpoint")
def checkpoint_state() -> Dict[str, Any]:
    session = _participant_session()
    required = PRACTICE_GATES.get(session["condition"], ())
    cleared = set(session.get("checkpoints") or [])
    return {
        "required": list(required),
        "cleared": sorted(cleared),
        "remaining": [g for g in required if g not in cleared],
        "complete": all(g in cleared for g in required),
    }


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

    if session["phase"] == "practice":
        required = PRACTICE_GATES.get(session["condition"], ())
        cleared = set(session.get("checkpoints") or [])
        missing = [g for g in required if g not in cleared]
        if missing:
            # FS-06: not a warning, a refusal. The moderator can see what is
            # outstanding and ask the participant to do it.
            raise HTTPException(
                status_code=409,
                detail=f"Practice gates not cleared: {missing}",
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


@router.post("/close/{session_id}")
def close_session(session_id: str) -> Dict[str, Any]:
    """Close-out: run the integrity checks and store the report (BE-15, MOD-06).

    Run while the participant is still in the room. That is the point of doing
    it here rather than in an analysis script weeks later -- a missing
    checkpoint or a truncated log is sometimes still fixable at that moment,
    and never fixable afterwards.

    Idempotent and non-destructive: the report is a reading of what is on disk,
    so re-running it on the same session gives the same answer.
    """
    _require_moderator()
    session = _moderator_session(session_id)

    report = integrity.build_report(session, baseline=_cohort_baseline(session))
    integrity.write_report(session, report)
    return report


def _cohort_baseline(session: Dict[str, Any]) -> Dict[str, float]:
    """Event-count baseline from the OTHER sessions on the same track.

    Same track only: a test run and a formal run are the same software but not
    the same behaviour, and pooling them would widen the baseline until nothing
    looked unusual. The session being judged is excluded from its own baseline.
    """
    counts = []
    for sid, ref in study.load_index().items():
        if sid == session["session_id"] or ref.get("track") != session.get("track"):
            continue
        other = study.load_session(sid)
        if not other or not other.get("submitted"):
            continue
        counts.append(int(other.get("event_count", 0)))
    return integrity.cohort_baseline(counts)


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
        "seq_acked": session.get("seq_acked", -1),
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
