"""
Interaction log ingestion (Doc/01 M6, plan 0.3).

POST /api/logs/interactions
    body: {session_id, project_id, logs: [{ts, event, panel, payload}, ...]}

Each record is appended (JSONL, crash-safe by construction) to
    data/workspaces/{ws}/logs/{session_id}.jsonl
with the canonical schema {ts, session_id, project_id, event, panel, payload}
plus a server-side `received_at`.

The body is read raw and parsed here rather than via a Pydantic model because
the browser's final flush uses navigator.sendBeacon(), which can only send a
text/plain Blob (an application/json Blob would need a CORS preflight that
beacons cannot perform). Auth for that path comes via ?token= (see the
workspace middleware).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core.atomic_io import append_jsonl
from app.core.ids import is_safe_id, validate_path_params
from app.services.storage import workspace_dir

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"], dependencies=[Depends(validate_path_params)])

# Closed vocabulary -- analysis scripts key on these (Doc/01 M6).
EVENTS = {
    "node_create", "node_rename", "node_move", "node_merge", "node_delete",
    "snippet_assign", "snippet_unassign", "generate_trigger",
    "citation_click", "bbox_hover", "pdf_scroll", "letter_edit", "panel_focus",
    # M13 judgement surface
    "coverage_view", "diff_view", "undo",
}
PANELS = {"evidence", "pdf", "tree", "letter", "header", "other"}

MAX_BATCH = 2000
MAX_PAYLOAD_BYTES = 8 * 1024


def _normalise(record: Dict[str, Any], session_id: str, project_id: Any) -> Optional[Dict[str, Any]]:
    """Return a canonical record or None if the input is not usable."""
    if not isinstance(record, dict):
        return None
    event = record.get("event")
    if event not in EVENTS:
        return None
    panel = record.get("panel") if record.get("panel") in PANELS else "other"
    ts = record.get("ts")
    if not isinstance(ts, (int, float)):
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    if len(json.dumps(payload, ensure_ascii=False)) > MAX_PAYLOAD_BYTES:
        payload = {"_truncated": True}
    return {
        "ts": ts,
        "session_id": session_id,
        "project_id": record.get("project_id", project_id),
        "event": event,
        "panel": panel,
        "payload": payload,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


@router.post("/interactions")
async def ingest_interactions(request: Request):
    raw = await request.body()
    try:
        body = json.loads(raw.decode("utf-8") if raw else "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise HTTPException(status_code=400, detail="Body must be JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Body must be a JSON object")

    session_id = body.get("session_id")
    if not isinstance(session_id, str) or not is_safe_id(session_id):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    project_id = body.get("project_id")
    logs: List[Any] = body.get("logs") or []
    if not isinstance(logs, list):
        raise HTTPException(status_code=400, detail="logs must be a list")
    if len(logs) > MAX_BATCH:
        raise HTTPException(status_code=413, detail=f"Batch too large (> {MAX_BATCH})")

    path = workspace_dir() / "logs" / f"{session_id}.jsonl"
    accepted = 0
    rejected = 0
    for rec in logs:
        norm = _normalise(rec, session_id, project_id)
        if norm is None:
            rejected += 1
            continue
        append_jsonl(path, norm)
        accepted += 1

    if rejected:
        logger.info("interaction logs: session=%s accepted=%d rejected=%d", session_id, accepted, rejected)
    return {"success": True, "accepted": accepted, "rejected": rejected}
