"""Scoring service: run the LLM, validate, compute, route, and persist evaluations."""

from __future__ import annotations

import logging
from dataclasses import asdict

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Call, Evaluation, EvaluationItem, Scorecard
from app.models.enums import EvalTrigger, ReviewStatus
from app.services.app_settings import get_runtime_settings
from app.services.scoring.compute import compute_score
from app.services.scoring.llm import get_llm
from app.services.scoring.routing import review_reasons
from app.services.scoring.scorecard import ScorecardDefinition, definition_from_row, load_seed
from app.services.scoring.validate import validate_and_repair

log = logging.getLogger(__name__)


def ensure_default_scorecard(db: Session) -> Scorecard:
    sc = db.scalar(select(Scorecard).where(Scorecard.is_active.is_(True)).order_by(Scorecard.id.desc()))
    if sc:
        return sc
    seed = load_seed()
    sc = Scorecard(key="telecom-sw", name=seed.name, version=1, definition=seed.storage_dict(),
                   pass_threshold=seed.pass_threshold, is_active=True)
    db.add(sc)
    db.flush()
    return sc


def segment_dicts(call: Call) -> list[dict]:
    return [{"idx": s.idx, "speaker": s.speaker, "speaker_raw": s.speaker_raw, "start_s": s.start_s,
             "end_s": s.end_s, "text": s.text} for s in call.segments]


def apply_routing(db: Session, call: Call, ev: Evaluation, sc_def: ScorecardDefinition) -> None:
    cfg = get_runtime_settings(db)
    result = compute_score(sc_def, ev.items)
    reasons = review_reasons(result, ev.items, ev.flags or [], cfg, ev.repair_log)
    call.review_reasons = reasons
    if call.review_status in (ReviewStatus.in_review, ReviewStatus.reviewed):
        return  # a human already owns this call
    call.review_status = ReviewStatus.pending if reasons else ReviewStatus.not_required


def recompute(ev: Evaluation, sc_def: ScorecardDefinition) -> None:
    r = compute_score(sc_def, ev.items)
    ev.score, ev.points_earned, ev.points_applicable = r.score, r.points_earned, r.points_applicable
    ev.auto_fail, ev.passed = r.auto_fail, r.passed


def score_call(db: Session, call: Call, *, user_id: int | None = None) -> Evaluation:
    """Evaluate the call's current transcript with the active scorecard.

    Creates a new evaluation revision. Human overrides on the previous revision are
    carried over (the new AI answer is kept in ai_answer for comparison)."""
    sc_row = ensure_default_scorecard(db)
    sc_def = definition_from_row(sc_row)
    segments = segment_dicts(call)
    if not segments:
        raise ValueError("Call has no transcript to score")
    llm = get_llm()
    meta = {"queue": call.queue, "duration_s": call.duration_s, "speaker_method": call.speaker_method}
    raw = llm.evaluate(sc_def, segments, meta)
    v = validate_and_repair(raw, sc_def, segments)
    if v.repair_log:
        log.info("call %s: repaired LLM output: %s", call.id, "; ".join(v.repair_log))

    prev = db.scalar(select(Evaluation).where(Evaluation.call_id == call.id, Evaluation.is_current.is_(True)))
    overrides = {}
    if prev is not None:
        overrides = {i.criterion_id: i for i in prev.items if i.overridden_by_id is not None}
    rev = (db.scalar(select(func.max(Evaluation.rev)).where(Evaluation.call_id == call.id)) or 0) + 1
    db.execute(update(Evaluation).where(Evaluation.call_id == call.id).values(is_current=False))

    ev = Evaluation(
        call_id=call.id, scorecard_id=sc_row.id, rev=rev, is_current=True,
        trigger=EvalTrigger.rescore if prev is not None else EvalTrigger.pipeline,
        llm_provider=llm.name, llm_model=llm.model, call_reason=v.call_reason,
        resolution_status=v.resolution_status, sentiment=v.sentiment, summary_sw=v.summary_sw,
        summary_en=v.summary_en, flags=v.flags, raw_output=raw if isinstance(raw, dict) else None,
        repair_log=v.repair_log, created_by_id=user_id,
    )
    for it in v.items:
        item = EvaluationItem(**{k: val for k, val in asdict(it).items()}, ai_answer=it.answer)
        o = overrides.get(it.criterion_id)
        if o is not None:
            item.answer, item.overridden_by_id = o.answer, o.overridden_by_id
            item.override_reason, item.overridden_at = o.override_reason, o.overridden_at
        ev.items.append(item)
    recompute(ev, sc_def)
    db.add(ev)
    db.flush()
    apply_routing(db, call, ev, sc_def)
    return ev


def override_item(db: Session, ev: Evaluation, criterion_id: str, answer: str, reason: str | None,
                  user_id: int) -> EvaluationItem:
    sc_def = definition_from_row(ev.scorecard)
    crit = sc_def.by_id().get(criterion_id)
    if crit is None:
        raise KeyError(criterion_id)
    if answer not in ("yes", "no", "na"):
        raise ValueError("answer must be yes, no or na")
    if answer == "na" and not crit.allow_na:
        raise ValueError("This criterion does not allow N/A")
    item = next(i for i in ev.items if i.criterion_id == criterion_id)
    if answer == item.ai_answer and not reason:
        # Reverting to the AI answer clears the override.
        item.answer, item.overridden_by_id, item.override_reason, item.overridden_at = answer, None, None, None
    else:
        item.answer, item.overridden_by_id, item.override_reason, item.overridden_at = answer, user_id, reason, utcnow()
    recompute(ev, sc_def)
    return item
