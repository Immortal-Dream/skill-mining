"""Schemas for mined standalone CLI scripts."""

from __future__ import annotations

import re
from typing import Literal

from pydantic.v1 import BaseModel, Extra, Field, validator


SCRIPT_FILENAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,118}[A-Za-z0-9])?$")
SKILL_ID_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class ScriptCliArgument(BaseModel):
    """A concrete CLI argument exposed by a generated skill script."""

    name: str = Field(..., min_length=1)
    flag: str = Field(..., min_length=3)
    required: bool
    value_type: Literal["str", "int", "float", "bool", "json"]
    help: str = Field(..., min_length=1)
    default: str | None = None

    class Config:
        extra = Extra.forbid

    @validator("flag")
    @classmethod
    def _validate_flag(cls, value: str) -> str:
        if not value.startswith("--"):
            raise ValueError("CLI flags must start with --")
        return value.strip()


class GeneratedScript(BaseModel):
    """A packaged skill script, either distilled or source-preserving."""

    skill_id: str = Field(..., max_length=64)
    language: str = Field(..., min_length=1, max_length=64)
    runtime_hint: str = Field(..., min_length=1, max_length=64)
    filename: str = Field(..., max_length=80)
    description: str = Field(..., min_length=1, max_length=512)
    script_text: str = Field(..., min_length=1)
    entry_function: str = Field("core_function", min_length=1)
    entry_symbol: str | None = None
    cli_arguments: tuple[ScriptCliArgument, ...] = Field(default_factory=tuple)
    dependencies: tuple[str, ...] = Field(default_factory=tuple)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    source: str = Field(..., min_length=1)
    example_command: str = Field(..., min_length=1, max_length=512)
    supports_help: bool = False

    class Config:
        extra = Extra.forbid

    @validator("skill_id")
    @classmethod
    def _validate_skill_id(cls, value: str) -> str:
        if not SKILL_ID_RE.fullmatch(value):
            raise ValueError("skill_id must use lower-kebab-case without a skill_ prefix")
        if value.startswith(("skill_", "skill-")):
            raise ValueError("skill_id must not start with skill_ or skill-")
        return value

    @validator("filename")
    @classmethod
    def _validate_filename(cls, value: str) -> str:
        if not SCRIPT_FILENAME_RE.fullmatch(value):
            raise ValueError("filename must be a safe single-file script or source filename")
        if value.startswith("skill_"):
            raise ValueError("filename must not start with skill_")
        return value

    @validator("script_text")
    @classmethod
    def _validate_script_text_shape(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("script_text must contain source text")
        return stripped + "\n"


class ScriptValidationResult(BaseModel):
    """Static and dynamic validation result for a generated script."""

    passed: bool
    static_errors: tuple[str, ...] = Field(default_factory=tuple)
    security_findings: tuple[str, ...] = Field(default_factory=tuple)
    help_exit_code: int | None = None
    example_exit_code: int | None = None
    stdout_sample: str | None = None
    stderr_sample: str | None = None

    class Config:
        extra = Extra.forbid


