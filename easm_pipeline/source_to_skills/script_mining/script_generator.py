"""Generate standalone Python CLI scripts from mined source logic."""

from __future__ import annotations

import ast
import json
import re
import textwrap
from dataclasses import dataclass
from typing import Any

from loguru import logger

from easm_pipeline.core.llm_infra.clients import StructuredLLMClient
from easm_pipeline.core.llm_infra.schemas import CapabilitySlice, ExtractedNode
from easm_pipeline.source_to_skills.extraction.common import slugify
from easm_pipeline.source_to_skills.extraction.dependency_resolver import DependencyContext
from easm_pipeline.source_to_skills.mining.candidate_schema import CandidateDecision

from .script_schema import GeneratedScript, ScriptCliArgument


@dataclass(frozen=True)
class _Parameter:
    name: str
    flag: str
    dest: str
    value_type: str
    required: bool
    default: Any


class ScriptGenerator:
    """Distill a candidate capability into a reusable Python CLI tool."""

    def __init__(self, llm_client: StructuredLLMClient | None = None) -> None:
        self._llm_client = llm_client

    def generate(self, capability: CapabilitySlice, dependencies: DependencyContext, decision: CandidateDecision) -> GeneratedScript:
        if self._llm_client is None:
            logger.info("Generating script with deterministic fallback: skill_id={}", decision.skill_id)
            return self.generate_fallback(capability, dependencies, decision)

        logger.info("Generating distilled script with LLM: skill_id={}", decision.skill_id)
        try:
            return self._llm_client.generate(
                prompt=build_script_prompt(capability, dependencies, decision),
                response_schema=GeneratedScript,
                system_prompt=(
                    "Generate a standalone Python CLI script distilled from proven source logic. "
                    "Return only structured fields and a complete script_text."
                ),
            )
        except Exception as exc:
            logger.warning(
                "LLM script generation failed; using deterministic fallback: skill_id={} error={}",
                decision.skill_id,
                exc.__class__.__name__,
            )
            return self.generate_fallback(capability, dependencies, decision)

    def generate_fallback(
        self,
        capability: CapabilitySlice,
        dependencies: DependencyContext,
        decision: CandidateDecision,
    ) -> GeneratedScript:
        node = capability.nodes[0]
        skill_id = decision.skill_id or slugify(node.name)
        filename = f"{skill_id.replace('-', '_')}.py"
        description = _description_for_node(node)
        core_source, parameters = _distill_core_function(node)
        cli_arguments = tuple(
            ScriptCliArgument(
                name=parameter.name,
                flag=parameter.flag,
                required=parameter.required,
                value_type=parameter.value_type,  # type: ignore[arg-type]
                help=_help_for_parameter(parameter),
                default=None if parameter.required else json.dumps(parameter.default, default=str),
            )
            for parameter in parameters
        )
        script_text = _render_script(
            skill_id=skill_id,
            description=description,
            source=node,
            imports=_safe_import_lines(node.imports, dependencies),
            core_source=core_source,
            parameters=parameters,
        )
        return GeneratedScript(
            skill_id=skill_id,
            language="python",
            runtime_hint="python",
            filename=filename,
            description=description,
            script_text=script_text,
            entry_function="core_function",
            entry_symbol="core_function",
            cli_arguments=cli_arguments,
            dependencies=decision.dependencies,
            tags=decision.tags,
            source=decision.source,
            example_command=_example_command(filename, cli_arguments),
            supports_help=True,
        )


def build_script_prompt(
    capability: CapabilitySlice,
    dependencies: DependencyContext,
    decision: CandidateDecision,
) -> str:
    return (
        "Distill the extracted source logic into one standalone Python CLI script.\n\n"
        "Hard requirements:\n"
        "- script_text must be a complete executable Python file.\n"
        "- File starts with #!/usr/bin/env python3.\n"
        "- Include imports: argparse, json, sys, and only necessary stdlib/pip imports.\n"
        "- Strip business-specific imports and project-internal imports.\n"
        "- Expose the reusable logic as def core_function(...): with full type hints and a docstring.\n"
        "- Expose semantic argparse flags, not only generic --args-json wrappers.\n"
        "- Use lower-kebab-case skill_id without a skill_ prefix.\n"
        "- Use lower_snake_case filename without a skill_ prefix.\n"
        "- Set language to python and runtime_hint to python.\n"
        "- Set entry_symbol to core_function.\n"
        "- Set example_command to a real runnable python scripts/<filename> invocation with semantic flags and --output json.\n"
        "- Set supports_help to true.\n"
        "- Include --output with choices json/text and default json.\n"
        "- Print normal results to stdout.\n"
        "- Print errors to stderr and exit non-zero on failure.\n"
        "- Do not use eval, exec, subprocess, network calls, file deletion, or hard-coded absolute paths.\n"
        "- Use ASCII source text only.\n\n"
        f"Candidate decision:\n{decision.json(indent=2)}\n\n"
        f"Dependency context:\n{dependencies.json(indent=2)}\n\n"
        f"Deterministic capability context:\n{capability.render_llm_context(max_node_code_chars=5000)}"
    )


