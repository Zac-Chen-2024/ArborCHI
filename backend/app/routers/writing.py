"""
Writing Router - 写作 API

/api/write/v3 端点 - SubArgument 感知写作（完整溯源链）

(v2 endpoints were removed in M1: no live frontend caller, see Doc/03.)
"""

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.ids import validate_path_params
from app.core.jobs import manager as job_manager
from app.services.petition_writer_v3 import (
    analyze_change_impact,
    load_latest_writing_v3,
    save_writing_v3,
    write_petition_section_v3,
)
from app.services.storage import project_path

router = APIRouter(prefix="/api/write/v3", tags=["Writing V3"], dependencies=[Depends(validate_path_params)])


class WriteV3Request(BaseModel):
    """V3 写作请求"""
    provider: str = "deepseek"
    argument_ids: Optional[List[str]] = None  # 可选，指定要生成的 Argument IDs
    subargument_ids: Optional[List[str]] = None  # 可选，指定要生成的 SubArgument IDs（用于局部重新生成）
    style: str = "legal"
    additional_instructions: Optional[str] = None
    exploration_writing: bool = False  # ON: backfill uses global registry + syncs new snippets to subarguments


class SentenceWithProvenanceV3(BaseModel):
    """带完整溯源的句子"""
    text: str
    snippet_ids: List[str]
    subargument_id: Optional[str] = None
    argument_id: Optional[str] = None
    exhibit_refs: List[str] = []
    sentence_type: str = "body"  # opening, body, closing


class ProvenanceIndex(BaseModel):
    """溯源索引"""
    by_subargument: Dict[str, List[int]] = {}
    by_argument: Dict[str, List[int]] = {}
    by_snippet: Dict[str, List[int]] = {}


class ValidationResult(BaseModel):
    """验证结果"""
    total_sentences: int
    traced_sentences: int
    warnings: List[str] = []


class WriteV3Response(BaseModel):
    """V3 写作响应"""
    success: bool
    section: str
    paragraph_text: str
    sentences: List[SentenceWithProvenanceV3]
    provenance_index: ProvenanceIndex
    validation: ValidationResult
    error: Optional[str] = None
    updated_subargument_snippets: Optional[Dict[str, List[str]]] = None


@router.get("/{project_id}/sections")
async def get_all_v3_sections(project_id: str):
    """
    获取所有已保存的 V3 写作章节（每个 standard_key 取最新版本）

    Returns:
        sections: [{section, paragraph_text, sentences, provenance_index, ...}]
    """
    try:
        # Dynamically discover standard_keys from saved writing_v3 files
        writing_dir = project_path(project_id, "writing_v3")
        standard_keys = set()
        if writing_dir.exists():
            for f in writing_dir.glob("*.json"):
                # Extract standard_key from filename pattern: writing_{key}_{version}.json
                parts = f.stem.split("_", 1)  # split off "writing" prefix
                if len(parts) >= 2:
                    # Remove version suffix: e.g. "membership_20240101_120000" -> "membership"
                    rest = parts[1]
                    # Version is last two _-separated parts (date_time)
                    rest_parts = rest.rsplit("_", 2)
                    if len(rest_parts) >= 3:
                        key = rest_parts[0]
                    else:
                        key = rest
                    standard_keys.add(key)

        sections = []
        seen = set()
        for key in sorted(standard_keys):
            result = load_latest_writing_v3(project_id, key)
            if result and key not in seen:
                seen.add(key)
                sections.append({
                    "section": result.get("section", key),
                    "paragraph_text": result.get("paragraph_text", ""),
                    "sentences": result.get("sentences", []),
                    "provenance_index": result.get("provenance_index"),
                    "validation": result.get("validation"),
                    "version_id": result.get("version_id"),
                    "timestamp": result.get("timestamp"),
                })

        return {
            "success": True,
            "project_id": project_id,
            "sections": sections,
            "section_count": len(sections),
        }

    except Exception:
        raise


