"""Build and update skills_registry.json for script-first skills."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger
from pydantic.v1 import BaseModel, Extra, Field

from easm_pipeline.script_mining.script_schema import ScriptValidationResult

from .registered_skill import RegisteredSkillPackage


class RegistryEntry(BaseModel):
    """One discoverable script skill entry."""

    skill_id: str
    script: str
    doc: str
    source: str
    source_file: str | None = None
    source_span: dict[str, int] = Field(default_factory=dict)
    tags: tuple[str, ...] = Field(default_factory=tuple)
    dependencies: tuple[str, ...] = Field(default_factory=tuple)
    status: str = "active"
    validation: ScriptValidationResult

    class Config:
        extra = Extra.forbid


class SkillsRegistry(BaseModel):
    """Registry file persisted under output_skills/skills_registry.json."""

    version: int = 1
    generated_at: str
    skills: tuple[RegistryEntry, ...] = Field(default_factory=tuple)

    class Config:
        extra = Extra.forbid


class RegistryBuilder:
    """Merge generated skills into the output registry."""

    def update(self, output_root: Path, packages: tuple[RegisteredSkillPackage, ...]) -> Path:
        output_root = output_root.resolve()
        output_root.mkdir(parents=True, exist_ok=True)
        registry_path = output_root / "skills_registry.json"
        existing = _read_registry(registry_path)
        entries = {entry.skill_id: entry for entry in existing.skills}

        for package in packages:
            entries[package.script.skill_id] = _entry_from_package(package)

        registry = SkillsRegistry(
            generated_at=datetime.now(timezone.utc).isoformat(),
            skills=tuple(entries[key] for key in sorted(entries)),
        )
        registry_path.write_text(registry.json(indent=2), encoding="utf-8")
        logger.info("Updated skills registry: path={} entries={}", registry_path, len(registry.skills))
        return registry_path


def _read_registry(path: Path) -> SkillsRegistry:
    if not path.exists():
        return SkillsRegistry(generated_at=datetime.now(timezone.utc).isoformat(), skills=())
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return SkillsRegistry.parse_obj(raw)
    except Exception:
        logger.warning("Existing registry is invalid; rebuilding: {}", path)
        return SkillsRegistry(generated_at=datetime.now(timezone.utc).isoformat(), skills=())


def _entry_from_package(package: RegisteredSkillPackage) -> RegistryEntry:
    return RegistryEntry(
        skill_id=package.script.skill_id,
        script=f"scripts/{package.script.filename}",
        doc=f"skills/{package.script.skill_id}/SKILL.md",
        source=package.decision.source,
        source_file=package.source_file,
        source_span=package.source_span,
        tags=package.script.tags,
        dependencies=package.script.dependencies,
        status="active" if package.validation.passed else "failed-validation",
        validation=package.validation,
    )
