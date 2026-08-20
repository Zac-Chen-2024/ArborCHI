"""
Snippet Recommender - 根据标题/描述为新 SubArgument 推荐相关 Snippets

策略：
1. 规则过滤：排除已分配的 Snippets，优先同 Argument 范围内的
2. LLM 精排：语义相关性评分
"""

import copy
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..core.atomic_io import read_json, update_json, write_json
from ..core.prompt_loader import body as _prompt_body
from ..core.prompt_loader import render as _prompt_render
from .llm_client import call_llm, call_llm_text
from .snippet_registry import load_registry
from .storage import project_path

logger = logging.getLogger(__name__)

# ==================== 数据加载 ====================

def _legal_arguments_file(project_id: str) -> Path:
    return project_path(project_id, "arguments", "legal_arguments.json")


_EMPTY_LEGAL_ARGS = {"arguments": [], "sub_arguments": []}


def load_legal_arguments(project_id: str) -> Dict:
    """加载 legal_arguments.json"""
    data = read_json(_legal_arguments_file(project_id))
    if data is None:
        return {"arguments": [], "sub_arguments": []}
    return data


def save_legal_arguments(project_id: str, data: Dict):
    """保存 legal_arguments.json（原子写）"""
    write_json(_legal_arguments_file(project_id), data)


def _op_label(mutator) -> str:
    """Undo label from the enclosing function name: 'merge_subarguments.<locals>._mutate' -> 'merge_subarguments'."""
    name = getattr(mutator, "__qualname__", "") or "change"
    return name.split(".<locals>")[0].split(".")[-1].lstrip("_") or "change"


def update_legal_arguments(project_id: str, mutator, label: Optional[str] = None, record: bool = True) -> Dict:
    """锁内 read → mutator(data) → write。所有读-改-写都应走这里，避免并发丢更新。

    Every write that changes the document is snapshotted onto the undo stack
    (M13; see services/history.py) unless ``record=False``.
    """
    from . import history

    def _wrapped(data):
        before = copy.deepcopy(data)
        result = mutator(data)
        if result is None:
            result = data
        if record and result != before:
            history.record_change(project_id, label or _op_label(mutator), before)
        return result

    return update_json(
        _legal_arguments_file(project_id),
        _wrapped,
        default={"arguments": [], "sub_arguments": []},
    )


def get_assigned_snippet_ids(project_id: str) -> Set[str]:
    """获取已分配给 SubArguments 的所有 snippet_ids"""
    legal_args = load_legal_arguments(project_id)
    assigned = set()

    for sub_arg in legal_args.get("sub_arguments", []):
        for snippet_id in sub_arg.get("snippet_ids", []):
            assigned.add(snippet_id)

    return assigned


def remove_standard(project_id: str, standard_key: str) -> Dict:
    """移除一个 Standard 下的所有 Arguments 和 SubArguments，清理 writing_v3 文件"""

    matched_arg_ids = None
    matched_subarg_ids = None
    def _mutate(legal_args):
        nonlocal matched_arg_ids, matched_subarg_ids
        arguments = legal_args.get("arguments", [])
        sub_arguments = legal_args.get("sub_arguments", [])

        # Find arguments belonging to this standard
        matched_arg_ids = set()
        matched_subarg_ids = set()
        for arg in arguments:
            if arg.get("standard_key") == standard_key:
                matched_arg_ids.add(arg["id"])
                for sa_id in arg.get("sub_argument_ids", []):
                    matched_subarg_ids.add(sa_id)

        # Also collect sub_arguments whose argument_id matches
        for sa in sub_arguments:
            if sa.get("argument_id") in matched_arg_ids:
                matched_subarg_ids.add(sa["id"])

        # Filter out
        legal_args["arguments"] = [a for a in arguments if a["id"] not in matched_arg_ids]
        legal_args["sub_arguments"] = [sa for sa in sub_arguments if sa["id"] not in matched_subarg_ids]

        return legal_args

    update_legal_arguments(project_id, _mutate)

    # Delete writing_v3 files for this standard
    writing_dir = project_path(project_id, "writing_v3")
    deleted_files = []
    if writing_dir.exists():
        for f in writing_dir.glob(f"writing_{standard_key}_*.json"):
            f.unlink()
            deleted_files.append(f.name)

    return {
        "success": True,
        "deleted_argument_ids": list(matched_arg_ids),
        "deleted_subargument_ids": list(matched_subarg_ids),
        "deleted_writing_files": deleted_files,
    }


