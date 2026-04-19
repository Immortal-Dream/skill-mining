"""Optional tree-sitter setup utilities.

Imports are intentionally lazy so the rest of the pipeline can still run unit
tests in environments where parser wheels have not been installed yet.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

from .common import ExtractionDependencyError


QUERY_FILE_MAP = {
    "python": "py_docstrings.scm",
    "java": "java_methods.scm",
}

TREE_SITTER_PACKAGE_MAP = {
    "python": "tree_sitter_python",
    "java": "tree_sitter_java",
    "javascript": "tree_sitter_javascript",
    "typescript": "tree_sitter_typescript",
    "tsx": "tree_sitter_typescript",
    "go": "tree_sitter_go",
    "rust": "tree_sitter_rust",
    "ruby": "tree_sitter_ruby",
    "php": "tree_sitter_php",
    "bash": "tree_sitter_bash",
    "c": "tree_sitter_c",
    "cpp": "tree_sitter_cpp",
    "csharp": "tree_sitter_c_sharp",
    "swift": "tree_sitter_swift",
    "kotlin": "tree_sitter_kotlin",
}


def query_path(language: str) -> Path:
    filename = QUERY_FILE_MAP.get(language)
    if filename is None:
        raise ValueError(f"no bundled query available for tree-sitter language: {language}")
    return Path(__file__).resolve().parent / "queries" / filename


def load_query_source(language: str) -> str:
    return query_path(language).read_text(encoding="utf-8")


def build_parser(language: str) -> Any:
    """Build a tree-sitter parser for a supported language."""

    try:
        from tree_sitter import Language, Parser
    except ImportError as exc:
        raise ExtractionDependencyError("tree-sitter is not installed") from exc

    package_name = TREE_SITTER_PACKAGE_MAP.get(language)
    if package_name is None:
        raise ValueError(f"unsupported tree-sitter language: {language}")
    try:
        language_module = importlib.import_module(package_name)
    except ImportError as exc:
        raise ExtractionDependencyError(f"{package_name} is not installed") from exc
    language_capsule = language_module.language()

    parser = Parser()
    ts_language = Language(language_capsule)
    if hasattr(parser, "set_language"):
        parser.set_language(ts_language)
    else:
        parser.language = ts_language
    return parser