def _description_for_node(node: ExtractedNode) -> str:
    if node.docstring:
        return node.docstring.splitlines()[0].strip()[:180]
    words = node.name.replace("_", " ")
    return f"Run reusable {words} logic from mined source code."


def _distill_core_function(node: ExtractedNode) -> tuple[str, list[_Parameter]]:
    module = ast.parse(textwrap.dedent(node.raw_code))
    function = next((child for child in module.body if isinstance(child, ast.FunctionDef)), None)
    if function is None:
        raise ValueError(f"could not find Python function in node {node.name}")

    function.decorator_list = []
    function.name = "core_function"
    _ensure_type_hints(function)
    _ensure_docstring(function, _description_for_node(node))
    parameters = _parameters_from_function(function)
    ast.fix_missing_locations(function)
    return ast.unparse(function), parameters


def _ensure_type_hints(function: ast.FunctionDef) -> None:
    for arg in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]:
        if arg.annotation is None:
            arg.annotation = ast.Name(id="Any", ctx=ast.Load())
    if function.args.vararg and function.args.vararg.annotation is None:
        function.args.vararg.annotation = ast.Name(id="Any", ctx=ast.Load())
    if function.args.kwarg and function.args.kwarg.annotation is None:
        function.args.kwarg.annotation = ast.Name(id="Any", ctx=ast.Load())
    if function.returns is None:
        function.returns = ast.Name(id="Any", ctx=ast.Load())


def _ensure_docstring(function: ast.FunctionDef, description: str) -> None:
    if function.body and isinstance(function.body[0], ast.Expr):
        value = function.body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            return
    function.body.insert(0, ast.Expr(value=ast.Constant(value=description)))


def _parameters_from_function(function: ast.FunctionDef) -> list[_Parameter]:
    if function.args.vararg is not None or function.args.kwarg is not None:
        raise ValueError("varargs and kwargs are not supported for CLI distillation")

    args = [*function.args.posonlyargs, *function.args.args]
    defaults = [None] * (len(args) - len(function.args.defaults)) + list(function.args.defaults)
    parameters: list[_Parameter] = []
    for arg, default_node in zip(args, defaults):
        parameters.append(_parameter_from_ast_arg(arg, default_node))
    for arg, default_node in zip(function.args.kwonlyargs, function.args.kw_defaults):
        parameters.append(_parameter_from_ast_arg(arg, default_node))
    return parameters


def _parameter_from_ast_arg(arg: ast.arg, default_node: ast.expr | None) -> _Parameter:
    value_type = _annotation_to_cli_type(arg.annotation)
    required = default_node is None
    default = _literal_default(default_node)
    base_flag = arg.arg.replace("_", "-")
    flag = f"--{base_flag}-json" if value_type == "json" else f"--{base_flag}"
    return _Parameter(
        name=arg.arg,
        flag=flag,
        dest=arg.arg,
        value_type=value_type,
        required=required,
        default=default,
    )


def _annotation_to_cli_type(annotation: ast.expr | None) -> str:
    if annotation is None:
        return "json"
    text = ast.unparse(annotation)
    normalized = text.replace("typing.", "").lower()
    if normalized in {"str"}:
        return "str"
    if normalized in {"int"}:
        return "int"
    if normalized in {"float"}:
        return "float"
    if normalized in {"bool"}:
        return "bool"
    return "json"


def _literal_default(default_node: ast.expr | None) -> Any:
    if default_node is None:
        return None
    try:
        return ast.literal_eval(default_node)
    except (ValueError, SyntaxError):
        return None


def _help_for_parameter(parameter: _Parameter) -> str:
    if parameter.value_type == "json":
        return f"JSON value for {parameter.name}."
    return f"{parameter.value_type} value for {parameter.name}."


def _safe_import_lines(imports: tuple[str, ...], dependencies: DependencyContext) -> list[str]:
    allowed = set(dependencies.stdlib_imports) | set(dependencies.pip_imports)
    safe: list[str] = []
    for line in imports:
        if line in allowed and not _is_banned_import(line):
            safe.append(line)
    return list(dict.fromkeys(safe))


def _is_banned_import(import_line: str) -> bool:
    banned_roots = {"os", "subprocess", "shutil", "requests"}
    match = re.match(r"(?:from|import)\s+([A-Za-z0-9_]+)", import_line)
    return bool(match and match.group(1) in banned_roots)


