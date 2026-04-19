"""Strict data contracts shared between EASM pipeline stages.

These models are deliberately deterministic. They do not import or call any
LLM client code, so extraction can produce instances without depending on
probabilistic synthesis.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any, ClassVar

from pydantic.v1 import BaseModel, Extra, Field, root_validator, validator


_XML_TAG_RE = re.compile(r"<\/?[A-Za-z][^>]*>")
_SKILL_NAME_RE = re.compile(r"^[a-z0-9-]+$")


def _must_not_contain_xml(value: str, field_name: str) -> str:
    if _XML_TAG_RE.search(value):
        raise ValueError(f"{field_name} must not contain XML tags")
    return value


def _require_non_empty(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


class StrictModel(BaseModel):
    """Base model that rejects accidental cross-stage data leakage."""

    class Config:
        extra = Extra.forbid
        validate_assignment = True


class ExtractedNode(StrictModel):
    """Deterministic extraction result for a source node or source file."""

    node_id: str = Field(
        ...,
        min_length=1,
        description="Stable deterministic identifier, usually derived from file path and byte span.",
    )
    language: str = Field(..., min_length=1, description="Source language used by the miner.")
    node_type: str = Field(
        ...,
        description="AST node category captured by deterministic parsing.",
    )
    name: str = Field(..., min_length=1, description="Function, method, constructor, or class name.")
    signature: str = Field(..., min_length=1, description="Source-level callable signature.")
    raw_code: str = Field(..., min_length=1, description="Exact source bytes decoded to text.")
    docstring: str | None = Field(None, description="Best-effort leading documentation text for the node.")
    file_path: str | None = Field(None, description="Project-relative path to the source file.")
    start_byte: int = Field(..., ge=0, description="Inclusive byte offset in the source file.")
    end_byte: int = Field(..., ge=0, description="Exclusive byte offset in the source file.")
    start_line: int = Field(..., ge=1, description="One-based inclusive start line.")
    end_line: int = Field(..., ge=1, description="One-based inclusive end line.")
    scope_path: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Hierarchical scope, for example module, class, nested function.",
    )
    annotations: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Decorators or Java annotations attached to the node.",
    )
    imports: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Localized import statements relevant to this node.",
    )
    dependencies: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Deterministically resolved local type or symbol dependencies.",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Miner-owned deterministic metadata. LLM outputs do not belong here.",
    )

    @validator("node_id", "name", "signature", "language", "node_type")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value, "field")

    @validator("raw_code")
    @classmethod
    def _validate_raw_code(cls, value: str) -> str:
        return _require_non_empty(value, "raw_code")

    @validator("docstring")
    @classmethod
    def _normalize_docstring(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @validator("file_path")
    @classmethod
    def _validate_file_path(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.replace("\\", "/").strip()
        if not normalized:
            raise ValueError("file_path must be non-empty when supplied")
        path = PurePosixPath(normalized)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("file_path must be a safe project-relative path")
        return normalized

    @validator("scope_path", "annotations", "imports", "dependencies")
    @classmethod
    def _validate_string_tuple(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not item or not item.strip():
                raise ValueError("tuple entries must be non-empty strings")
        return tuple(item.strip() for item in value)

    @root_validator(skip_on_failure=True)
    def _validate_offsets_and_lines(cls, values: dict[str, Any]) -> dict[str, Any]:
        if values["end_byte"] <= values["start_byte"]:
            raise ValueError("end_byte must be greater than start_byte")
        if values["end_line"] < values["start_line"]:
            raise ValueError("end_line must be greater than or equal to start_line")
        return values

    @property
    def source_code(self) -> str:
        """Backward-compatible alias for callers that name raw code source_code."""

        return self.raw_code

    def render_llm_context(self, max_code_chars: int = 4000) -> str:
        """Render deterministic context for later synthesis prompts."""

        code = self.raw_code
        if len(code) > max_code_chars:
            code = f"{code[:max_code_chars]}\n# ... truncated by ExtractedNode.render_llm_context"

        sections = [
            f"Node: {self.name}",
            f"Language: {self.language}",
            f"Type: {self.node_type}",
            f"Signature: {self.signature}",
            f"Lines: {self.start_line}-{self.end_line}",
            f"Bytes: {self.start_byte}-{self.end_byte}",
        ]
        if self.file_path:
            sections.append(f"File: {self.file_path}")
        if self.scope_path:
            sections.append(f"Scope: {' > '.join(self.scope_path)}")
        if self.docstring:
            sections.append(f"Docstring: {self.docstring}")
        if self.annotations:
            sections.append(f"Annotations: {', '.join(self.annotations)}")
        if self.dependencies:
            sections.append(f"Dependencies: {', '.join(self.dependencies)}")
        sections.append(f"```{self.language}\n{code}\n```")
        return "\n".join(sections)


class CapabilitySlice(StrictModel):
    """A deterministic group of related extracted nodes for one synthesis unit."""

    slice_id: str = Field(..., min_length=1, description="Stable deterministic slice identifier.")
    title: str = Field(..., min_length=1, description="Human-readable capability title.")
    nodes: tuple[ExtractedNode, ...] = Field(
        default_factory=tuple,
        description="Extracted source nodes that jointly implement this capability.",
    )
    summary: str | None = Field(None, description="Optional deterministic summary from extraction.")
    source_files: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Project-relative source files represented by this slice.",
    )
    references: dict[str, str] = Field(
        default_factory=dict,
        description="Additional deterministic context, keyed by reference filename.",
    )
    warnings: tuple[str, ...] = Field(
        default_factory=tuple,
        description="Extraction or static-analysis warnings to carry into synthesis.",
    )

    @validator("slice_id", "title")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _require_non_empty(value, "field")

    @validator("summary")
    @classmethod
    def _normalize_summary(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @validator("source_files")
    @classmethod
    def _validate_source_files(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized_files: list[str] = []
        for item in value:
            normalized = item.replace("\\", "/").strip()
            path = PurePosixPath(normalized)
            if not normalized or path.is_absolute() or ".." in path.parts:
                raise ValueError("source_files must contain safe project-relative paths")
            normalized_files.append(normalized)
        return tuple(normalized_files)

    @validator("references")
    @classmethod
    def _validate_references(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for key, content in value.items():
            safe_key = key.replace("\\", "/").strip()
            path = PurePosixPath(safe_key)
            if not safe_key or path.is_absolute() or ".." in path.parts:
                raise ValueError("reference keys must be safe project-relative paths")
            if not content or not content.strip():
                raise ValueError("reference content must be non-empty")
            normalized[safe_key] = content
        return normalized

    @validator("warnings")
    @classmethod
    def _validate_warnings(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for warning in value:
            if not warning or not warning.strip():
                raise ValueError("warnings must be non-empty strings")
        return tuple(warning.strip() for warning in value)

    @root_validator(skip_on_failure=True)
    def _require_context(cls, values: dict[str, Any]) -> dict[str, Any]:
        if not values.get("nodes") and not values.get("references") and not values.get("summary"):
            raise ValueError("CapabilitySlice requires nodes, references, or a summary")
        return values

    def render_llm_context(self, max_node_code_chars: int = 4000) -> str:
        """Render this slice as bounded deterministic prompt context."""

        lines = [f"# Capability Slice: {self.title}", f"Slice ID: {self.slice_id}"]
        if self.summary:
            lines.append(f"Summary: {self.summary}")
        if self.source_files:
            lines.append(f"Source files: {', '.join(self.source_files)}")
        if self.warnings:
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in self.warnings)
        if self.references:
            lines.append("References:")
            lines.extend(f"- {name}" for name in sorted(self.references))
        if self.nodes:
            lines.append("Extracted nodes:")
            for node in self.nodes:
                lines.append(node.render_llm_context(max_code_chars=max_node_code_chars))
        return "\n\n".join(lines)

    def to_llm_context(self, max_node_code_chars: int = 4000) -> str:
        """Compatibility alias for downstream callers."""

        return self.render_llm_context(max_node_code_chars=max_node_code_chars)


class SkillPayload(StrictModel):
    """Validated output contract for final skill material before filesystem build."""

    RESERVED_NAME_TERMS: ClassVar[set[str]] = {"anthropic", "claude"}

    name: str = Field(
        ...,
        min_length=1,
        max_length=64,
        regex=r"^[a-z0-9-]+$",
        description="Filesystem-safe skill directory name.",
    )
    description: str = Field(..., min_length=1, max_length=1024)
    instructions: str = Field(..., min_length=1, description="SKILL.md body without YAML frontmatter.")
    scripts_dict: dict[str, str] = Field(
        default_factory=dict,
        description="Standalone script file contents keyed by safe filename.",
    )
    references_dict: dict[str, str] = Field(
        default_factory=dict,
        description="Reference file contents keyed by safe filename.",
    )

    @validator("name")
    @classmethod
    def _validate_name(cls, value: str) -> str:
        normalized = value.strip()
        _must_not_contain_xml(normalized, "name")
        if not _SKILL_NAME_RE.fullmatch(normalized):
            raise ValueError("name must match ^[a-z0-9-]+$")
        lowered = normalized.lower()
        for term in cls.RESERVED_NAME_TERMS:
            if term in lowered:
                raise ValueError(f"name must not contain reserved term: {term}")
        return normalized

    @validator("description")
    @classmethod
    def _validate_description(cls, value: str) -> str:
        normalized = _require_non_empty(value.strip(), "description")
        return _must_not_contain_xml(normalized, "description")

    @validator("instructions")
    @classmethod
    def _validate_instructions(cls, value: str) -> str:
        return _require_non_empty(value, "instructions")

    @validator("scripts_dict", "references_dict")
    @classmethod
    def _validate_bundle_files(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for raw_name, content in value.items():
            safe_name = raw_name.replace("\\", "/").strip()
            path = PurePosixPath(safe_name)
            if (
                not safe_name
                or path.is_absolute()
                or ".." in path.parts
                or len(path.parts) != 1
            ):
                raise ValueError("bundle file keys must be safe filenames, not paths")
            if not content or not content.strip():
                raise ValueError(f"bundle file {safe_name} must contain non-empty content")
            normalized[safe_name] = content
        return normalized

    def frontmatter(self) -> dict[str, str]:
        """Return the YAML frontmatter fields required by Claude Agent Skills."""

        return {"name": self.name, "description": self.description}


