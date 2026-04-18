"""Generate source-preserving native-language skill artifacts."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

from easm_pipeline.core.llm_infra.clients import StructuredLLMClient
from easm_pipeline.core.llm_infra.schemas import CapabilitySlice, ExtractedNode
from easm_pipeline.source_to_skills.extraction.common import slugify
from easm_pipeline.source_to_skills.extraction.dependency_resolver import DependencyContext
from easm_pipeline.source_to_skills.language_support import detect_runtime_for_path, runtime_for_language
from easm_pipeline.source_to_skills.mining.candidate_schema import CandidateDecision

from .script_schema import GeneratedScript


class NativeSourceScriptGenerator:
    """Package the source-language implementation as the skill script artifact."""

    def __init__(self, llm_client: StructuredLLMClient | None = None) -> None:
        self._llm_client = llm_client

    def generate(
        self,
        capability: CapabilitySlice,
        dependencies: DependencyContext,
        decision: CandidateDecision,
        *,
        source_root: Path | None = None,
    ) -> GeneratedScript:
        del dependencies
        logger.info("Generating native-language source artifact: skill_id={}", decision.skill_id)
        return self.generate_fallback(capability, decision, source_root=source_root)

    def generate_fallback(
        self,
        capability: CapabilitySlice,
        decision: CandidateDecision,
        *,
        source_root: Path | None = None,
    ) -> GeneratedScript:
        node = capability.nodes[0]
        skill_id = decision.skill_id or slugify(node.name)
        filename = _filename_for_node(node, skill_id)
        source_text = _source_text_for_node(node, source_root=source_root)
        runtime = _runtime_for_node(node, filename)
        description = _description_for_node(node)
        return GeneratedScript(
            skill_id=skill_id,
            language=node.language,
            runtime_hint=runtime.runtime_hint,
            filename=filename,
            description=description,
            script_text=source_text,
            entry_function=_entry_symbol(node) or "main",
            entry_symbol=_entry_symbol(node),
            cli_arguments=(),
            dependencies=decision.dependencies,
            tags=decision.tags,
            source=decision.source,
            example_command=runtime.example_command(
                script_path=f"scripts/{filename}",
                entry_symbol=_entry_symbol(node),
            ),
            supports_help=runtime.supports_help,
        )


def _source_text_for_node(node: ExtractedNode, *, source_root: Path | None = None) -> str:
    if source_root is not None and node.file_path:
        path = source_root / node.file_path
        if path.exists() and path.is_file():
            return path.read_text(encoding="utf-8").rstrip() + "\n"
    return node.raw_code.rstrip() + "\n"


def _filename_for_node(node: ExtractedNode, skill_id: str) -> str:
    if node.file_path:
        path = Path(node.file_path)
        if path.name:
            return path.name
    extension = _extension_for_language(node.language)
    stem = skill_id.replace("-", "_")
    return f"{stem}{extension}"


def _extension_for_language(language_id: str) -> str:
    runtime = runtime_for_language(language_id)
    if runtime.suffixes:
        return runtime.suffixes[0]
    return ".txt"


def _runtime_for_node(node: ExtractedNode, filename: str):
    if node.file_path:
        return detect_runtime_for_path(Path(node.file_path))
    return detect_runtime_for_path(Path(filename))


def _description_for_node(node: ExtractedNode) -> str:
    if node.docstring:
        return node.docstring.splitlines()[0].strip()[:180]
    words = node.name.replace("_", " ").replace("-", " ")
    return f"Run reusable {words} logic from mined {node.language} source code."


def _entry_symbol(node: ExtractedNode) -> str | None:
    if node.node_type == "file":
        return None
    return node.name
