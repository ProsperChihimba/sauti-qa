"""Dashboard aggregations (shared with the Excel report)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from app.models import Agent, Call, EvaluationItem, Scorecard
from app.models.enums import ReviewStatus
from app.services.call_query import EAT, CallFilters, base_query


def _pct(n, d) -> float | None:
    return round(100.0 * n / d, 1) if d else None


def criterion_labels(db: Session) -> dict[str, dict[str, Any]]:
    """Latest label/section/weight per criterion id across all scorecards."""
    out: dict[str, dict[str, Any]] = {}
    for sc in db.scalars(select(Scorecard).order_by(Scorecard.version)):
        for c in sc.definition.get("criteria", []):
            out[c["id"]] = {"label": c.get("label", c["id"]), "section": c.get("section", ""),
                            "critical": bool(c.get("critical")), "weight": c.get("weight")}
    return out


def build_dashboard(db: Session, f: CallFilters) -> dict[str, Any]:
    stmt, ev = base_query(f)
    sub = stmt.with_only_columns(
        Call.id.label("call_id"), Call.agent_id, Call.duration_s, Call.status, Call.review_status, Call.call_time,
        ev.id.label("eval_id"), ev.score, ev.passed, ev.auto_fail, ev.call_reason, ev.resolution_status,
        ev.sentiment, func.coalesce(func.jsonb_array_length(ev.flags), 0).label("n_flags"),
    ).subquery()

    k = db.execute(select(
        func.count(),
        func.count(sub.c.eval_id),
        func.coalesce(func.sum(sub.c.duration_s), 0),
        func.avg(sub.c.score),
        func.sum(cast(sub.c.passed, Integer)),
        func.sum(cast(sub.c.auto_fail, Integer)),
        func.sum(cast(sub.c.review_status == ReviewStatus.pending, Integer)),
        func.sum(cast(sub.c.review_status == ReviewStatus.in_review, Integer)),
        func.sum(cast(sub.c.review_status == ReviewStatus.reviewed, Integer)),
        func.sum(cast(sub.c.n_flags > 0, Integer)),
        func.sum(cast(sub.c.status == "failed", Integer)),
        func.sum(cast(sub.c.eval_id.is_(None) & (sub.c.status != "failed"), Integer)),
    )).one()
    total, evaluated, seconds, avg, passed, auto_fail, pending, in_review, reviewed, flagged, failed, processing = (
        x or 0 for x in k)
    kpis = {
        "calls_total": total, "calls_evaluated": evaluated, "minutes": round(float(seconds) / 60, 1),
        "avg_score": round(float(avg), 1) if avg is not None else None, "pass_rate": _pct(passed, evaluated),
        "critical_breaches": auto_fail, "pending_review": pending + in_review, "reviewed": reviewed,
        "flagged": flagged, "failed_processing": failed, "processing": processing,
        "review_rate": _pct(pending + in_review + reviewed, evaluated),
    }

    labels = criterion_labels(db)
    rows = db.execute(
        select(EvaluationItem.criterion_id, EvaluationItem.answer, func.count(),
               func.sum(cast(EvaluationItem.overridden_by_id.is_not(None), Integer)))
        .join(sub, sub.c.eval_id == EvaluationItem.evaluation_id)
        .group_by(EvaluationItem.criterion_id, EvaluationItem.answer)
    ).all()
    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"yes": 0, "no": 0, "na": 0, "overridden": 0})
    for cid, ans, n, ov in rows:
        agg[cid][ans] += n
        agg[cid]["overridden"] += ov or 0
    criteria = []
    for cid, a in agg.items():
        applicable = a["yes"] + a["no"]
        meta = labels.get(cid, {"label": cid, "section": "", "critical": False})
        criteria.append({"criterion_id": cid, **meta, "yes": a["yes"], "no": a["no"], "na": a["na"],
                         "overridden": a["overridden"], "pass_rate": _pct(a["yes"], applicable)})
    criteria.sort(key=lambda c: (c["pass_rate"] if c["pass_rate"] is not None else 101, c["criterion_id"]))

    agents = [
        {"agent_id": aid, "agent": name or "Unassigned", "calls": n,
         "avg_score": round(float(avg_s), 1) if avg_s is not None else None,
         "pass_rate": _pct(p or 0, n_ev), "critical_breaches": af or 0, "minutes": round(float(sec or 0) / 60, 1)}
        for aid, name, n, n_ev, avg_s, p, af, sec in db.execute(
            select(sub.c.agent_id, Agent.name, func.count(), func.count(sub.c.eval_id), func.avg(sub.c.score),
                   func.sum(cast(sub.c.passed, Integer)), func.sum(cast(sub.c.auto_fail, Integer)),
                   func.sum(sub.c.duration_s))
            .outerjoin(Agent, Agent.id == sub.c.agent_id)
            .group_by(sub.c.agent_id, Agent.name)
        ).all()
    ]
    agents.sort(key=lambda a: (-(a["avg_score"] or -1), -a["calls"]))

    def counts(col):
        return [{"name": name or "Unknown", "count": n} for name, n in
                db.execute(select(col, func.count()).where(sub.c.eval_id.is_not(None)).group_by(col)
                           .order_by(func.count().desc())).all()]

    day = func.date(func.timezone("Africa/Dar_es_Salaam", sub.c.call_time))
    trend = [
        {"date": d.isoformat(), "calls": n, "avg_score": round(float(a), 1) if a is not None else None,
         "pass_rate": _pct(p or 0, ne)}
        for d, n, ne, a, p in db.execute(
            select(day, func.count(), func.count(sub.c.eval_id), func.avg(sub.c.score),
                   func.sum(cast(sub.c.passed, Integer))).group_by(day).order_by(day)
        ).all()
    ]
    return {
        "kpis": kpis,
        "criteria": criteria,
        "agents": agents,
        "call_reasons": counts(sub.c.call_reason),
        "resolution": counts(sub.c.resolution_status),
        "sentiment": counts(sub.c.sentiment),
        "trend": trend,
        "filters": f.to_dict(),
        "timezone": str(EAT),
    }
