"""Decide whether a call needs a human reviewer."""

from __future__ import annotations

from app.services.app_settings import RuntimeSettings
from app.services.scoring.compute import ScoreResult


def review_reasons(result: ScoreResult, items: list, flags: list[dict], cfg: RuntimeSettings,
                   repair_log: list[str] | None = None) -> list[str]:
    reasons: list[str] = []
    if cfg.review_on_auto_fail and result.auto_fail:
        reasons.append("auto_fail")
    if cfg.review_on_flags:
        for t in sorted({f["type"] for f in flags}):
            reasons.append(f"flag:{t}")
    if result.score is None:
        reasons.append("unscorable")
    elif result.score < cfg.review_score_threshold:
        reasons.append("low_score")
    if any(it.confidence < cfg.review_confidence_threshold for it in items):
        reasons.append("low_confidence")
    if any(getattr(it, "repaired", False) for it in items):
        reasons.append("repaired_output")
    return reasons
