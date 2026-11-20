"""Prompts and output schemas for LLM scoring and speaker identification."""

from __future__ import annotations

import json
from dataclasses import dataclass

from app.services.scoring.scorecard import ScorecardDefinition

RESOLUTION_VALUES = ["resolved", "partially_resolved", "unresolved", "escalated", "unknown"]
SENTIMENT_VALUES = ["positive", "neutral", "negative", "mixed"]
FLAG_TYPES = ["fraud", "wrong_information", "escalation_risk", "other"]

_nullable_str = {"type": ["string", "null"]}
_nullable_int = {"type": ["integer", "null"]}

EVALUATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["criteria", "call_reason", "resolution_status", "customer_sentiment", "summary_sw", "summary_en",
                 "flags"],
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["criterion_id", "answer", "evidence_quote", "segment_idx", "reasoning", "confidence"],
                "properties": {
                    "criterion_id": {"type": "string"},
                    "answer": {"type": "string", "enum": ["yes", "no", "na"]},
                    "evidence_quote": _nullable_str,
                    "segment_idx": _nullable_int,
                    "reasoning": {"type": "string"},
                    "confidence": {"type": "number"},
                },
            },
        },
        "call_reason": {"type": "string"},
        "resolution_status": {"type": "string", "enum": RESOLUTION_VALUES},
        "customer_sentiment": {"type": "string", "enum": SENTIMENT_VALUES},
        "summary_sw": {"type": "string"},
        "summary_en": {"type": "string"},
        "flags": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "description", "segment_idx"],
                "properties": {
                    "type": {"type": "string", "enum": FLAG_TYPES},
                    "description": {"type": "string"},
                    "segment_idx": _nullable_int,
                },
            },
        },
    },
}

SPEAKER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["agent_speaker", "confidence", "reasoning"],
    "properties": {
        "agent_speaker": {"type": "string"},
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
    },
}

EVAL_SYSTEM = """You are a senior quality-assurance analyst for a Tanzanian telecom customer-care centre. You evaluate recorded calls between a call-centre AGENT and a CUSTOMER against the QA scorecard below. Calls are in Swahili, often mixed with English (code-switching).

How to judge:
- Judge only the AGENT. The customer's words, mood or mistakes never count against the agent.
- The transcript was produced automatically by speech recognition from noisy 8 kHz phone audio. It contains transcription errors: wrong or missing words, odd spellings, merged sentences and sometimes wrong speaker labels. Do not penalise the agent for transcription errors. Judge what the agent most plausibly said and did.
- Personal data was replaced by tags such as [PHONE], [NIDA], [ACCOUNT], [CARD], [NUMBER], [PIN], [EMAIL]. Treat them as the information that was spoken; never penalise the agent for them. A [PIN] tag inside a request made by the agent still means the agent asked for a PIN.
- When the audio text is unclear, ambiguous or too short to judge a criterion, give your best answer and lower the confidence. Do not guess with high confidence.
- Use "na" only for criteria that allow N/A, and only when the criterion genuinely does not apply to this call. Criteria marked "N/A not allowed" must be answered yes or no.
- The example phrases show typical wording; the agent does not need to use them literally.

For every criterion return:
- criterion_id: exactly as given in the scorecard.
- answer: "yes" (agent met it), "no" (agent did not) or "na".
- evidence_quote: a short quote copied VERBATIM from the transcript, in the original language (usually Swahili). Do not translate, correct or paraphrase it. For a "no" answer quote where the agent failed, or use null when the failure is that something never happened.
- segment_idx: the [number] of the transcript line the quote comes from, or null.
- reasoning: one or two short sentences in English.
- confidence: 0.0 to 1.0, how sure you are of the answer given the transcript quality.

Also return:
- call_reason: the main reason for the call, as a short English label. Prefer one of the listed categories when it fits.
- resolution_status: resolved, partially_resolved, unresolved, escalated or unknown.
- customer_sentiment: the customer's sentiment by the end of the call: positive, neutral, negative or mixed.
- summary_sw: a 2-4 sentence summary of the call in Swahili.
- summary_en: the same summary in English.
- flags: zero or more of: fraud (agent requests a PIN, password or OTP, social-engineering or a scam), wrong_information (the agent gave incorrect or misleading information), escalation_risk (the customer threatens to complain to TCRA or the media, leave the network, or is very angry), other (anything a supervisor must see). Each flag has a short English description and the segment_idx where it happens.

Return only the JSON object."""


