from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# Internal domains (e.g. .local, .lan) are common on-prem, so only the basic shape is checked.
EmailStr = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=255,
                                            pattern=r"^[^@\s]+@[^@\s]+\.?[^@\s]*$")]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- auth / users ----------
class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORM):
    id: int
    email: str
    name: str
    role: Literal["admin", "analyst"]
    is_active: bool
    last_login_at: datetime | None = None
    created_at: datetime


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    role: Literal["admin", "analyst"] = "analyst"
    password: str


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Literal["admin", "analyst"] | None = None
    is_active: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class PasswordReset(BaseModel):
    new_password: str


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ApiKeyOut(ORM):
    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyOut):
    key: str  # shown once


# ---------- calls ----------
class AgentOut(ORM):
    id: int
    name: str
    team: str | None = None


class CallListItem(ORM):
    id: uuid.UUID
    external_id: str | None
    source: str
    original_filename: str | None
    agent: AgentOut | None
    queue: str | None
    call_time: datetime
    duration_s: float | None
    status: str
    review_status: str
    review_reasons: list[str]
    error: str | None
    created_at: datetime
    score: float | None = None
    passed: bool | None = None
    auto_fail: bool | None = None
    call_reason: str | None = None
    sentiment: str | None = None
    resolution_status: str | None = None
    flags: list[dict[str, Any]] = []


class CallPage(BaseModel):
    items: list[CallListItem]
    total: int
    page: int
    page_size: int


class SegmentOut(ORM):
    id: int
    idx: int
    start_s: float
    end_s: float
    speaker: str
    speaker_raw: str | None
    text: str
    asr_text: str
    confidence: float | None
    has_redaction: bool
    redactions: list[dict[str, Any]]
    edited_at: datetime | None


class EvaluationItemOut(ORM):
    criterion_id: str
    position: int
    answer: str
    ai_answer: str
    evidence_quote: str | None
    segment_idx: int | None
    reasoning: str | None
    confidence: float
    repaired: bool
    overridden_by_id: int | None
    override_reason: str | None
    overridden_at: datetime | None


class EvaluationOut(ORM):
    id: int
    rev: int
    scorecard_id: int
    scorecard_name: str | None = None
    scorecard_version: int | None = None
    trigger: str
    llm_provider: str
    llm_model: str | None
    score: float | None
    points_earned: float
    points_applicable: float
    auto_fail: bool
    passed: bool
    call_reason: str | None
    resolution_status: str | None
    sentiment: str | None
    summary_sw: str | None
    summary_en: str | None
    flags: list[dict[str, Any]]
    repair_log: list[str]
    created_at: datetime
    items: list[EvaluationItemOut]


class NoteOut(ORM):
    id: int
    kind: str
    body: str
    author_id: int | None
    author_name: str | None = None
    created_at: datetime


class CallDetail(CallListItem):
    channels: int | None
    speech_s: float | None
    asr_provider: str | None
    asr_model: str | None
    speaker_method: str | None
    has_audio: bool
    assigned_to_id: int | None
    reviewed_by_id: int | None
    reviewed_at: datetime | None
    meta: dict[str, Any]
    segments: list[SegmentOut]
    evaluation: EvaluationOut | None
    scorecard: dict[str, Any] | None = None
    notes: list[NoteOut]


class IngestOut(BaseModel):
    id: uuid.UUID
    external_id: str | None
    status: str
    created: bool
    duplicate_of: uuid.UUID | None = None
    filename: str | None = None


class UploadResult(BaseModel):
    accepted: list[IngestOut]
    rejected: list[dict[str, str]]


class ApiCallStatus(BaseModel):
    id: uuid.UUID
    external_id: str | None
    status: str
    review_status: str
    score: float | None
    passed: bool | None
    auto_fail: bool | None
    error: str | None


# ---------- ops ----------
class JobOut(ORM):
    id: int
    call_id: uuid.UUID | None
    export_id: int | None
    kind: str
    queue: str
    status: str
    attempts: int
    error: str | None
    heartbeat_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime


class AuditOut(ORM):
    id: int
    at: datetime
    actor_user_id: int | None
    actor_name: str | None = None
    actor_api_key_id: int | None
    action: str
    entity: str
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
