"""Optional tree-sitter setup utilities.

Imports are intentionally lazy so the rest of the pipeline can still run unit
tests in environments where parser wheels have not been installed yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from .common import ExtractionDependencyError


LanguageName = Literal["python", "java"]


def query_path(language: LanguageName) -> Path:
    filename = "py_docstrings.scm" if language == "python" else "java_methods.scm"
    return Path(__file__).resolve().parent / "queries" / filename


def load_query_source(language: LanguageName) -> str:
    return query_path(language).read_text(encoding="utf-8")


def build_parser(language: LanguageName) -> Any:
    """Build a tree-sitter parser for a supported language."""

    try:
        from tree_sitter import Language, Parser
    except ImportError as exc:
        raise ExtractionDependencyError("tree-sitter is not installed") from exc

    if language == "python":
        try:
            import tree_sitter_python
        except ImportError as exc:
            raise ExtractionDependencyError("tree-sitter-python is not installed") from exc
        language_capsule = tree_sitter_python.language()
    elif language == "java":
        try:
            import tree_sitter_java
        except ImportError as exc:
            raise ExtractionDependencyError("tree-sitter-java is not installed") from exc
        language_capsule = tree_sitter_java.language()
    else:
        raise ValueError(f"unsupported tree-sitter language: {language}")

    parser = Parser()
    ts_language = Language(language_capsule)
    if hasattr(parser, "set_language"):
        parser.set_language(ts_language)
    else:
        parser.language = ts_language
    return parser

