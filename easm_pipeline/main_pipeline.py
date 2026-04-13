"""Entry point orchestrator for Stage 1 of the EASM pipeline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from easm_pipeline.core.logging import configure_logging
from easm_pipeline.core.llm_infra.clients import (
    RIGHT_CODE_DEFAULT_MODEL,
    LLMClientConfig,
    LLMProvider,
    StructuredLLMClient,
)
from easm_pipeline.core.llm_infra.schemas import CapabilitySlice, ExtractedNode, SkillPayload
from easm_pipeline.extraction.common import iter_source_files, slugify
from easm_pipeline.extraction.dependency_resolver import DependencyResolver
from easm_pipeline.extraction.java_miner import JavaMiner
from easm_pipeline.extraction.python_miner import PythonMiner
from easm_pipeline.mining.candidate_evaluator import CandidateEvaluator
from easm_pipeline.mining.candidate_schema import CandidateDecision
from easm_pipeline.packaging.filesystem_builder import FilesystemBuilder
from easm_pipeline.packaging.registered_skill import RegisteredSkillPackage
from easm_pipeline.packaging.registry_builder import RegistryBuilder
from easm_pipeline.script_mining.script_generator import ScriptGenerator
from easm_pipeline.script_mining.script_validator import ScriptValidator
from easm_pipeline.synthesis.code_bundler import CodeBundler
from easm_pipeline.synthesis.instruction_writer import InstructionWriter
from easm_pipeline.synthesis.metadata_generator import MetadataGenerator
from easm_pipeline.synthesis.skill_doc_generator import SkillDocGenerator
from easm_pipeline.synthesis.skill_reviewer import SkillInstructionReviewer


@dataclass(frozen=True)
class PipelineConfig:
    """Runtime configuration for the Stage 1 pipeline."""

    source_dir: Path
    output_dir: Path
    overwrite: bool = False
    prefer_tree_sitter: bool = True
    allow_parser_fallback: bool = True
    llm_client: StructuredLLMClient | None = None


@dataclass(frozen=True)
class PipelineResult:
    """Summary of a pipeline run."""

    capabilities: tuple[CapabilitySlice, ...]
    skill_dirs: tuple[Path, ...]
    packages: tuple[RegisteredSkillPackage, ...] = field(default_factory=tuple)
    skipped: tuple[CandidateDecision, ...] = field(default_factory=tuple)


class EASMPipeline:
    """DAG orchestrator: source dir -> extraction -> synthesis -> packaging."""

    def __init__(self, config: PipelineConfig) -> None:
        configure_logging()
        self.config = config
        self.python_miner = PythonMiner(
            prefer_tree_sitter=config.prefer_tree_sitter,
            allow_ast_fallback=config.allow_parser_fallback,
        )
        self.java_miner = JavaMiner(
            prefer_tree_sitter=config.prefer_tree_sitter,
            allow_regex_fallback=config.allow_parser_fallback,
        )
        self.metadata_generator = MetadataGenerator(config.llm_client)
        self.instruction_writer = InstructionWriter(config.llm_client)
        self.skill_reviewer = SkillInstructionReviewer(config.llm_client)
        self.code_bundler = CodeBundler()
        self.dependency_resolver = DependencyResolver()
        self.candidate_evaluator = CandidateEvaluator(config.llm_client)
        self.script_generator = ScriptGenerator(config.llm_client)
        self.script_validator = ScriptValidator()
        self.skill_doc_generator = SkillDocGenerator(config.llm_client)
        self.filesystem_builder = FilesystemBuilder()
        self.registry_builder = RegistryBuilder()

    def run(self) -> PipelineResult:
        logger.info(
            "Starting EASM Stage 1 run: source_dir={} output_dir={} overwrite={} llm_enabled={}",
            self.config.source_dir,
            self.config.output_dir,
            self.config.overwrite,
            self.config.llm_client is not None,
        )
        capabilities = tuple(self.extract_capabilities())
        logger.info("Extracted {} capability slice(s)", len(capabilities))
        skill_dirs: list[Path] = []
        packages: list[RegisteredSkillPackage] = []
        skipped: list[CandidateDecision] = []
        for capability in capabilities:
            logger.info(
                "Mining script-first skill for slice={} title={} node_count={}",
                capability.slice_id,
                capability.title,
                len(capability.nodes),
            )
            package = self.mine_registered_skill(capability)
            if package is None:
                decision = self._last_skip_decision
                if decision is not None:
                    skipped.append(decision)
                continue
            skill_dir = self.filesystem_builder.build_registered_skill(
                package,
                self.config.output_dir,
                overwrite=self.config.overwrite,
            )
            logger.info("Wrote skill directory: {}", skill_dir)
            skill_dirs.append(skill_dir)
            packages.append(package)
        if packages:
            self.registry_builder.update(self.config.output_dir, tuple(packages))
        logger.info(
            "Completed EASM Stage 1 run: generated_skills={} skipped={}",
            len(skill_dirs),
            len(skipped),
        )
        return PipelineResult(
            capabilities=capabilities,
            skill_dirs=tuple(skill_dirs),
            packages=tuple(packages),
            skipped=tuple(skipped),
        )

    def extract_capabilities(self) -> list[CapabilitySlice]:
        source_dir = self.config.source_dir.resolve()
        if not source_dir.exists() or not source_dir.is_dir():
            raise FileNotFoundError(f"source directory does not exist: {source_dir}")

        capabilities: list[CapabilitySlice] = []
        for source_file in iter_source_files(source_dir):
            logger.debug("Mining source file: {}", source_file)
            if source_file.suffix.lower() == ".py":
                nodes = self.python_miner.mine_file(source_file, project_root=source_dir)
            elif source_file.suffix.lower() == ".java":
                nodes = self.java_miner.mine_file(source_file, project_root=source_dir)
            else:
                continue
            if not nodes:
                logger.debug("No extractable nodes found: {}", source_file)
                continue
            logger.info("Extracted {} node(s) from {}", len(nodes), source_file)
            for node in nodes:
                capabilities.append(_capability_from_nodes(source_file, source_dir, [node]))
        return capabilities

    _last_skip_decision: CandidateDecision | None = None

    def mine_registered_skill(self, capability: CapabilitySlice) -> RegisteredSkillPackage | None:
        self._last_skip_decision = None
        dependencies = self.dependency_resolver.resolve(capability, self.config.source_dir)
        decision = self.candidate_evaluator.evaluate(capability, dependencies)
        if decision.decision == "skip":
            self._last_skip_decision = decision
            logger.info("Skipped capability: slice={} reason={}", capability.slice_id, decision.reason)
            return None

        script = self.script_generator.generate(capability, dependencies, decision)
        validation = self.script_validator.validate(script)
        if not validation.passed and self.config.llm_client is not None:
            logger.warning(
                "LLM-generated script failed validation; falling back to deterministic script: skill_id={}",
                decision.skill_id,
            )
            script = self.script_generator.generate_fallback(capability, dependencies, decision)
            validation = self.script_validator.validate(script)
        if not validation.passed:
            self._last_skip_decision = decision.copy(
                update={"decision": "skip", "skill_id": None, "reason": "generated script failed validation"}
            )
            logger.warning("Skipped invalid generated script: skill_id={}", decision.skill_id)
            return None

        try:
            skill_doc = self.skill_doc_generator.generate(script=script, decision=decision, validation=validation)
        except Exception:
            logger.warning("LLM-generated SKILL.md failed validation; falling back to deterministic doc: {}", script.skill_id)
            skill_doc = self.skill_doc_generator.generate_fallback(script=script, decision=decision, validation=validation)

        node = capability.nodes[0]
        return RegisteredSkillPackage(
            decision=decision,
            script=script,
            skill_doc=skill_doc,
            validation=validation,
            source_file=node.file_path,
            source_span={"start_line": node.start_line, "end_line": node.end_line},
        )

    def synthesize_payload(self, capability: CapabilitySlice) -> SkillPayload:
        """Legacy payload synthesis retained for callers that still use the old layout."""

        # Code is bundled before LLM synthesis so prompts can reference approved
        # script names without asking the model to decide execution safety.
        bundle = self.code_bundler.bundle(capability)
        warnings = tuple(
            f"{finding.severity}:{finding.rule_id}:{finding.message}" for finding in bundle.findings
        )
        logger.info(
            "Bundled slice={} scripts={} references={} security_findings={}",
            capability.slice_id,
            len(bundle.scripts_dict),
            len(bundle.references_dict),
            len(bundle.findings),
        )
        logger.debug("Generating metadata for slice={}", capability.slice_id)
        metadata = self.metadata_generator.generate(capability)
        logger.debug("Generating draft instructions for slice={}", capability.slice_id)
        instructions = self.instruction_writer.write(
            capability,
            script_names=tuple(sorted(bundle.scripts_dict)),
            reference_names=tuple(sorted(bundle.references_dict)),
            warnings=warnings,
        )
        logger.debug("Reviewing instruction draft for slice={}", capability.slice_id)
        reviewed = self.skill_reviewer.review(
            capability,
            draft_instructions=instructions.instructions,
            script_names=tuple(sorted(bundle.scripts_dict)),
            reference_names=tuple(sorted(bundle.references_dict)),
            warnings=warnings,
        )
        return SkillPayload(
            name=metadata.name,
            description=metadata.description,
            instructions=reviewed.instructions,
            scripts_dict=bundle.scripts_dict,
            references_dict=bundle.references_dict,
        )


def _capability_from_nodes(source_file: Path, source_root: Path, nodes: list[ExtractedNode]) -> CapabilitySlice:
    relative = source_file.resolve().relative_to(source_root.resolve()).as_posix()
    node_label = nodes[0].name if len(nodes) == 1 else source_file.stem
    title = node_label.replace("_", " ").replace("-", " ").title()
    return CapabilitySlice(
        slice_id=slugify(f"{relative}-{node_label}", max_length=64),
        title=title,
        nodes=tuple(nodes),
        summary=f"Extracted {len(nodes)} callable node(s) from {relative}.",
        source_files=(relative,),
    )


def _dedupe_payload_name(payload: SkillPayload, used_names: set[str]) -> SkillPayload:
    if payload.name not in used_names:
        return payload
    counter = 2
    while True:
        suffix = f"-{counter}"
        base = payload.name[: 64 - len(suffix)].rstrip("-")
        candidate = f"{base}{suffix}"
        if candidate not in used_names:
            return payload.copy(update={"name": candidate})
        counter += 1


def _build_llm_client(args: argparse.Namespace) -> StructuredLLMClient | None:
    if not args.use_llm and not args.provider and not args.model and not args.api_key and not args.base_url:
        return None
    provider = LLMProvider(args.provider) if args.provider else LLMProvider.RIGHT_CODE
    config = LLMClientConfig(
        provider=provider,
        model=args.model or RIGHT_CODE_DEFAULT_MODEL,
        api_key=args.api_key,
        base_url=args.base_url,
        max_retries=args.max_retries,
        requests_per_minute=args.requests_per_minute,
    )
    return StructuredLLMClient(config)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stage 1 of the EASM skill mining pipeline.")
    parser.add_argument("source_dir", type=Path, help="Directory containing Python and Java legacy source files.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output_skills"),
        help="Directory where generated skill folders will be written.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing generated skill directories.")
    parser.add_argument(
        "--strict-tree-sitter",
        action="store_true",
        help="Fail when tree-sitter dependencies are unavailable instead of using deterministic fallbacks.",
    )
    parser.add_argument(
        "--provider",
        choices=[provider.value for provider in LLMProvider],
        help="Structured-output provider protocol. Defaults to right-code when LLM synthesis is enabled.",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help=f"Enable LLM synthesis. Defaults to right-code with RIGHT_CODE_API_KEY and model {RIGHT_CODE_DEFAULT_MODEL}.",
    )
    parser.add_argument("--model", help=f"LLM model name for synthesis. Defaults to {RIGHT_CODE_DEFAULT_MODEL}.")
    parser.add_argument(
        "--api-key",
        help="Provider API key override. Prefer RIGHT_CODE_API_KEY for right-code.",
    )
    parser.add_argument("--base-url", help="Provider API base URL override.")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--requests-per-minute", type=float, default=60.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    pipeline = EASMPipeline(
        PipelineConfig(
            source_dir=args.source_dir,
            output_dir=args.output_dir,
            overwrite=args.overwrite,
            prefer_tree_sitter=True,
            allow_parser_fallback=not args.strict_tree_sitter,
            llm_client=_build_llm_client(args),
        )
    )
    result = pipeline.run()
    for skill_dir in result.skill_dirs:
        print(skill_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
