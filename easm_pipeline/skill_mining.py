"""Skill-mining entry points for DAG/provenance-based skill generation."""

from __future__ import annotations

import argparse
import json
import keyword
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger

from easm_pipeline.core.logging import configure_logging
from easm_pipeline.core.llm_infra.cli_support import add_llm_arguments, build_llm_client_from_args
from easm_pipeline.core.llm_infra.clients import StructuredLLMClient
from easm_pipeline.dag_to_skills.graph import DataflowGraph
from easm_pipeline.dag_to_skills.library_learning import RepresentativePattern, mine_representative_patterns, to_jsonable_term
from easm_pipeline.dag_to_skills.meta_tool_codegen import SynthesizedMetaTool, synthesize_parallel_meta_tool
from easm_pipeline.provenance_trace import capture_provenance_report_to_path
from easm_pipeline.registered_skill_writer import RegisteredSkillWriter
from easm_pipeline.source_to_skills.extraction.common import slugify
from easm_pipeline.source_to_skills.mining.candidate_schema import CandidateDecision
from easm_pipeline.source_to_skills.packaging.registered_skill import RegisteredSkillPackage
from easm_pipeline.source_to_skills.script_mining.script_schema import GeneratedScript, ScriptCliArgument
from easm_pipeline.source_to_skills.script_mining.script_validator import ScriptValidator
from easm_pipeline.source_to_skills.synthesis.skill_doc_generator import SkillDoc, SkillDocGenerator


@dataclass(frozen=True)
class DAGSkillPipelineConfig:
    report_paths: tuple[Path, ...]
    output_dir: Path
    overwrite: bool = False
    max_depth: int = 2
    min_support: int = 2
    llm_client: StructuredLLMClient | None = None


@dataclass(frozen=True)
class DAGSkillPipelineResult:
    report_paths: tuple[Path, ...]
    patterns: tuple[RepresentativePattern, ...]
    skill_dirs: tuple[Path, ...]
    packages: tuple[RegisteredSkillPackage, ...] = field(default_factory=tuple)
    skipped: tuple[str, ...] = field(default_factory=tuple)


class DAGSkillPipeline:
    def __init__(self, config: DAGSkillPipelineConfig) -> None:
        configure_logging()
        self.config = config
        self.script_validator = ScriptValidator()
        self.skill_doc_generator = SkillDocGenerator(config.llm_client)
        self.skill_writer = RegisteredSkillWriter()

    def run(self) -> DAGSkillPipelineResult:
        report_paths = _normalize_report_paths(self.config.report_paths)
        graphs = [DataflowGraph.from_report_dict(json.loads(path.read_text(encoding="utf-8"))) for path in report_paths]
        patterns = tuple(
            mine_representative_patterns(
                graphs,
                max_depth=self.config.max_depth,
                min_support=self.config.min_support,
            )
        )
        logger.info(
            "Starting DAG skill mining: reports={} patterns={} output_dir={} overwrite={}",
            len(report_paths),
            len(patterns),
            self.config.output_dir,
            self.config.overwrite,
        )
        packages: list[RegisteredSkillPackage] = []
        skipped: list[str] = []
        for index, pattern in enumerate(patterns, start=1):
            package = self._build_package(
                pattern=pattern,
                graph=graphs[pattern.occurrence.graph_index],
                index=index,
                report_path=report_paths[pattern.occurrence.graph_index],
            )
            if package is None:
                skipped.append(pattern.pattern.root_tool_name)
                continue
            packages.append(package)
        write_result = self.skill_writer.write_packages(
            packages=tuple(packages),
            output_dir=self.config.output_dir,
            overwrite=self.config.overwrite,
        )
        return DAGSkillPipelineResult(
            report_paths=tuple(report_paths),
            patterns=patterns,
            skill_dirs=write_result.skill_dirs,
            packages=write_result.packages,
            skipped=tuple(skipped),
        )

    def _build_package(
        self,
        *,
        pattern: RepresentativePattern,
        graph: DataflowGraph,
        index: int,
        report_path: Path,
    ) -> RegisteredSkillPackage | None:
        call_ids = set(pattern.occurrence.call_ids)
        skill_id = _skill_id_for_pattern(pattern, index)
        meta_tool = synthesize_parallel_meta_tool(graph, call_ids, name=f"{skill_id.replace('-', '_')}_tool")
        decision = _decision_for_pattern(pattern, skill_id)
        script = _build_generated_script(skill_id=skill_id, meta_tool=meta_tool, decision=decision)
        validation = self.script_validator.validate(script)
        if not validation.passed:
            logger.warning("Skipping DAG skill with failed validation: skill_id={} errors={}", skill_id, validation.static_errors)
            return None
        try:
            skill_doc = self.skill_doc_generator.generate(script=script, decision=decision, validation=validation)
        except Exception:
            logger.warning("LLM-generated SKILL.md failed validation; falling back to deterministic doc: {}", script.skill_id)
            skill_doc = _build_skill_doc(script, meta_tool, pattern)
        skill_doc = _adapt_skill_doc_for_dag(skill_doc, script=script)
        references = {
            "meta_tool.py": meta_tool.code,
            "pattern.json": json.dumps(_pattern_reference_payload(pattern, meta_tool), indent=2, sort_keys=True),
        }
        return RegisteredSkillPackage(
            decision=decision,
            script=script,
            skill_doc=skill_doc,
            validation=validation,
            source_file=str(report_path),
            source_span={},
            references_dict=references,
        )


