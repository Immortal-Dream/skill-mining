"""Schemas for mined standalone CLI scripts."""

from __future__ import annotations

import re
from typing import Literal

from pydantic.v1 import BaseModel, Extra, Field, validator


SCRIPT_FILENAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_]{0,74}[a-z0-9])?\.py$")
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
    """A distilled Python CLI script ready for validation and packaging."""

    skill_id: str = Field(..., max_length=64)
    filename: str = Field(..., max_length=80)
    description: str = Field(..., min_length=1, max_length=512)
    script_text: str = Field(..., min_length=1)
    entry_function: str = Field("core_function", min_length=1)
    cli_arguments: tuple[ScriptCliArgument, ...] = Field(default_factory=tuple)
    dependencies: tuple[str, ...] = Field(default_factory=tuple)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    source: str = Field(..., min_length=1)

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
            raise ValueError("filename must be lower_snake_case .py without a skill_ prefix")
        if value.startswith("skill_"):
            raise ValueError("filename must not start with skill_")
        return value

    @validator("script_text")
    @classmethod
    def _validate_script_text_shape(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped.startswith("#!/usr/bin/env python3"):
            raise ValueError("script_text must start with a python3 shebang")
        required_snippets = ("import argparse", "import json", "import sys", "def core_function", "def main()")
        missing = [snippet for snippet in required_snippets if snippet not in stripped]
        if missing:
            raise ValueError(f"script_text missing required snippets: {', '.join(missing)}")
        if 'if __name__ == "__main__"' not in stripped:
            raise ValueError("script_text must call main under __main__")
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


