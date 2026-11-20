"""Celery application.

Queues:
  cpu          audio preparation, exports
  gpu          transcription + diarization (scale GPU workers independently)
  llm          speaker identification and scoring (network/IO bound)
  maintenance  stuck-job recovery, retention purge
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

s = get_settings()

celery = Celery("sauti", broker=s.redis_url, backend=None, include=["app.workers.tasks.pipeline",
                                                                     "app.workers.tasks.maintenance",
                                                                     "app.workers.tasks.exports"])
celery.conf.update(
    task_acks_late=True,  # a crashed worker leaves the message for another worker
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # long tasks: do not hoard messages
    task_default_queue="cpu",
    task_always_eager=s.celery_eager,
    task_eager_propagates=False,
    broker_connection_retry_on_startup=True,
    task_routes={
        "pipeline.prepare": {"queue": "cpu"},
        "pipeline.transcribe": {"queue": "gpu"},
        "pipeline.label": {"queue": "llm"},
        "pipeline.score": {"queue": "llm"},
        "exports.*": {"queue": "cpu"},
        "maintenance.*": {"queue": "maintenance"},
    },
    beat_schedule={
        "recover-stuck-jobs": {"task": "maintenance.recover_stuck_jobs", "schedule": 300.0},
        "purge-expired-audio": {"task": "maintenance.purge_expired_audio", "schedule": crontab(minute=17)},
    },
    timezone="UTC",
)
