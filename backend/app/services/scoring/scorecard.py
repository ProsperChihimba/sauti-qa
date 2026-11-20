"""Scorecard definition (editable JSON) and validation."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator, model_validator

SEED_PATH = Path(__file__).resolve().parents[3] / "seed" / "scorecard_telecom_sw.json"


class Criterion(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    section: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    examples: list[str] = Field(default_factory=list, description="Swahili phrases that show the behaviour")
    negative_examples: list[str] = Field(default_factory=list, description="Phrases that show a failure")
    weight: float = Field(gt=0, le=1000)
    critical: bool = False
    allow_na: bool = False
    na_guidance: str | None = Field(default=None, max_length=500, description="When N/A is appropriate")

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_\-]*", v):
            raise ValueError("id must be lowercase letters, digits, '_' or '-'")
        return v


class ScorecardDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    pass_threshold: float = Field(default=80.0, ge=0, le=100)
    call_reasons: list[str] = Field(default_factory=list, description="Preferred call reason categories")
    criteria: list[Criterion] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self):
        ids = [c.id for c in self.criteria]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"Duplicate criterion ids: {', '.join(sorted(dupes))}")
        return self

    @property
    def sections(self) -> list[str]:
        out: list[str] = []
        for c in self.criteria:
            if c.section not in out:
                out.append(c.section)
        return out

    def by_id(self) -> dict[str, Criterion]:
        return {c.id: c for c in self.criteria}

    def storage_dict(self) -> dict:
        """What goes in scorecards.definition (name / threshold live in columns too)."""
        return self.model_dump(exclude={"name", "pass_threshold"})


def load_seed() -> ScorecardDefinition:
    return ScorecardDefinition(**json.loads(SEED_PATH.read_text(encoding="utf-8")))


def definition_from_row(row) -> ScorecardDefinition:
    return ScorecardDefinition(name=row.name, pass_threshold=row.pass_threshold, **row.definition)
