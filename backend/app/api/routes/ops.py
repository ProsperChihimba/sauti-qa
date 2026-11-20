from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import DB, client_ip, current_user, require_admin
from app.models import AuditLog, Job, User
from app.models.enums import JobStatus
from app.schemas import AuditOut, JobOut, Page
from app.services.app_settings import RuntimeSettings, get_runtime_settings, update_runtime_settings
from app.services.audit import audit

router = APIRouter(tags=["ops"])


@router.get("/jobs", response_model=Page[JobOut])
def list_jobs(status: list[str] = Query(default=[]), call_id: str | None = None,
              page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
              _: User = Depends(current_user), db: Session = DB):
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status.in_(status))
    if call_id:
        stmt = stmt.where(Job.call_id == call_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(Job.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    return Page[JobOut](items=items, total=total or 0, page=page, page_size=page_size)


@router.get("/jobs/summary")
def jobs_summary(_: User = Depends(current_user), db: Session = DB) -> dict[str, Any]:
    rows = db.execute(select(Job.kind, Job.status, func.count()).group_by(Job.kind, Job.status)).all()
    out: dict[str, dict[str, int]] = {}
    for kind, status, n in rows:
        out.setdefault(kind, {})[status] = n
    return out


@router.post("/jobs/{job_id}/retry", status_code=202)
def retry(job_id: int, request: Request, admin: User = Depends(require_admin), db: Session = DB):
    from app.workers.jobs import active_job_exists, retry_job

    job = db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != JobStatus.failed:
        raise HTTPException(409, "Only failed jobs can be retried")
    if job.call_id is None:
        raise HTTPException(400, "Re-run the export instead")
    if active_job_exists(db, job.call_id):
        raise HTTPException(409, "This call is already being processed")
    audit(db, "job.retry", "call", job.call_id, user_id=admin.id, ip=client_ip(request), after={"job": job_id})
    new_id = retry_job(db, job)
    return {"job_id": new_id}


@router.post("/jobs/recover", status_code=200)
def recover(_: User = Depends(require_admin)):
    from app.workers.tasks.maintenance import recover_stuck_jobs_now

    return {"recovered": recover_stuck_jobs_now()}


@router.get("/settings", response_model=RuntimeSettings)
def read_settings(_: User = Depends(current_user), db: Session = DB):
    return get_runtime_settings(db)


@router.put("/settings", response_model=RuntimeSettings)
def write_settings(body: dict[str, Any], request: Request, admin: User = Depends(require_admin), db: Session = DB):
    before = get_runtime_settings(db).model_dump()
    try:
        after = update_runtime_settings(db, body)
    except ValidationError as exc:
        raise HTTPException(422, exc.errors(include_url=False)) from exc
    audit(db, "settings.update", "settings", "runtime", user_id=admin.id, ip=client_ip(request),
          before=before, after=after.model_dump())
    db.commit()
    return after


@router.get("/audit", response_model=Page[AuditOut])
def audit_log(action: str | None = None, entity: str | None = None, entity_id: str | None = None,
              user_id: int | None = None, page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
              _: User = Depends(require_admin), db: Session = DB):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if user_id:
        stmt = stmt.where(AuditLog.actor_user_id == user_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(AuditLog.at.desc()).offset((page - 1) * page_size).limit(page_size)).all()
    items = [AuditOut(**AuditOut.model_validate(a).model_dump(exclude={"actor_name"}),
                      actor_name=a.actor.name if a.actor else None) for a in rows]
    return Page[AuditOut](items=items, total=total or 0, page=page, page_size=page_size)