def _normalize_report_paths(report_paths: tuple[Path, ...]) -> list[Path]:
    normalized = [path.resolve() for path in report_paths]
    if not normalized:
        raise ValueError("at least one provenance report path is required")
    for path in normalized:
        if not path.is_file():
            raise FileNotFoundError(f"provenance report does not exist: {path}")
    return normalized


def _skill_id_for_pattern(pattern: RepresentativePattern, index: int) -> str:
    raw = f"{pattern.pattern.root_tool_name}-{index}"
    return slugify(raw, max_length=64)


def _decision_for_pattern(pattern: RepresentativePattern, skill_id: str) -> CandidateDecision:
    tags = tuple(dict.fromkeys(_normalize_tag(tool_name) for tool_name, _ in pattern.pattern.shape_signature))
    dependencies = tuple(sorted({tool_name.split('.', 1)[0] for tool_name, _ in pattern.pattern.shape_signature}))
    return CandidateDecision(
        decision="extract",
        reason="frequent provenance DAG pattern adapted into a reusable skill wrapper",
        skill_id=skill_id,
        source="dag-provenance",
        tags=tags,
        dependencies=dependencies,
        reusable_boundary_score=min(1.0, 0.6 + pattern.pattern.support * 0.1),
        domain_value_score=min(1.0, 0.5 + pattern.pattern.latency_gain_seconds * 0.1),
        coupling_score=0.2,
    )


def _normalize_tag(value: str) -> str:
    return value.replace('.', '-').replace('_', '-')


def _build_generated_script(*, skill_id: str, meta_tool: SynthesizedMetaTool, decision: CandidateDecision) -> GeneratedScript:
    filename = f"{skill_id.replace('-', '_')}.py"
    boundary_arguments = [_boundary_to_cli_argument(boundary) for boundary in meta_tool.boundary_inputs]
    argument_paths = {argument.name: str(boundary["arg_path"]) for argument, boundary in zip(boundary_arguments, meta_tool.boundary_inputs)}
    script_text = _render_script_text(
        skill_id=skill_id,
        meta_tool=meta_tool,
        arguments=boundary_arguments,
        argument_paths=argument_paths,
    )
    return GeneratedScript(
        skill_id=skill_id,
        filename=filename,
        description=_description_for_meta_tool(meta_tool),
        script_text=script_text,
        entry_function="core_function",
        cli_arguments=tuple(boundary_arguments),
        dependencies=decision.dependencies,
        tags=decision.tags,
        source=decision.source,
    )


def _description_for_meta_tool(meta_tool: SynthesizedMetaTool) -> str:
    root_tool = meta_tool.internal_calls[-1].replace('.', ' ')
    return f"Execute the mined DAG workflow ending in {root_tool}."


