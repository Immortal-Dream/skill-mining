"""Static security analysis and code bundling for mined skills."""

from __future__ import annotations

import ast
import re
import textwrap
from pathlib import PurePosixPath
from typing import Literal

from loguru import logger
from pydantic.v1 import BaseModel, Extra, Field

from easm_pipeline.core.llm_infra.schemas import CapabilitySlice, ExtractedNode
from easm_pipeline.source_to_skills.extraction.common import slugify


DangerSeverity = Literal["low", "medium", "high", "critical"]


class SecurityFinding(BaseModel):
    """Static-analysis finding attached to extracted code."""

    node_id: str
    language: str
    severity: DangerSeverity
    rule_id: str
    message: str
    line: int | None = None

    class Config:
        extra = Extra.forbid


class BundleResult(BaseModel):
    """Scripts and references produced by code bundling."""

    scripts_dict: dict[str, str] = Field(default_factory=dict)
    references_dict: dict[str, str] = Field(default_factory=dict)
    findings: tuple[SecurityFinding, ...] = Field(default_factory=tuple)

    class Config:
        extra = Extra.forbid


class CodeBundler:
    """Split extracted nodes into approved scripts and isolated references."""

    def bundle(self, capability: CapabilitySlice) -> BundleResult:
        scripts: dict[str, str] = {}
        references: dict[str, str] = {}
        findings: list[SecurityFinding] = []

        for index, node in enumerate(capability.nodes, start=1):
            node_findings = self.scan_node(node)
            findings.extend(node_findings)
            if node_findings:
                reference_name = _unique_name(references, f"quarantined-{slugify(node.name, max_length=40)}.md")
                references[reference_name] = _render_quarantine_reference(node, node_findings)
                logger.warning(
                    "Quarantined extracted node: slice={} node={} findings={}",
                    capability.slice_id,
                    node.name,
                    len(node_findings),
                )
                continue

            if node.language == "python":
                if _is_bound_python_method(node):
                    reference_name = _unique_name(references, f"method-{slugify(node.name, max_length=44)}.md")
                    references[reference_name] = _render_python_reference(
                        node,
                        reason="Class-bound method was kept as a reference because standalone execution may require object state.",
                    )
                    logger.debug("Kept class-bound method as reference: node={}", node.name)
                    continue
                script_name = _unique_name(scripts, f"{slugify(node.name, max_length=48)}.py")
                scripts[script_name] = _render_python_script(node, script_name=script_name)
                logger.debug("Bundled Python helper script: node={} script={}", node.name, script_name)
            else:
                reference_name = _unique_name(references, f"{slugify(node.name, max_length=48)}.md")
                references[reference_name] = _render_source_reference(node, index=index)
                logger.debug("Bundled non-Python node as reference: node={} reference={}", node.name, reference_name)

        logger.info(
            "Code bundling complete: slice={} scripts={} references={} findings={}",
            capability.slice_id,
            len(scripts),
            len(references),
            len(findings),
        )
        return BundleResult(scripts_dict=scripts, references_dict=references, findings=tuple(findings))

    def scan_node(self, node: ExtractedNode) -> tuple[SecurityFinding, ...]:
        if node.language == "python":
            return tuple(_scan_python_code(node))
        if node.language == "java":
            return tuple(_scan_java_code(node))
        return ()


PYTHON_DANGEROUS_CALLS = {
    "eval": ("critical", "python-eval", "Dynamic eval can execute arbitrary code."),
    "exec": ("critical", "python-exec", "Dynamic exec can execute arbitrary code."),
    "os.remove": ("high", "python-delete-file", "File deletion must be reviewed before script execution."),
    "os.unlink": ("high", "python-delete-file", "File deletion must be reviewed before script execution."),
    "os.rmdir": ("high", "python-delete-dir", "Directory deletion must be reviewed before script execution."),
    "shutil.rmtree": ("critical", "python-delete-tree", "Recursive deletion must be quarantined."),
    "subprocess.call": ("high", "python-subprocess", "Subprocess execution must be reviewed."),
    "subprocess.run": ("high", "python-subprocess", "Subprocess execution must be reviewed."),
    "subprocess.Popen": ("high", "python-subprocess", "Subprocess execution must be reviewed."),
    "requests.delete": ("high", "python-http-delete", "HTTP DELETE calls require explicit review."),
}

