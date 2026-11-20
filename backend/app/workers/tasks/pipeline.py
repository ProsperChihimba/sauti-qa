from __future__ import annotations

from app.models.enums import JobKind
from app.services import pipeline as stages
from app.workers.celery_app import celery
from app.workers.jobs import run_stage

_opts = dict(bind=True, acks_late=True, max_retries=5)


@celery.task(name="pipeline.prepare", **_opts)
def prepare(self, call_id: str, job_id: int) -> None:
    run_stage(self, call_id, job_id, JobKind.prepare, stages.prepare)


@celery.task(name="pipeline.transcribe", **_opts)
def transcribe(self, call_id: str, job_id: int) -> None:
    run_stage(self, call_id, job_id, JobKind.transcribe, stages.transcribe)


@celery.task(name="pipeline.label", **_opts)
def label(self, call_id: str, job_id: int) -> None:
    run_stage(self, call_id, job_id, JobKind.label, stages.label)


@celery.task(name="pipeline.score", **_opts)
def score(self, call_id: str, job_id: int) -> None:
    run_stage(self, call_id, job_id, JobKind.score, stages.score)
