from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import DB, client_ip, current_user
from app.api.routes.calls import build_detail, current_evaluation, evaluation_out, get_call_or_404
from app.db import utcnow
from app.models import Call, Evaluation, ReviewNote, Segment, User
from app.models.enums import JobKind, ReviewStatus, Role, Speaker
from app.schemas import CallDetail, CallPage, EvaluationOut, NoteOut, SegmentOut
from app.services.audit import audit
from app.services.call_query import CallFilters, base_query, filters_dep
from app.services.redaction import redact
from app.services.scoring import apply_routing, override_item
from app.services.scoring.scorecard import definition_from_row

router = APIRouter(tags=["review"])


def _priority(ev):
    """Most urgent first: auto-fails, then flagged, then lowest score."""
    flagged = func.coalesce(func.jsonb_array_length(ev.flags), 0) > 0
    return [
        case((ev.auto_fail.is_(True), 0), else_=1),
        case((flagged, 0), else_=1),
        ev.score.asc().nulls_first(),
        Call.call_time.asc(),
    ]


@router.get("/review/queue", response_model=CallPage)
def review_queue(f: CallFilters = Depends(filters_dep), mine: bool = False, page: int = 1, page_size: int = 50,
                 user: User = Depends(current_user), db: Session = DB):
    from app.api.routes.calls import list_item

    if not f.review_status:
        f.review_status = [ReviewStatus.pending, ReviewStatus.in_review]
    stmt, ev = base_query(f)
    if mine:
        stmt = stmt.where(Call.assigned_to_id == user.id)
    total = db.scalar(select(func.count()).select_from(stmt.with_only_columns(Call.id).subquery())) or 0
    rows = db.execute(stmt.order_by(*_priority(ev)).offset((page - 1) * page_size).limit(page_size)).all()
    return CallPage(items=[list_item(c, e) for c, e in rows], total=total, page=page, page_size=page_size)


def claim_next(db: Session, user: User, f: CallFilters | None = None, exclude: uuid.UUID | None = None) -> Call | None:
    """Claim the most urgent pending call (or one already assigned to this user).
    SKIP LOCKED lets several analysts pull from the queue at the same time."""
    f = f or CallFilters()
    f.review_status = [ReviewStatus.pending, ReviewStatus.in_review]
    stmt, ev = base_query(f)
    stmt = stmt.where(or_(Call.assigned_to_id.is_(None), Call.assigned_to_id == user.id,
                          Call.review_status == ReviewStatus.pending))
    if exclude:
        stmt = stmt.where(Call.id != exclude)
    stmt = stmt.order_by(case((Call.assigned_to_id == user.id, 0), else_=1), *_priority(ev)).limit(1)
    stmt = stmt.with_for_update(of=Call, skip_locked=True)
    row = db.execute(stmt).first()
    if not row:
        return None
    call = row[0]
    call.review_status = ReviewStatus.in_review
    call.assigned_to_id = user.id
    db.commit()
    return call


@router.post("/review/next")
def review_next(f: CallFilters = Depends(filters_dep), user: User = Depends(current_user), db: Session = DB):
    call = claim_next(db, user, f)
    if not call:
        return Response(status_code=204)
    return {"call_id": str(call.id)}


@router.post("/calls/{call_id}/review/claim", response_model=CallDetail)
def claim(call_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = DB):
    call = get_call_or_404(db, call_id)
    if call.review_status == ReviewStatus.in_review and call.assigned_to_id not in (None, user.id) \
            and user.role != Role.admin:
        raise HTTPException(409, "Another analyst is reviewing this call")
    call.review_status = ReviewStatus.in_review
    call.assigned_to_id = user.id
    audit(db, "review.claim", "call", call.id, user_id=user.id, ip=client_ip(request))
    db.commit()
    return build_detail(db, call)


@router.post("/calls/{call_id}/review/release", status_code=204)
def release(call_id: uuid.UUID, user: User = Depends(current_user), db: Session = DB):
    call = get_call_or_404(db, call_id)
    if call.review_status == ReviewStatus.in_review:
        call.review_status = ReviewStatus.pending
        call.assigned_to_id = None
        db.commit()


class CompleteIn(BaseModel):
    note: str | None = Field(default=None, max_length=10000)
    next: bool = True


@router.post("/calls/{call_id}/review/complete")
def complete(call_id: uuid.UUID, body: CompleteIn, request: Request, user: User = Depends(current_user),
             db: Session = DB):
    call = get_call_or_404(db, call_id)
    if body.note and body.note.strip():
        db.add(ReviewNote(call_id=call.id, author_id=user.id, body=body.note.strip()))
    ev = current_evaluation(db, call.id)
    call.review_status = ReviewStatus.reviewed
    call.reviewed_by_id = user.id
    call.reviewed_at = utcnow()
    call.assigned_to_id = user.id
    audit(db, "review.complete", "call", call.id, user_id=user.id, ip=client_ip(request),
          after={"score": ev.score if ev else None, "passed": ev.passed if ev else None})
    db.commit()
    nxt = claim_next(db, user, exclude=call.id) if body.next else None
    return {"next_call_id": str(nxt.id) if nxt else None}


# ---------------------------------------------------------------- transcript edits
class SegmentPatch(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=5000)
    speaker: Literal["agent", "customer", "unknown"] | None = None


