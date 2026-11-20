"""Automatic deletion of audio after the configured retention period.

Transcripts (already redacted) and evaluations are kept for reporting; only the
audio objects are removed. Set the retention to 0 days to keep audio forever.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select

from app.db import session_scope, utcnow
from app.models import Call
from app.services.app_settings import get_runtime_settings
from app.services.audit import audit
from app.services.storage import get_storage

log = logging.getLogger(__name__)


def delete_call_audio(call: Call) -> None:
    storage = get_storage()
    for attr in ("audio_original_key", "audio_processed_key", "audio_playback_key"):
        key = getattr(call, attr)
        if key:
            try:
                storage.delete(key)
            except Exception:  # noqa: BLE001
                log.exception("could not delete %s", key)
            setattr(call, attr, None)
    call.audio_deleted_at = utcnow()


def purge_expired_audio(batch: int = 500) -> int:
    with session_scope() as db:
        days = get_runtime_settings(db).audio_retention_days
        if days <= 0:
            return 0
        cutoff = utcnow() - timedelta(days=days)
        calls = db.scalars(
            select(Call)
            .where(Call.audio_deleted_at.is_(None), Call.created_at < cutoff)
            .limit(batch)
        ).all()
        for call in calls:
            delete_call_audio(call)
        if calls:
            audit(db, "retention.purge_audio", "call", None, after={"count": len(calls), "days": days})
        return len(calls)