def _boundary_to_cli_argument(boundary: dict[str, Any]) -> ScriptCliArgument:
    flag_name = _arg_flag_from_path(str(boundary["arg_path"]))
    value_type = _value_type_for_boundary(boundary)
    required = boundary.get("source") == "external_tracked" and "default" not in boundary
    default = boundary.get("default")
    return ScriptCliArgument(
        name=_arg_dest_from_path(str(boundary["arg_path"])),
        flag=f"--{flag_name}-json" if value_type == "json" else f"--{flag_name}",
        required=required,
        value_type=value_type,
        help=_help_for_boundary(boundary, value_type),
        default=None if required or default is None else json.dumps(default, default=str),
    )


def _arg_flag_from_path(arg_path: str) -> str:
    leaf = arg_path.split('.')[-1].replace('[', '-').replace(']', '')
    return slugify(leaf, max_length=40).replace('_', '-')


def _arg_dest_from_path(arg_path: str) -> str:
    leaf = arg_path.split('.')[-1].replace('[', '_').replace(']', '')
    cleaned = ''.join(char if char.isalnum() or char == '_' else '_' for char in leaf).strip('_') or 'value'
    if cleaned[0].isdigit():
        cleaned = f"value_{cleaned}"
    if keyword.iskeyword(cleaned):
        cleaned += '_value'
    return cleaned


def _value_type_for_boundary(boundary: dict[str, Any]) -> str:
    default = boundary.get("default")
    if isinstance(default, bool):
        return "bool"
    if isinstance(default, int) and not isinstance(default, bool):
        return "int"
    if isinstance(default, float):
        return "float"
    if isinstance(default, str):
        return "str"
    return "json"


def _help_for_boundary(boundary: dict[str, Any], value_type: str) -> str:
    tool_name = str(boundary["tool_name"])
    arg_path = str(boundary["arg_path"])
    suffix = "Provide as JSON." if value_type == "json" else f"Provide as {value_type}."
    return f"Input for {tool_name} {arg_path}. {suffix}"


def _pattern_reference_payload(pattern: RepresentativePattern, meta_tool: SynthesizedMetaTool) -> dict[str, Any]:
    return {
        "root_tool_name": pattern.pattern.root_tool_name,
        "shape_signature": [list(item) for item in pattern.pattern.shape_signature],
        "support": pattern.pattern.support,
        "occurrences": pattern.pattern.occurrences,
        "compression_gain": pattern.pattern.compression_gain,
        "latency_gain_seconds": pattern.pattern.latency_gain_seconds,
        "generalized_arguments": to_jsonable_term(pattern.pattern.generalized_arguments),
        "internal_calls": meta_tool.internal_calls,
        "boundary_inputs": meta_tool.boundary_inputs,
        "plan": meta_tool.plan,
    }


def _build_skill_doc(script: GeneratedScript, meta_tool: SynthesizedMetaTool, pattern: RepresentativePattern) -> SkillDoc:
    script_path = f"scripts/{script.filename}"
    example = _example_command(script)
    inputs = "\n".join(_input_line(argument) for argument in script.cli_arguments)
    body = f"""# {script.skill_id.replace('-', ' ').title()}

## Quick start

1. Inspect the generated help:
   ```bash
   python {script_path} --help
   ```

2. Provide an AppWorld-style factory that returns an `apis` object, then run the wrapper:
   ```bash
   {example}
   ```

3. Read stdout for the final root tool result. Check stderr only on failure.

## Scripts

- `{script_path}` - {_description_for_meta_tool(meta_tool)}

## Inputs

- `--apis-factory` (required): Python import path in `module:function` format. The callable must return an `apis` object exposing the mined tool namespaces.
{inputs if inputs else '- This workflow has no external boundary arguments beyond `--apis-factory`.'}
- `--output` (optional, default: json): Output format. Use `json` for machine-readable stdout or `text` for human-readable stdout.

## Output

stdout contains the final result from `{meta_tool.internal_calls[-1]}`. stderr contains validation or runtime errors.

```json
{{"result": "see root tool output", "root_tool": "{meta_tool.internal_calls[-1]}"}}
```

Exit code 0 on success, non-zero on failure.

## When to use

Use when: a task needs the repeated DAG workflow rooted at `{pattern.pattern.root_tool_name}` and an `apis` object is available.

Do not use when: the caller cannot provide `--apis-factory`, the workflow shape differs from the mined pattern, or side-effect safety is uncertain.
"""
    return SkillDoc(instructions=body)


