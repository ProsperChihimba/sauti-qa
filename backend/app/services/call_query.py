"""Shared call filtering used by the calls list, dashboard and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from fastapi import Query
from sqlalchemy import Select, and_, false, or_, select
from sqlalchemy.orm import aliased

from app.models import Agent, Call, Evaluation, Segment

EAT = timezone(timedelta(hours=3))  # reporting days follow Tanzanian time


@dataclass
class CallFilters:
    date_from: date | None = None
    date_to: date | None = None
    agent_ids: list[int] = field(default_factory=list)
    queues: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=list)
    review_status: list[str] = field(default_factory=list)
    min_score: float | None = None
    max_score: float | None = None
    auto_fail: bool | None = None
    flagged: bool | None = None
    passed: bool | None = None
    q: str | None = None

    def to_dict(self) -> dict:
        return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in self.__dict__.items()
                if v not in (None, [], "")}

    @classmethod
    def from_dict(cls, d: dict) -> CallFilters:
        d = dict(d or {})
        for k in ("date_from", "date_to"):
            if isinstance(d.get(k), str):
                d[k] = date.fromisoformat(d[k])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def filters_dep(
    date_from: date | None = None,
    date_to: date | None = None,
    agent_id: list[int] = Query(default=[]),
    queue: list[str] = Query(default=[]),
    status: list[str] = Query(default=[]),
    review_status: list[str] = Query(default=[]),
    min_score: float | None = None,
    max_score: float | None = None,
    auto_fail: bool | None = None,
    flagged: bool | None = None,
    passed: bool | None = None,
    q: str | None = None,
) -> CallFilters:
    return CallFilters(date_from, date_to, agent_id, queue, status, review_status, min_score, max_score,
                       auto_fail, flagged, passed, q)


def current_eval():
    return aliased(Evaluation, name="cur_eval")


def base_query(f: CallFilters, ev=None) -> tuple[Select, object]:
    """Calls joined (outer) with their current evaluation, filters applied."""
    ev = ev if ev is not None else current_eval()
    stmt = select(Call, ev).outerjoin(ev, and_(ev.call_id == Call.id, ev.is_current.is_(True)))
    return apply_filters(stmt, f, ev), ev


def apply_filters(stmt: Select, f: CallFilters, ev) -> Select:
    conds = []
    if f.date_from:
        conds.append(Call.call_time >= datetime.combine(f.date_from, time.min, EAT))
    if f.date_to:
        conds.append(Call.call_time < datetime.combine(f.date_to + timedelta(days=1), time.min, EAT))
    if f.agent_ids:
        conds.append(Call.agent_id.in_(f.agent_ids))
    if f.queues:
        conds.append(Call.queue.in_(f.queues))
    if f.status:
        conds.append(Call.status.in_(f.status))
    if f.review_status:
        conds.append(Call.review_status.in_(f.review_status))
    if f.min_score is not None:
        conds.append(ev.score >= f.min_score)
    if f.max_score is not None:
        conds.append(ev.score <= f.max_score)
    if f.auto_fail is not None:
        conds.append(ev.auto_fail.is_(f.auto_fail))
    if f.passed is not None:
        conds.append(ev.passed.is_(f.passed))
    if f.flagged is not None:
        from sqlalchemy import func

        n = func.coalesce(func.jsonb_array_length(ev.flags), 0)
        conds.append(n > 0 if f.flagged else n == 0)
    if f.q:
        like = f"%{f.q.strip()}%"
        seg_match = select(Segment.id).where(Segment.call_id == Call.id, Segment.text.ilike(like)).exists()
        agent_match = select(Agent.id).where(Agent.id == Call.agent_id, Agent.name.ilike(like)).exists()
        conds.append(or_(Call.original_filename.ilike(like), Call.external_id.ilike(like), agent_match, seg_match,
                         ev.call_reason.ilike(like) if ev is not None else false()))
    return stmt.where(and_(*conds)) if conds else stmt
