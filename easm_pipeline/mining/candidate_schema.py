"""Structured candidate extraction decisions."""

from __future__ import annotations

import re
from typing import Literal

from pydantic.v1 import BaseModel, Extra, Field, root_validator, validator


SKILL_ID_RE = re.compile(r"^skill_[a-z0-9_]+$")


class CandidateDecision(BaseModel):
    """Decision for whether a mined capability should become a reusable script skill."""

    decision: Literal["extract", "skip"]
    reason: str = Field(..., min_length=1)
    skill_id: str | None = Field(None, max_length=64)
    source: str = Field(..., min_length=1)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    dependencies: tuple[str, ...] = Field(default_factory=tuple)
    reusable_boundary_score: float = Field(..., ge=0.0, le=1.0)
    domain_value_score: float = Field(..., ge=0.0, le=1.0)
    coupling_score: float = Field(..., ge=0.0, le=1.0)

    class Config:
        extra = Extra.forbid

    @validator("skill_id")
    @classmethod
    def _validate_skill_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not SKILL_ID_RE.fullmatch(normalized):
            raise ValueError("skill_id must match ^skill_[a-z0-9_]+$")
        return normalized

    @validator("tags", "dependencies")
    @classmethod
    def _normalize_tuple(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for item in value:
            cleaned = item.strip().lower()
            if cleaned:
                normalized.append(cleaned)
        return tuple(dict.fromkeys(normalized))

    @root_validator(skip_on_failure=True)
    def _validate_decision_consistency(cls, values: dict[str, object]) -> dict[str, object]:
        decision = values.get("decision")
        skill_id = values.get("skill_id")
        if decision == "extract" and not skill_id:
            raise ValueError("extract decisions require skill_id")
        if decision == "skip" and skill_id:
            raise ValueError("skip decisions must not include skill_id")
        return values

