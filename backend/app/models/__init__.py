from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, TimestampMixin, utcnow
from app.models.enums import (
    CallStatus,
    JobStatus,
    NoteKind,
    ReviewStatus,
    Speaker,
)

# JSONB on Postgres, JSON elsewhere.
JSONType = JSON().with_variant(JSONB(), "postgresql")


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Bumped on password reset / deactivation to invalidate existing sessions.
    token_version: Mapped[int] = mapped_column(Integer, default=0)


class ApiKey(TimestampMixin, Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    key_hash: Mapped[str] = mapped_column(String(128))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    external_ref: Mapped[str | None] = mapped_column(String(100))
    team: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Scorecard(TimestampMixin, Base):
    """Versioned scorecard. A saved version is never modified; edits create a new row."""

    __tablename__ = "scorecards"
    __table_args__ = (UniqueConstraint("key", "version", name="uq_scorecards_key_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), index=True)  # stable id across versions
    name: Mapped[str] = mapped_column(String(200))
    version: Mapped[int] = mapped_column(Integer, default=1)
    definition: Mapped[dict[str, Any]] = mapped_column(JSONType)
    pass_threshold: Mapped[float] = mapped_column(Float, default=80.0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Call(TimestampMixin, Base):
    __tablename__ = "calls"
    __table_args__ = (
        Index("ix_calls_call_time", "call_time"),
        Index("ix_calls_status_review", "status", "review_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    external_id: Mapped[str | None] = mapped_column(String(200), unique=True)
    source: Mapped[str] = mapped_column(String(20))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    original_filename: Mapped[str | None] = mapped_column(String(500))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"), index=True)
    queue: Mapped[str | None] = mapped_column(String(100), index=True)
    call_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    duration_s: Mapped[float | None] = mapped_column(Float)
    speech_s: Mapped[float | None] = mapped_column(Float)
    channels: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=CallStatus.received)
    review_status: Mapped[str] = mapped_column(String(20), default=ReviewStatus.not_required)
    review_reasons: Mapped[list[str]] = mapped_column(JSONType, default=list)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    audio_original_key: Mapped[str | None] = mapped_column(String(500))
    audio_processed_key: Mapped[str | None] = mapped_column(String(500))  # 16 kHz wav (stereo kept)
    audio_playback_key: Mapped[str | None] = mapped_column(String(500))  # mp3 for the browser
    audio_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    asr_provider: Mapped[str | None] = mapped_column(String(100))
    asr_model: Mapped[str | None] = mapped_column(String(200))
    speaker_method: Mapped[str | None] = mapped_column(String(50))  # stereo / llm / heuristic
    speech_regions: Mapped[list[list[float]] | None] = mapped_column(JSONType)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSONType, default=dict)
    error: Mapped[str | None] = mapped_column(Text)

    agent: Mapped[Agent | None] = relationship(lazy="joined")
    segments: Mapped[list[Segment]] = relationship(
        back_populates="call", order_by="Segment.idx", cascade="all, delete-orphan"
    )


class Segment(Base):
    __tablename__ = "segments"
    __table_args__ = (UniqueConstraint("call_id", "idx", name="uq_segments_call_idx"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    start_s: Mapped[float] = mapped_column(Float)
    end_s: Mapped[float] = mapped_column(Float)
    speaker: Mapped[str] = mapped_column(String(20), default=Speaker.unknown)
    speaker_raw: Mapped[str | None] = mapped_column(String(50))  # diarization label / channel
    text: Mapped[str] = mapped_column(Text)  # current (possibly corrected) redacted text
    asr_text: Mapped[str] = mapped_column(Text)  # original redacted ASR output
    confidence: Mapped[float | None] = mapped_column(Float)
    words: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONType)  # optional word timings
    has_redaction: Mapped[bool] = mapped_column(Boolean, default=False)
    redactions: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    edited_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    call: Mapped[Call] = relationship(back_populates="segments")


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        UniqueConstraint("call_id", "rev", name="uq_evaluations_call_rev"),
        Index("ix_evaluations_current", "call_id", "is_current"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    scorecard_id: Mapped[int] = mapped_column(ForeignKey("scorecards.id"))
    rev: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    trigger: Mapped[str] = mapped_column(String(20))
    llm_provider: Mapped[str] = mapped_column(String(50))
    llm_model: Mapped[str | None] = mapped_column(String(200))
    score: Mapped[float | None] = mapped_column(Float)
    points_earned: Mapped[float] = mapped_column(Float, default=0)
    points_applicable: Mapped[float] = mapped_column(Float, default=0)
    auto_fail: Mapped[bool] = mapped_column(Boolean, default=False)
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    call_reason: Mapped[str | None] = mapped_column(String(200))
    resolution_status: Mapped[str | None] = mapped_column(String(50))
    sentiment: Mapped[str | None] = mapped_column(String(50))
    summary_sw: Mapped[str | None] = mapped_column(Text)
    summary_en: Mapped[str | None] = mapped_column(Text)
    flags: Mapped[list[dict[str, Any]]] = mapped_column(JSONType, default=list)
    raw_output: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    repair_log: Mapped[list[str]] = mapped_column(JSONType, default=list)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    scorecard: Mapped[Scorecard] = relationship(lazy="joined")
    items: Mapped[list[EvaluationItem]] = relationship(
        back_populates="evaluation", cascade="all, delete-orphan", order_by="EvaluationItem.position"
    )


class EvaluationItem(Base):
    __tablename__ = "evaluation_items"
    __table_args__ = (UniqueConstraint("evaluation_id", "criterion_id", name="uq_eval_items_eval_crit"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("evaluations.id", ondelete="CASCADE"), index=True)
    criterion_id: Mapped[str] = mapped_column(String(100), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    answer: Mapped[str] = mapped_column(String(10))  # effective answer (after override)
    ai_answer: Mapped[str] = mapped_column(String(10))
    evidence_quote: Mapped[str | None] = mapped_column(Text)
    segment_idx: Mapped[int | None] = mapped_column(Integer)
    reasoning: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    repaired: Mapped[bool] = mapped_column(Boolean, default=False)
    overridden_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    override_reason: Mapped[str | None] = mapped_column(Text)
    overridden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    evaluation: Mapped[Evaluation] = relationship(back_populates="items")


class ReviewNote(TimestampMixin, Base):
    __tablename__ = "review_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20), default=NoteKind.note)
    body: Mapped[str] = mapped_column(Text)

    author: Mapped[User | None] = relationship(lazy="joined")


class Job(TimestampMixin, Base):
    """One pipeline stage execution. Gives failed-job visibility and stuck-job recovery."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_heartbeat", "status", "heartbeat_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    call_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="CASCADE"), index=True)
    export_id: Mapped[int | None] = mapped_column(ForeignKey("exports.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))
    queue: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.queued)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    celery_id: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Export(TimestampMixin, Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    filters: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(20), default=JobStatus.queued)
    file_key: Mapped[str | None] = mapped_column(String(500))
    filename: Mapped[str | None] = mapped_column(String(300))
    stats: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_entity", "entity", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_api_key_id: Mapped[int | None] = mapped_column(ForeignKey("api_keys.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100), index=True)
    entity: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str | None] = mapped_column(String(100))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    ip: Mapped[str | None] = mapped_column(String(64))

    actor: Mapped[User | None] = relationship(lazy="joined")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONType)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


__all__ = [
    "Agent",
    "ApiKey",
    "AppSetting",
    "AuditLog",
    "Call",
    "Evaluation",
    "EvaluationItem",
    "Export",
    "Job",
    "ReviewNote",
    "Scorecard",
    "Segment",
    "User",
]
