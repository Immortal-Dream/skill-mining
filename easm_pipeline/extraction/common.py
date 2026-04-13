"""Shared deterministic extraction helpers."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath
from typing import Iterable


SUPPORTED_SOURCE_SUFFIXES = {".py", ".java"}


class ExtractionDependencyError(RuntimeError):
    """Raised when an optional parser dependency is unavailable."""


def iter_source_files(source_dir: Path, suffixes: set[str] | None = None) -> Iterable[Path]:
    """Yield supported source files in stable order."""

    allowed = suffixes or SUPPORTED_SOURCE_SUFFIXES
    for path in sorted(source_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in allowed:
            yield path


def safe_relative_path(path: Path, root: Path | None = None) -> str:
    """Return a safe POSIX relative path for schema storage."""

    resolved = path.resolve()
    if root is not None:
        try:
            relative = resolved.relative_to(root.resolve())
        except ValueError:
            relative = Path(path.name)
    else:
        relative = Path(path.name)
    normalized = relative.as_posix()
    posix = PurePosixPath(normalized)
    if posix.is_absolute() or ".." in posix.parts:
        raise ValueError(f"unsafe relative path: {normalized}")
    return normalized


def byte_offset_for_line_col(source: str, line: int, col: int) -> int:
    """Convert one-based line and zero-based column to a UTF-8 byte offset."""

    if line < 1:
        raise ValueError("line must be one-based")
    lines = source.splitlines(keepends=True)
    prefix = "".join(lines[: line - 1])
    return len(prefix.encode("utf-8")) + len(lines[line - 1][:col].encode("utf-8"))


def line_for_byte(source: str, byte_offset: int) -> int:
    """Return one-based line number for a UTF-8 byte offset."""

    if byte_offset < 0:
        raise ValueError("byte_offset must be non-negative")
    encoded = source.encode("utf-8")
    prefix = encoded[:byte_offset].decode("utf-8", errors="ignore")
    return prefix.count("\n") + 1


def deterministic_node_id(file_path: str, start_byte: int, end_byte: int, name: str) -> str:
    """Build a stable compact node identifier."""

    digest = hashlib.sha1(f"{file_path}:{start_byte}:{end_byte}:{name}".encode("utf-8")).hexdigest()[:12]
    return f"{file_path}:{start_byte}-{end_byte}:{name}:{digest}"


def normalize_signature(signature: str) -> str:
    """Collapse whitespace while preserving a readable declaration."""

    return re.sub(r"\s+", " ", signature).strip()


def slugify(value: str, *, max_length: int = 64) -> str:
    """Convert arbitrary text into a conservative lowercase slug."""

    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        slug = "generated-skill"
    return slug[:max_length].strip("-") or "generated-skill"

