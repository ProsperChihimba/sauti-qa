"""Common intake for all three ingestion paths (browser upload, inbox folder, REST API)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Agent, Call
from app.models.enums import CallSource, CallStatus
from app.services.audit import audit
from app.services.storage import get_storage

log = logging.getLogger(__name__)


class IngestError(ValueError):
    pass


class CallMetadata(BaseModel):
    """Metadata accepted from the JSON sidecar, the API, or the upload form."""

    model_config = ConfigDict(extra="allow")

    agent_name: str | None = Field(default=None, max_length=200)
    queue: str | None = Field(default=None, max_length=100)
    call_time: datetime | None = None
    external_id: str | None = Field(default=None, max_length=200)
    agent_channel: str | None = Field(default=None, pattern="^(left|right)$")

    @field_validator("agent_name", "queue", "external_id", mode="before")
    @classmethod
    def _strip(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return v or None
        if isinstance(v, int | float):
            return str(v)
        return v

    @field_validator("call_time")
    @classmethod
    def _tz(cls, v: datetime | None) -> datetime | None:
        if v is not None and v.tzinfo is None:
            # Recorder timestamps without zone are assumed to be East Africa Time (UTC+3).
            from datetime import timedelta, timezone

            v = v.replace(tzinfo=timezone(timedelta(hours=3)))
        return v

    def extras(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


@dataclass
class IngestResult:
    call: Call
    created: bool
    duplicate_of: uuid.UUID | None = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def get_or_create_agent(db: Session, name: str | None) -> Agent | None:
    if not name:
        return None
    agent = db.scalar(select(Agent).where(Agent.name.ilike(name)))
    if agent is None:
        agent = Agent(name=name)
        db.add(agent)
        db.flush()
    return agent


def ingest_file(
    db: Session,
    path: Path,
    *,
    filename: str,
    source: CallSource,
    meta: CallMetadata | None = None,
    user_id: int | None = None,
    api_key_id: int | None = None,
    enqueue: bool = True,
) -> IngestResult:
    """Store an audio file, create the call and start the pipeline.

    Idempotent: re-sending the same external_id returns the existing call, and an
    identical file (same SHA-256) is not processed twice.
    """
    s = get_settings()
    meta = meta or CallMetadata()
    ext = Path(filename).suffix.lower()
    if ext not in s.allowed_audio_ext:
        raise IngestError(f"Unsupported file type '{ext}'. Allowed: {', '.join(s.allowed_audio_ext)}")
    size = path.stat().st_size
    if size == 0:
        raise IngestError("Empty file")
    if size > s.max_upload_mb * 1024 * 1024:
        raise IngestError(f"File larger than {s.max_upload_mb} MB")

    if meta.external_id:
        existing = db.scalar(select(Call).where(Call.external_id == meta.external_id))
        if existing:
            return IngestResult(existing, created=False, duplicate_of=existing.id)

    digest = sha256_file(path)
    existing = db.scalar(select(Call).where(Call.sha256 == digest).limit(1))
    if existing:
        return IngestResult(existing, created=False, duplicate_of=existing.id)

    call_id = uuid.uuid4()
    key = f"calls/{call_id}/original{ext}"
    get_storage().put_file(key, path)

    agent = get_or_create_agent(db, meta.agent_name)
    extra = meta.extras()
    if meta.agent_channel:
        extra["agent_channel"] = meta.agent_channel
    call = Call(
        id=call_id,
        external_id=meta.external_id,
        source=source,
        sha256=digest,
        original_filename=Path(filename).name[:500],
        agent_id=agent.id if agent else None,
        queue=meta.queue,
        call_time=meta.call_time or datetime.now(UTC),
        status=CallStatus.received,
        audio_original_key=key,
        meta=extra,
    )
    db.add(call)
    audit(db, "call.ingest", "call", call_id, user_id=user_id, api_key_id=api_key_id,
          after={"source": str(source), "filename": call.original_filename, "external_id": meta.external_id})
    db.commit()

    if enqueue:
        from app.workers.jobs import enqueue_pipeline

        enqueue_pipeline(call_id)
        db.refresh(call)
    return IngestResult(call, created=True)