def get_argument_snippet_ids(project_id: str, argument_id: str) -> Set[str]:
    """获取某个 Argument 下的所有 snippet_ids（父论点范围）"""
    legal_args = load_legal_arguments(project_id)

    for arg in legal_args.get("arguments", []):
        if arg.get("id") == argument_id:
            return set(arg.get("snippet_ids", []))

    return set()


def get_argument_info(project_id: str, argument_id: str) -> Optional[Dict]:
    """获取 Argument 信息"""
    legal_args = load_legal_arguments(project_id)

    for arg in legal_args.get("arguments", []):
        if arg.get("id") == argument_id:
            return arg

    return None


# ==================== 推荐核心逻辑 ====================

async def recommend_snippets_for_subargument(
    project_id: str,
    argument_id: str,
    title: str,
    description: str = None,
    exclude_snippet_ids: List[str] = None,
    max_candidates: int = 20,
    max_results: int = 5,
    provider: str = "deepseek"
) -> List[Dict]:
    """
    为新 SubArgument 推荐相关 Snippets

    Args:
        project_id: 项目 ID
        argument_id: 父 Argument ID
        title: 新 SubArgument 的标题
        description: 可选的描述
        exclude_snippet_ids: 要排除的 snippet IDs（如已在其他 SubArgument 中）
        max_candidates: 发送给 LLM 的最大候选数
        max_results: 返回的最大推荐数

    Returns:
        推荐的 snippets 列表，每个包含：
        - snippet_id
        - text
        - exhibit_id
        - page
        - relevance_score (0-1)
        - reason (推荐理由)
    """
    # 1. 加载所有 snippets
    all_snippets = load_registry(project_id)
    if not all_snippets:
        return []

    # 2. 获取已分配的 snippet_ids
    assigned_ids = get_assigned_snippet_ids(project_id)
    exclude_set = set(exclude_snippet_ids or []) | assigned_ids

    # 3. 获取父 Argument 的 snippet 范围（优先推荐这些）
    parent_snippet_ids = get_argument_snippet_ids(project_id, argument_id)

    # 4. 获取 Argument 信息（用于 LLM 上下文）
    argument_info = get_argument_info(project_id, argument_id)
    standard_key = argument_info.get("standard_key", "") if argument_info else ""
    argument_title = argument_info.get("title", "") if argument_info else ""

    # 5. 筛选候选集
    # 策略：优先父 Argument 范围内未分配的，其次是其他未分配的
    priority_candidates = []
    other_candidates = []

    for snip in all_snippets:
        snippet_id = snip.get("snippet_id")
        if snippet_id in exclude_set:
            continue

        if snippet_id in parent_snippet_ids:
            priority_candidates.append(snip)
        else:
            other_candidates.append(snip)

    # 合并候选集，优先级高的在前
    candidates = priority_candidates + other_candidates

    # 限制候选数量
    if len(candidates) > max_candidates:
        candidates = candidates[:max_candidates]

    if not candidates:
        return []

    # 6. 调用 LLM 精排
    ranked_snippets = await llm_rank_snippets(
        title=title,
        description=description,
        standard_key=standard_key,
        argument_title=argument_title,
        candidates=candidates,
        max_results=max_results,
        provider=provider
    )

    return ranked_snippets


