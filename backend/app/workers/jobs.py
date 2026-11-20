"""Job bookkeeping shared by all pipeline stages.

Every stage execution has a row in `jobs`, so the UI can show what is queued,
running, failed, and the maintenance task can find stuck work. Stages are
idempotent: running one twice must produce the same result.
"""

from __future__ import annotations

import logging
import traceback
import uuid
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import session_scope, utcnow
from app.models import Call, Job
from app.models.enums import CallStatus, JobKind, JobStatus

log = logging.getLogger(__name__)

STAGE_ORDER: list[JobKind] = [JobKind.prepare, JobKind.transcribe, JobKind.label, JobKind.score]
STAGE_QUEUE = {
    JobKind.prepare: "cpu",
    JobKind.transcribe: "gpu",
    JobKind.label: "llm",
    JobKind.score: "llm",
}
STAGE_STATUS = {
    JobKind.prepare: CallStatus.preparing,
    JobKind.transcribe: CallStatus.transcribing,
    JobKind.label: CallStatus.labelling,
    JobKind.score: CallStatus.scoring,
}


class PermanentError(Exception):
    """An error that retrying will not fix (corrupt audio, invalid scorecard...)."""


def next_stage(kind: JobKind) -> JobKind | None:
    i = STAGE_ORDER.index(kind)
    return STAGE_ORDER[i + 1] if i + 1 < len(STAGE_ORDER) else None


def _send(kind: JobKind, call_id: str, job_id: int) -> str | None:
    from app.workers.tasks import pipeline

    task = {
        JobKind.prepare: pipeline.prepare,
        JobKind.transcribe: pipeline.transcribe,
        JobKind.label: pipeline.label,
        JobKind.score: pipeline.score,
    }[kind]
    res = task.apply_async(args=[call_id, job_id])
    return res.id


def enqueue_stage(call_id: uuid.UUID | str, kind: JobKind) -> int:
    """Create a job row (committed) and send the task. Callers must commit the call first."""
    with session_scope() as db:
        job = Job(call_id=uuid.UUID(str(call_id)), kind=kind, queue=STAGE_QUEUE[kind], status=JobStatus.queued)
        db.add(job)
        db.flush()
        job_id = job.id
    celery_id = _send(kind, str(call_id), job_id)
    if celery_id:
        with session_scope() as db:
            j = db.get(Job, job_id)
            if j and j.celery_id is None:
                j.celery_id = celery_id
    return job_id


def enqueue_pipeline(call_id: uuid.UUID | str, from_stage: JobKind = JobKind.prepare) -> int:
    return enqueue_stage(call_id, from_stage)


def heartbeat(job_id: int) -> None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job:
            job.heartbeat_at = utcnow()


StageFn = Callable[[Session, Call, Callable[[], None]], None]


def run_stage(task, call_id: str, job_id: int, kind: JobKind, fn: StageFn, *, chain: bool = True) -> None:
    """Execute one stage with job tracking, retries and failure reporting."""
    s = get_settings()
    with session_scope() as db:
        job = db.get(Job, job_id)
        call = db.get(Call, uuid.UUID(call_id))
        if job is None or call is None:
            log.warning("job %s / call %s vanished; skipping", job_id, call_id)
            return
        if job.status == JobStatus.succeeded:
            return  # duplicate delivery (acks_late): already done
        job.status = JobStatus.running
        job.attempts += 1
        job.started_at = job.started_at or utcnow()
        job.heartbeat_at = utcnow()
        job.celery_id = getattr(task.request, "id", None) or job.celery_id
        call.status = STAGE_STATUS[kind]
        call.error = None
        attempts = job.attempts

    try:
        with session_scope() as db:
            call = db.get(Call, uuid.UUID(call_id))
            fn(db, call, lambda: heartbeat(job_id))
    except Exception as exc:  # noqa: BLE001 - we record every failure
        permanent = isinstance(exc, PermanentError)
        retry = not permanent and attempts < s.job_max_attempts and not s.celery_eager
        detail = f"{type(exc).__name__}: {exc}"
        log.exception("stage %s failed for call %s (attempt %s)", kind, call_id, attempts)
        with session_scope() as db:
            job = db.get(Job, job_id)
            call = db.get(Call, uuid.UUID(call_id))
            job.error = detail + "\n" + traceback.format_exc(limit=8)
            if retry:
                job.status = JobStatus.queued
            else:
                job.status = JobStatus.failed
                job.finished_at = utcnow()
                if call:
                    call.status = CallStatus.failed
                    call.error = f"{kind}: {detail}"
        if retry:
            raise task.retry(exc=exc, countdown=min(30 * 2 ** (attempts - 1), 600)) from exc
        return

    with session_scope() as db:
        job = db.get(Job, job_id)
        job.status = JobStatus.succeeded
        job.error = None
        job.finished_at = utcnow()
        nxt = next_stage(kind) if chain else None
        if nxt is None:
            call = db.get(Call, uuid.UUID(call_id))
            call.status = CallStatus.done
    if nxt is not None:
        enqueue_stage(call_id, nxt)


def retry_job(db: Session, job: Job) -> int:
    """Re-run a failed job's stage (and the rest of the pipeline)."""
    if job.call_id is None:
        raise ValueError("only pipeline jobs can be retried here")
    call = db.get(Call, job.call_id)
    call.status = CallStatus.received
    call.error = None
    db.commit()
    return enqueue_stage(job.call_id, JobKind(job.kind))


def active_job_exists(db: Session, call_id: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(Job.id).where(Job.call_id == call_id, Job.status.in_([JobStatus.queued, JobStatus.running]))
        )
        is not None
    )
