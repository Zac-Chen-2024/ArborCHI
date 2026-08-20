"""
Arguments Router - AI 论据组装 API

Endpoints:
- POST /api/arguments/{project_id}/generate - 一键生成论据
- GET /api/arguments/{project_id} - 获取生成的论据列表
- POST /api/arguments/{project_id}/recommend-snippets - 推荐 snippets
- POST /api/arguments/{project_id}/subarguments - 创建 SubArgument
- PUT /api/arguments/{project_id}/subarguments/{id} - 更新 SubArgument
- DELETE /api/arguments/{project_id}/subarguments/{id} - 删除 SubArgument
- POST /api/arguments/{project_id}/infer-relationship - 推断关系
"""

import copy
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.ids import validate_path_params
from app.core.jobs import manager as job_manager

from ..services.legal_argument_organizer import (
    full_legal_pipeline,
    regenerate_standard_pipeline,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/arguments", tags=["arguments"], dependencies=[Depends(validate_path_params)])


# ============================================
# Request/Response Models
# ============================================

class GenerateRequest(BaseModel):
    force_reanalyze: bool = False
    applicant_name: Optional[str] = None
    provider: str = "deepseek"  # LLM provider: "deepseek" or "openai"


class ArgumentResponse(BaseModel):
    id: str
    title: str
    subject: str
    snippet_ids: List[str]
    standard_key: str
    confidence: float
    created_at: str
    is_ai_generated: bool


class GenerateResponse(BaseModel):
    success: bool
    main_subject: Optional[str]
    argument_count: int
    arguments: List[ArgumentResponse]
    stats: Dict


# ============================================
# Generation Endpoints
# ============================================

async def _run_generate(project_id: str, request: GenerateRequest, job=None) -> dict:
    result = await full_legal_pipeline(
        project_id=project_id,
        applicant_name=request.applicant_name or "the applicant",
        provider=request.provider,
        job=job,
    )
    return GenerateResponse(
        success=True,
        main_subject=request.applicant_name,
        argument_count=result.get("stats", {}).get("argument_count", 0),
        arguments=result.get("arguments", []),
        stats=result.get("stats", {})
    ).model_dump()


@router.post("/{project_id}/generate", status_code=202)
async def generate_arguments(
    project_id: str,
    request: GenerateRequest = GenerateRequest()
):
    """
    一键生成论据 (LLM + 法律条例驱动) —— M10：异步 job

    Pipeline:
    1. LLM + 法律条例 → 组织子论点 (~7-8个，符合律师论证风格)
    2. LLM → 划分次级子论点 (每个2-4个 SubArguments)
    3. 智能过滤弱证据（如普通认证）

    立即返回 job 记录；轮询 GET /api/jobs/{id}，succeeded 时 result 是 GenerateResponse。
    """
    params = {"project_id": project_id, **request.model_dump()}
    return job_manager.submit("generate_arguments", project_id, params,
                              lambda job: _run_generate(project_id, request, job=job))


class RegenerateStandardRequest(BaseModel):
    standard_key: str
    applicant_name: Optional[str] = None
    provider: str = "deepseek"


@router.post("/{project_id}/regenerate-standard")
async def regenerate_standard(project_id: str, request: RegenerateStandardRequest):
    """
    按单个 standard 重新生成 Arguments + SubArguments。

    只替换该 standard_key 下的 arguments 和 sub_arguments，
    其余标准的数据保持不动。省去重跑全部标准的时间和 API credits。
    """
    result = await regenerate_standard_pipeline(
        project_id=project_id,
        standard_key=request.standard_key,
        applicant_name=request.applicant_name or "the applicant",
        provider=request.provider
    )

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))

    return result


# ============================================
# Arguments CRUD
# ============================================

