"""
llm_client (M9): retry, tracing, cache, provider request shapes.
HTTP is mocked with respx; the Anthropic SDK client is replaced by a fake.
"""
import json
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.core.config import settings
from app.core.errors import ConfigError
from app.core.prompt_loader import render
from app.services import llm_client, llm_providers
from app.services.llm_providers import LLMError

DEEPSEEK = "https://api.deepseek.com/v1/chat/completions"
OPENAI = "https://api.openai.com/v1/chat/completions"


def _chat_response(content, model="deepseek-chat", pin=11, pout=7):
    return {"choices": [{"message": {"content": content}}], "model": model,
            "usage": {"prompt_tokens": pin, "completion_tokens": pout}}


@pytest.fixture(autouse=True)
def _llm_env(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "dk")
    monkeypatch.setattr(settings, "openai_api_key", "ok")
    monkeypatch.setattr(settings, "llm_trace_enabled", True)
    monkeypatch.setattr(settings, "llm_cache_enabled", False)
    # make retries fast
    monkeypatch.setattr(llm_client, "RETRY_ATTEMPTS", 3)
    import tenacity
    monkeypatch.setattr(llm_client, "wait_exponential_jitter", lambda **kw: tenacity.wait_fixed(0))
    yield


def _traces(tmp_data_dir):
    files = list((tmp_data_dir / "traces").glob("*.jsonl"))
    if not files:
        return []
    return [json.loads(line) for f in files for line in f.read_text().splitlines()]


# ---- request shapes ---------------------------------------------------------

@respx.mock
async def test_deepseek_json_mode_uses_json_object(tmp_data_dir):
    route = respx.post(DEEPSEEK).mock(return_value=httpx.Response(200, json=_chat_response('{"a": 1}')))
    out = await llm_client.call_llm("hi", system_prompt="sys", json_schema={"type": "object"}, provider="deepseek")
    assert out == {"a": 1}
    body = json.loads(route.calls[0].request.content)
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"] == [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
    assert route.calls[0].request.headers["authorization"] == "Bearer dk"


@respx.mock
async def test_openai_json_mode_uses_strict_schema(tmp_data_dir):
    route = respx.post(OPENAI).mock(return_value=httpx.Response(200, json=_chat_response('{"a": 1}', model="gpt-4.1")))
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"], "additionalProperties": False}
    await llm_client.call_llm("hi", json_schema=schema, provider="openai")
    body = json.loads(route.calls[0].request.content)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"] == schema


@respx.mock
async def test_text_mode_has_no_response_format(tmp_data_dir):
    route = respx.post(DEEPSEEK).mock(return_value=httpx.Response(200, json=_chat_response("plain")))
    assert await llm_client.call_llm_text("hi", provider="deepseek") == "plain"
    assert "response_format" not in json.loads(route.calls[0].request.content)


# ---- retry ------------------------------------------------------------------

@respx.mock
async def test_retries_on_429_then_succeeds(tmp_data_dir):
    route = respx.post(DEEPSEEK).mock(side_effect=[
        httpx.Response(429, json={"error": "slow down"}),
        httpx.Response(503, text="overloaded"),
        httpx.Response(200, json=_chat_response('{"ok": true}')),
    ])
    assert await llm_client.call_llm("hi", provider="deepseek") == {"ok": True}
    assert route.call_count == 3
    t = _traces(tmp_data_dir)[-1]
    assert t["attempts"] == 3 and t["status"] == "ok"


@respx.mock
async def test_gives_up_after_three_retryable_failures(tmp_data_dir):
    route = respx.post(DEEPSEEK).mock(return_value=httpx.Response(500, text="boom"))
    with pytest.raises(LLMError):
        await llm_client.call_llm("hi", provider="deepseek")
    assert route.call_count == 3
    t = _traces(tmp_data_dir)[-1]
    assert t["status"] == "error" and t["attempts"] == 3


@respx.mock
async def test_4xx_is_not_retried_and_body_not_in_message(tmp_data_dir):
    route = respx.post(DEEPSEEK).mock(return_value=httpx.Response(400, json={"error": {"message": "sk-SECRET leaked?"}}))
    with pytest.raises(LLMError) as ei:
        await llm_client.call_llm("hi", provider="deepseek")
    assert route.call_count == 1
    assert "SECRET" not in str(ei.value)


@respx.mock
async def test_timeout_is_retried(tmp_data_dir):
    route = respx.post(DEEPSEEK).mock(side_effect=[httpx.ReadTimeout("t"), httpx.Response(200, json=_chat_response("x"))])
    assert await llm_client.call_llm_text("hi", provider="deepseek") == "x"
    assert route.call_count == 2


# ---- tracing ----------------------------------------------------------------

@respx.mock
async def test_trace_record_fields_and_prompt_metadata(tmp_data_dir):
    respx.post(DEEPSEEK).mock(return_value=httpx.Response(200, json=_chat_response('{"t": "x"}', pin=100, pout=50)))
    prompt = render("recommender/infer_argument_title_user_prompt", standard_key="awards", current_title_or_none="-", child_info="-")
    await llm_client.call_llm(prompt, provider="deepseek", caller="test.caller")
    t = _traces(tmp_data_dir)[-1]
    assert t["caller"] == "test.caller"
    assert t["provider"] == "deepseek" and t["model"] == "deepseek-chat"
    assert t["prompt_id"] == "recommender/infer_argument_title_user_prompt"
    assert t["prompt_version"] == 1 and len(t["prompt_hash"]) == 16
    assert t["tokens_in"] == 100 and t["tokens_out"] == 50
    assert t["cost_est"] == pytest.approx(100 / 1e6 * 0.27 + 50 / 1e6 * 1.10)
    assert t["cache_hit"] is False and t["workspace"] == "default"
    assert "latency_ms" in t and t["status"] == "ok"