def _adapt_skill_doc_for_dag(skill_doc: SkillDoc, *, script: GeneratedScript) -> SkillDoc:
    instructions = skill_doc.instructions
    apis_input = (
        "- `--apis-factory` (required): Python import path in `module:function` format. "
        "The callable must return an `apis` object exposing the mined tool namespaces."
    )
    if "## Inputs" in instructions and "--apis-factory" not in instructions:
        instructions = instructions.replace("## Inputs\n\n", f"## Inputs\n\n{apis_input}\n", 1)
    shared_example = _shared_example_command_without_factory(script)
    dag_example = _example_command(script)
    if shared_example in instructions and dag_example not in instructions:
        instructions = instructions.replace(shared_example, dag_example, 1)
    return SkillDoc(instructions=instructions)


def _input_line(argument: ScriptCliArgument) -> str:
    requirement = "required" if argument.required else f"optional, default: {argument.default or 'null'}"
    return f"- `{argument.flag}` ({requirement}): {argument.help}"


def _example_command(script: GeneratedScript) -> str:
    parts = [f"python scripts/{script.filename}", "--apis-factory demo:create_apis"]
    for argument in script.cli_arguments:
        parts.append(f"{argument.flag} '{_example_value(argument)}'")
    parts.append("--output json")
    return " ".join(parts)


def _shared_example_command_without_factory(script: GeneratedScript) -> str:
    parts = [f"python scripts/{script.filename}"]
    for argument in script.cli_arguments:
        parts.append(f"{argument.flag} '{_example_value(argument)}'")
    parts.append("--output json")
    return " ".join(parts)


def _example_value(argument: ScriptCliArgument) -> str:
    if argument.value_type == "json":
        return "{}"
    if argument.value_type == "int":
        return "0"
    if argument.value_type == "float":
        return "1.0"
    if argument.value_type == "bool":
        return "true"
    return "sample"


