from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import DB, client_ip, current_user, require_admin
from app.models import Agent, AuditLog, Call, Evaluation, ReviewNote, Scorecard, User
from app.models.enums import JobKind
from app.schemas import AgentOut, AuditOut, CallDetail, CallListItem, CallPage, EvaluationOut, NoteOut
from app.services.audit import audit
from app.services.call_query import CallFilters, base_query, filters_dep
from app.services.retention import delete_call_audio
from app.services.storage import get_storage

router = APIRouter(tags=["calls"])

SORTS = {"call_time", "score", "created_at", "duration_s"}


def list_item(call: Call, ev: Evaluation | None) -> CallListItem:
    item = CallListItem.model_validate(call)
    if ev is not None:
        item.score, item.passed, item.auto_fail = ev.score, ev.passed, ev.auto_fail
        item.call_reason, item.sentiment, item.resolution_status = ev.call_reason, ev.sentiment, ev.resolution_status
        item.flags = ev.flags or []
    return item


def get_call_or_404(db: Session, call_id: uuid.UUID) -> Call:
    call = db.get(Call, call_id)
    if not call:
        raise HTTPException(404, "Call not found")
    return call


def current_evaluation(db: Session, call_id: uuid.UUID) -> Evaluation | None:
    return db.scalar(
        select(Evaluation)
        .options(selectinload(Evaluation.items))
        .where(Evaluation.call_id == call_id, Evaluation.is_current.is_(True))
    )


def evaluation_out(ev: Evaluation) -> EvaluationOut:
    out = EvaluationOut.model_validate(ev)
    out.scorecard_name, out.scorecard_version = ev.scorecard.name, ev.scorecard.version
    return out


def build_detail(db: Session, call: Call) -> CallDetail:
    ev = current_evaluation(db, call.id)
    base = list_item(call, ev).model_dump()
    if ev:
        scorecard = ev.scorecard
    else:
        scorecard = db.scalar(select(Scorecard).where(Scorecard.is_active.is_(True)).order_by(Scorecard.id.desc()))
    notes = db.scalars(select(ReviewNote).where(ReviewNote.call_id == call.id).order_by(ReviewNote.created_at)).all()
    return CallDetail(
        **base,
        channels=call.channels,
        speech_s=call.speech_s,
        asr_provider=call.asr_provider,
        asr_model=call.asr_model,
        speaker_method=call.speaker_method,
        has_audio=bool(call.audio_playback_key or call.audio_original_key),
        assigned_to_id=call.assigned_to_id,
        reviewed_by_id=call.reviewed_by_id,
        reviewed_at=call.reviewed_at,
        meta=call.meta or {},
        segments=call.segments,
        evaluation=evaluation_out(ev) if ev else None,
        scorecard=(
            {"id": scorecard.id, "key": scorecard.key, "name": scorecard.name, "version": scorecard.version,
             "pass_threshold": scorecard.pass_threshold, **scorecard.definition}
            if scorecard else None
        ),
        notes=[NoteOut(**NoteOut.model_validate(n).model_dump(exclude={"author_name"}),
                       author_name=n.author.name if n.author else None) for n in notes],
    )


@router.get("/calls", response_model=CallPage)
def list_calls(
    f: CallFilters = Depends(filters_dep),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    sort: str = "call_time",
    order: str = Query("desc", pattern="^(asc|desc)$"),
    _: User = Depends(current_user),
    db: Session = DB,
):
    stmt, ev = base_query(f)
    total = db.scalar(select(func.count()).select_from(stmt.with_only_columns(Call.id).subquery()))
    col = ev.score if sort == "score" else getattr(Call, sort if sort in SORTS else "call_time")
    col = col.desc().nulls_last() if order == "desc" else col.asc().nulls_last()
    rows = db.execute(stmt.order_by(col, Call.id).offset((page - 1) * page_size).limit(page_size)).all()
    return CallPage(items=[list_item(c, e) for c, e in rows], total=total or 0, page=page, page_size=page_size)


@router.get("/calls/{call_id}", response_model=CallDetail)
def get_call(call_id: uuid.UUID, _: User = Depends(current_user), db: Session = DB):
    return build_detail(db, get_call_or_404(db, call_id))