JAVA_DANGEROUS_PATTERNS = (
    (re.compile(r"Runtime\.getRuntime\(\)\.exec\s*\("), "critical", "java-runtime-exec", "Runtime exec must be quarantined."),
    (re.compile(r"new\s+ProcessBuilder\s*\("), "high", "java-process-builder", "ProcessBuilder execution must be reviewed."),
    (re.compile(r"\bFiles\.delete(?:IfExists)?\s*\("), "high", "java-delete-file", "File deletion must be reviewed."),
    (re.compile(r"\bSystem\.exit\s*\("), "medium", "java-system-exit", "System.exit can terminate host processes."),
)


def _scan_python_code(node: ExtractedNode) -> list[SecurityFinding]:
    try:
        module = ast.parse(textwrap.dedent(node.raw_code))
    except SyntaxError as exc:
        return [
            SecurityFinding(
                node_id=node.node_id,
                language="python",
                severity="medium",
                rule_id="python-parse-error",
                message=f"Python code could not be parsed for security scanning: {exc.msg}.",
                line=node.start_line,
            )
        ]

    findings: list[SecurityFinding] = []
    for child in ast.walk(module):
        if not isinstance(child, ast.Call):
            continue
        call_name = _call_name(child.func)
        if call_name in PYTHON_DANGEROUS_CALLS:
            severity, rule_id, message = PYTHON_DANGEROUS_CALLS[call_name]
            findings.append(
                SecurityFinding(
                    node_id=node.node_id,
                    language="python",
                    severity=severity,
                    rule_id=rule_id,
                    message=message,
                    line=node.start_line + getattr(child, "lineno", 1) - 1,
                )
            )
        if call_name.startswith("requests.") and not any(keyword.arg == "timeout" for keyword in child.keywords):
            findings.append(
                SecurityFinding(
                    node_id=node.node_id,
                    language="python",
                    severity="medium",
                    rule_id="python-http-timeout",
                    message="HTTP request call lacks an explicit timeout.",
                    line=node.start_line + getattr(child, "lineno", 1) - 1,
                )
            )
    return findings


def _scan_java_code(node: ExtractedNode) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    for pattern, severity, rule_id, message in JAVA_DANGEROUS_PATTERNS:
        for match in pattern.finditer(node.raw_code):
            line = node.start_line + node.raw_code[: match.start()].count("\n")
            findings.append(
                SecurityFinding(
                    node_id=node.node_id,
                    language="java",
                    severity=severity,
                    rule_id=rule_id,
                    message=message,
                    line=line,
                )
            )
    if re.search(r"\bHttpClient\b|\bHttpURLConnection\b", node.raw_code) and "Authorization" not in node.raw_code:
        findings.append(
            SecurityFinding(
                node_id=node.node_id,
                language="java",
                severity="medium",
                rule_id="java-http-auth-context",
                message="HTTP client usage does not show authentication context in the extracted method.",
                line=node.start_line,
            )
        )
    return findings


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parent = _call_name(func.value)
        return f"{parent}.{func.attr}" if parent else func.attr
    return ""


def _is_bound_python_method(node: ExtractedNode) -> bool:
    if not node.scope_path:
        return False
    try:
        module = ast.parse(textwrap.dedent(node.raw_code))
    except SyntaxError:
        return True
    function = next(
        (child for child in module.body if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))),
        None,
    )
    if function is None:
        return True
    if not function.args.args:
        return False
    first_arg = function.args.args[0].arg
    return first_arg in {"self", "cls"}


