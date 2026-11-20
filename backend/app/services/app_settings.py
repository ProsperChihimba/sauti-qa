"""Runtime-tunable settings. .env provides defaults; admins override them in the UI."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AppSetting

KEY = "runtime"


class RuntimeSettings(BaseModel):
    review_score_threshold: float = Field(ge=0, le=100)
    review_confidence_threshold: float = Field(ge=0, le=1)
    review_on_flags: bool
    review_on_auto_fail: bool
    stereo_agent_channel: Literal["left", "right"]
    audio_retention_days: int = Field(ge=0)


def defaults() -> RuntimeSettings:
    s = get_settings()
    return RuntimeSettings(
        review_score_threshold=s.review_score_threshold,
        review_confidence_threshold=s.review_confidence_threshold,
        review_on_flags=s.review_on_flags,
        review_on_auto_fail=s.review_on_auto_fail,
        stereo_agent_channel=s.stereo_agent_channel,
        audio_retention_days=s.audio_retention_days,
    )


def get_runtime_settings(db: Session) -> RuntimeSettings:
    row = db.get(AppSetting, KEY)
    base = defaults().model_dump()
    if row and isinstance(row.value, dict):
        base.update({k: v for k, v in row.value.items() if k in base})
    return RuntimeSettings(**base)


def update_runtime_settings(db: Session, changes: dict[str, Any]) -> RuntimeSettings:
    current = get_runtime_settings(db).model_dump()
    current.update(changes)
    validated = RuntimeSettings(**current)
    row = db.get(AppSetting, KEY)
    if row is None:
        db.add(AppSetting(key=KEY, value=validated.model_dump()))
    else:
        row.value = validated.model_dump()
    return validated