@router.patch("/calls/{call_id}/segments/{segment_id}", response_model=SegmentOut)
def edit_segment(call_id: uuid.UUID, segment_id: int, body: SegmentPatch, request: Request,
                 user: User = Depends(current_user), db: Session = DB):
    seg = db.get(Segment, segment_id)
    if not seg or seg.call_id != call_id:
        raise HTTPException(404, "Segment not found")
    before = {"text": seg.text, "speaker": seg.speaker}
    if body.text is not None:
        # Corrections are redacted too: analysts may type numbers they hear.
        r = redact(" ".join(body.text.split()))
        seg.text = r.text
        # Once a segment's audio is known to contain PII it stays excluded from datasets.
        seg.has_redaction = seg.has_redaction or r.redacted
        seg.redactions = r.as_json()
    if body.speaker is not None:
        seg.speaker = body.speaker
    seg.edited_by_id, seg.edited_at = user.id, utcnow()
    audit(db, "transcript.edit", "call", call_id, user_id=user.id, ip=client_ip(request), before=before,
          after={"segment": seg.idx, "text": seg.text, "speaker": seg.speaker})
    db.commit()
    return seg


@router.post("/calls/{call_id}/speakers/swap", response_model=list[SegmentOut])
def swap_speakers(call_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = DB):
    call = get_call_or_404(db, call_id)
    swap = {Speaker.agent: Speaker.customer, Speaker.customer: Speaker.agent}
    for seg in call.segments:
        seg.speaker = swap.get(Speaker(seg.speaker), seg.speaker)
        seg.edited_by_id, seg.edited_at = user.id, utcnow()
    audit(db, "transcript.swap_speakers", "call", call.id, user_id=user.id, ip=client_ip(request))
    db.commit()
    return call.segments


# ---------------------------------------------------------------- overrides / rescore
class OverrideIn(BaseModel):
    answer: Literal["yes", "no", "na"]
    reason: str | None = Field(default=None, max_length=2000)


@router.patch("/calls/{call_id}/evaluation/items/{criterion_id}", response_model=EvaluationOut)
def override(call_id: uuid.UUID, criterion_id: str, body: OverrideIn, request: Request,
             user: User = Depends(current_user), db: Session = DB):
    call = get_call_or_404(db, call_id)
    ev = current_evaluation(db, call.id)
    if not ev:
        raise HTTPException(404, "Call has not been scored")
    item = next((i for i in ev.items if i.criterion_id == criterion_id), None)
    if not item:
        raise HTTPException(404, "Criterion not in this evaluation")
    before = {"criterion": criterion_id, "answer": item.answer, "score": ev.score}
    try:
        override_item(db, ev, criterion_id, body.answer, body.reason, user.id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    apply_routing(db, call, ev, definition_from_row(ev.scorecard))
    audit(db, "evaluation.override", "call", call.id, user_id=user.id, ip=client_ip(request), before=before,
          after={"criterion": criterion_id, "answer": body.answer, "reason": body.reason, "score": ev.score,
                 "ai_answer": item.ai_answer})
    db.commit()
    db.refresh(ev)
    return evaluation_out(ev)


@router.post("/calls/{call_id}/rescore", status_code=202)
def rescore(call_id: uuid.UUID, request: Request, user: User = Depends(current_user), db: Session = DB):
    """Re-run AI scoring on the (corrected) transcript. Human overrides are kept."""
    from app.workers.jobs import active_job_exists, enqueue_stage

    call = get_call_or_404(db, call_id)
    if not call.segments:
        raise HTTPException(409, "Call has no transcript yet")
    if active_job_exists(db, call.id):
        raise HTTPException(409, "This call is already being processed")
    call.meta = {**(call.meta or {}), "rescore_requested_by": user.id}
    audit(db, "evaluation.rescore", "call", call.id, user_id=user.id, ip=client_ip(request))
    db.commit()
    job_id = enqueue_stage(call.id, JobKind.score)
    return {"job_id": job_id}


# ---------------------------------------------------------------- notes
class NoteIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    kind: Literal["note", "coaching"] = "note"


@router.post("/calls/{call_id}/notes", response_model=NoteOut, status_code=201)
def add_note(call_id: uuid.UUID, body: NoteIn, request: Request, user: User = Depends(current_user),
             db: Session = DB):
    get_call_or_404(db, call_id)
    note = ReviewNote(call_id=call_id, author_id=user.id, body=body.body.strip(), kind=body.kind)
    db.add(note)
    db.flush()
    audit(db, "note.add", "call", call_id, user_id=user.id, ip=client_ip(request),
          after={"kind": body.kind, "body": note.body[:500]})
    db.commit()
    return NoteOut(**NoteOut.model_validate(note).model_dump(exclude={"author_name"}), author_name=user.name)


@router.delete("/calls/{call_id}/notes/{note_id}", status_code=204)
def delete_note(call_id: uuid.UUID, note_id: int, request: Request, user: User = Depends(current_user),
                db: Session = DB):
    note = db.get(ReviewNote, note_id)
    if not note or note.call_id != call_id:
        raise HTTPException(404, "Note not found")
    if note.author_id != user.id and user.role != Role.admin:
        raise HTTPException(403, "Only the author or an admin can delete a note")
    audit(db, "note.delete", "call", call_id, user_id=user.id, ip=client_ip(request), before={"body": note.body[:500]})
    db.delete(note)
    db.commit()


@router.get("/calls/{call_id}/evaluations/{rev}", response_model=EvaluationOut)
def get_revision(call_id: uuid.UUID, rev: int, _: User = Depends(current_user), db: Session = DB):
    ev = db.scalar(select(Evaluation).where(Evaluation.call_id == call_id, Evaluation.rev == rev))
    if not ev:
        raise HTTPException(404, "Revision not found")
    return evaluation_out(ev)
