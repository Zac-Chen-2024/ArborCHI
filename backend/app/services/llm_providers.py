"""
LLM provider registry (Doc/01 M9, plan 1.2).

One class per wire protocol. Each provider turns a normalised request into a
`ProviderResponse(content, tokens_in, tokens_out, model)` and raises
`RetryableError` / `LLMError` so that llm_client can apply one retry policy
to all of them.

    deepseek  -> OpenAICompatProvider (chat/completions, json_object)
    openai    -> OpenAICompatProvider (chat/completions, strict json_schema)
    anthropic -> AnthropicProvider    (official `anthropic` SDK, Messages API,
                                       structured outputs via output_config)

Structured output strategy per provider:
    OpenAI    : response_format = {type: json_schema, strict: true}
    DeepSeek  : response_format = {type: json_object}
    Anthropic : output_config.format = {type: json_schema, schema} when a schema
                is given; otherwise a "return only JSON" system line + the
                shared extract_json() parser.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from ..core.config import settings
from ..core.errors import ConfigError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LLMError(Exception):
    """Non-retryable provider error (4xx other than 429, refusal, bad config)."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class RetryableError(LLMError):
    """429 / 5xx / timeout / connection error -- llm_client retries these."""


# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------

@dataclass
class LLMRequest:
    provider: str
    model: str
    messages: List[Dict[str, str]]         # [{role: system|user, content}]
    temperature: float
    max_tokens: int
    timeout: float
    json_mode: bool = False                # caller wants JSON back
    json_schema: Optional[Dict[str, Any]] = None
    # Reasoning models (GPT-5 family) take effort instead of temperature --
    # they run several rounds of reasoning and selection internally, so the
    # sampling knobs are not exposed at all. None = leave at the model default.
    reasoning_effort: Optional[str] = None


@dataclass
class ProviderResponse:
    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    model: str = ""


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_MODELS = {
    "deepseek": "deepseek-chat",
    "openai": "gpt-4.1",
    # Cost-tier reasoning model on the Responses API; 1.05M context.
    "openai_responses": "gpt-5.6-luna",
    "anthropic": "claude-opus-5",
}

