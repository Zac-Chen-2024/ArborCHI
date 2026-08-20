"""
Workspace isolation (Doc/01 M5, plan 0.2).

One bearer token == one workspace == one study participant. No accounts, no
roles, no sharing. Data layout:

    data/workspaces.json                       {token: {workspace_id, label, created_at}}
    data/workspaces/{workspace_id}/projects/   (storage.projects_dir() resolves here)
    data/workspaces/{workspace_id}/logs/       (M6 interaction logs)
    data/workspaces/{workspace_id}/jobs/       (M10)

Request flow: WorkspaceMiddleware reads `Authorization: Bearer <token>` (or
`?token=` for direct resource URLs such as PDFs) -> looks it up -> stores the
workspace id in a ContextVar for the duration of the request. Every path the
storage layer builds goes through storage.projects_dir(), which reads that
ContextVar -- so business code never sees workspaces at all.

Missing / invalid token -> 401. With settings.auth_disabled (local dev) an
unauthenticated request falls back to the "default" workspace; a valid token
is still honoured so several workspaces can be exercised locally.

Study extension (BE-02 / BE-19): a token entry may additionally carry

    role       "participant" | "moderator"   (default: participant)
    track      "formal" | "test"             (default: formal)
    session_id  the study session this token is bound to (participants only)

The middleware puts the whole entry in a second ContextVar so `/api/study`
endpoints can gate on role without re-reading the token table. Product tokens
minted before the study simply have no role/track keys and fall back to the
least-privileged defaults.
"""

from __future__ import annotations

import json
import secrets
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import parse_qs

from .atomic_io import read_json, update_json
from .config import settings
from .ids import is_safe_id

DEFAULT_WORKSPACE = "default"

DEFAULT_ROLE = "participant"
DEFAULT_TRACK = "formal"
ROLES = ("participant", "moderator")
TRACKS = ("formal", "test")

_current_workspace: ContextVar[str] = ContextVar("workspace_id", default=DEFAULT_WORKSPACE)
# The full token-table entry for this request ({} when auth_disabled and no
# token was supplied). Read via current_role() / current_track() / ...
_current_entry: ContextVar[Dict] = ContextVar("token_entry", default={})


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

def current_workspace() -> str:
    return _current_workspace.get()


def set_current_workspace(workspace_id: str):
    """Set the workspace for the current context. Returns a token for reset()."""
    if not is_safe_id(workspace_id):
        raise ValueError(f"Invalid workspace_id: {workspace_id!r}")
    return _current_workspace.set(workspace_id)


def reset_current_workspace(token) -> None:
    _current_workspace.reset(token)


def current_entry() -> Dict:
    """The token-table entry backing this request (may be empty in dev)."""
    return _current_entry.get()


def current_role() -> str:
    role = _current_entry.get().get("role")
    return role if role in ROLES else DEFAULT_ROLE


def current_track() -> str:
    track = _current_entry.get().get("track")
    return track if track in TRACKS else DEFAULT_TRACK


def current_session_id() -> Optional[str]:
    """The study session this token is bound to, if any (participants)."""
    sid = _current_entry.get().get("session_id")
    return sid if isinstance(sid, str) and is_safe_id(sid) else None


# ---------------------------------------------------------------------------
# Token table
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    # Late import: storage imports this module for current_workspace().
    from ..services.storage import data_dir
    return data_dir()


def token_table_path() -> Path:
    return _data_dir() / "workspaces.json"


def load_token_table() -> Dict[str, Dict]:
    return read_json(token_table_path(), default={}) or {}


def lookup_entry(token: str) -> Optional[Dict]:
    """Return the whole token-table entry, or None if the token is unknown
    or its workspace id is unsafe."""
    if not token:
        return None
    entry = load_token_table().get(token)
    if not entry:
        return None
    return entry if is_safe_id(entry.get("workspace_id")) else None


def lookup_token(token: str) -> Optional[str]:
    """Return the workspace_id for a token, or None."""
    entry = lookup_entry(token)
    return entry.get("workspace_id") if entry else None


def mint_token(
    label: str,
    workspace_id: Optional[str] = None,
    role: str = DEFAULT_ROLE,
    track: str = DEFAULT_TRACK,
    session_id: Optional[str] = None,
) -> Dict:
    """Create a token (and its workspace directory). Returns the table entry + token."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    if track not in TRACKS:
        raise ValueError(f"track must be one of {TRACKS}, got {track!r}")
    token = secrets.token_urlsafe(24)
    ws = workspace_id or _slug(label)
    if not is_safe_id(ws):
        raise ValueError(f"Cannot derive a safe workspace id from label {label!r}")
    entry = {
        "workspace_id": ws,
        "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "role": role,
        "track": track,
    }
    if session_id is not None:
        entry["session_id"] = session_id

    def _add(table):
        table = table or {}
        table[token] = entry
        return table

    update_json(token_table_path(), _add, default={})
    (_data_dir() / "workspaces" / ws / "projects").mkdir(parents=True, exist_ok=True)
    return {"token": token, **entry}


def _slug(label: str) -> str:
    out = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in label.strip())
    out = out.strip("-_")
    return out or "ws"


# ---------------------------------------------------------------------------
# ASGI middleware
# ---------------------------------------------------------------------------

_PUBLIC_PATHS = {"/", "/api/health", "/docs", "/openapi.json", "/redoc"}


def _extract_token(scope) -> str:
    headers = dict(scope.get("headers") or [])
    auth = headers.get(b"authorization", b"").decode("latin-1")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    qs = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
    vals = qs.get("token")
    return vals[0] if vals else ""


class WorkspaceMiddleware:
    """Pure ASGI middleware (not BaseHTTPMiddleware) so the ContextVar set here
    is visible to the endpoint, including sync endpoints run in the threadpool
    (anyio copies the context into worker threads)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in _PUBLIC_PATHS or not path.startswith("/api/") or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        token = _extract_token(scope)
        entry = lookup_entry(token) if token else None
        ws = entry.get("workspace_id") if entry else None

        if ws is None:
            if settings.auth_disabled and not token:
                ws = DEFAULT_WORKSPACE
                entry = {}
            else:
                await _unauthorized(send)
                return

        ctx_token = _current_workspace.set(ws)
        ctx_entry = _current_entry.set(entry or {})
        try:
            await self.app(scope, receive, send)
        finally:
            _current_entry.reset(ctx_entry)
            _current_workspace.reset(ctx_token)


async def _unauthorized(send):
    body = json.dumps({"success": False, "error": "Unauthorized", "detail": None}).encode()
    await send({
        "type": "http.response.start",
        "status": 401,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"www-authenticate", b"Bearer"),
        ],
    })
    await send({"type": "http.response.body", "body": body})
