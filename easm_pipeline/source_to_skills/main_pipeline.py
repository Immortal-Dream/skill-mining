"""Entry point orchestrator for Stage 1 of the EASM pipeline."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger

from easm_pipeline.constants.path_config import DEFAULT_DOMAIN, SUPPORTED_DOMAINS, domain_output_dir, domain_source_dir
from easm_pipeline.core.logging import configure_logging
from easm_pipeline.core.llm_infra.cli_support import add_llm_arguments, build_llm_client_from_args
from easm_pipeline.core.llm_infra.clients import StructuredLLMClient
from easm_pipeline.core.llm_infra.schemas import CapabilitySlice, ExtractedNode, SkillPayload
from easm_pipeline.registered_skill_writer import RegisteredSkillWriter
from easm_pipeline.source_to_skills.extraction.common import iter_source_files, slugify
from easm_pipeline.source_to_skills.extraction.dependency_resolver import DependencyResolver
from easm_pipeline.source_to_skills.extraction.generic_miner import GenericTextMiner
from easm_pipeline.source_to_skills.extraction.java_miner import JavaMiner
from easm_pipeline.source_to_skills.extraction.python_miner import PythonMiner
from easm_pipeline.source_to_skills.extraction.registry import SourceMinerRegistry
from easm_pipeline.source_to_skills.mining.candidate_evaluator import CandidateEvaluator
from easm_pipeline.source_to_skills.mining.candidate_schema import CandidateDecision
from easm_pipeline.source_to_skills.packaging.registered_skill import RegisteredSkillPackage
from easm_pipeline.source_to_skills.packaging.registry_builder import RegistryBuilder
from easm_pipeline.source_to_skills.script_mining.native_script_generator import NativeSourceScriptGenerator
from easm_pipeline.source_to_skills.script_mining.script_generator import ScriptGenerator
from easm_pipeline.source_to_skills.script_mining.script_validator import ScriptValidator
from easm_pipeline.source_to_skills.synthesis.code_bundler import CodeBundler
from easm_pipeline.source_to_skills.synthesis.instruction_writer import InstructionWriter
from easm_pipeline.source_to_skills.synthesis.metadata_generator import MetadataGenerator
from easm_pipeline.source_to_skills.synthesis.skill_doc_generator import SkillDocGenerator
from easm_pipeline.source_to_skills.synthesis.skill_reviewer import SkillInstructionReviewer


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
        self.generic_miner = GenericTextMiner()
        self.miner_registry = SourceMinerRegistry(
            python_miner=self.python_miner,
            java_miner=self.java_miner,
            generic_miner=self.generic_miner,
        )
        self.metadata_generator = MetadataGenerator(config.llm_client)
        self.instruction_writer = InstructionWriter(config.llm_client)
        self.skill_reviewer = SkillInstructionReviewer(config.llm_client)
        self.code_bundler = CodeBundler()
        self.dependency_resolver = DependencyResolver()
        self.candidate_evaluator = CandidateEvaluator(config.llm_client)
        self.script_generator = ScriptGenerator(config.llm_client)
        self.native_script_generator = NativeSourceScriptGenerator(config.llm_client)
        self.script_validator = ScriptValidator()
        self.skill_doc_generator = SkillDocGenerator(config.llm_client)
        self.skill_writer = RegisteredSkillWriter()

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
            packages.append(package)
        write_result = self.skill_writer.write_packages(
            packages=tuple(packages),
            output_dir=self.config.output_dir,
            overwrite=self.config.overwrite,
        )
        for skill_dir in write_result.skill_dirs:
            logger.info("Wrote skill directory: {}", skill_dir)
        logger.info(
            "Completed EASM Stage 1 run: generated_skills={} skipped={}",
            len(write_result.skill_dirs),
            len(skipped),
        )
        return PipelineResult(
            capabilities=capabilities,
            skill_dirs=write_result.skill_dirs,
            packages=write_result.packages,
            skipped=tuple(skipped),
        )

    def extract_capabilities(self) -> list[CapabilitySlice]:
        source_dir = self.config.source_dir.resolve()
        if not source_dir.exists() or not source_dir.is_dir():
            raise FileNotFoundError(f"source directory does not exist: {source_dir}")

        capabilities: list[CapabilitySlice] = []
        for source_file in iter_source_files(source_dir):
            logger.debug("Mining source file: {}", source_file)
            nodes = self.miner_registry.mine_file(source_file, project_root=source_dir)
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

        node = capability.nodes[0]
        if node.language == "python":
            script = self.script_generator.generate(capability, dependencies, decision)
        else:
            script = self.native_script_generator.generate(
                capability,
                dependencies,
                decision,
                source_root=self.config.source_dir,
            )
        validation = self.script_validator.validate(script)
        if not validation.passed and self.config.llm_client is not None:
            logger.warning(
                "LLM-generated script failed validation; falling back to deterministic script: skill_id={}",
                decision.skill_id,
            )
            if node.language == "python":
                script = self.script_generator.generate_fallback(capability, dependencies, decision)
            else:
                script = self.native_script_generator.generate_fallback(
                    capability,
                    decision,
                    source_root=self.config.source_dir,
                )
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
        summary=f"Extracted {len(nodes)} source node(s) from {relative}.",
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


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stage 1 of the EASM skill mining pipeline.")
    parser.add_argument(
        "source_dir",
        type=Path,
        nargs="?",
        help="Directory containing source files to mine into skills. Omit when using --domain.",
    )
    parser.add_argument(
        "--domain",
        default=None,
        help=(
            "Mine a configured domain from data/sample_source/<domain> into "
            "data/output_skills/<domain>. "
            f"Known starter domains: {', '.join(SUPPORTED_DOMAINS)}."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory where generated skill folders will be written. Overrides the configured domain output path.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing generated skill directories.")
    parser.add_argument(
        "--strict-tree-sitter",
        action="store_true",
        help="Fail when tree-sitter dependencies are unavailable instead of using deterministic fallbacks.",
    )
    return add_llm_arguments(parser)


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    source_dir, output_dir = _resolve_cli_paths(args)
    pipeline = EASMPipeline(
        PipelineConfig(
            source_dir=source_dir,
            output_dir=output_dir,
            overwrite=args.overwrite,
            prefer_tree_sitter=True,
            allow_parser_fallback=not args.strict_tree_sitter,
            llm_client=build_llm_client_from_args(args),
        )
    )
    result = pipeline.run()
    for skill_dir in result.skill_dirs:
        print(skill_dir)
    return 0


def _resolve_cli_paths(args: argparse.Namespace) -> tuple[Path, Path]:
    domain = args.domain
    if domain:
        source_dir = args.source_dir or domain_source_dir(domain)
        output_dir = args.output_dir or domain_output_dir(domain)
        return source_dir, output_dir

    if args.source_dir is None:
        domain = DEFAULT_DOMAIN
        return domain_source_dir(domain), args.output_dir or domain_output_dir(domain)

    return args.source_dir, args.output_dir or Path("output_skills")


if __name__ == "__main__":
    raise SystemExit(main())

