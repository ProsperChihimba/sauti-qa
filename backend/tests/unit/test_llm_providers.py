"""Provider request construction, without any network access."""

from contextlib import contextmanager
from types import SimpleNamespace as NS

import pytest

from app.services.scoring.llm import AnthropicProvider, LLMError, OpenAICompatProvider
from app.services.scoring.scorecard import load_seed

SEGS = [{"idx": 0, "speaker": "agent", "start_s": 0, "text": "Karibu Vodacom"}]


def _anthropic(monkeypatch, msg):
    p = AnthropicProvider("claude-sonnet-5-5")
    seen = {}

    @contextmanager
    def stream(**kw):
        seen.update(kw)
        yield NS(get_final_message=lambda: msg)

    monkeypatch.setattr(p.client.beta.messages, "stream", stream)
    return p, seen


def test_anthropic_request_shape(monkeypatch):
    msg = NS(stop_reason="end_turn", stop_details=None, content=[NS(type="text", text='{"criteria": []}')])
    p, seen = _anthropic(monkeypatch, msg)
    assert p.evaluate(load_seed(), SEGS) == {"criteria": []}
    assert seen["model"] == "claude-sonnet-5-5"
    assert seen["output_config"]["format"]["type"] == "json_schema"
    assert seen["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert seen["fallbacks"] == "default" and seen["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in seen and "thinking" not in seen


def test_anthropic_refusal_raises(monkeypatch):
    msg = NS(stop_reason="refusal", stop_details=NS(category="other"), content=[])
    p, _ = _anthropic(monkeypatch, msg)
    with pytest.raises(LLMError):
        p.evaluate(load_seed(), SEGS)


def test_openai_compat_falls_back_through_json_modes(monkeypatch):
    import httpx
    import openai

    monkeypatch.setattr("app.services.scoring.llm.get_settings",
                        lambda: NS(llm_openai_base_url="http://vllm:8000/v1", llm_openai_api_key="x",
                                   llm_timeout_seconds=5, llm_json_mode="auto", llm_temperature=0.0,
                                   llm_max_tokens=1000))
    p = OpenAICompatProvider("qwen")
    calls = []

    def create(**kw):
        calls.append(kw.get("response_format", {}) and kw["response_format"]["type"])
        if kw.get("response_format", {}).get("type") == "json_schema":
            req = httpx.Request("POST", "http://vllm")
            raise openai.BadRequestError("no", response=httpx.Response(400, request=req), body=None)
        return NS(choices=[NS(finish_reason="stop", message=NS(content='<think>x</think>```json\n{"ok": 1}\n```'))])

    monkeypatch.setattr(p.client.chat.completions, "create", create)
    assert p.evaluate(load_seed(), SEGS) == {"ok": 1}
    assert calls == ["json_schema", "json_object"]
    p.evaluate(load_seed(), SEGS)
    assert calls[-1] == "json_object"  # remembered