# USD per 1M tokens (input, output). Estimates for cost_est in traces only.
PRICING = {
    "deepseek-chat": (0.27, 1.10),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> Optional[float]:
    p = PRICING.get(model)
    if not p:
        return None
    return round(tokens_in / 1e6 * p[0] + tokens_out / 1e6 * p[1], 6)


# ---------------------------------------------------------------------------
# Shared HTTP client (connection pooling; closed at app shutdown)
# ---------------------------------------------------------------------------

_http: Optional[httpx.AsyncClient] = None


def http_client() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
    return _http


async def close_clients() -> None:
    global _http
    if _http is not None and not _http.is_closed:
        await _http.aclose()
    _http = None


# ---------------------------------------------------------------------------
# OpenAI-compatible (DeepSeek, OpenAI)
# ---------------------------------------------------------------------------

class OpenAICompatProvider:
    def __init__(self, name: str, api_key: str, api_base: str, strict_schema: bool):
        self.name = name
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.strict_schema = strict_schema

    def _response_format(self, req: LLMRequest) -> Optional[Dict[str, Any]]:
        if not req.json_mode:
            return None
        if self.strict_schema and req.json_schema:
            return {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": True, "schema": req.json_schema},
            }
        return {"type": "json_object"}

    async def complete(self, req: LLMRequest) -> ProviderResponse:
        if not self.api_key:
            raise ConfigError(
                f"{self.name.capitalize()} API key not configured. Set {self.name.upper()}_API_KEY in .env"
            )
        body: Dict[str, Any] = {
            "model": req.model,
            "messages": req.messages,
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        rf = self._response_format(req)
        if rf:
            body["response_format"] = rf
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        try:
            resp = await http_client().post(
                f"{self.api_base}/chat/completions", json=body, headers=headers, timeout=req.timeout,
            )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            raise RetryableError(f"{self.name}: {type(e).__name__}") from e

        if resp.status_code != 200:
            # Body goes to the log only; never into an exception message that
            # might reach an API response.
            logger.error("%s API error %s: %s", self.name, resp.status_code, resp.text[:500])
            msg = f"{self.name.capitalize()} API error {resp.status_code}"
            if resp.status_code == 429 or resp.status_code >= 500:
                raise RetryableError(msg, resp.status_code)
            raise LLMError(msg, resp.status_code)

        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""
        usage = data.get("usage") or {}
        return ProviderResponse(
            content=content,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            model=data.get("model") or req.model,
        )


# ---------------------------------------------------------------------------
# OpenAI Responses API (GPT-5.6 family)
# ---------------------------------------------------------------------------

class OpenAIResponsesProvider:
    """OpenAI's Responses API -- the endpoint the GPT-5.6 models are served on.

    Separate from OpenAICompatProvider because the request shape genuinely
    differs, not just in field names:

    * `input` instead of `messages`, `instructions` for the system prompt
    * `max_output_tokens` instead of `max_tokens`
    * **no `temperature`, no `seed`.** Reasoning models disable the sampling
      parameters; `reasoning.effort` is what steers the output instead.

    That last point matters for this study and is worth stating where someone
    will read it. Generation is NOT reproducible by re-running the model, and
    no parameter will make it so. The study does not rely on that: the frozen
    material is generated once, offline, and hashed, so every participant reads
    identical bytes and reproducibility comes from the bundle rather than from
    the model. Live generation (a node the participant edited) is inherently
    per-participant; what makes it auditable is the trace record of the actual
    call, not the ability to replay it.
    """

    def __init__(self, api_key: str, api_base: str):
        self.name = "openai"
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")

    async def complete(self, req: LLMRequest) -> ProviderResponse:
        if not self.api_key:
            raise ConfigError(
                "OpenAI API key not configured. Set OPENAI_API_KEY in .env")

        system = "\n\n".join(
            m["content"] for m in req.messages if m.get("role") == "system")
        user = "\n\n".join(
            m["content"] for m in req.messages if m.get("role") != "system")

        body: Dict[str, Any] = {
            "model": req.model,
            "input": user,
            "max_output_tokens": req.max_tokens,
        }
        if system:
            body["instructions"] = system
        if req.reasoning_effort:
            body["reasoning"] = {"effort": req.reasoning_effort}
        if req.json_mode and req.json_schema:
            body["text"] = {"format": {
                "type": "json_schema", "name": "response",
                "strict": True, "schema": req.json_schema,
            }}

        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        try:
            resp = await http_client().post(
                f"{self.api_base}/responses", json=body, headers=headers,
                timeout=req.timeout,
            )
        except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as e:
            raise RetryableError(f"openai: {type(e).__name__}") from e

        if resp.status_code != 200:
            logger.error("openai responses error %s: %s", resp.status_code, resp.text[:500])
            msg = f"OpenAI API error {resp.status_code}"
            if resp.status_code == 429 or resp.status_code >= 500:
                raise RetryableError(msg, resp.status_code)
            raise LLMError(msg, resp.status_code)

        data = resp.json()
        content = _responses_text(data)
        usage = data.get("usage") or {}
        return ProviderResponse(
            content=content,
            tokens_in=int(usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("output_tokens") or 0),
            model=data.get("model") or req.model,
        )


def _responses_text(data: Dict[str, Any]) -> str:
    """Pull the assistant text out of a Responses payload.

    `output` is a list of items and only some of them are messages -- a
    reasoning model also returns reasoning items, which carry no text for us.
    Concatenating everything blindly would splice reasoning traces into the
    petition letter.
    """
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts: List[str] = []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for chunk in item.get("content") or []:
            if chunk.get("type") in ("output_text", "text") and chunk.get("text"):
                parts.append(chunk["text"])
    return "".join(parts)


# ---------------------------------------------------------------------------
# Anthropic (official SDK, native Messages API)
# ---------------------------------------------------------------------------

class AnthropicProvider:
    """Uses the `anthropic` SDK. Retries are disabled on the SDK client so the
    shared tenacity policy in llm_client is the single retry authority."""

    name = "anthropic"

    def __init__(self, api_key: str, api_base: Optional[str] = None):
        self.api_key = api_key
        self.api_base = api_base or None
        self._client = None

    def _client_or_raise(self):
        if not self.api_key:
            raise ConfigError("Anthropic API key not configured. Set ANTHROPIC_API_KEY in .env")
        if self._client is None:
            import anthropic  # local import: optional dependency at import time

            kwargs: Dict[str, Any] = {"api_key": self.api_key, "max_retries": 0}
            if self.api_base:
                kwargs["base_url"] = self.api_base
            self._client = anthropic.AsyncAnthropic(**kwargs)
        return self._client

    @staticmethod
    def _split(messages: List[Dict[str, str]]):
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        user_msgs = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") != "system"]
        return ("\n\n".join(system_parts) or None), user_msgs

    async def complete(self, req: LLMRequest) -> ProviderResponse:
        import anthropic

        client = self._client_or_raise()
        system, msgs = self._split(req.messages)

        kwargs: Dict[str, Any] = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "messages": msgs,
            "timeout": req.timeout,
        }
        # NB: no `temperature` -- rejected (400) on current Opus/Sonnet models;
        # thinking is adaptive by default on Claude Opus 5, so it is not set here.
        if req.json_mode and req.json_schema:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": req.json_schema}}
        elif req.json_mode:
            system = (system + "\n\n" if system else "") + "Return ONLY a valid JSON object. No markdown fences, no prose."
        if system:
            kwargs["system"] = system

        try:
            try:
                # Server-side refusal fallback (routes a policy decline to
                # Anthropic's recommended model instead of returning nothing).
                resp = await client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs,
                )
            except TypeError:
                # Older SDK without `fallbacks`: plain call.
                resp = await client.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            raise RetryableError("Anthropic API error 429", 429) from e
        except anthropic.APIStatusError as e:
            logger.error("anthropic API error %s: %s", e.status_code, str(e)[:500])
            if e.status_code >= 500:
                raise RetryableError(f"Anthropic API error {e.status_code}", e.status_code) from e
            raise LLMError(f"Anthropic API error {e.status_code}", e.status_code) from e
        except (anthropic.APITimeoutError, anthropic.APIConnectionError) as e:
            raise RetryableError(f"anthropic: {type(e).__name__}") from e

        if getattr(resp, "stop_reason", None) == "refusal":
            raise LLMError("Anthropic refused the request (stop_reason=refusal)")
        text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
        usage = getattr(resp, "usage", None)
        return ProviderResponse(
            content=text,
            tokens_in=int(getattr(usage, "input_tokens", 0) or 0),
            tokens_out=int(getattr(usage, "output_tokens", 0) or 0),
            model=getattr(resp, "model", req.model) or req.model,
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def get_provider(name: str):
    if name == "deepseek":
        return OpenAICompatProvider("deepseek", settings.deepseek_api_key, settings.deepseek_api_base, strict_schema=False)
    if name == "openai":
        return OpenAICompatProvider("openai", settings.openai_api_key, settings.openai_api_base, strict_schema=True)
    if name == "openai_responses":
        return OpenAIResponsesProvider(settings.openai_api_key, settings.openai_api_base)
    if name == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_api_base or None)
    raise ConfigError(f"Unknown provider: {name}. Use 'deepseek', 'openai' or 'anthropic'.")


PROVIDERS = ("deepseek", "openai", "openai_responses", "anthropic")