async def llm_rank_snippets(
    title: str,
    description: str,
    standard_key: str,
    argument_title: str,
    candidates: List[Dict],
    max_results: int = 5,
    provider: str = "deepseek"
) -> List[Dict]:
    """
    使用 LLM 对候选 Snippets 进行语义相关性排序

    Returns:
        排序后的 snippets 列表，包含 relevance_score 和 reason
    """
    # 构建候选列表文本
    snippets_formatted = []
    snippet_map = {}  # 用于快速查找

    for i, snip in enumerate(candidates):
        snippet_id = snip.get("snippet_id")
        text = snip.get("text", "")[:300]  # 截取前300字符
        exhibit_id = snip.get("exhibit_id", "")
        page = snip.get("page", 0)

        snippets_formatted.append(
            f"[{i+1}] ID: {snippet_id}\n"
            f"    Source: Exhibit {exhibit_id}, Page {page}\n"
            f"    Text: {text}"
        )
        snippet_map[snippet_id] = snip

    system_prompt = _prompt_body("recommender/llm_rank_snippets_system_prompt")

    user_prompt = _prompt_render("recommender/llm_rank_snippets_user_prompt",
        standard_key=standard_key,
        argument_title=argument_title,
        title=title,
        description_or_n_a=description or 'N/A',
        chr_10_join_snippets_formatted=chr(10).join(snippets_formatted),
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=1500,
            provider=provider
        )

        ranked = result.get("ranked_snippets", [])

        # 填充完整信息
        enriched_results = []
        for item in ranked[:max_results]:
            snippet_id = item.get("snippet_id")
            if snippet_id in snippet_map:
                snip = snippet_map[snippet_id]
                enriched_results.append({
                    "snippet_id": snippet_id,
                    "text": snip.get("text", ""),
                    "exhibit_id": snip.get("exhibit_id", ""),
                    "page": snip.get("page", 0),
                    "bbox": snip.get("bbox"),
                    "relevance_score": item.get("relevance_score", 0.5),
                    "reason": item.get("reason", "")
                })

        return enriched_results

    except Exception as e:
        logger.warning(f"LLM ranking failed: {e}")
        # 降级：返回前 N 个候选（无排序）
        return [
            {
                "snippet_id": snip.get("snippet_id"),
                "text": snip.get("text", ""),
                "exhibit_id": snip.get("exhibit_id", ""),
                "page": snip.get("page", 0),
                "bbox": snip.get("bbox"),
                "relevance_score": 0.5,
                "reason": "Fallback recommendation (LLM unavailable)"
            }
            for snip in candidates[:max_results]
        ]


# ==================== Argument 创建 ====================