def _render_python_script(node: ExtractedNode, *, script_name: str) -> str:
    safe_script_name = PurePosixPath(script_name).name
    header = (
        "#!/usr/bin/env python3\n"
        '"""Extracted EASM helper script.\n\n'
        f"Source: {node.file_path or '<unknown>'}:{node.start_line}-{node.end_line}\n"
        "Run with --help before use. Pass function arguments as JSON so the script can\n"
        "act as a black-box helper without loading source into the agent context.\n\n"
        "Usage:\n"
        f"    python scripts/{safe_script_name} --help\n"
        f"    python scripts/{safe_script_name} --args-json '[...]'\n"
        f"    python scripts/{safe_script_name} --kwargs-json '{{...}}'\n"
        '"""\n\n'
    )
    cli = f'''

def _main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Run extracted function {node.name}")
    parser.add_argument("--args-json", default="[]", help="JSON array of positional arguments")
    parser.add_argument("--kwargs-json", default="{{}}", help="JSON object of keyword arguments")
    parsed = parser.parse_args()

    args = json.loads(parsed.args_json)
    kwargs = json.loads(parsed.kwargs_json)
    if not isinstance(args, list):
        raise SystemExit("--args-json must decode to a JSON array")
    if not isinstance(kwargs, dict):
        raise SystemExit("--kwargs-json must decode to a JSON object")

    result = {node.name}(*args, **kwargs)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    _main()
'''
    imports = "\n".join(node.imports)
    import_block = f"{imports}\n\n" if imports else ""
    return header + import_block + textwrap.dedent(node.raw_code).rstrip() + "\n" + cli


def _render_python_reference(node: ExtractedNode, *, reason: str) -> str:
    return (
        f"# Python Source Reference: {node.name}\n\n"
        f"- Source: `{node.file_path or '<unknown>'}:{node.start_line}-{node.end_line}`\n"
        f"- Signature: `{node.signature}`\n"
        f"- Reason: {reason}\n\n"
        "## Source\n"
        f"```python\n{textwrap.dedent(node.raw_code).rstrip()}\n```\n"
    )


def _render_source_reference(node: ExtractedNode, *, index: int) -> str:
    dependencies = "\n".join(f"- {dependency}" for dependency in node.dependencies) or "- none resolved"
    annotations = "\n".join(f"- {annotation}" for annotation in node.annotations) or "- none"
    return (
        f"# {node.language.title()} Source Reference {index}: {node.name}\n\n"
        f"- Source: `{node.file_path or '<unknown>'}:{node.start_line}-{node.end_line}`\n"
        f"- Signature: `{node.signature}`\n\n"
        "## Annotations\n"
        f"{annotations}\n\n"
        "## Localized Dependencies\n"
        f"{dependencies}\n\n"
        "## Source\n"
        f"```{node.language}\n{node.raw_code.rstrip()}\n```\n"
    )


def _render_quarantine_reference(node: ExtractedNode, findings: tuple[SecurityFinding, ...]) -> str:
    finding_text = "\n".join(
        f"- [{finding.severity}] {finding.rule_id}"
        f"{f' at line {finding.line}' if finding.line else ''}: {finding.message}"
        for finding in findings
    )
    return (
        f"# Quarantined Source: {node.name}\n\n"
        "This code was not approved as an executable script because static analysis found risky behavior.\n\n"
        "## Findings\n"
        f"{finding_text}\n\n"
        "## Source\n"
        f"```{node.language}\n{node.raw_code.rstrip()}\n```\n"
    )


def _unique_name(existing: dict[str, str], candidate: str) -> str:
    if candidate not in existing:
        return candidate
    stem, dot, suffix = candidate.partition(".")
    counter = 2
    while True:
        name = f"{stem}-{counter}{dot}{suffix}" if dot else f"{stem}-{counter}"
        if name not in existing:
            return name
        counter += 1


