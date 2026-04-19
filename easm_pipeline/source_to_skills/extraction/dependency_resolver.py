"""Deterministic dependency context for script mining."""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from pathlib import Path

from pydantic.v1 import BaseModel, Extra, Field

from easm_pipeline.core.llm_infra.schemas import CapabilitySlice
from easm_pipeline.source_to_skills.language_support import KNOWN_SOURCE_SUFFIXES


class DependencyContext(BaseModel):
    """Resolved import and coupling context for one candidate capability."""

    stdlib_imports: tuple[str, ...] = Field(default_factory=tuple)
    pip_imports: tuple[str, ...] = Field(default_factory=tuple)
    internal_imports: tuple[str, ...] = Field(default_factory=tuple)
    internal_source_blocks: dict[str, str] = Field(default_factory=dict)
    business_coupling: tuple[str, ...] = Field(default_factory=tuple)
    side_effects: tuple[str, ...] = Field(default_factory=tuple)

    class Config:
        extra = Extra.forbid


class DependencyResolver:
    """Resolve lightweight dependency context without importing project code."""

    def resolve(self, capability: CapabilitySlice, source_root: Path | None = None) -> DependencyContext:
        imports = tuple(dict.fromkeys(item for node in capability.nodes for item in node.imports))
        stdlib: list[str] = []
        pip: list[str] = []
        internal: list[str] = []
        internal_blocks: dict[str, str] = {}
        language = capability.nodes[0].language if capability.nodes else None

        for import_line in imports:
            module_name = _root_module_name(import_line, language=language)
            if not module_name:
                continue
            if _is_stdlib_module(module_name):
                stdlib.append(import_line)
            elif source_root is not None and _looks_internal(module_name, source_root):
                internal.append(import_line)
                internal_blocks.update(_read_internal_source(module_name, source_root))
            else:
                pip.append(import_line)

        raw_code = "\n\n".join(node.raw_code for node in capability.nodes)
        return DependencyContext(
            stdlib_imports=tuple(dict.fromkeys(stdlib)),
            pip_imports=tuple(dict.fromkeys(pip)),
            internal_imports=tuple(dict.fromkeys(internal)),
            internal_source_blocks=internal_blocks,
            business_coupling=tuple(_detect_business_coupling(raw_code, imports)),
            side_effects=tuple(_detect_side_effects(raw_code)),
        )


def _root_module_name(import_line: str, *, language: str | None = None) -> str | None:
    if language == "python":
        return _python_root_module_name(import_line)
    if language == "java":
        return import_line.split(".", 1)[0].strip() or None
    return _generic_root_module_name(import_line)


def _python_root_module_name(import_line: str) -> str | None:
    try:
        parsed = ast.parse(import_line)
    except SyntaxError:
        return _generic_root_module_name(import_line)
    if not parsed.body:
        return None
    statement = parsed.body[0]
    if isinstance(statement, ast.Import):
        return statement.names[0].name.split(".", 1)[0]
    if isinstance(statement, ast.ImportFrom) and statement.module:
        return statement.module.split(".", 1)[0]
    return None


def _generic_root_module_name(import_line: str) -> str | None:
    quoted = re.search(r"""["'](?P<module>[@A-Za-z0-9_./-]+)["']""", import_line)
    if quoted:
        return quoted.group("module").lstrip("@").split("/", 1)[0].split(".", 1)[0]
    match = re.search(r"\b(?:import|from|using|use|require|include|package|namespace)\s+([A-Za-z0-9_.-]+)", import_line)
    if match:
        return match.group(1).split(".", 1)[0].split("/", 1)[0]
    simple = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", import_line)
    return simple.group(1) if simple else None


def _is_stdlib_module(module_name: str) -> bool:
    if module_name in sys.builtin_module_names:
        return True
    stdlib_names = getattr(sys, "stdlib_module_names", set())
    if module_name in stdlib_names:
        return True
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        return False
    origin = spec.origin.replace("\\", "/").lower()
    return "site-packages" not in origin and "dist-packages" not in origin


def _looks_internal(module_name: str, source_root: Path) -> bool:
    dotted_path = Path(*module_name.split("."))
    candidates = [source_root / dotted_path / "__init__.py"]
    candidates.extend(source_root / f"{dotted_path}{suffix}" for suffix in KNOWN_SOURCE_SUFFIXES)
    candidates.extend(source_root / dotted_path / f"index{suffix}" for suffix in KNOWN_SOURCE_SUFFIXES)
    return any(path.exists() for path in candidates)


def _read_internal_source(module_name: str, source_root: Path, *, max_chars: int = 4000) -> dict[str, str]:
    dotted_path = Path(*module_name.split("."))
    candidates = [source_root / dotted_path / "__init__.py"]
    candidates.extend(source_root / f"{dotted_path}{suffix}" for suffix in KNOWN_SOURCE_SUFFIXES)
    candidates.extend(source_root / dotted_path / f"index{suffix}" for suffix in KNOWN_SOURCE_SUFFIXES)
    blocks: dict[str, str] = {}
    for path in candidates:
        if path.exists() and path.is_file():
            relative = path.resolve().relative_to(source_root.resolve()).as_posix()
            blocks[relative] = path.read_text(encoding="utf-8")[:max_chars]
    return blocks


def _detect_business_coupling(raw_code: str, imports: tuple[str, ...]) -> list[str]:
    coupling: list[str] = []
    lowered_imports = "\n".join(imports).lower()
    lowered_code = raw_code.lower()
    framework_terms = {
        "django": "depends on Django framework context",
        "flask": "depends on Flask request/application context",
        "fastapi": "depends on FastAPI request/application context",
        "sqlalchemy": "depends on SQLAlchemy/database context",
        "boto3": "depends on cloud provider credentials or clients",
        "spring": "depends on Spring application context",
        "jakarta": "depends on Jakarta EE container context",
        "express": "depends on Express request/application context",
        "nestjs": "depends on NestJS application context",
        "react": "depends on React component/runtime context",
    }
    for term, reason in framework_terms.items():
        if term in lowered_imports or term in lowered_code:
            coupling.append(reason)
    if "os.environ" in raw_code:
        coupling.append("reads process environment variables")
    if "settings." in lowered_code or "config." in lowered_code:
        coupling.append("references project settings or configuration")
    if "self." in raw_code:
        coupling.append("uses instance state")
    return list(dict.fromkeys(coupling))


def _detect_side_effects(raw_code: str) -> list[str]:
    side_effects: list[str] = []
    checks = {
        "open(": "uses filesystem open",
        ".write(": "writes to an object or file-like sink",
        "requests.": "performs HTTP request",
        "subprocess.": "spawns subprocesses",
        "os.remove": "deletes files",
        "shutil.rmtree": "deletes directory trees",
    }
    for token, reason in checks.items():
        if token in raw_code:
            side_effects.append(reason)
    return side_effects