_RANGE = re.compile(r"bytes=(\d*)-(\d*)")


@router.get("/calls/{call_id}/audio")
def call_audio(call_id: uuid.UUID, request: Request, _: User = Depends(current_user), db: Session = DB):
    """Stream the browser playback copy, honouring HTTP Range so seeking works."""
    call = get_call_or_404(db, call_id)
    key = call.audio_playback_key or call.audio_original_key
    if not key:
        raise HTTPException(410, "Audio has been deleted (retention policy)")
    storage = get_storage()
    size = storage.size(key)
    media = "audio/mpeg" if key.endswith(".mp3") else "application/octet-stream"
    start, end, code = 0, size - 1, 200
    m = _RANGE.match(request.headers.get("range", ""))
    if m and (m.group(1) or m.group(2)):
        if m.group(1):
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else size - 1
        else:  # suffix range
            start = max(0, size - int(m.group(2)))
        end = min(end, size - 1)
        if start > end:
            raise HTTPException(416, "Range not satisfiable")
        code = 206
    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1), "Cache-Control": "private, max-age=300"}
    if code == 206:
        headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(storage.open_range(key, start, end), status_code=code, media_type=media, headers=headers)


@router.get("/calls/{call_id}/history", response_model=dict)
def call_history(call_id: uuid.UUID, _: User = Depends(current_user), db: Session = DB):
    get_call_or_404(db, call_id)
    evs = db.scalars(select(Evaluation).options(selectinload(Evaluation.items))
                     .where(Evaluation.call_id == call_id).order_by(Evaluation.rev.desc())).all()
    logs = db.scalars(select(AuditLog).where(AuditLog.entity == "call", AuditLog.entity_id == str(call_id))
                      .order_by(AuditLog.at.desc()).limit(500)).all()
    return {
        "evaluations": [evaluation_out(e).model_dump(mode="json") for e in evs],
        "audit": [AuditOut(**AuditOut.model_validate(a).model_dump(exclude={"actor_name"}),
                           actor_name=a.actor.name if a.actor else None).model_dump(mode="json") for a in logs],
    }


@router.post("/calls/{call_id}/reprocess", status_code=202)
def reprocess(call_id: uuid.UUID, request: Request, from_stage: JobKind = Query(JobKind.prepare, alias="from"),
              admin: User = Depends(require_admin), db: Session = DB):
    from app.workers.jobs import STAGE_ORDER, active_job_exists, enqueue_stage

    call = get_call_or_404(db, call_id)
    if from_stage not in STAGE_ORDER:
        raise HTTPException(400, "Invalid stage")
    if call.audio_deleted_at and from_stage in (JobKind.prepare, JobKind.transcribe):
        raise HTTPException(409, "Audio was deleted; only labelling and scoring can be re-run")
    if active_job_exists(db, call.id):
        raise HTTPException(409, "This call is already being processed")
    call.status = "received"
    call.error = None
    audit(db, "call.reprocess", "call", call.id, user_id=admin.id, ip=client_ip(request), after={"from": from_stage})
    db.commit()
    job_id = enqueue_stage(call.id, from_stage)
    return {"job_id": job_id}


@router.delete("/calls/{call_id}", status_code=204)
def delete_call(call_id: uuid.UUID, request: Request, admin: User = Depends(require_admin), db: Session = DB):
    call = get_call_or_404(db, call_id)
    delete_call_audio(call)
    audit(db, "call.delete", "call", call.id, user_id=admin.id, ip=client_ip(request),
          before={"filename": call.original_filename, "external_id": call.external_id})
    db.delete(call)
    db.commit()


@router.get("/agents", response_model=list[AgentOut])
def list_agents(_: User = Depends(current_user), db: Session = DB):
    return db.scalars(select(Agent).where(Agent.is_active.is_(True)).order_by(Agent.name)).all()


@router.get("/queues", response_model=list[str])
def list_queues(_: User = Depends(current_user), db: Session = DB):
    return [q for q in db.scalars(select(Call.queue).where(Call.queue.is_not(None)).distinct().order_by(Call.queue))]
