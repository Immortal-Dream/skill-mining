"""Shared registered-skill packaging workflow for skill-mining pipelines."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from easm_pipeline.source_to_skills.packaging.filesystem_builder import FilesystemBuilder
from easm_pipeline.source_to_skills.packaging.registered_skill import RegisteredSkillPackage
from easm_pipeline.source_to_skills.packaging.registry_builder import RegistryBuilder


@dataclass(frozen=True)
class RegisteredSkillWriteResult:
    """Summary of a registered-skill packaging run."""

    skill_dirs: tuple[Path, ...]
    packages: tuple[RegisteredSkillPackage, ...]


class RegisteredSkillWriter:
    """Write validated registered-skill packages and refresh the registry."""

    def __init__(
        self,
        filesystem_builder: FilesystemBuilder | None = None,
        registry_builder: RegistryBuilder | None = None,
    ) -> None:
        self._filesystem_builder = filesystem_builder or FilesystemBuilder()
        self._registry_builder = registry_builder or RegistryBuilder()

    def write_packages(
        self,
        *,
        packages: tuple[RegisteredSkillPackage, ...],
        output_dir: Path,
        overwrite: bool = False,
    ) -> RegisteredSkillWriteResult:
        if overwrite:
            self._filesystem_builder.cleanup_legacy_registered_layout(output_dir)

        skill_dirs: list[Path] = []
        for package in packages:
            skill_dirs.append(
                self._filesystem_builder.build_registered_skill(
                    package,
                    output_dir,
                    overwrite=overwrite,
                )
            )
        if packages:
            self._registry_builder.update(output_dir, packages, replace=overwrite)
        return RegisteredSkillWriteResult(skill_dirs=tuple(skill_dirs), packages=packages)
