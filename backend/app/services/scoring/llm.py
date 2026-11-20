"""LLM providers behind one interface: Anthropic Claude, any OpenAI-compatible
server (vLLM, Ollama, TGI... for on-prem), and a heuristic mock for tests.

Providers only return raw JSON; validation, repair and scoring happen in code.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Any

from app.config import get_settings
from app.services.scoring.prompts import (
    EVALUATION_SCHEMA,
    SPEAKER_SCHEMA,
    EvalPrompt,
    build_eval_prompt,
    build_speaker_prompt,
)
from app.services.scoring.scorecard import ScorecardDefinition

log = logging.getLogger(__name__)


class LLMError(Exception):
    pass


def extract_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from model text (tolerates code fences and <think> blocks)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise LLMError("Model response contained no JSON object") from None
        try:
            data = json.loads(text[start: end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise LLMError("Model returned JSON that is not an object")
    return data


class LLMProvider(ABC):
    name = "base"
    model = ""

    @abstractmethod
    def complete_json(self, prompt: EvalPrompt, schema: dict, schema_name: str, max_tokens: int) -> dict: ...

    def evaluate(self, sc: ScorecardDefinition, segments: list[dict], meta: dict | None = None) -> dict:
        prompt = build_eval_prompt(sc, segments, meta)
        return self.complete_json(prompt, EVALUATION_SCHEMA, "call_evaluation", get_settings().llm_max_tokens)

    def identify_agent(self, segments: list[dict]) -> dict:
        return self.complete_json(build_speaker_prompt(segments), SPEAKER_SCHEMA, "speaker_identification", 2000)


class AnthropicProvider(LLMProvider):
    """Claude via the official SDK. Sends transcripts to Anthropic: only when
    LLM_PROVIDER=anthropic is configured explicitly."""

    name = "anthropic"

    def __init__(self, model: str | None = None):
        import anthropic

        s = get_settings()
        self.model = model or "claude-sonnet-5-5"
        self.client = anthropic.Anthropic(api_key=s.anthropic_api_key, timeout=s.llm_timeout_seconds, max_retries=3)

    def complete_json(self, prompt, schema, schema_name, max_tokens):
        import anthropic

        s = get_settings()
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": schema}}
        if s.llm_effort:
            output_config["effort"] = s.llm_effort
        kwargs: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_tokens,
            # Instructions + scorecard are identical for every call: cache them.
            system=[{"type": "text", "text": prompt.system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt.user}],
            output_config=output_config,
        )
        if s.anthropic_fallbacks:
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["fallbacks"] = s.anthropic_fallbacks
        try:
            with self.client.beta.messages.stream(**kwargs) as stream:
                msg = stream.get_final_message()
        except anthropic.BadRequestError as exc:
            raise LLMError(f"Anthropic rejected the request: {exc.message}") from exc
        except anthropic.APIError:  # rate limits / 5xx after SDK retries: let the job retry
            raise
        if msg.stop_reason == "refusal":
            raise LLMError(f"Model declined to evaluate this call ({getattr(msg.stop_details, 'category', None)})")
        if msg.stop_reason == "max_tokens":
            raise LLMError("Model output was cut off (raise LLM_MAX_TOKENS)")
        text = "".join(b.text for b in msg.content if b.type == "text")
        return extract_json(text)


class OpenAICompatProvider(LLMProvider):
    """Any OpenAI-compatible chat endpoint. For on-prem production, point
    LLM_OPENAI_BASE_URL at vLLM / Ollama serving an open model on the internal network."""

    name = "openai"

    def __init__(self, model: str | None = None):
        from openai import OpenAI

        s = get_settings()
        if not model:
            raise LLMError("LLM_MODEL must be set for LLM_PROVIDER=openai")
        self.model = model
        self.client = OpenAI(base_url=s.llm_openai_base_url, api_key=s.llm_openai_api_key or "not-needed",
                             timeout=s.llm_timeout_seconds, max_retries=2)
        self._mode = s.llm_json_mode

    def _formats(self, schema, schema_name):
        js = {"type": "json_schema", "json_schema": {"name": schema_name, "schema": schema, "strict": True}}
        order = {"json_schema": [js], "json_object": [{"type": "json_object"}], "none": [None],
                 "auto": [js, {"type": "json_object"}, None]}
        return order[self._mode]

    def complete_json(self, prompt, schema, schema_name, max_tokens):
        import openai

        s = get_settings()
        user = prompt.user + "\n\nJSON schema of the answer:\n" + json.dumps(schema)
        last_exc: Exception | None = None
        for fmt in self._formats(schema, schema_name):
            kwargs: dict[str, Any] = dict(
                model=self.model,
                messages=[{"role": "system", "content": prompt.system}, {"role": "user", "content": user}],
                temperature=s.llm_temperature,
                max_tokens=max_tokens,
            )
            if fmt:
                kwargs["response_format"] = fmt
            try:
                resp = self.client.chat.completions.create(**kwargs)
            except openai.BadRequestError as exc:  # server does not support this response_format
                last_exc = exc
                log.info("response_format %s rejected by server, trying next", fmt and fmt["type"])
                continue
            choice = resp.choices[0]
            if choice.finish_reason == "length":
                raise LLMError("Model output was cut off (raise LLM_MAX_TOKENS)")
            if self._mode == "auto" and fmt is not None:
                self._mode = fmt["type"]  # remember what works
            return extract_json(choice.message.content or "")
        raise LLMError(f"OpenAI-compatible server rejected every JSON mode: {last_exc}")


@lru_cache
def get_llm() -> LLMProvider:
    s = get_settings()
    if s.llm_provider == "anthropic":
        return AnthropicProvider(s.llm_model)
    if s.llm_provider == "openai":
        return OpenAICompatProvider(s.llm_model)
    from app.services.scoring.mock_llm import MockLLM

    return MockLLM()