def _render_script_text(
    *,
    skill_id: str,
    meta_tool: SynthesizedMetaTool,
    arguments: list[ScriptCliArgument],
    argument_paths: dict[str, str],
) -> str:
    tool_code = meta_tool.code.rstrip()
    core_params = ["apis_factory: str"]
    for argument in arguments:
        annotation = {"str": "str", "int": "int", "float": "float", "bool": "bool", "json": "Any"}[argument.value_type]
        if argument.required:
            core_params.append(f"{argument.name}: {annotation}")
        else:
            core_params.append(f"{argument.name}: {annotation} = {_python_default_literal(argument)}")
    core_signature = ", ".join(core_params)
    parser_lines = [
        "    parser = argparse.ArgumentParser(description=" + repr(_description_for_meta_tool(meta_tool)) + ")",
        '    parser.add_argument("--apis-factory", required=True, help="module:function returning an apis object")',
    ]
    coercions: list[str] = []
    input_items: list[str] = []
    core_call_values: list[str] = []
    for argument in arguments:
        parser_lines.append(f"    parser.add_argument({_argparse_add_argument(argument)})")
        raw_expr = f"args.{argument.name}"
        coerced_expr = _coerced_expression(argument, raw_expr)
        if coerced_expr != raw_expr:
            target_name = f"{argument.name}_value"
            coercions.append(f"        {target_name} = {coerced_expr}")
            core_call_values.append(target_name)
        else:
            core_call_values.append(raw_expr)
        input_items.append(f"        {argument_paths[argument.name]!r}: {argument.name},")
    parser_lines.append('    parser.add_argument("--output", choices=("json", "text"), default="json")')
    parser_block = "\n".join(parser_lines)
    coercion_block = "\n".join(coercions) if coercions else "        pass"
    inputs_block = "\n".join(input_items)
    core_call_args = ", ".join(core_call_values)
    if core_call_args:
        core_call_args = ", " + core_call_args
    return f'''#!/usr/bin/env python3
import argparse
import importlib
import json
import sys
from typing import Any

{tool_code}


def _load_factory(spec: str) -> Any:
    if ":" not in spec:
        raise ValueError("--apis-factory must use module:function format")
    module_name, attr_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    factory = getattr(module, attr_name)
    if not callable(factory):
        raise TypeError("apis factory must be callable")
    return factory


def _parse_bool(raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in {{"1", "true", "yes", "on"}}:
        return True
    if lowered in {{"0", "false", "no", "off"}}:
        return False
    raise ValueError(f"invalid boolean value: {{raw}}")


def _parse_json(raw: str, flag: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{{flag}} must be valid JSON: {{exc.msg}}") from exc


def core_function({core_signature}) -> Any:
    apis = _load_factory(apis_factory)()
    inputs = {{
{inputs_block}
    }}
    return {meta_tool.name}(apis, inputs)


def main() -> int:
{parser_block}
    args = parser.parse_args()
    try:
{coercion_block}
        result = core_function(args.apis_factory{core_call_args})
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.output == "json":
        print(json.dumps(result, ensure_ascii=False, default=str))
    else:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _python_default_literal(argument: ScriptCliArgument) -> str:
    if argument.default is None:
        return "None"
    return repr(_parse_default(argument))


def _parse_default(argument: ScriptCliArgument) -> Any:
    if argument.default is None:
        return None
    if argument.value_type == "json":
        return json.loads(argument.default)
    if argument.value_type == "bool":
        return argument.default.lower() == "true"
    if argument.value_type == "int":
        return int(argument.default)
    if argument.value_type == "float":
        return float(argument.default)
    return json.loads(argument.default)


def _argparse_add_argument(argument: ScriptCliArgument) -> str:
    parts = [repr(argument.flag)]
    if argument.value_type in {"int", "float"}:
        parts.append(f"type={argument.value_type}")
    else:
        parts.append("type=str")
    if argument.required:
        parts.append("required=True")
    if argument.default is not None and not argument.required:
        parts.append(f"default={_parse_default(argument)!r}")
    parts.append(f"help={argument.help!r}")
    parts.append(f"dest={argument.name!r}")
    return ", ".join(parts)


def _coerced_expression(argument: ScriptCliArgument, raw_expr: str) -> str:
    if argument.value_type == "json":
        return f"_parse_json({raw_expr}, {argument.flag!r})"
    if argument.value_type == "bool":
        return f"_parse_bool({raw_expr})"
    return raw_expr


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mine provenance DAG reports into skill folders.")
    parser.add_argument("report", nargs="*", type=Path, help="One or more provenance_report.json files.")
    parser.add_argument("--output-dir", type=Path, default=Path("output_skills"))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--min-support", type=int, default=2)
    parser.add_argument("--trace-apis-factory", help="module:function returning an apis object to proxy and trace.")
    parser.add_argument("--trace-workflow", help="module:function that accepts proxied apis and executes a workflow.")
    parser.add_argument(
        "--trace-workflow-input-json",
        help="Optional JSON object/array/scalar passed to the traced workflow after proxied apis.",
    )
    parser.add_argument(
        "--trace-output-path",
        type=Path,
        help="Optional file path where the captured provenance report should be written before mining.",
    )
    return add_llm_arguments(parser)


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    report_paths = list(args.report)
    if args.trace_apis_factory or args.trace_workflow:
        if not args.trace_apis_factory or not args.trace_workflow:
            parser.error("--trace-apis-factory and --trace-workflow must be provided together")
        workflow_input = None
        if args.trace_workflow_input_json:
            workflow_input = json.loads(args.trace_workflow_input_json)
        trace_output_path = args.trace_output_path
        if trace_output_path is None:
            temp_root = Path(tempfile.gettempdir()) / f"skill-mining-trace-{uuid.uuid4().hex[:8]}"
            trace_output_path = temp_root / "provenance_report.json"
        report_paths.append(
            capture_provenance_report_to_path(
                output_path=trace_output_path,
                apis_factory_spec=args.trace_apis_factory,
                workflow_spec=args.trace_workflow,
                workflow_input=workflow_input,
            )
        )
    if not report_paths:
        parser.error("provide at least one report path or one trace workflow via --trace-apis-factory/--trace-workflow")
    result = DAGSkillPipeline(
        DAGSkillPipelineConfig(
            report_paths=tuple(report_paths),
            output_dir=args.output_dir,
            overwrite=args.overwrite,
            max_depth=args.max_depth,
            min_support=args.min_support,
            llm_client=build_llm_client_from_args(args),
        )
    ).run()
    for skill_dir in result.skill_dirs:
        print(skill_dir)
    return 0


__all__ = [
    "DAGSkillPipeline",
    "DAGSkillPipelineConfig",
    "DAGSkillPipelineResult",
    "build_arg_parser",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