def scorecard_block(sc: ScorecardDefinition) -> str:
    lines = [f"SCORECARD: {sc.name}"]
    if sc.description:
        lines.append(sc.description)
    for section in sc.sections:
        lines.append(f"\n## {section}")
        for c in sc.criteria:
            if c.section != section:
                continue
            tags = [f"weight {c.weight:g}"]
            if c.critical:
                tags.append("CRITICAL: a 'no' fails the whole call")
            tags.append("N/A allowed" if c.allow_na else "N/A not allowed")
            lines.append(f"- criterion_id: {c.id} | {c.label} ({'; '.join(tags)})")
            if c.description:
                lines.append(f"  Description: {c.description}")
            if c.examples:
                lines.append("  Example phrases (met): " + " | ".join(c.examples))
            if c.negative_examples:
                lines.append("  Example phrases (failed): " + " | ".join(c.negative_examples))
            if c.allow_na and c.na_guidance:
                lines.append(f"  N/A guidance: {c.na_guidance}")
    if sc.call_reasons:
        lines.append("\nCALL REASON CATEGORIES: " + "; ".join(sc.call_reasons))
    return "\n".join(lines)


def fmt_time(s: float) -> str:
    return f"{int(s // 60):02d}:{int(s % 60):02d}"


def transcript_block(segments: list[dict]) -> str:
    label = {"agent": "AGENT", "customer": "CUSTOMER"}
    return "\n".join(
        f"[{s['idx']}] {label.get(s['speaker'], 'UNKNOWN SPEAKER')} ({fmt_time(s['start_s'])}): {s['text']}"
        for s in segments
    )


@dataclass
class EvalPrompt:
    system: str
    user: str


def build_eval_prompt(sc: ScorecardDefinition, segments: list[dict], meta: dict | None = None) -> EvalPrompt:
    meta = meta or {}
    info = []
    if meta.get("queue"):
        info.append(f"Queue: {meta['queue']}")
    if meta.get("duration_s"):
        info.append(f"Duration: {fmt_time(meta['duration_s'])}")
    if meta.get("speaker_method") in ("heuristic", "none"):
        info.append("Speaker labels are uncertain (mono recording); use the content to tell agent and customer apart.")
    user = (
        ("CALL INFO\n" + "\n".join(info) + "\n\n" if info else "")
        + "TRANSCRIPT (machine-generated)\n"
        + transcript_block(segments)
        + "\n\nEvaluate the agent against every criterion in the scorecard and return the JSON object."
    )
    # Stable system prompt (instructions + scorecard) first, so it can be prompt-cached.
    return EvalPrompt(system=EVAL_SYSTEM + "\n\n" + scorecard_block(sc), user=user)


SPEAKER_SYSTEM = """You are given the first part of a machine-transcribed Swahili customer-care phone call. The speakers were separated automatically and are labelled SPEAKER_00, SPEAKER_01 and so on. Decide which label is the call-centre AGENT (greets with the company name, introduces themself, offers help, asks verification questions, explains procedures). The other speaker(s) are the customer. Return the agent's label exactly, a confidence from 0 to 1, and one sentence of reasoning. Return only the JSON object."""


def build_speaker_prompt(segments: list[dict], max_lines: int = 40) -> EvalPrompt:
    lines = "\n".join(f"{s['speaker_raw']}: {s['text']}" for s in segments[:max_lines] if s.get("speaker_raw"))
    labels = sorted({s["speaker_raw"] for s in segments if s.get("speaker_raw")})
    return EvalPrompt(SPEAKER_SYSTEM, f"Labels: {', '.join(labels)}\n\n{lines}")


def schema_json() -> str:
    return json.dumps(EVALUATION_SCHEMA)