def _render_script(
    *,
    skill_id: str,
    description: str,
    source: ExtractedNode,
    imports: list[str],
    core_source: str,
    parameters: list[_Parameter],
) -> str:
    parser_lines = [
        f'    parser = argparse.ArgumentParser(description="{_escape_string(description)}")',
    ]
    for parameter in parameters:
        parser_lines.append(_render_add_argument(parameter))
    parser_lines.append('    parser.add_argument("--output", choices=["json", "text"], default="json", help="Output format.")')

    value_lines = [_render_value_loader(parameter) for parameter in parameters]
    call_kwargs = ", ".join(f"{parameter.name}={parameter.dest}" for parameter in parameters)
    lines = [
        "#!/usr/bin/env python3",
        f'"""Skill: {skill_id} - {_escape_docstring(description)}',
        "",
        f"Source: {source.file_path or '<unknown>'}:{source.start_line}-{source.end_line}",
        '"""',
        "",
        "import argparse",
        "import json",
        "import sys",
        "from typing import Any",
    ]
    if imports:
        lines.extend(imports)
    lines.extend(
        [
            "",
            *core_source.splitlines(),
            "",
            "",
            "def _load_json_argument(raw_value: str, flag_name: str) -> Any:",
            "    try:",
            "        return json.loads(raw_value)",
            "    except json.JSONDecodeError as exc:",
            '        raise ValueError(f"{flag_name} must be valid JSON: {exc}") from exc',
            "",
            "",
            "def _parse_bool(raw_value: str) -> bool:",
            "    normalized = raw_value.strip().lower()",
            '    if normalized in {"1", "true", "yes", "y", "on"}:',
            "        return True",
            '    if normalized in {"0", "false", "no", "n", "off"}:',
            "        return False",
            '    raise argparse.ArgumentTypeError("expected a boolean value")',
            "",
            "",
            "def _json_safe(value: Any) -> Any:",
            "    if isinstance(value, set):",
            "        return sorted(_json_safe(item) for item in value)",
            "    if isinstance(value, tuple):",
            "        return [_json_safe(item) for item in value]",
            "    if isinstance(value, list):",
            "        return [_json_safe(item) for item in value]",
            "    if isinstance(value, dict):",
            "        return {str(key): _json_safe(item) for key, item in value.items()}",
            "    return value",
            "",
            "",
            "def main() -> None:",
            *parser_lines,
            "    args = parser.parse_args()",
            "",
            "    try:",
            *value_lines,
            f"        result = core_function({call_kwargs})",
            '        if args.output == "json":',
            "            print(json.dumps(_json_safe(result), ensure_ascii=False, indent=2))",
            "        else:",
            "            print(result)",
            "    except Exception as exc:",
            '        print(f"Error: {exc}", file=sys.stderr)',
            "        sys.exit(1)",
            "",
            "",
            'if __name__ == "__main__":',
            "    main()",
        ]
    )
    return "\n".join(lines) + "\n"


def _render_add_argument(parameter: _Parameter) -> str:
    parts = [f'    parser.add_argument("{parameter.flag}"', f'dest="{parameter.dest}"']
    if parameter.value_type == "int":
        parts.append("type=int")
    elif parameter.value_type == "float":
        parts.append("type=float")
    elif parameter.value_type == "bool":
        parts.append("type=_parse_bool")
    if parameter.required:
        parts.append("required=True")
    elif parameter.default is not None:
        default = json.dumps(parameter.default)
        parts.append(f"default={default}")
    parts.append(f'help="{_escape_string(_help_for_parameter(parameter))}"')
    return ", ".join(parts) + ")"


def _render_value_loader(parameter: _Parameter) -> str:
    if parameter.value_type == "json":
        return f"        {parameter.dest} = _load_json_argument(args.{parameter.dest}, \"{parameter.flag}\")"
    return f"        {parameter.dest} = args.{parameter.dest}"


def _escape_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _escape_docstring(value: str) -> str:
    return value.replace('"""', "'''").replace("\n", " ")


def _example_command(filename: str, cli_arguments: tuple[ScriptCliArgument, ...]) -> str:
    parts = [f"python scripts/{filename}"]
    for argument in cli_arguments:
        parts.append(f"{argument.flag} '{_example_value(argument)}'")
    parts.append("--output json")
    return " ".join(parts)


def _example_value(argument: ScriptCliArgument) -> str:
    if argument.value_type == "json":
        return "{}"
    if argument.value_type == "int":
        return "10"
    if argument.value_type == "float":
        return "1.0"
    if argument.value_type == "bool":
        return "true"
    return "sample"


