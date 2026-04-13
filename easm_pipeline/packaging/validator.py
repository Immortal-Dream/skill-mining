"""Strict validation before writing filesystem-based Claude Agent Skills."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Mapping

from loguru import logger
from pydantic.v1 import ValidationError

from easm_pipeline.core.llm_infra.schemas import SkillPayload


NAME_RE = re.compile(r"^[a-z0-9-]+$")
XML_TAG_RE = re.compile(r"<\/?[A-Za-z][^>]*>")
BUNDLE_REF_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"(?P<path>(?:scripts|references)/[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*)"
)
RESERVED_NAME_TERMS = {"anthropic", "claude"}
PLACEHOLDERS = {"todo", "tbd", "placeholder", "fixme"}


class SkillValidationError(ValueError):
    """Raised with all validation failures found in a candidate skill."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


class SkillValidator:
    """Programmatic checks for filesystem skill payloads."""

    def validate(self, payload: SkillPayload | Mapping[str, object]) -> SkillPayload:
        errors: list[str] = []
        candidate: SkillPayload | None = None

        try:
            candidate = payload if isinstance(payload, SkillPayload) else SkillPayload.parse_obj(payload)
        except ValidationError as exc:
            errors.extend(_format_pydantic_errors(exc))

        raw = _payload_mapping(payload)
        errors.extend(self._validate_name(raw.get("name")))
        errors.extend(self._validate_description(raw.get("description")))
        errors.extend(self._validate_instruction_text(raw.get("instructions")))

        if candidate is not None:
            errors.extend(self._validate_bundle_filenames(candidate.scripts_dict, "scripts"))
            errors.extend(self._validate_bundle_filenames(candidate.references_dict, "references"))
            errors.extend(self._validate_script_guidance(candidate))
            errors.extend(self._validate_reference_integrity(candidate))

        if errors:
            logger.error("Skill payload validation failed: errors={}", len(_dedupe(errors)))
            raise SkillValidationError(_dedupe(errors))
        if candidate is None:
            raise SkillValidationError(["payload could not be validated"])
        logger.debug("Skill payload validation passed: name={}", candidate.name)
        return candidate

    def _validate_name(self, value: object) -> list[str]:
        errors: list[str] = []
        if not isinstance(value, str) or not value.strip():
            return ["name: must be non-empty"]
        name = value.strip()
        if len(name) > 64:
            errors.append("name: must be 64 characters or fewer")
        if not NAME_RE.fullmatch(name):
            errors.append("name: must match ^[a-z0-9-]+$")
        if XML_TAG_RE.search(name):
            errors.append("name: must not contain XML tags")
        lowered = name.lower()
        reserved = sorted(term for term in RESERVED_NAME_TERMS if term in lowered)
        if reserved:
            errors.append(f"name: must not contain reserved terms: {', '.join(reserved)}")
        return errors

    def _validate_description(self, value: object) -> list[str]:
        errors: list[str] = []
        if not isinstance(value, str) or not value.strip():
            return ["description: must be non-empty"]
        description = value.strip()
        if len(description) > 1024:
            errors.append("description: must be 1024 characters or fewer")
        if XML_TAG_RE.search(description):
            errors.append("description: must not contain XML tags")
        if any(ord(char) > 127 for char in description):
            errors.append("description: must use ASCII text and punctuation only")
        return errors

    def _validate_instruction_text(self, value: object) -> list[str]:
        errors: list[str] = []
        if not isinstance(value, str) or not value.strip():
            return ["instructions: must be non-empty"]
        lowered = value.strip().lower()
        if lowered in PLACEHOLDERS:
            errors.append("instructions: must not be a placeholder")
        if len([line for line in value.splitlines() if line.strip()]) > 500:
            errors.append("instructions: must be 500 lines or fewer")
        if any(ord(char) > 127 for char in value):
            errors.append("instructions: must use ASCII text and punctuation only")
        if "# " not in value:
            errors.append("instructions: must include a top-level markdown heading")
        if "## Helper Scripts Available" not in value:
            errors.append("instructions: must include ## Helper Scripts Available")
        if "## Quick Start" not in value:
            errors.append("instructions: must include ## Quick Start")
        errors.extend(_validate_quick_start_numbering(value))
        if "scripts/" in value:
            if "## Running Bundled Scripts" not in value:
                errors.append("instructions: script references require ## Running Bundled Scripts")
            if "--help" not in value:
                errors.append("instructions: script references must tell Claude to run --help first")
            if "--args-json" not in value and "--kwargs-json" not in value:
                errors.append("instructions: script references must include JSON invocation examples")
        return errors

    def _validate_bundle_filenames(self, files: Mapping[str, str], folder: str) -> list[str]:
        errors: list[str] = []
        for filename, content in files.items():
            path = PurePosixPath(filename.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts or len(path.parts) != 1:
                errors.append(f"{folder}: {filename} must be a safe filename")
            if not content or not content.strip():
                errors.append(f"{folder}: {filename} must be non-empty")
        return errors

    def _validate_reference_integrity(self, payload: SkillPayload) -> list[str]:
        available = {f"scripts/{name}" for name in payload.scripts_dict}
        available.update(f"references/{name}" for name in payload.references_dict)
        errors: list[str] = []
        for match in BUNDLE_REF_RE.finditer(payload.instructions):
            referenced = match.group("path")
            if referenced not in available:
                errors.append(f"instructions: referenced file does not exist: {referenced}")
        return errors

    def _validate_script_guidance(self, payload: SkillPayload) -> list[str]:
        if not payload.scripts_dict:
            return []
        instructions = payload.instructions
        errors: list[str] = []
        if "## Running Bundled Scripts" not in instructions:
            errors.append("instructions: skills with scripts must include ## Running Bundled Scripts")
        if "--help" not in instructions:
            errors.append("instructions: skills with scripts must tell Claude to run --help first")
        if "--args-json" not in instructions and "--kwargs-json" not in instructions:
            errors.append("instructions: skills with scripts must include --args-json or --kwargs-json examples")
        for filename in payload.scripts_dict:
            script_path = f"scripts/{filename}"
            if script_path not in instructions:
                errors.append(f"instructions: must mention packaged script {script_path}")
        return errors


def _payload_mapping(payload: SkillPayload | Mapping[str, object]) -> Mapping[str, object]:
    if isinstance(payload, SkillPayload):
        return payload.dict()
    return payload


def _format_pydantic_errors(exc: ValidationError) -> list[str]:
    errors: list[str] = []
    for error in exc.errors():
        location = ".".join(str(item) for item in error.get("loc", ())) or "payload"
        errors.append(f"{location}: {error.get('msg', 'invalid value')}")
    return errors


def _dedupe(errors: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for error in errors:
        if error not in seen:
            seen.add(error)
            deduped.append(error)
    return deduped


def _validate_quick_start_numbering(markdown: str) -> list[str]:
    lines = markdown.splitlines()
    in_quick_start = False
    numbered: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == "## Quick Start":
            in_quick_start = True
            continue
        if in_quick_start and stripped.startswith("## "):
            break
        if in_quick_start and re.match(r"^\d+[\.)]\s+\S", stripped):
            numbered.append(stripped)
    if not in_quick_start:
        return []
    if not numbered:
        return ["instructions: Quick Start must include numbered steps"]
    errors: list[str] = []
    for expected, line in enumerate(numbered, start=1):
        match = re.match(r"^(?P<number>\d+)\.\s+\S", line)
        if match is None:
            errors.append("instructions: Quick Start steps must use '1.' numbering, not '1)'")
            continue
        if int(match.group("number")) != expected:
            errors.append("instructions: Quick Start steps must be numbered without gaps")
    return errors