@router.get("/{project_id}")
async def get_arguments(project_id: str):
    """
    获取生成的论据列表

    Returns:
        - arguments: 论据列表 (LLM + 法律条例生成的精华子论点)
        - sub_arguments: 次级子论点列表
        - main_subject: 识别的主体（申请人）
        - generated_at: 生成时间
        - stats: 统计信息
        - filtered: 过滤掉的弱证据
    """
    from ..services.snippet_recommender import load_legal_arguments
    legal_data = load_legal_arguments(project_id)

    if not legal_data.get("arguments"):
        return {
            "project_id": project_id,
            "arguments": [],
            "sub_arguments": [],
            "main_subject": None,
            "generated_at": None
        }

    return {
        "project_id": project_id,
        "arguments": legal_data.get("arguments", []),
        "sub_arguments": legal_data.get("sub_arguments", []),
        "main_subject": legal_data.get("main_subject"),
        "generated_at": legal_data.get("generated_at"),
        "stats": legal_data.get("stats", {}),
        "filtered": legal_data.get("filtered", []),
    }


# ============================================
# SubArgument Management Endpoints
# ============================================

from ..services.snippet_recommender import (
    consolidate_subarguments,
    create_subargument,
    get_assigned_snippet_ids,
    infer_relationship,
    merge_subarguments,
    recommend_snippets_for_subargument,
)


class SnippetRecommendRequest(BaseModel):
    """Snippet 推荐请求"""
    argument_id: str
    title: str
    description: Optional[str] = None
    exclude_snippet_ids: List[str] = []
    provider: str = "deepseek"


class RecommendedSnippet(BaseModel):
    """推荐的 Snippet"""
    snippet_id: str
    text: str
    exhibit_id: str
    page: int
    relevance_score: float
    reason: str


class SnippetRecommendResponse(BaseModel):
    """Snippet 推荐响应"""
    success: bool
    recommended_snippets: List[RecommendedSnippet]
    total_available: int


class CreateSubArgumentRequest(BaseModel):
    """创建 SubArgument 请求"""
    argument_id: str
    title: str
    purpose: str = ""
    relationship: str = ""
    snippet_ids: List[str] = []


class SubArgumentResponse(BaseModel):
    """SubArgument 响应"""
    id: str
    argument_id: str
    title: str
    purpose: str
    relationship: str
    snippet_ids: List[str]
    is_ai_generated: bool
    status: str
    created_at: str


@router.post("/{project_id}/recommend-snippets", response_model=SnippetRecommendResponse)
async def recommend_snippets(
    project_id: str,
    request: SnippetRecommendRequest
):
    """
    为新 SubArgument 推荐相关 Snippets

    使用 LLM 进行语义相关性排序，推荐最相关的 snippets。

    Args:
        project_id: 项目 ID
        request: 包含 argument_id, title, description 等信息

    Returns:
        推荐的 snippets 列表，包含 relevance_score 和 reason
    """
    try:
        # 获取已分配的 snippet IDs
        assigned_ids = get_assigned_snippet_ids(project_id)

        # 合并排除列表
        exclude_ids = list(set(request.exclude_snippet_ids) | assigned_ids)

        # 调用推荐服务
        recommended = await recommend_snippets_for_subargument(
            project_id=project_id,
            argument_id=request.argument_id,
            title=request.title,
            description=request.description,
            exclude_snippet_ids=exclude_ids,
            provider=request.provider
        )

        return SnippetRecommendResponse(
            success=True,
            recommended_snippets=[
                RecommendedSnippet(
                    snippet_id=s.get("snippet_id", ""),
                    text=s.get("text", ""),
                    exhibit_id=s.get("exhibit_id", ""),
                    page=s.get("page", 0),
                    relevance_score=s.get("relevance_score", 0.5),
                    reason=s.get("reason", "")
                )
                for s in recommended
            ],
            total_available=len(recommended)
        )

    except Exception:
        raise


class CreateArgumentRequest(BaseModel):
    """创建 Argument 请求"""
    standard_key: str
    title: str = ""


@router.post("/{project_id}/arguments")
async def create_argument_endpoint(
    project_id: str,
    request: CreateArgumentRequest
):
    """手动创建新的 Argument"""
    try:
        from ..services.snippet_recommender import create_argument
        result = create_argument(
            project_id=project_id,
            standard_key=request.standard_key,
            title=request.title,
        )
        return {"success": True, "argument": result}
    except Exception:
        raise


class MoveSubArgumentsRequest(BaseModel):
    """转移 SubArguments 请求"""
    subargument_ids: List[str]
    target_argument_id: str