@respx.mock
async def test_caller_is_inferred_from_stack(tmp_data_dir):
    respx.post(DEEPSEEK).mock(return_value=httpx.Response(200, json=_chat_response("x")))

    async def my_pipeline_step():
        return await llm_client.call_llm_text("hi", provider="deepseek")

    await my_pipeline_step()
    assert _traces(tmp_data_dir)[-1]["caller"] == "test_llm_client.my_pipeline_step"


# ---- cache ------------------------------------------------------------------

@respx.mock
async def test_cache_hit_skips_network(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(settings, "llm_cache_enabled", True)
    route = respx.post(DEEPSEEK).mock(return_value=httpx.Response(200, json=_chat_response('{"v": 1}')))
    a = await llm_client.call_llm("same prompt", provider="deepseek")
    b = await llm_client.call_llm("same prompt", provider="deepseek")
    assert a == b == {"v": 1}
    assert route.call_count == 1
    assert list((tmp_data_dir / "llm_cache").glob("*.json"))
    traces = _traces(tmp_data_dir)
    assert [t["cache_hit"] for t in traces[-2:]] == [False, True]
    # different params -> different key -> network again
    await llm_client.call_llm("same prompt", provider="deepseek", temperature=0.9)
    assert route.call_count == 2


# ---- config errors ----------------------------------------------------------

async def test_unknown_provider_and_missing_key(tmp_data_dir, monkeypatch):
    with pytest.raises(ConfigError):
        await llm_client.call_llm_text("hi", provider="gemini")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        await llm_client.call_llm_text("hi", provider="anthropic")


# ---- anthropic provider (SDK client faked) ---------------------------------

class _FakeMessages:
    def __init__(self, log, resp=None, err=None):
        self.log, self.resp, self.err = log, resp, err

    async def create(self, **kwargs):
        self.log.append(kwargs)
        if self.err:
            raise self.err
        return self.resp


def _fake_anthropic_client(log, resp=None, err=None):
    msgs = _FakeMessages(log, resp, err)
    return SimpleNamespace(beta=SimpleNamespace(messages=msgs), messages=msgs)


def _anthropic_response(text, stop="end_turn", model="claude-opus-5"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop, model=model,
        usage=SimpleNamespace(input_tokens=30, output_tokens=12),
    )


async def test_anthropic_json_schema_uses_output_config(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "ak")
    log = []
    monkeypatch.setattr(llm_providers.AnthropicProvider, "_client_or_raise",
                        lambda self: _fake_anthropic_client(log, _anthropic_response('{"a": 2}')))
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"], "additionalProperties": False}
    out = await llm_client.call_llm("hi", system_prompt="sys", json_schema=schema, provider="anthropic", temperature=0.5)
    assert out == {"a": 2}
    kw = log[0]
    assert kw["model"] == "claude-opus-5"
    assert kw["system"] == "sys"
    assert kw["messages"] == [{"role": "user", "content": "hi"}]
    assert kw["output_config"] == {"format": {"type": "json_schema", "schema": schema}}
    assert "temperature" not in kw  # rejected by current Claude models
    assert kw.get("fallbacks") == "default"
    t = _traces(tmp_data_dir)[-1]
    assert t["provider"] == "anthropic" and t["tokens_in"] == 30 and t["cost_est"] == pytest.approx(30 / 1e6 * 5 + 12 / 1e6 * 25)


async def test_anthropic_json_mode_without_schema_adds_instruction(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "ak")
    log = []
    monkeypatch.setattr(llm_providers.AnthropicProvider, "_client_or_raise",
                        lambda self: _fake_anthropic_client(log, _anthropic_response('```json\n{"b": 3}\n```')))
    assert await llm_client.call_llm("hi", provider="anthropic") == {"b": 3}
    assert "output_config" not in log[0]
    assert "Return ONLY a valid JSON object" in log[0]["system"]


async def test_anthropic_refusal_is_an_error(tmp_data_dir, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "ak")
    log = []
    monkeypatch.setattr(llm_providers.AnthropicProvider, "_client_or_raise",
                        lambda self: _fake_anthropic_client(log, _anthropic_response("", stop="refusal")))
    with pytest.raises(LLMError, match="refus"):
        await llm_client.call_llm_text("hi", provider="anthropic")


async def test_anthropic_rate_limit_is_retried(tmp_data_dir, monkeypatch):
    import anthropic

    monkeypatch.setattr(settings, "anthropic_api_key", "ak")
    calls = {"n": 0}

    class _Msgs:
        async def create(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise anthropic.RateLimitError("rl", response=httpx.Response(429, request=httpx.Request("POST", "x")), body=None)
            return _anthropic_response("ok")

    m = _Msgs()
    monkeypatch.setattr(llm_providers.AnthropicProvider, "_client_or_raise",
                        lambda self: SimpleNamespace(beta=SimpleNamespace(messages=m), messages=m))
    assert await llm_client.call_llm_text("hi", provider="anthropic") == "ok"
    assert calls["n"] == 2
