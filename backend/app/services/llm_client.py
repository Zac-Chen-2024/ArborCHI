"""
LLM Client - 统一的 LLM API 客户端 (Doc/01 M9, plan 1.2)

Public API is unchanged from the original module:

    await call_llm(prompt, system_prompt=None, json_schema=None, ...)  -> Dict
    await call_llm_text(prompt, system_prompt=None, ...)              -> str
    extract_json(text) -> Dict | list

Behind it:
    * provider registry  (llm_providers: deepseek / openai / anthropic)
    * retry              (tenacity: 429 / 5xx / timeout / connection, 3 attempts,
                          exponential backoff with jitter; 4xx never retried)
    * tracing            (one JSONL line per call in data/traces/{date}.jsonl:
                          ts, caller, provider, model, prompt_id, prompt_version,
                          prompt_hash, tokens_in/out, latency_ms, cost_est,
                          cache_hit, attempts, status, error, workspace)
    * content cache      (data/llm_cache/{sha256}.json, key = provider + model +
                          params + messages; env LLM_CACHE_ENABLED)

`caller` defaults to "<module>.<function>" of the calling frame so the 23
existing call sites get a useful label without edits; pass caller= to override.
prompt_id / version / hash are read from a RenderedPrompt (M8) when the prompt
argument is one.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from ..core.atomic_io import append_jsonl, read_json, write_json
from ..core.config import settings
from ..core.errors import ConfigError
from ..core.workspace import current_workspace
from .llm_providers import (
    DEFAULT_MODELS,
    LLMRequest,
    RetryableError,
    close_clients,
    estimate_cost,
    get_provider,
)

logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_TOKENS = 16000
DEFAULT_TEMPERATURE = 0.1

RETRY_ATTEMPTS = 3

__all__ = [
    "call_llm", "call_llm_text", "extract_json", "test_connection",
    "DEFAULT_MODELS", "DEFAULT_TIMEOUT", "DEFAULT_MAX_TOKENS", "DEFAULT_TEMPERATURE",
    "close_clients",
]


# ---------------------------------------------------------------------------
# helpers: caller label, prompt metadata, cache key, trace/cache paths
# ---------------------------------------------------------------------------

def _infer_caller() -> str:
    """'<module>.<function>' of the first frame outside this module."""
    frame = inspect.currentframe()
    try:
        f = frame.f_back
        while f is not None:
            mod = f.f_globals.get("__name__", "")
            if mod != __name__:
                return f"{mod.rsplit('.', 1)[-1]}.{f.f_code.co_name}"
            f = f.f_back
    finally:
        del frame
    return "unknown"


def _prompt_meta(*candidates: Any) -> Dict[str, Any]:
    """Pull prompt_id/version/hash off the first RenderedPrompt among candidates."""
    for c in candidates:
        pid = getattr(c, "prompt_id", None)
        if pid:
            return {"prompt_id": pid, "prompt_version": getattr(c, "version", None), "prompt_hash": getattr(c, "hash", None)}
    return {"prompt_id": None, "prompt_version": None, "prompt_hash": None}


def _data_dir() -> Path:
    from .storage import data_dir  # late import (storage imports nothing from here)
    return data_dir()


def _cache_key(req: LLMRequest) -> str:
    payload = {
        "provider": req.provider, "model": req.model, "temperature": req.temperature,
        "max_tokens": req.max_tokens, "json_mode": req.json_mode, "json_schema": req.json_schema,
        "messages": req.messages,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _cache_get(key: str) -> Optional[Dict[str, Any]]:
    if not settings.llm_cache_enabled:
        return None
    return read_json(_data_dir() / "llm_cache" / f"{key}.json")


def _cache_put(key: str, record: Dict[str, Any]) -> None:
    if not settings.llm_cache_enabled:
        return
    try:
        write_json(_data_dir() / "llm_cache" / f"{key}.json", record)
    except Exception as e:  # cache is best-effort
        logger.warning("llm cache write failed: %s", e)


def _trace(record: Dict[str, Any]) -> None:
    if not settings.llm_trace_enabled:
        return
    try:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        append_jsonl(_data_dir() / "traces" / f"{day}.jsonl", record)
    except Exception as e:  # tracing must never break a call
        logger.warning("llm trace write failed: %s", e)


# ---------------------------------------------------------------------------
# core call
# ---------------------------------------------------------------------------

async def _complete(req: LLMRequest, caller: str, prompt_meta: Dict[str, Any]) -> str:
    provider = get_provider(req.provider)
    key = _cache_key(req)
    started = time.perf_counter()
    base = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "caller": caller,
        "provider": req.provider,
        "model": req.model,
        **prompt_meta,
        "workspace": current_workspace(),
        "json_mode": req.json_mode,
        "cache_key": key[:16],
    }

    cached = _cache_get(key)
    if cached is not None:
        _trace({**base, "cache_hit": True, "tokens_in": cached.get("tokens_in", 0), "tokens_out": cached.get("tokens_out", 0),
                "latency_ms": 0, "cost_est": 0.0, "attempts": 0, "status": "ok", "error": None})
        return cached.get("content", "")

    attempts = 0
    error: Optional[str] = None
    resp = None
    try:
        async for attempt in AsyncRetrying(
            retry=retry_if_exception_type(RetryableError),
            wait=wait_exponential_jitter(initial=1, max=30),
            stop=stop_after_attempt(RETRY_ATTEMPTS),
            reraise=True,
        ):
            with attempt:
                attempts += 1
                resp = await provider.complete(req)
    except RetryError as e:  # pragma: no cover - reraise=True makes this unlikely
        error = str(e.last_attempt.exception())
        raise
    except Exception as e:
        error = f"{type(e).__name__}: {e}"
        raise
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp is not None:
            _trace({**base, "model": resp.model or req.model, "cache_hit": False,
                    "tokens_in": resp.tokens_in, "tokens_out": resp.tokens_out, "latency_ms": latency_ms,
                    "cost_est": estimate_cost(resp.model or req.model, resp.tokens_in, resp.tokens_out),
                    "attempts": attempts, "status": "ok", "error": None})
        else:
            _trace({**base, "cache_hit": False, "tokens_in": 0, "tokens_out": 0, "latency_ms": latency_ms,
                    "cost_est": None, "attempts": attempts, "status": "error", "error": error})

    _cache_put(key, {"content": resp.content, "tokens_in": resp.tokens_in, "tokens_out": resp.tokens_out,
                     "model": resp.model, "created_at": base["ts"]})
    return resp.content


def _build_request(prompt: str, system_prompt: Optional[str], provider: Optional[str], model: Optional[str],
                   temperature: float, max_tokens: int, timeout: float,
                   json_mode: bool, json_schema: Optional[Dict]) -> LLMRequest:
    provider = provider or settings.llm_provider
    if provider not in DEFAULT_MODELS:
        raise ConfigError(f"Unknown provider: {provider}. Use 'deepseek', 'openai' or 'anthropic'.")
    messages: List[Dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": str(system_prompt)})
    messages.append({"role": "user", "content": str(prompt)})
    return LLMRequest(
        provider=provider, model=model or DEFAULT_MODELS[provider], messages=messages,
        temperature=temperature, max_tokens=max_tokens, timeout=timeout,
        json_mode=json_mode, json_schema=json_schema or None,
    )


# ==================== 公开 API ====================

async def call_llm(
    prompt: str,
    system_prompt: str = None,
    json_schema: Dict = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
    provider: str = None,
    model: str = None,
    caller: str = None,
) -> Dict:
    """统一 LLM JSON 调用。返回解析后的 Dict。"""
    req = _build_request(prompt, system_prompt, provider, model, temperature, max_tokens, timeout,
                         json_mode=True, json_schema=json_schema)
    content = await _complete(req, caller or _infer_caller(), _prompt_meta(prompt, system_prompt))
    return extract_json(content)


async def call_llm_text(
    prompt: str,
    system_prompt: str = None,
    temperature: float = 0.7,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    timeout: float = DEFAULT_TIMEOUT,
    provider: str = None,
    model: str = None,
    caller: str = None,
) -> str:
    """统一 LLM 文本调用。返回纯文本。"""
    req = _build_request(prompt, system_prompt, provider, model, temperature, max_tokens, timeout,
                         json_mode=False, json_schema=None)
    return await _complete(req, caller or _infer_caller(), _prompt_meta(prompt, system_prompt))


def extract_json(content: str) -> Dict:
    """从 LLM 响应中提取 JSON。支持纯 JSON、```json 代码块、混合文本。"""
    if not content or not content.strip():
        return {"content": ""}

    content = content.strip()

    # 1. 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2. 尝试提取 markdown 代码块
    for match in re.findall(r'```(?:json)?\s*([\s\S]*?)```', content):
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue

    # 3. 尝试查找 JSON 对象 {...}
    for match in re.findall(r'\{[\s\S]*\}', content):
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    # 4. 尝试查找 JSON 数组 [...]
    for match in re.findall(r'\[[\s\S]*\]', content):
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    return {"content": content}


async def test_connection(provider: str = "deepseek") -> Dict:
    """测试 API 连接。"""
    try:
        result = await call_llm(
            prompt="Say 'Hello, connection test successful!' in JSON format with key 'message'.",
            max_tokens=100,
            provider=provider,
            caller="llm_client.test_connection",
        )
        return {"success": True, "provider": provider, "response": result}
    except Exception as e:
        return {"success": False, "provider": provider, "error": str(e)}
