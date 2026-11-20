"""Validate and repair raw LLM output against the scorecard.

The model's JSON is never trusted: every scorecard criterion must end up with a
valid answer, a confidence in [0, 1] and an evidence reference that really
exists in the transcript. Every repair is logged, and repaired items get zero
confidence so the call is routed to a human.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.services.scoring.prompts import FLAG_TYPES, RESOLUTION_VALUES, SENTIMENT_VALUES
from app.services.scoring.scorecard import ScorecardDefinition

YES = {"yes", "y", "ndiyo", "ndio", "true", "pass", "met", "1"}
NO = {"no", "n", "hapana", "false", "fail", "not met", "0"}
NA = {"na", "n/a", "n.a.", "not applicable", "none", "haihusiki", "not_applicable"}


@dataclass
class ItemResult:
    criterion_id: str
    position: int
    answer: str
    evidence_quote: str | None
    segment_idx: int | None
    reasoning: str
    confidence: float
    repaired: bool = False


@dataclass
class ValidatedEvaluation:
    items: list[ItemResult]
    call_reason: str | None
    resolution_status: str
    sentiment: str
    summary_sw: str | None
    summary_en: str | None
    flags: list[dict[str, Any]]
    repair_log: list[str] = field(default_factory=list)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(re.sub(r"[^a-z0-9\[\]]+", " ", s).split())


def locate_quote(quote: str, segments: list[dict], hint: int | None = None) -> tuple[int | None, float]:
    """Find the segment a quote comes from. Returns (idx, similarity 0-1)."""
    q = _norm(quote)
    if not q:
        return None, 0.0
    best, best_score = None, 0.0
    ordered = sorted(segments, key=lambda s: 0 if s["idx"] == hint else 1)
    for seg in ordered:
        t = _norm(seg["text"])
        if not t:
            continue
        if q in t:
            return seg["idx"], 1.0
        # Partial match: best window of the segment against the quote.
        sm = difflib.SequenceMatcher(None, q, t, autojunk=False)
        blocks = sum(b.size for b in sm.get_matching_blocks())
        score = blocks / max(len(q), 1)
        if score > best_score:
            best, best_score = seg["idx"], score
    return best, best_score


def _answer(raw: Any) -> str | None:
    if isinstance(raw, bool):
        return "yes" if raw else "no"
    if raw is None:
        return None
    v = str(raw).strip().lower()
    if v in YES:
        return "yes"
    if v in NO:
        return "no"
    if v in NA:
        return "na"
    return None


def _confidence(raw: Any) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    if 1 < v <= 100:  # model answered in percent
        v = v / 100
    return max(0.0, min(1.0, v))


def _enum(raw: Any, allowed: list[str], default: str) -> str:
    v = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    return v if v in allowed else default


def validate_and_repair(raw: dict[str, Any] | None, sc: ScorecardDefinition, segments: list[dict]
                        ) -> ValidatedEvaluation:
    raw = raw if isinstance(raw, dict) else {}
    log: list[str] = []
    valid_idx = {s["idx"] for s in segments}
    criteria = sc.by_id()

    by_id: dict[str, dict] = {}
    raw_items = raw.get("criteria")
    if not isinstance(raw_items, list):
        log.append("Model output had no criteria list.")
        raw_items = []
    labels = {_norm(c.label): c.id for c in sc.criteria}
    for it in raw_items:
        if not isinstance(it, dict):
            continue
        cid = str(it.get("criterion_id") or it.get("id") or "").strip()
        if cid not in criteria:
            lowered = cid.lower().replace(" ", "_")
            cid = lowered if lowered in criteria else labels.get(_norm(cid), cid)
        if cid not in criteria:
            log.append(f"Ignored unknown criterion '{it.get('criterion_id')}'.")
            continue
        if cid in by_id:
            log.append(f"Ignored duplicate answer for '{cid}'.")
            continue
        by_id[cid] = it

    items: list[ItemResult] = []
    for pos, c in enumerate(sc.criteria):
        it = by_id.get(c.id)
        if it is None:
            log.append(f"{c.id}: missing from model output; set to 'no' for human review.")
            items.append(ItemResult(c.id, pos, "no", None, None, "Not evaluated by the model.", 0.0, True))
            continue
        repaired = False
        ans = _answer(it.get("answer"))
        if ans is None:
            log.append(f"{c.id}: invalid answer {it.get('answer')!r}; set to 'no'.")
            ans, repaired = "no", True
        if ans == "na" and not c.allow_na:
            log.append(f"{c.id}: 'na' is not allowed for this criterion; set to 'no'.")
            ans, repaired = "no", True

        conf = _confidence(it.get("confidence"))
        if conf is None:
            log.append(f"{c.id}: missing or invalid confidence.")
            conf, repaired = 0.0, True

        quote = it.get("evidence_quote")
        quote = str(quote).strip() if quote not in (None, "") else None
        seg_raw = it.get("segment_idx")
        try:
            seg_idx = int(seg_raw) if seg_raw is not None and str(seg_raw).strip() != "" else None
        except (TypeError, ValueError):
            seg_idx = None
            log.append(f"{c.id}: invalid segment reference {seg_raw!r}.")
        if seg_idx is not None and seg_idx not in valid_idx:
            log.append(f"{c.id}: segment {seg_idx} does not exist.")
            seg_idx = None
        if quote:
            found, sim = locate_quote(quote, segments, seg_idx)
            if sim >= 0.8:
                if seg_idx is not None and found != seg_idx and _norm(quote) not in _norm(
                        next(s["text"] for s in segments if s["idx"] == seg_idx)):
                    log.append(f"{c.id}: quote found in segment {found}, not {seg_idx}; reference corrected.")
                    seg_idx = found
                elif seg_idx is None:
                    seg_idx = found
            else:
                # Quote not in the transcript: probably paraphrased or translated.
                log.append(f"{c.id}: evidence quote not found verbatim in the transcript; confidence capped at 0.5.")
                conf = min(conf, 0.5)
                if seg_idx is None and found is not None and sim >= 0.5:
                    seg_idx = found
        reasoning = str(it.get("reasoning") or "").strip()[:2000]
        if repaired:
            conf = 0.0
        items.append(ItemResult(c.id, pos, ans, quote[:2000] if quote else None, seg_idx, reasoning, round(conf, 3),
                                repaired))

    flags = []
    for f in raw.get("flags") or []:
        if not isinstance(f, dict):
            continue
        ftype = _enum(f.get("type"), FLAG_TYPES, "other")
        idx = f.get("segment_idx")
        idx = idx if isinstance(idx, int) and idx in valid_idx else None
        flags.append({"type": ftype, "description": str(f.get("description") or "")[:500], "segment_idx": idx})

    def _s(key):
        v = raw.get(key)
        return str(v).strip()[:4000] if v not in (None, "") else None

    return ValidatedEvaluation(
        items=items,
        call_reason=(_s("call_reason") or "Other")[:200],
        resolution_status=_enum(raw.get("resolution_status"), RESOLUTION_VALUES, "unknown"),
        sentiment=_enum(raw.get("customer_sentiment") or raw.get("sentiment"), SENTIMENT_VALUES, "neutral"),
        summary_sw=_s("summary_sw"),
        summary_en=_s("summary_en"),
        flags=flags,
        repair_log=log,
    )