@router.post("/{project_id}/subarguments/move")
async def move_subarguments_endpoint(
    project_id: str,
    request: MoveSubArgumentsRequest
):
    """将 SubArguments 转移到已有的 Argument 下"""
    try:
        from ..services.snippet_recommender import move_subarguments
        result = move_subarguments(
            project_id=project_id,
            subargument_ids=request.subargument_ids,
            target_argument_id=request.target_argument_id,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Move sub-arguments failed")
        raise


class MergeSubArgumentsRequest(BaseModel):
    """合并 SubArguments 请求"""
    subargument_ids: List[str]  # min 2
    merged_title: str
    merged_purpose: str = ""
    merged_relationship: str = ""


@router.post("/{project_id}/subarguments/merge")
async def merge_subarguments_endpoint(
    project_id: str,
    request: MergeSubArgumentsRequest
):
    """
    合并多个 SubArguments → 新建 Argument + SubArgument

    要求：
    - subargument_ids 至少 2 个
    - 所有 sub-args 必须属于同一个 standard（可跨 Argument）

    Returns:
        {success, new_argument, merged_subargument, deleted_subargument_ids, writing_changes}
    """
    try:
        result = merge_subarguments(
            project_id=project_id,
            subargument_ids=request.subargument_ids,
            merged_title=request.merged_title,
            merged_purpose=request.merged_purpose,
            merged_relationship=request.merged_relationship,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Merge sub-arguments failed")
        raise


class ConsolidateSubArgumentsRequest(BaseModel):
    """合并 SubArguments 为单个新 SubArgument"""
    subargument_ids: List[str]  # min 2
    target_argument_id: str
    provider: str = "deepseek"


@router.post("/{project_id}/subarguments/consolidate")
async def consolidate_subarguments_endpoint(
    project_id: str,
    request: ConsolidateSubArgumentsRequest
):
    """
    合并多个 SubArguments → 新的单个 SubArgument（同级合并）

    与 merge 不同：merge 创建新 Argument（升级），consolidate 保持同级。
    snippet_ids = 所有来源的并集，LLM 生成新 title/purpose/relationship。

    要求：
    - subargument_ids 至少 2 个
    - 所有 sub-args 必须属于同一个 standard（可跨 Argument）

    Returns:
        {success, new_subargument, deleted_subargument_ids}
    """
    try:
        result = await consolidate_subarguments(
            project_id=project_id,
            subargument_ids=request.subargument_ids,
            target_argument_id=request.target_argument_id,
            provider=request.provider,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Consolidate sub-arguments failed")
        raise


@router.post("/{project_id}/subarguments")
async def create_new_subargument(
    project_id: str,
    request: CreateSubArgumentRequest
):
    """
    创建新的 SubArgument

    将新的 SubArgument 添加到 legal_arguments.json，
    并更新父 Argument 的 sub_argument_ids。

    Args:
        project_id: 项目 ID
        request: 包含 argument_id, title, purpose, relationship, snippet_ids

    Returns:
        新创建的 SubArgument 对象
    """
    try:
        new_subarg = create_subargument(
            project_id=project_id,
            argument_id=request.argument_id,
            title=request.title,
            purpose=request.purpose,
            relationship=request.relationship,
            snippet_ids=request.snippet_ids
        )

        return {
            "success": True,
            "subargument": new_subarg
        }

    except Exception:
        raise


class InferRelationshipRequest(BaseModel):
    """推断 Relationship 请求"""
    argument_id: str
    subargument_title: str
    provider: str = "deepseek"


class UpdateSubArgumentRequest(BaseModel):
    """更新 SubArgument 请求"""
    title: Optional[str] = None
    purpose: Optional[str] = None
    relationship: Optional[str] = None
    snippet_ids: Optional[List[str]] = None
    pending_snippet_ids: Optional[List[str]] = None
    needs_snippet_confirmation: Optional[bool] = None
    status: Optional[str] = None


@router.put("/{project_id}/subarguments/{subargument_id}")
async def update_subargument(
    project_id: str,
    subargument_id: str,
    request: UpdateSubArgumentRequest
):
    """
    更新 SubArgument

    可更新字段:
    - title: 标题
    - purpose: 目的描述
    - relationship: 与父论点的关系
    - snippet_ids: 已确认的 snippet IDs
    - pending_snippet_ids: 待确认的 snippet IDs
    - needs_snippet_confirmation: 是否需要确认 snippets
    - status: 状态 (draft/verified)
    """
    from ..services.snippet_recommender import update_legal_arguments

    def _mutate(legal_args):
        sub_arguments = legal_args.get("sub_arguments", [])

        found = False
        for sub_arg in sub_arguments:
            if sub_arg.get("id") == subargument_id:
                if request.title is not None:
                    sub_arg["title"] = request.title
                if request.purpose is not None:
                    sub_arg["purpose"] = request.purpose
                if request.relationship is not None:
                    sub_arg["relationship"] = request.relationship
                if request.snippet_ids is not None:
                    sub_arg["snippet_ids"] = request.snippet_ids
                if request.pending_snippet_ids is not None:
                    sub_arg["pending_snippet_ids"] = request.pending_snippet_ids
                if request.needs_snippet_confirmation is not None:
                    sub_arg["needs_snippet_confirmation"] = request.needs_snippet_confirmation
                if request.status is not None:
                    sub_arg["status"] = request.status
                sub_arg["updated_at"] = datetime.now(timezone.utc).isoformat()
                found = True
                break

        if not found:
            raise HTTPException(status_code=404, detail=f"SubArgument not found: {subargument_id}")

        return legal_args

    update_legal_arguments(project_id, _mutate)

    return {
        "success": True,
        "subargument_id": subargument_id,
        "message": "SubArgument updated"
    }


@router.delete("/{project_id}/subarguments/{subargument_id}")
async def delete_subargument(
    project_id: str,
    subargument_id: str
):
    """
    删除 SubArgument

    同时从父 Argument 的 sub_argument_ids 中移除引用，
    并级联清理 writing_v3 文件中对应的句子。
    """
    logger.debug(f"DELETE SubArgument: project_id={project_id}, subargument_id={subargument_id}")

    from ..services.petition_writer_v3 import remove_subargument_from_writing
    from ..services.snippet_recommender import update_legal_arguments

    parent_standard_key = None
    sub_arguments = None
    def _mutate(legal_args):
        nonlocal parent_standard_key, sub_arguments
        sub_arguments = legal_args.get("sub_arguments", [])
        arguments = legal_args.get("arguments", [])

        logger.debug(f"DELETE SubArgument: before={len(sub_arguments)}")

        # Find and remove the SubArgument
        original_count = len(sub_arguments)
        sub_arguments = [sa for sa in sub_arguments if sa.get("id") != subargument_id]

        if len(sub_arguments) == original_count:
            logger.warning(f"DELETE SubArgument: not found {subargument_id}")
            raise HTTPException(status_code=404, detail=f"SubArgument not found: {subargument_id}")

        legal_args["sub_arguments"] = sub_arguments

        # Find parent Argument's standard_key before removing reference
        parent_standard_key = None
        for arg in arguments:
            if "sub_argument_ids" in arg and subargument_id in arg["sub_argument_ids"]:
                parent_standard_key = arg.get("standard_key")
                arg["sub_argument_ids"].remove(subargument_id)

        return legal_args

    update_legal_arguments(project_id, _mutate)
    logger.debug(f"DELETE SubArgument: after={len(sub_arguments)}, saved")

    # Layer 1: Cascade - clean up writing_v3 files
    writing_changes = None
    if parent_standard_key:
        try:
            result = remove_subargument_from_writing(project_id, subargument_id, parent_standard_key)
            if result.get("changed"):
                writing_changes = {
                    "section": parent_standard_key,
                    "removed_indices": result["removed_indices"],
                    "remaining_sentence_count": len(result["new_sentences"])
                }
                logger.debug(f"DELETE SubArgument: cleaned writing_v3 for {parent_standard_key}, removed {len(result['removed_indices'])} sentences")
        except Exception as e:
            logger.warning(f"DELETE SubArgument: writing cascade failed: {e}")

    return {
        "success": True,
        "subargument_id": subargument_id,
        "message": "SubArgument deleted",
        "writing_changes": writing_changes
    }


@router.delete("/{project_id}/standards/{standard_key}")
async def remove_standard_endpoint(
    project_id: str,
    standard_key: str
):
    """
    移除一个 Standard 下的所有 Arguments、SubArguments，
    同时清理对应的 writing_v3 文件。
    """
    logger.debug(f"DELETE Standard: project_id={project_id}, standard_key={standard_key}")

    from ..services.snippet_recommender import remove_standard

    result = remove_standard(project_id, standard_key)

    logger.debug(
        f"DELETE Standard: removed {len(result['deleted_argument_ids'])} arguments, "
        f"{len(result['deleted_subargument_ids'])} sub-arguments, "
        f"{len(result['deleted_writing_files'])} writing files"
    )

    return result


class MoveToOverallMeritsRequest(BaseModel):
    level: str  # "standard" | "argument" | "subargument"
    target_id: str  # standard_key, argument_id, or subargument_id


@router.post("/{project_id}/move-to-overall-merits")
async def move_to_overall_merits(project_id: str, request: MoveToOverallMeritsRequest):
    """
    Move a Standard / Argument / SubArgument into the Overall Merits section.

    - standard level: all arguments under that standard_key are moved
    - argument level: single argument is moved
    - subargument level: single sub-argument is moved (creates/joins an OM argument)
    """
    import uuid as _uuid

    from ..services.snippet_recommender import update_legal_arguments

    if request.level not in ("standard", "argument", "subargument"):
        raise HTTPException(status_code=400, detail=f"Invalid level: {request.level}")

    moved_argument_ids = None
    moved_subargument_ids = None
    def _mutate(legal_args):
        nonlocal moved_argument_ids, moved_subargument_ids
        arguments = legal_args.get("arguments", [])
        sub_arguments = legal_args.get("sub_arguments", [])

        moved_argument_ids = []
        moved_subargument_ids = []

        if request.level == "standard":
            # Move all arguments under this standard_key
            standard_key = request.target_id
            if standard_key == "overall_merits":
                raise HTTPException(status_code=400, detail="Cannot move overall_merits into itself")
            for arg in arguments:
                if arg.get("standard_key") == standard_key:
                    arg["original_standard"] = arg.get("original_standard") or arg.get("standard_key")
                    arg["standard_key"] = "overall_merits"
                    if "standard" in arg:
                        arg["original_standard_field"] = arg.get("original_standard_field") or arg.get("standard")
                        arg["standard"] = "overall_merits"
                    moved_argument_ids.append(arg["id"])

        elif request.level == "argument":
            # Move single argument
            arg_id = request.target_id
            for arg in arguments:
                if arg.get("id") == arg_id:
                    if arg.get("standard_key") == "overall_merits":
                        raise HTTPException(status_code=400, detail="Argument is already in Overall Merits")
                    arg["original_standard"] = arg.get("original_standard") or arg.get("standard_key")
                    arg["standard_key"] = "overall_merits"
                    if "standard" in arg:
                        arg["original_standard_field"] = arg.get("original_standard_field") or arg.get("standard")
                        arg["standard"] = "overall_merits"
                    moved_argument_ids.append(arg["id"])
                    break
            else:
                raise HTTPException(status_code=404, detail=f"Argument not found: {arg_id}")

        elif request.level == "subargument":
            # Move single sub-argument into an overall_merits argument
            subarg_id = request.target_id
            target_subarg = None
            parent_arg = None
            for sa in sub_arguments:
                if sa.get("id") == subarg_id:
                    target_subarg = sa
                    break
            if not target_subarg:
                raise HTTPException(status_code=404, detail=f"SubArgument not found: {subarg_id}")

            # Find parent argument
            for arg in arguments:
                if subarg_id in arg.get("sub_argument_ids", []):
                    parent_arg = arg
                    break

            if parent_arg and parent_arg.get("standard_key") == "overall_merits":
                raise HTTPException(status_code=400, detail="SubArgument is already in Overall Merits")

            # Remove from parent argument's sub_argument_ids
            if parent_arg:
                parent_arg["sub_argument_ids"] = [
                    sid for sid in parent_arg.get("sub_argument_ids", [])
                    if sid != subarg_id
                ]

            # Find or create an overall_merits argument to house this sub-argument
            om_arg = None
            original_std = parent_arg.get("standard_key", "unknown") if parent_arg else "unknown"
            for arg in arguments:
                if arg.get("standard_key") == "overall_merits":
                    om_arg = arg
                    break

            if not om_arg:
                om_arg = {
                    "id": f"arg-om-{_uuid.uuid4().hex[:8]}",
                    "title": "Supplemental Evidence — Overall Merits",
                    "standard_key": "overall_merits",
                    "standard": "overall_merits",
                    "original_standard": "overall_merits",
                    "sub_argument_ids": [],
                    "snippet_ids": [],
                    "is_ai_generated": False,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                arguments.append(om_arg)

            om_arg["sub_argument_ids"].append(subarg_id)
            # Tag the sub-argument with its original standard for cross-reference
            target_subarg["original_standard"] = original_std
            moved_subargument_ids.append(subarg_id)

        legal_args["arguments"] = arguments
        legal_args["sub_arguments"] = sub_arguments
        return legal_args

    update_legal_arguments(project_id, _mutate)

    return {
        "success": True,
        "moved_argument_ids": moved_argument_ids,
        "moved_subargument_ids": moved_subargument_ids,
    }


@router.post("/{project_id}/infer-relationship")
async def infer_subargument_relationship(
    project_id: str,
    request: InferRelationshipRequest
):
    """
    根据子论点标题推断与父论点的关系

    使用 LLM 分析子论点标题与父论点的语义关系，
    返回最合适的 relationship 标签。

    Args:
        project_id: 项目 ID
        request: 包含 argument_id 和 subargument_title

    Returns:
        推断出的 relationship 字符串
    """
    try:
        relationship = await infer_relationship(
            project_id=project_id,
            argument_id=request.argument_id,
            subargument_title=request.subargument_title,
            provider=request.provider
        )

        return {
            "success": True,
            "relationship": relationship
        }

    except Exception:
        raise


class InferArgumentTitleRequest(BaseModel):
    """生成 Argument 标题请求"""
    argument_id: str
    provider: str = "deepseek"


@router.post("/{project_id}/infer-argument-title")
async def infer_argument_title_endpoint(
    project_id: str,
    request: InferArgumentTitleRequest
):
    """用 LLM 为 Argument 生成简洁标题"""
    try:
        from ..services.snippet_recommender import infer_argument_title
        title = await infer_argument_title(
            project_id=project_id,
            argument_id=request.argument_id,
            provider=request.provider
        )
        return {"success": True, "title": title}
    except Exception:
        raise


# ============================================
# Evidence coverage overview (M13)
# ============================================

@router.get("/{project_id}/coverage")
async def get_coverage(project_id: str):
    """Facts about evidence coverage: unassigned snippets, thin SubArguments,
    per-standard evidence-layer gaps. No scores, no recommendations."""
    from ..services.coverage import compute_coverage
    from ..services.petition_writer_v3 import _load_snippet_source
    from ..services.snippet_recommender import load_legal_arguments

    return {"success": True, "project_id": project_id,
            **compute_coverage(load_legal_arguments(project_id), _load_snippet_source(project_id))}



# ============================================
# Structural undo / redo (M13)
# ============================================

def _step_history(project_id: str, direction: str) -> Dict:
    from ..core.atomic_io import update_json
    from ..services import history
    from ..services.snippet_recommender import _legal_arguments_file

    outcome: Dict = {"applied": False}

    def _mutate(data):
        current = copy.deepcopy(data)
        entry = history.step(project_id, direction, current)
        if entry is None:
            return data
        outcome.update({
            "applied": True,
            "label": entry["label"],
            "seq": entry["seq"],
            "affected_standard_keys": history.affected_standards(current, entry["data"]),
        })
        return entry["data"]

    update_json(_legal_arguments_file(project_id), _mutate, default={"arguments": [], "sub_arguments": []})
    return {"success": True, "direction": direction, **outcome, **history.peek(project_id)}


@router.get("/{project_id}/history")
async def get_history(project_id: str):
    """What undo / redo would do next (labels + depths)."""
    from ..services import history
    return {"success": True, **history.peek(project_id)}


@router.post("/{project_id}/undo")
async def undo_last_change(project_id: str):
    """Restore the document as it was before the last structural change."""
    return _step_history(project_id, "undo")


@router.post("/{project_id}/redo")
async def redo_last_change(project_id: str):
    """Re-apply the last undone change."""
    return _step_history(project_id, "redo")