async def _run_write_v3(project_id: str, standard_key: str, req: "WriteV3Request", job=None) -> dict:
    """The generation pipeline + persistence, shared by the job runner and tests."""
    result = await write_petition_section_v3(
        project_id=project_id,
        standard_key=standard_key,
        argument_ids=req.argument_ids,
        subargument_ids=req.subargument_ids,
        additional_instructions=req.additional_instructions,
        provider=req.provider,
        exploration_writing=req.exploration_writing,
        job=job,
    )

    if not result.get("success"):
        return WriteV3Response(
            success=False,
            section=standard_key,
            paragraph_text="",
            sentences=[],
            provenance_index=ProvenanceIndex(),
            validation=ValidationResult(total_sentences=0, traced_sentences=0),
            error=result.get("error", "Unknown error")
        ).model_dump()

    if req.subargument_ids:
        # Partial regeneration: only the requested SubArguments' sentences.
        # Persisted for audit, but never served as "the section" (see
        # load_latest_writing_v3). The full spliced section is written by the
        # client through PUT .../sentences on accept.
        result["partial"] = True
        result["subargument_ids"] = list(req.subargument_ids)
    save_writing_v3(project_id, standard_key, result)

    return WriteV3Response(
        success=True,
        section=result["section"],
        paragraph_text=result["paragraph_text"],
        sentences=[SentenceWithProvenanceV3(**s) for s in result["sentences"]],
        provenance_index=ProvenanceIndex(**result.get("provenance_index", {})),
        validation=ValidationResult(**result.get("validation", {})),
        updated_subargument_snippets=result.get("updated_subargument_snippets")
    ).model_dump()


@router.post("/{project_id}/{standard_key}", status_code=202)
async def write_petition_v3(
    project_id: str,
    standard_key: str,
    request: WriteV3Request = None
):
    """
    V3 写作端点 - SubArgument 感知的写作（M10：异步 job）

    立即返回 job 记录 `{id, status, ...}`；轮询 GET /api/jobs/{id}，
    `status == "succeeded"` 时 `result` 是原来的 WriteV3Response。
    相同请求体在已有 running job 时返回同一个 job（幂等）。
    """
    req = request or WriteV3Request()
    params = {"project_id": project_id, "standard_key": standard_key, **req.model_dump()}
    return job_manager.submit(
        "write_v3", project_id, params,
        lambda job: _run_write_v3(project_id, standard_key, req, job=job),
    )


class PutSentencesRequest(BaseModel):
    """Client-side edited/accepted section (M13 diff view accept / revert)."""
    sentences: List[SentenceWithProvenanceV3]
    source: str = "user_commit"  # user_commit | user_revert | user_edit


@router.put("/{project_id}/{standard_key}/sentences")
async def put_section_sentences(project_id: str, standard_key: str, request: PutSentencesRequest):
    """
    Persist the section exactly as the user sees it (after accepting or
    reverting a regeneration, or after manual sentence edits) as a new full
    version. Rebuilds paragraph_text and provenance_index server-side.
    """
    from app.services.petition_writer_v3 import _build_provenance_from_sentences

    sentences = [s.model_dump() for s in request.sentences]
    paragraph_text = " ".join(s["text"] for s in sentences)
    result = {
        "success": True,
        "section": standard_key,
        "paragraph_text": paragraph_text,
        "sentences": sentences,
        "provenance_index": _build_provenance_from_sentences(sentences),
        "validation": {
            "total_sentences": len(sentences),
            "traced_sentences": sum(1 for s in sentences if s.get("snippet_ids") or s.get("subargument_id")),
            "warnings": [],
        },
        "source": request.source,
    }
    version_id = save_writing_v3(project_id, standard_key, result)
    return {"success": True, "version_id": version_id, "section": standard_key,
            "sentence_count": len(sentences)}


class AnalyzeImpactRequest(BaseModel):
    """分析变更影响请求"""
    standard_key: str
    change_type: str = "deletion"  # "deletion" | "addition"
    affected_subargument_id: str
    affected_title: str = ""


@router.post("/{project_id}/analyze-impact")
async def analyze_writing_impact(project_id: str, request: AnalyzeImpactRequest):
    """
    分析 SubArgument 变更对文章的间接影响。

    前端在 DELETE SubArgument 完成后调用此端点获取调整建议。
    """
    try:
        result = await analyze_change_impact(
            project_id=project_id,
            standard_key=request.standard_key,
            change_type=request.change_type,
            affected_subargument_id=request.affected_subargument_id,
            affected_title=request.affected_title,
        )
        return {
            "success": True,
            "suggestions": result.get("suggestions", [])
        }
    except Exception:
        raise


