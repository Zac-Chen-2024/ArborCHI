"""
Background jobs (Doc/01 M10, plan 1.3): task queue + polling, no broker.

Long LLM pipelines (letter generation, argument organisation, extraction) run
as asyncio background tasks inside the API process. The HTTP request that
starts one returns a job id immediately; clients poll GET /api/jobs/{id}.

Job record (data/workspaces/{ws}/jobs/{job_id}.json, written via update_json):
    id, type, project_id, status, step, progress, detail, result, error,
    params_hash, created_at, started_at, finished_at, updated_at, workspace
    status: queued | running | succeeded | failed | cancelled

Semantics
    * idempotent submit: same (workspace, type, params_hash) with a job still
      queued/running -> the existing job id is returned (double-clicks)
    * cooperative cancel: POST /cancel flips a flag; the pipeline calls
      job.checkpoint(...) at natural boundaries (each SubArgument / Argument),
      which persists progress and raises JobCancelled if the flag is set
    * crash recovery: recover_on_startup() marks every queued/running record
      as failed ("server restarted") -- a job cannot survive the process
    * the workspace ContextVar is captured at submit time (asyncio copies the
      context into the task), so storage paths inside the pipeline resolve to
      the right workspace without any plumbing

This is the smallest thing that works without Redis/Celery: one process, one
event loop, JSON files. If a second API worker is ever needed, the same
records can be picked up by a real queue -- the client contract (submit ->
poll -> result) does not change.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .atomic_io import read_json, update_json
from .ids import is_safe_id
from .workspace import current_workspace

logger = logging.getLogger(__name__)

TERMINAL = {"succeeded", "failed", "cancelled"}


class JobCancelled(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jobs_dir(workspace_id: Optional[str] = None) -> Path:
    from ..services.storage import workspace_dir  # late import
    return workspace_dir(workspace_id) / "jobs"


def job_path(job_id: str, workspace_id: Optional[str] = None) -> Path:
    if not is_safe_id(job_id):
        raise ValueError(f"Invalid job_id: {job_id!r}")
    return _jobs_dir(workspace_id) / f"{job_id}.json"


def params_hash(params: Any) -> str:
    return hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


class JobHandle:
    """What a running pipeline sees. Persist progress; raise on cancel."""

    def __init__(self, manager: "JobManager", job_id: str):
        self._m = manager
        self.id = job_id

    @property
    def cancel_requested(self) -> bool:
        return self.id in self._m._cancel_flags

    def checkpoint(self, step: Optional[str] = None, detail: Optional[str] = None,
                   progress: Optional[float] = None) -> None:
        """Record progress and give the job a chance to stop cooperatively."""
        self._m._update(self.id, {
            **({"step": step} if step is not None else {}),
            **({"detail": detail} if detail is not None else {}),
            **({"progress": max(0.0, min(1.0, float(progress)))} if progress is not None else {}),
        })
        if self.cancel_requested:
            raise JobCancelled(self.id)


class NullJob:
    """Stand-in when a pipeline runs synchronously (tests, scripts)."""

    id = None
    cancel_requested = False

    def checkpoint(self, *a, **kw) -> None:  # noqa: D401
        return None


class JobManager:
    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}
        self._cancel_flags: set = set()
        self._active_by_key: Dict[str, str] = {}   # f"{ws}:{type}:{params_hash}" -> job_id

    # ---- persistence -----------------------------------------------------

    def _update(self, job_id: str, patch: Dict[str, Any], workspace_id: Optional[str] = None) -> Dict[str, Any]:
        def _mut(rec):
            rec = rec or {"id": job_id}
            rec.update(patch)
            rec["updated_at"] = _now()
            return rec
        return update_json(job_path(job_id, workspace_id), _mut, default={})

    def get(self, job_id: str, workspace_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not is_safe_id(job_id):
            return None
        return read_json(job_path(job_id, workspace_id))

    def list(self, project_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        d = _jobs_dir()
        if not d.is_dir():
            return []
        recs = []
        for f in d.glob("*.json"):
            rec = read_json(f)
            if not rec:
                continue
            if project_id and rec.get("project_id") != project_id:
                continue
            recs.append(rec)
        recs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return recs[:limit]

    # ---- submit / run ------------------------------------------------------

    def submit(
        self,
        job_type: str,
        project_id: Optional[str],
        params: Dict[str, Any],
        run: Callable[[JobHandle], Awaitable[Any]],
    ) -> Dict[str, Any]:
        """Start `run(job)` in the background. Returns the job record.

        If an identical job (same workspace/type/params) is already queued or
        running, that job's record is returned instead of starting another.
        """
        ws = current_workspace()
        ph = params_hash(params)
        key = f"{ws}:{job_type}:{ph}"
        existing_id = self._active_by_key.get(key)
        if existing_id:
            rec = self.get(existing_id, ws)
            if rec and rec.get("status") in ("queued", "running"):
                return rec
            self._active_by_key.pop(key, None)

        job_id = f"job-{uuid.uuid4().hex[:12]}"
        rec = {
            "id": job_id, "type": job_type, "project_id": project_id, "workspace": ws,
            "status": "queued", "step": None, "progress": 0.0, "detail": "queued",
            "result": None, "error": None, "params_hash": ph,
            "created_at": _now(), "started_at": None, "finished_at": None,
        }
        self._update(job_id, rec, ws)
        self._active_by_key[key] = job_id

        handle = JobHandle(self, job_id)

        async def _runner():
            self._update(job_id, {"status": "running", "started_at": _now(), "detail": "running"}, ws)
            try:
                result = await run(handle)
                self._update(job_id, {"status": "succeeded", "progress": 1.0, "result": result,
                                      "detail": "done", "finished_at": _now()}, ws)
            except (JobCancelled, asyncio.CancelledError):
                self._update(job_id, {"status": "cancelled", "detail": "cancelled", "finished_at": _now()}, ws)
            except Exception as e:  # noqa: BLE001 - job failures are data, not crashes
                logger.error("job %s (%s) failed: %s\n%s", job_id, job_type, e, traceback.format_exc())
                self._update(job_id, {"status": "failed", "error": f"{type(e).__name__}: {e}"[:2000],
                                      "detail": "failed", "finished_at": _now()}, ws)
            finally:
                self._tasks.pop(job_id, None)
                self._cancel_flags.discard(job_id)
                if self._active_by_key.get(key) == job_id:
                    self._active_by_key.pop(key, None)

        # create_task copies the current contextvars (workspace) into the task
        self._tasks[job_id] = asyncio.get_running_loop().create_task(_runner())
        return self.get(job_id, ws)

    # ---- cancel ---------------------------------------------------------------

    def cancel(self, job_id: str) -> Optional[Dict[str, Any]]:
        rec = self.get(job_id)
        if not rec:
            return None
        if rec.get("status") in TERMINAL:
            return rec
        self._cancel_flags.add(job_id)
        rec = self._update(job_id, {"detail": "cancel requested"})
        if job_id not in self._tasks:
            # queued-but-not-running (should not happen with create_task) or lost task
            rec = self._update(job_id, {"status": "cancelled", "finished_at": _now()})
        return rec

    # ---- startup ------------------------------------------------------------

    def recover_on_startup(self) -> int:
        """Mark records left in queued/running by a previous process as failed."""
        from ..services.storage import data_dir  # late import
        root = data_dir() / "workspaces"
        n = 0
        if not root.is_dir():
            return 0
        for ws_dir in root.iterdir():
            jobs = ws_dir / "jobs"
            if not jobs.is_dir():
                continue
            for f in jobs.glob("*.json"):
                rec = read_json(f)
                if rec and rec.get("status") in ("queued", "running"):
                    self._update(rec["id"], {"status": "failed", "error": "server restarted",
                                             "detail": "server restarted", "finished_at": _now()}, ws_dir.name)
                    n += 1
        if n:
            logger.warning("jobs: marked %d interrupted job(s) as failed after restart", n)
        return n


manager = JobManager()

__all__ = ["JobCancelled", "JobHandle", "NullJob", "JobManager", "manager", "params_hash", "job_path"]
