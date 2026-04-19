"""Best-effort extraction for source languages without dedicated miners."""

from __future__ import annotations

import re
from pathlib import Path

from loguru import logger

from easm_pipeline.core.llm_infra.schemas import ExtractedNode
from easm_pipeline.source_to_skills.language_support import detect_runtime_for_path

from .common import deterministic_node_id, safe_relative_path


IMPORT_PATTERNS = (
    re.compile(r"^\s*import\s+.+$", re.MULTILINE),
    re.compile(r"^\s*from\s+.+$", re.MULTILINE),
    re.compile(r"^\s*using\s+.+$", re.MULTILINE),
    re.compile(r"^\s*require\s+.+$", re.MULTILINE),
    re.compile(r"^\s*include\s+.+$", re.MULTILINE),
    re.compile(r"^\s*use\s+.+$", re.MULTILINE),
)


class GenericTextMiner:
    """Fallback miner that packages an entire source file as one executable unit."""

    def mine_file(self, path: Path, *, project_root: Path | None = None) -> list[ExtractedNode]:
        source = path.read_text(encoding="utf-8")
        first_line = source.splitlines()[0] if source.splitlines() else ""
        runtime = detect_runtime_for_path(path, first_line=first_line)
        relative_path = safe_relative_path(path, project_root)
        raw_bytes = source.encode("utf-8")
        name = _node_name_from_path(path)
        imports = _extract_imports(source)
        node = ExtractedNode(
            node_id=deterministic_node_id(relative_path, 0, len(raw_bytes), name),
            language=runtime.language_id,
            node_type="file",
            name=name,
            signature=f"{runtime.display_name} source file {path.name}",
            raw_code=source,
            docstring=_leading_comment(source),
            file_path=relative_path,
            start_byte=0,
            end_byte=len(raw_bytes),
            start_line=1,
            end_line=max(source.count("\n") + 1, 1),
            imports=imports,
            metadata={"parser": "generic-text-file", "runtime_hint": runtime.runtime_hint},
        )
        logger.debug("Generic extraction complete: file={} language={}", relative_path, runtime.language_id)
        return [node]


def _node_name_from_path(path: Path) -> str:
    if path.stem:
        return path.stem.replace(".", "_")
    return path.name.replace(".", "_") or "source_file"


def _extract_imports(source: str) -> tuple[str, ...]:
    imports: list[str] = []
    for pattern in IMPORT_PATTERNS:
        imports.extend(match.group(0).strip() for match in pattern.finditer(source))
    return tuple(dict.fromkeys(imports))


def _leading_comment(source: str) -> str | None:
    lines = source.splitlines()
    collected: list[str] = []
    for line in lines[:12]:
        stripped = line.strip()
        if not stripped:
            if collected:
                break
            continue
        if stripped.startswith(("#", "//", "--", ";", "/*", "*", "%")):
            cleaned = stripped.lstrip("#/;-*% ").rstrip("*/ ").strip()
            if cleaned:
                collected.append(cleaned)
            continue
        break
    if not collected:
        return None
    return " ".join(collected)