def create_argument(
    project_id: str,
    standard_key: str,
    title: str = "",
) -> Dict:
    """手动创建 Argument 并持久化到 legal_arguments.json"""
    import uuid

    new_arg = None
    def _mutate(legal_args):
        nonlocal new_arg

        new_arg = {
            "id": f"arg-{uuid.uuid4().hex[:8]}",
            "standard": standard_key,
            "standard_key": standard_key,
            "title": title,
            "rationale": "",
            "snippet_ids": [],
            "evidence_strength": "moderate",
            "sub_argument_ids": [],
            "subject": "",
            "confidence": 0.5,
            "is_ai_generated": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        legal_args.setdefault("arguments", []).append(new_arg)
        return legal_args

    update_legal_arguments(project_id, _mutate)

    return new_arg


# ==================== SubArgument 创建 ====================

def create_subargument(
    project_id: str,
    argument_id: str,
    title: str,
    purpose: str,
    relationship: str,
    snippet_ids: List[str]
) -> Dict:
    """
    创建新的 SubArgument 并持久化

    Returns:
        新创建的 SubArgument 对象
    """
    import uuid

    # 加载现有数据
    new_subarg = None
    def _mutate(legal_args):
        nonlocal new_subarg

        # 生成新 SubArgument
        new_subarg = {
            "id": f"subarg-{uuid.uuid4().hex[:8]}",
            "argument_id": argument_id,
            "title": title,
            "purpose": purpose,
            "relationship": relationship,
            "snippet_ids": snippet_ids,
            "is_ai_generated": False,  # 用户手动创建
            "status": "draft",
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # 添加到 sub_arguments 列表
        if "sub_arguments" not in legal_args:
            legal_args["sub_arguments"] = []
        legal_args["sub_arguments"].append(new_subarg)

        # 更新父 Argument 的 sub_argument_ids
        for arg in legal_args.get("arguments", []):
            if arg["id"] == argument_id:
                if "sub_argument_ids" not in arg:
                    arg["sub_argument_ids"] = []
                arg["sub_argument_ids"].append(new_subarg["id"])
                break

        # 保存
        return legal_args

    update_legal_arguments(project_id, _mutate)

    return new_subarg


# ==================== SubArgument 合并 ====================

def merge_subarguments(
    project_id: str,
    subargument_ids: List[str],
    merged_title: str,
    merged_purpose: str = "",
    merged_relationship: str = "",
) -> Dict:
    """
    将多个 SubArguments 归组到一个新 Argument 下

    不删除、不合并 sub-args，只是移动它们到新的 parent Argument。

    约束：
    1. subargument_ids >= 2
    2. 所有 sub-args 必须属于同一个 standard_key（可跨 Argument）

    流程：
    - 创建新 Argument（standard_key 同源）
    - 把选中的 sub-args 的 argument_id 改为新 Argument
    - 从旧 parent arguments 的 sub_argument_ids 中移除
    - 新 Argument 的 snippet_ids = 所有 sub-args 的 snippet_ids 并集

    Returns:
        {
          "success": True,
          "new_argument": {...},
          "moved_subargument_ids": [...],
        }
    """
    import uuid

    if len(subargument_ids) < 2:
        raise ValueError("At least 2 sub-arguments are required for merging")

    # 加载数据
    new_arg = None
    def _mutate(legal_args):
        nonlocal new_arg
        sub_arguments = legal_args.get("sub_arguments", [])
        arguments = legal_args.get("arguments", [])

        # 找到所有源 sub-args
        source_subargs = []
        for sa_id in subargument_ids:
            found = next((sa for sa in sub_arguments if sa.get("id") == sa_id), None)
            if not found:
                raise ValueError(f"SubArgument not found: {sa_id}")
            source_subargs.append(found)

        # 收集涉及的 argument_ids → 找到 standard_key
        old_argument_ids = set(sa.get("argument_id") for sa in source_subargs)
        arg_map = {a["id"]: a for a in arguments}

        standard_keys = set()
        for aid in old_argument_ids:
            arg = arg_map.get(aid)
            if arg:
                standard_keys.add(arg.get("standard_key"))

        if len(standard_keys) != 1:
            raise ValueError("All sub-arguments must belong to the same standard")
        standard_key = standard_keys.pop()

        # 获取 subject（从第一个 argument 拿）
        first_arg = arg_map.get(next(iter(old_argument_ids)))
        subject = first_arg.get("subject", "") if first_arg else ""

        # 收集所有 snippet_ids（去重，保持顺序）
        seen: Set[str] = set()
        all_snippet_ids: List[str] = []
        for sa in source_subargs:
            for snip_id in sa.get("snippet_ids", []):
                if snip_id not in seen:
                    seen.add(snip_id)
                    all_snippet_ids.append(snip_id)

        now_str = datetime.now(timezone.utc).isoformat()

        # 创建新 Argument
        new_arg = {
            "id": f"arg-{uuid.uuid4().hex[:8]}",
            "standard": standard_key,
            "standard_key": standard_key,
            "title": merged_title,
            "rationale": merged_purpose or f"Grouped from {len(subargument_ids)} sub-arguments",
            "snippet_ids": all_snippet_ids,
            "evidence_strength": "moderate",
            "sub_argument_ids": list(subargument_ids),
            "subject": subject,
            "confidence": 0.8,
            "is_ai_generated": False,
            "created_at": now_str,
        }

        # 移动 sub-args: 更新 argument_id
        moved_set = set(subargument_ids)
        for sa in sub_arguments:
            if sa["id"] in moved_set:
                sa["argument_id"] = new_arg["id"]

        # 从旧 parent arguments 的 sub_argument_ids 中移除
        for arg in arguments:
            if arg["id"] in old_argument_ids:
                old_ids = arg.get("sub_argument_ids", [])
                arg["sub_argument_ids"] = [sid for sid in old_ids if sid not in moved_set]

        # 添加新 Argument
        legal_args["arguments"].append(new_arg)

        # 保存
        return legal_args

    update_legal_arguments(project_id, _mutate)

    return {
        "success": True,
        "new_argument": new_arg,
        "moved_subargument_ids": subargument_ids,
    }


# ==================== SubArgument 转移 ====================

def move_subarguments(
    project_id: str,
    subargument_ids: List[str],
    target_argument_id: str,
) -> Dict:
    """
    将 SubArguments 转移到已有的 target Argument 下

    约束：
    1. target argument 必须存在
    2. 所有 sub-args 必须与 target 属于同一个 standard_key
    """
    def _mutate(legal_args):
        sub_arguments = legal_args.get("sub_arguments", [])
        arguments = legal_args.get("arguments", [])
        arg_map = {a["id"]: a for a in arguments}

        # 验证 target argument 存在
        target_arg = arg_map.get(target_argument_id)
        if not target_arg:
            raise ValueError(f"Target argument not found: {target_argument_id}")

        target_standard = target_arg.get("standard_key")

        # 找到所有源 sub-args 并验证 standard_key
        moved_set = set(subargument_ids)
        old_argument_ids: Set[str] = set()
        for sa in sub_arguments:
            if sa["id"] in moved_set:
                parent = arg_map.get(sa.get("argument_id"))
                if parent and parent.get("standard_key") != target_standard:
                    raise ValueError(
                        f"SubArgument {sa['id']} belongs to standard "
                        f"'{parent.get('standard_key')}', cannot move to '{target_standard}'"
                    )
                old_argument_ids.add(sa.get("argument_id", ""))

        # 更新 sub-args 的 argument_id
        for sa in sub_arguments:
            if sa["id"] in moved_set:
                sa["argument_id"] = target_argument_id

        # 从旧 parent arguments 移除
        for arg in arguments:
            if arg["id"] in old_argument_ids:
                old_ids = arg.get("sub_argument_ids", [])
                arg["sub_argument_ids"] = [sid for sid in old_ids if sid not in moved_set]

        # 添加到 target argument
        existing_ids = set(target_arg.get("sub_argument_ids", []))
        target_arg.setdefault("sub_argument_ids", [])
        for sid in subargument_ids:
            if sid not in existing_ids:
                target_arg["sub_argument_ids"].append(sid)

        return legal_args

    update_legal_arguments(project_id, _mutate)

    return {
        "success": True,
        "moved_subargument_ids": subargument_ids,
        "target_argument_id": target_argument_id,
    }


# ==================== Relationship 推断 ====================

async def infer_relationship(
    project_id: str,
    argument_id: str,
    subargument_title: str,
    provider: str = "deepseek"
) -> str:
    """
    根据子论点标题推断与父论点的关系

    与 subargument_generator.py 保持一致，由 LLM 自由生成 2-5 个词的关系描述

    Returns:
        relationship 字符串（如 "Proves leadership role", "Quantifies contributions" 等）
    """
    # 获取父 Argument 信息
    argument_info = get_argument_info(project_id, argument_id)
    if not argument_info:
        return "Supports main argument"  # 默认

    argument_title = argument_info.get("title", "")
    standard_key = argument_info.get("standard_key", "")

    # 与 subargument_generator.py 的 prompt 风格保持一致
    system_prompt = _prompt_body("recommender/infer_relationship_system_prompt")

    user_prompt = f"""Standard: {standard_key}
Main Argument: {argument_title}
Sub-Argument Title: {subargument_title}

What is the relationship? (2-5 words)"""

    try:
        result = await call_llm_text(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.2,
            max_tokens=30,
            provider=provider
        )

        # 清理：移除引号和多余空格
        relationship = result.strip().strip('"\'').strip()

        # 如果为空或太长，使用默认值
        if not relationship or len(relationship) > 50:
            relationship = "Supports main argument"

        return relationship

    except Exception as e:
        logger.warning(f"Infer relationship failed: {e}")
        return "Supports main argument"  # 降级默认值


async def consolidate_subarguments(
    project_id: str,
    subargument_ids: List[str],
    target_argument_id: str,
    provider: str = "deepseek"
) -> Dict:
    """
    将多个 SubArguments 合并为一个新的 SubArgument（同级合并）

    与 merge 不同：merge 创建新 Argument（升级），consolidate 创建新 SubArgument（同级）。

    约束：
    1. subargument_ids >= 2
    2. 所有 sub-args 必须属于同一个 standard_key

    流程：
    - 验证所有 sub-args 存在且同 standard
    - 收集 snippet_ids（去重保序）
    - LLM 生成新 title / purpose / relationship
    - 创建新 SubArgument 挂到 target_argument_id
    - 删除原 sub-args
    """

    if len(subargument_ids) < 2:
        raise ValueError("At least 2 sub-arguments are required for consolidation")

    legal_args = load_legal_arguments(project_id)
    sub_arguments = legal_args.get("sub_arguments", [])
    arguments = legal_args.get("arguments", [])
    arg_map = {a["id"]: a for a in arguments}

    # Validate target argument exists
    target_arg = arg_map.get(target_argument_id)
    if not target_arg:
        raise ValueError(f"Target argument not found: {target_argument_id}")

    target_standard = target_arg.get("standard_key")

    # Find all source sub-args
    source_subargs = []
    for sa_id in subargument_ids:
        found = next((sa for sa in sub_arguments if sa.get("id") == sa_id), None)
        if not found:
            raise ValueError(f"SubArgument not found: {sa_id}")
        source_subargs.append(found)

    # Validate same standard_key
    for sa in source_subargs:
        parent = arg_map.get(sa.get("argument_id"))
        if parent and parent.get("standard_key") != target_standard:
            raise ValueError(
                f"SubArgument {sa['id']} belongs to standard "
                f"'{parent.get('standard_key')}', cannot consolidate into '{target_standard}'"
            )

    # Collect snippet_ids (deduplicated, order-preserving)
    seen: Set[str] = set()
    all_snippet_ids: List[str] = []
    for sa in source_subargs:
        for snip_id in sa.get("snippet_ids", []):
            if snip_id not in seen:
                seen.add(snip_id)
                all_snippet_ids.append(snip_id)

    # LLM: generate new title, purpose, relationship
    source_info = "\n".join(
        f"- Title: {sa.get('title', '')}\n  Purpose: {sa.get('purpose', '')}"
        for sa in source_subargs
    )
    target_title = target_arg.get("title", "")

    system_prompt = _prompt_body("recommender/consolidate_subarguments_system_prompt")

    user_prompt = _prompt_render("recommender/consolidate_subarguments_user_prompt",
        target_standard=target_standard,
        target_title=target_title,
        source_info=source_info,
    )

    try:
        result = await call_llm(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.3,
            max_tokens=200,
            provider=provider
        )
        new_title = result.get("title", "Consolidated sub-argument")
        new_purpose = result.get("purpose", "")
        new_relationship = result.get("relationship", "Combined evidence")
    except Exception as e:
        logger.warning(f"LLM consolidation failed: {e}")
        # Fallback: use title from the sub-arg with most snippets
        best = max(source_subargs, key=lambda sa: len(sa.get("snippet_ids", [])))
        new_title = best.get("title", "Consolidated sub-argument")
        purposes = [sa.get("purpose", "").strip() for sa in source_subargs if sa.get("purpose", "").strip()]
        new_purpose = "; ".join(dict.fromkeys(purposes))  # deduplicate while preserving order
        new_relationship = best.get("relationship", "Combined evidence")

    # Create new SubArgument (reuse existing helper for persistence)
    new_subarg = create_subargument(
        project_id=project_id,
        argument_id=target_argument_id,
        title=new_title,
        purpose=new_purpose,
        relationship=new_relationship,
        snippet_ids=all_snippet_ids,
    )

    # Delete original sub-args: reload (create_subargument saved), then remove
    def _mutate(legal_args):
        sub_arguments = legal_args.get("sub_arguments", [])
        arguments = legal_args.get("arguments", [])

        delete_set = set(subargument_ids)

        # Remove from sub_arguments list
        legal_args["sub_arguments"] = [sa for sa in sub_arguments if sa["id"] not in delete_set]

        # Remove from parent arguments' sub_argument_ids
        for arg in arguments:
            old_ids = arg.get("sub_argument_ids", [])
            if any(sid in delete_set for sid in old_ids):
                arg["sub_argument_ids"] = [sid for sid in old_ids if sid not in delete_set]

        return legal_args

    update_legal_arguments(project_id, _mutate)

    return {
        "success": True,
        "new_subargument": new_subarg,
        "deleted_subargument_ids": subargument_ids,
    }


async def infer_argument_title(
    project_id: str,
    argument_id: str,
    provider: str = "deepseek"
) -> str:
    """
    根据 Argument 下的 SubArguments 信息，用 LLM 生成简洁的 Argument 标题

    Returns:
        5-15 词的英文标题
    """
    legal_args = load_legal_arguments(project_id)
    arguments = legal_args.get("arguments", [])
    sub_arguments = legal_args.get("sub_arguments", [])

    # 找到目标 argument
    arg = next((a for a in arguments if a.get("id") == argument_id), None)
    if not arg:
        return "Untitled Argument"

    standard_key = arg.get("standard_key", "")
    current_title = arg.get("title", "")

    # 收集子论点标题
    child_ids = set(arg.get("sub_argument_ids", []))
    child_titles = [
        sa.get("title", "")
        for sa in sub_arguments
        if sa.get("id") in child_ids and sa.get("title")
    ]

    system_prompt = _prompt_body("recommender/infer_argument_title_system_prompt")

    child_info = "\n".join(f"- {t}" for t in child_titles) if child_titles else "(no sub-arguments yet)"

    user_prompt = _prompt_render("recommender/infer_argument_title_user_prompt",
        standard_key=standard_key,
        current_title_or_none=current_title or '(none)',
        child_info=child_info,
    )

    try:
        result = await call_llm_text(
            prompt=user_prompt,
            system_prompt=system_prompt,
            temperature=0.3,
            max_tokens=50,
            provider=provider
        )
        title = result.strip().strip('"\'').strip()
        if not title or len(title) > 100:
            return current_title or "Untitled Argument"
        return title
    except Exception as e:
        logger.warning(f"Infer argument title failed: {e}")
        return current_title or "Untitled Argument"
