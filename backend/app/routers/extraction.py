"""
Extraction Router - 统一提取 API

提供新的统一提取流程：
1. 一次性提取 snippets + entities + relations
2. 生成实体合并建议
3. 确认/拒绝合并
4. 应用合并

这将替代旧的 analysis router 的提取功能。
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.ids import validate_path_params
from app.core.jobs import manager as job_manager

from ..services.entity_merger import (
    apply_entity_merges,
    get_merge_status,
    load_merge_suggestions,
    suggest_entity_merges,
    update_merge_suggestion_status,
)
from ..services.unified_extractor import (
    extract_all_unified,
    load_combined_extraction,
)

router = APIRouter(prefix="/api/extraction", tags=["extraction"], dependencies=[Depends(validate_path_params)])


# ==================== Request/Response Models ====================

class ExtractionRequest(BaseModel):
    applicant_name: str
    provider: str = "deepseek"  # LLM provider: "deepseek" or "openai"
    project_type: Optional[str] = None  # "EB-1A" or "NIW"; auto-detected if not provided


class MergeConfirmation(BaseModel):
    suggestion_id: str
    status: str  # "accepted" or "rejected"


# ==================== Extraction Endpoints ====================

@router.post("/{project_id}/extract", status_code=202)
async def extract_project(
    project_id: str,
    request: ExtractionRequest
):
    """
    统一提取整个项目

    一次性提取所有 exhibits 的 snippets + entities + relations
    """
    applicant_name = request.applicant_name
    provider = request.provider

    if not applicant_name:
        raise HTTPException(status_code=400, detail="applicant_name is required")

    # Auto-detect project_type from storage if not provided
    project_type = request.project_type
    if not project_type:
        try:
            from ..services.storage import get_project_type
            project_type = get_project_type(project_id)
        except Exception:
            project_type = "EB-1A"

    async def _run(job):
        result = await extract_all_unified(
            project_id=project_id,
            applicant_name=applicant_name,
            provider=provider,
            project_type=project_type,
            job=job,
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error", "Extraction failed"))
        return result

    params = {"project_id": project_id, "applicant_name": applicant_name, "provider": provider,
              "project_type": project_type}
    return job_manager.submit("extract", project_id, params, _run)


# ==================== Snippet Query Endpoints ====================

@router.get("/{project_id}/snippets")
async def get_snippets(
    project_id: str,
    subject: Optional[str] = None,
    is_applicant: Optional[bool] = None,
    evidence_type: Optional[str] = None,
    limit: int = 500,
    offset: int = 0
):
    """
    查询 snippets

    支持过滤：
    - subject: 按主体过滤
    - is_applicant: 只看申请人/非申请人的成就
    - evidence_type: 按证据类型过滤
    """
    combined = load_combined_extraction(project_id)
    if not combined:
        return {
            "project_id": project_id,
            "total": 0,
            "snippets": []
        }

    snippets = combined.get("snippets", [])

    # 过滤
    if subject:
        snippets = [s for s in snippets if s.get("subject", "").lower() == subject.lower()]

    if is_applicant is not None:
        snippets = [s for s in snippets if s.get("is_applicant_achievement") == is_applicant]

    if evidence_type:
        snippets = [s for s in snippets if s.get("evidence_type") == evidence_type]

    total = len(snippets)
    paginated = snippets[offset:offset + limit]

    return {
        "project_id": project_id,
        "total": total,
        "offset": offset,
        "limit": limit,
        "filters": {
            "subject": subject,
            "is_applicant": is_applicant,
            "evidence_type": evidence_type
        },
        "snippets": paginated
    }


# ==================== Merge Suggestion Endpoints ====================

@router.post("/{project_id}/merge-suggestions/generate")
async def generate_merge_suggestions(
    project_id: str,
    request: ExtractionRequest
):
    """
    生成实体合并建议
    """
    applicant_name = request.applicant_name
    provider = request.provider

    if not applicant_name:
        raise HTTPException(status_code=400, detail="applicant_name is required")

    try:
        suggestions = await suggest_entity_merges(
            project_id=project_id,
            applicant_name=applicant_name,
            provider=provider
        )

        return {
            "success": True,
            "suggestion_count": len(suggestions),
            "suggestions": suggestions
        }

    except Exception:
        raise


@router.get("/{project_id}/merge-suggestions")
async def get_merge_suggestions(project_id: str):
    """
    获取合并建议
    """
    suggestions = load_merge_suggestions(project_id)
    status = get_merge_status(project_id)

    return {
        "project_id": project_id,
        "suggestions": suggestions,
        "status": status
    }


@router.post("/{project_id}/merges/confirm")
async def confirm_merges(
    project_id: str,
    confirmations: List[MergeConfirmation]
):
    """
    确认/拒绝合并建议
    """
    updated = 0
    for conf in confirmations:
        if conf.status not in ["accepted", "rejected"]:
            raise HTTPException(status_code=400, detail=f"Invalid status: {conf.status}")

        if update_merge_suggestion_status(project_id, conf.suggestion_id, conf.status):
            updated += 1

    return {
        "success": True,
        "updated": updated
    }


@router.post("/{project_id}/merges/apply")
async def apply_merges(project_id: str):
    """
    应用已确认的合并
    """
    result = apply_entity_merges(project_id)

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Apply failed"))

    return result


