"""Static and dynamic validation for generated skill scripts."""

from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from pathlib import Path

from loguru import logger

from .script_schema import GeneratedScript, ScriptValidationResult


DANGEROUS_CALLS = {
    "eval": "dynamic eval is not allowed",
    "exec": "dynamic exec is not allowed",
    "os.remove": "file deletion is not allowed",
    "os.unlink": "file deletion is not allowed",
    "os.rmdir": "directory deletion is not allowed",
    "shutil.rmtree": "recursive deletion is not allowed",
    "subprocess.run": "subprocess execution is not allowed",
    "subprocess.call": "subprocess execution is not allowed",
    "subprocess.Popen": "subprocess execution is not allowed",
    "requests.get": "network calls are not allowed in mined scripts",
    "requests.post": "network calls are not allowed in mined scripts",
    "requests.delete": "network calls are not allowed in mined scripts",
}


class ScriptValidator:
    """Validate generated scripts before packaging."""

    def validate(self, script: GeneratedScript) -> ScriptValidationResult:
        static_errors, security_findings = _static_validate(script)
        help_exit_code: int | None = None
        stdout_sample: str | None = None
        stderr_sample: str | None = None

        if not static_errors and not security_findings:
            help_exit_code, stdout_sample, stderr_sample = _run_help(script)

        dynamic_errors: list[str] = []
        if help_exit_code not in (None, 0):
            dynamic_errors.append("--help command failed")

        passed = not static_errors and not security_findings and not dynamic_errors
        if passed:
            logger.info("Generated script validation passed: {}", script.filename)
        else:
            logger.warning(
                "Generated script validation failed: {} static_errors={} security_findings={} dynamic_errors={}",
                script.filename,
                len(static_errors),
                len(security_findings),
                len(dynamic_errors),
            )
        return ScriptValidationResult(
            passed=passed,
            static_errors=tuple([*static_errors, *dynamic_errors]),
            security_findings=tuple(security_findings),
            help_exit_code=help_exit_code,
            stdout_sample=stdout_sample,
            stderr_sample=stderr_sample,
        )


def _static_validate(script: GeneratedScript) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    findings: list[str] = []
    try:
        tree = ast.parse(script.script_text)
    except SyntaxError as exc:
        return [f"syntax error: {exc.msg} at line {exc.lineno}"], findings

    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    if "core_function" not in functions:
        errors.append("missing core_function")
    if "main" not in functions:
        errors.append("missing main")
    if "core_function" in functions:
        _validate_type_hints(functions["core_function"], errors)

    imports = _import_roots(tree)
    banned_imports = sorted(imports & {"subprocess", "requests", "shutil"})
    for module in banned_imports:
        findings.append(f"banned import: {module}")

    for child in ast.walk(tree):
        if isinstance(child, ast.Call):
            call_name = _call_name(child.func)
            if call_name in DANGEROUS_CALLS:
                findings.append(f"{call_name}: {DANGEROUS_CALLS[call_name]}")
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            value = child.value.replace("\\", "/")
            if len(value) >= 3 and (":/" in value or value.startswith("/")):
                findings.append("hard-coded absolute path string detected")

    return errors, sorted(set(findings))


def _validate_type_hints(function: ast.FunctionDef, errors: list[str]) -> None:
    for arg in [*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs]:
        if arg.annotation is None:
            errors.append(f"core_function argument missing type hint: {arg.arg}")
    if function.returns is None:
        errors.append("core_function missing return type hint")


def _import_roots(tree: ast.Module) -> set[str]:
    roots: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def _call_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parent = _call_name(func.value)
        return f"{parent}.{func.attr}" if parent else func.attr
    return ""


def _run_help(script: GeneratedScript) -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        script_path = Path(tmp) / script.filename
        script_path.write_text(script.script_text, encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(script_path), "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    return completed.returncode, completed.stdout[:2000], completed.stderr[:2000]



