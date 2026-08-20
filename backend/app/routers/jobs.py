"""
Jobs API (Doc/01 M10).

    GET  /api/jobs?project_id=...        list recent jobs in this workspace
    GET  /api/jobs/{job_id}              poll one job
    POST /api/jobs/{job_id}/cancel       cooperative cancel
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.core.ids import validate_path_params
from app.core.jobs import manager

router = APIRouter(prefix="/api/jobs", tags=["jobs"], dependencies=[Depends(validate_path_params)])


@router.get("")
def list_jobs(project_id: Optional[str] = None, limit: int = 50):
    return {"success": True, "jobs": manager.list(project_id=project_id, limit=min(max(limit, 1), 200))}


@router.get("/{job_id}")
def get_job(job_id: str):
    rec = manager.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Job not found")
    return rec


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    rec = manager.cancel(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Job not found")
    return rec
