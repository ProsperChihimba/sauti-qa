from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select

from app.config import get_settings
from app.db import session_scope, utcnow
from app.models import Job
from app.models.enums import JobStatus
from app.workers.celery_app import celery
from app.workers.jobs import _send

log = logging.getLogger(__name__)


def recover_stuck_jobs_now() -> list[int]:
    """Re-send jobs whose worker died (running with a stale heartbeat) or that were lost
    from the broker (queued for too long). Returns the recovered job ids."""
    s = get_settings()
    cutoff = utcnow() - timedelta(minutes=s.job_stuck_minutes)
    recovered: list[tuple[int, str, str]] = []
    with session_scope() as db:
        stuck = db.scalars(
            select(Job).where(
                Job.call_id.is_not(None),
                (
                    (Job.status == JobStatus.running) & (Job.heartbeat_at < cutoff)
                ) | (
                    (Job.status == JobStatus.queued) & (Job.updated_at < cutoff)
                ),
            )
        ).all()
        for job in stuck:
            if job.attempts >= s.job_max_attempts:
                job.status = JobStatus.failed
                job.error = (job.error or "") + "\nGave up after repeated stalls."
                job.finished_at = utcnow()
                continue
            job.status = JobStatus.queued
            job.heartbeat_at = utcnow()
            recovered.append((job.id, job.kind, str(job.call_id)))
    for job_id, kind, call_id in recovered:
        log.warning("recovering stuck job %s (%s) for call %s", job_id, kind, call_id)
        _send(kind, call_id, job_id)
    return [r[0] for r in recovered]


@celery.task(name="maintenance.recover_stuck_jobs")
def recover_stuck_jobs() -> list[int]:
    return recover_stuck_jobs_now()


@celery.task(name="maintenance.purge_expired_audio")
def purge_expired_audio() -> int:
    from app.services.retention import purge_expired_audio as purge

    return purge()
