"""Score maths. The score is always computed here, never by the model.

score = points earned / applicable points * 100
  - "yes" earns the criterion weight
  - "no" earns 0 but counts as applicable
  - "na" is excluded from both
Any critical criterion answered "no" is an auto-fail: score 0.
If nothing is applicable the call cannot be scored (score None).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.services.scoring.scorecard import ScorecardDefinition


class HasAnswer(Protocol):
    criterion_id: str
    answer: str


@dataclass
class ScoreResult:
    score: float | None
    points_earned: float
    points_applicable: float
    auto_fail: bool
    passed: bool
    failed_critical: list[str]


def compute_score(sc: ScorecardDefinition, items: list[HasAnswer]) -> ScoreResult:
    crit = sc.by_id()
    earned = applicable = 0.0
    failed_critical = []
    for it in items:
        c = crit.get(it.criterion_id)
        if c is None:
            continue
        if it.answer == "yes":
            earned += c.weight
            applicable += c.weight
        elif it.answer == "no":
            applicable += c.weight
            if c.critical:
                failed_critical.append(c.id)
    auto_fail = bool(failed_critical)
    if auto_fail:
        score: float | None = 0.0
    elif applicable == 0:
        score = None
    else:
        score = round(earned / applicable * 100, 2)
    passed = (not auto_fail) and score is not None and score >= sc.pass_threshold
    return ScoreResult(score, earned, applicable, auto_fail, passed, failed_critical)
