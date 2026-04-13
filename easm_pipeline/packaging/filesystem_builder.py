"""Filesystem construction for validated Claude Agent Skills."""

from __future__ import annotations

import os
import shutil
import stat
import time
import uuid
from pathlib import Path

import yaml
from loguru import logger

from easm_pipeline.core.llm_infra.schemas import SkillPayload

from .validator import SkillValidator


class FilesystemBuilder:
    """Build a flattened skill directory after strict validation."""

    def __init__(self, validator: SkillValidator | None = None) -> None:
        self._validator = validator or SkillValidator()

    def build(self, payload: SkillPayload, output_root: Path, *, overwrite: bool = False) -> Path:
        validated = self._validator.validate(payload)
        output_root = output_root.resolve()
        target_dir = output_root / validated.name
        temp_dir = output_root / f".{validated.name}.tmp-{uuid.uuid4().hex[:8]}"
        logger.info("Building skill filesystem bundle: name={} target={}", validated.name, target_dir)

        if target_dir.exists() and not overwrite:
            raise FileExistsError(f"skill directory already exists: {target_dir}")

        output_root.mkdir(parents=True, exist_ok=True)
        old_dir: Path | None = None

        try:
            temp_dir.mkdir()
            (temp_dir / "SKILL.md").write_text(render_skill_md(validated), encoding="utf-8")
            if validated.scripts_dict:
                scripts_dir = temp_dir / "scripts"
                scripts_dir.mkdir()
                for filename, content in validated.scripts_dict.items():
                    (scripts_dir / filename).write_text(content, encoding="utf-8")
            if validated.references_dict:
                references_dir = temp_dir / "references"
                references_dir.mkdir()
                for filename, content in validated.references_dict.items():
                    (references_dir / filename).write_text(content, encoding="utf-8")

            _assert_flattened(temp_dir)
            if target_dir.exists():
                old_dir = output_root / f".{validated.name}.old-{uuid.uuid4().hex[:8]}"
                logger.debug("Replacing existing skill directory: target={} old={}", target_dir, old_dir)
                _replace_existing_directory(target_dir, old_dir)
                _install_tree(temp_dir, target_dir)
                _remove_tree(old_dir, missing_ok=True, fail_silently=True)
            else:
                _install_tree(temp_dir, target_dir)
        except Exception:
            if temp_dir.exists():
                _remove_tree(temp_dir, missing_ok=True, fail_silently=True)
            if old_dir is not None and old_dir.exists() and not target_dir.exists():
                try:
                    old_dir.rename(target_dir)
                except OSError:
                    pass
            raise

        return target_dir


def render_skill_md(payload: SkillPayload) -> str:
    frontmatter = yaml.safe_dump(payload.frontmatter(), sort_keys=False, allow_unicode=True).strip()
    return f"---\n{frontmatter}\n---\n\n{payload.instructions.strip()}\n"


def _assert_flattened(skill_dir: Path) -> None:
    for path in skill_dir.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(skill_dir).parts
        if len(relative_parts) > 2:
            raise ValueError(f"skill bundle exceeds max one-level depth: {path}")


def _replace_existing_directory(target_dir: Path, old_dir: Path) -> None:
    """Move an existing skill aside before replacing it.

    This is more reliable on Windows/OneDrive than deleting the target in place.
    The replacement can proceed even if the background sync client keeps a short
    handle on a nested directory.
    """

    try:
        target_dir.rename(old_dir)
    except OSError:
        logger.warning("Could not rename existing target; deleting in place: target={}", target_dir)
        _remove_tree(target_dir, missing_ok=False, fail_silently=False)


def _install_tree(temp_dir: Path, target_dir: Path, *, attempts: int = 5) -> None:
    """Install a prepared skill tree, tolerating short Windows/OneDrive locks."""

    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            temp_dir.rename(target_dir)
            return
        except OSError as exc:
            last_error = exc
            logger.debug(
                "Skill directory rename failed; retrying: temp={} target={} attempt={}",
                temp_dir,
                target_dir,
                attempt + 1,
            )
            time.sleep(0.1 * (attempt + 1))

    try:
        logger.warning("Falling back to copytree install for skill directory: target={}", target_dir)
        shutil.copytree(temp_dir, target_dir)
        _remove_tree(temp_dir, missing_ok=True, fail_silently=True)
        return
    except FileExistsError:
        _remove_tree(target_dir, missing_ok=True, fail_silently=False)
        shutil.copytree(temp_dir, target_dir)
        _remove_tree(temp_dir, missing_ok=True, fail_silently=True)
        return
    except OSError as exc:
        last_error = exc

    if last_error is not None:
        raise last_error


def _remove_tree(path: Path, *, missing_ok: bool, fail_silently: bool, attempts: int = 5) -> None:
    if missing_ok and not path.exists():
        return

    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            shutil.rmtree(path, onerror=_make_writable_and_retry)
            return
        except FileNotFoundError:
            if missing_ok:
                return
            raise
        except OSError as exc:
            last_error = exc
            time.sleep(0.1 * (attempt + 1))

    if fail_silently:
        return
    if last_error is not None:
        raise last_error


def _make_writable_and_retry(function: object, path: str, exc_info: object) -> None:
    del exc_info
    try:
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    except OSError:
        pass
    function(path)
