"""Worthiness evaluation for reusable script skills."""

from __future__ import annotations

import ast
import re
import textwrap

from loguru import logger

from easm_pipeline.core.llm_infra.clients import StructuredLLMClient
from easm_pipeline.core.llm_infra.schemas import CapabilitySlice, ExtractedNode
from easm_pipeline.source_to_skills.extraction.common import slugify
from easm_pipeline.source_to_skills.extraction.dependency_resolver import DependencyContext

from .candidate_schema import CandidateDecision


class CandidateEvaluator:
    """Decide whether a capability should become a standalone CLI skill."""

    def __init__(self, llm_client: StructuredLLMClient | None = None) -> None:
        self._llm_client = llm_client

    def evaluate(self, capability: CapabilitySlice, dependencies: DependencyContext) -> CandidateDecision:
        deterministic_skip = _deterministic_skip(capability, dependencies)
        if deterministic_skip is not None:
            logger.info(
                "Skipping capability before LLM evaluation: slice={} reason={}",
                capability.slice_id,
                deterministic_skip.reason,
            )
            return deterministic_skip

        if self._llm_client is None:
            logger.info("Evaluating candidate with deterministic fallback: slice={}", capability.slice_id)
            return _fallback_extract_decision(capability, dependencies)

        logger.info("Evaluating candidate with LLM: slice={}", capability.slice_id)
        try:
            return self._llm_client.generate(
                prompt=build_candidate_prompt(capability, dependencies),
                response_schema=CandidateDecision,
                system_prompt=(
                    "Judge whether source logic is worth extracting as a reusable source-language skill artifact. "
                    "Return only the structured decision."
                ),
            )
        except Exception as exc:
            logger.warning(
                "LLM candidate evaluation failed; using deterministic fallback: slice={} error={}",
                capability.slice_id,
                exc.__class__.__name__,
            )
            return _fallback_extract_decision(capability, dependencies)


def build_candidate_prompt(capability: CapabilitySlice, dependencies: DependencyContext) -> str:
    return (
        "Evaluate whether this capability should be extracted as a reusable source-language skill artifact.\n\n"
        "Extract only when:\n"
        "- The logic has clear input/output boundaries and can be packaged as a standalone script or source artifact.\n"
        "- The logic captures domain expertise or reusable engineering practice.\n"
        "- The logic can be reused across projects without heavy business coupling.\n\n"
        "Skip when:\n"
        "- It depends on database sessions, web request contexts, project settings, or instance state.\n"
        "- It is a trivial wrapper or is too business-specific.\n"
        "- It has unsafe side effects or cannot be executed safely through a packaged runtime or sandbox.\n\n"
        "Use skill_id format lower-kebab-case, for example find-connected-components. "
        "Do not start skill_id with skill_ or skill-.\n\n"
        f"Dependency context:\n{dependencies.json(indent=2)}\n\n"
        f"Deterministic capability context:\n{capability.render_llm_context(max_node_code_chars=3000)}"
    )


def _deterministic_skip(
    capability: CapabilitySlice,
    dependencies: DependencyContext,
) -> CandidateDecision | None:
    if len(capability.nodes) != 1:
        return _skip(capability, "module-level multi-function distillation is not enabled yet")
    node = capability.nodes[0]
    if node.name.startswith("_"):
        return _skip(capability, "private helper functions are not promoted to public skills")
    if node.language == "python" and _is_async_function(node):
        return _skip(capability, "async functions require event-loop specific CLI design")
    if node.language == "python" and _has_varargs(node):
        return _skip(capability, "varargs or kwargs require custom CLI design")
    if node.language == "python" and _is_bound_method(node):
        return _skip(capability, "class-bound methods depend on instance or class state")
    if dependencies.business_coupling:
        return _skip(capability, f"business coupling detected: {', '.join(dependencies.business_coupling)}")
    if _has_required_side_effects(dependencies):
        return _skip(capability, f"unsafe or hard-to-sandbox side effects detected: {', '.join(dependencies.side_effects)}")
    if _is_too_trivial(node):
        return _skip(capability, "function is too trivial to justify a reusable skill")
    return None


def _fallback_extract_decision(
    capability: CapabilitySlice,
    dependencies: DependencyContext,
) -> CandidateDecision:
    node = capability.nodes[0]
    tags = tuple(dict.fromkeys(_infer_tags(node)))
    return CandidateDecision(
        decision="extract",
        reason="source logic has a reusable standalone boundary and can be packaged as a source-language skill",
        skill_id=slugify(node.name, max_length=64),
        source=_source_name(node),
        tags=tags,
        dependencies=tuple(_dependency_names(dependencies)),
        reusable_boundary_score=0.85,
        domain_value_score=0.70,
        coupling_score=0.05,
    )


def _skip(capability: CapabilitySlice, reason: str) -> CandidateDecision:
    node = capability.nodes[0] if capability.nodes else None
    return CandidateDecision(
        decision="skip",
        reason=reason,
        skill_id=None,
        source=_source_name(node) if node is not None else capability.slice_id,
        tags=(),
        dependencies=(),
        reusable_boundary_score=0.0,
        domain_value_score=0.0,
        coupling_score=1.0,
    )


def _is_bound_method(node: ExtractedNode) -> bool:
    if not node.scope_path:
        return False
    try:
        module = ast.parse(textwrap.dedent(node.raw_code))
    except SyntaxError:
        return True
    function = next((child for child in module.body if isinstance(child, ast.FunctionDef)), None)
    if function is None or not function.args.args:
        return True
    return function.args.args[0].arg in {"self", "cls"}


def _is_async_function(node: ExtractedNode) -> bool:
    try:
        module = ast.parse(textwrap.dedent(node.raw_code))
    except SyntaxError:
        return False
    return any(isinstance(child, ast.AsyncFunctionDef) for child in module.body)


def _has_varargs(node: ExtractedNode) -> bool:
    try:
        module = ast.parse(textwrap.dedent(node.raw_code))
    except SyntaxError:
        return False
    function = next((child for child in module.body if isinstance(child, ast.FunctionDef)), None)
    if function is None:
        return False
    return function.args.vararg is not None or function.args.kwarg is not None


def _is_too_trivial(node: ExtractedNode) -> bool:
    if node.node_type == "file":
        return len(node.raw_code.splitlines()) <= 2 and not node.docstring
    if node.language != "python":
        lines = [line for line in textwrap.dedent(node.raw_code).splitlines() if line.strip()]
        return len(lines) <= 3 and not node.docstring
    try:
        module = ast.parse(textwrap.dedent(node.raw_code))
    except SyntaxError:
        return len(node.raw_code.splitlines()) <= 3 and not node.docstring
    function = next((child for child in module.body if isinstance(child, ast.FunctionDef)), None)
    if function is None:
        return False
    statements = [stmt for stmt in function.body if not _is_docstring_expr(stmt)]
    if len(statements) == 1 and isinstance(statements[0], ast.Pass):
        return True
    if len(statements) <= 1 and len(node.raw_code.splitlines()) <= 3 and not node.docstring:
        return True
    return False


def _is_docstring_expr(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _has_required_side_effects(dependencies: DependencyContext) -> bool:
    hard_side_effects = {"deletes files", "deletes directory trees", "spawns subprocesses", "performs HTTP request"}
    return any(item in hard_side_effects for item in dependencies.side_effects)


def _infer_tags(node: ExtractedNode) -> list[str]:
    words = re.findall(r"[a-z0-9]+", node.name.lower())
    tags = [word for word in words if word not in {"get", "set", "run", "make", "build", "compute"}]
    if "graph" in (node.file_path or "").lower():
        tags.append("graph")
    if "sequence" in (node.file_path or "").lower() or "dna" in node.name.lower():
        tags.append("bioinformatics")
    if "table" in (node.file_path or "").lower():
        tags.append("table")
    return tags[:8] or ["utility"]


def _dependency_names(dependencies: DependencyContext) -> list[str]:
    names: list[str] = []
    for import_line in dependencies.pip_imports:
        match = re.match(r"(?:from|import)\s+([A-Za-z0-9_]+)", import_line)
        if match:
            names.append(match.group(1).lower())
    return list(dict.fromkeys(names))


def _source_name(node: ExtractedNode) -> str:
    module = (node.file_path or "<memory>").replace("\\", "/").rsplit(".", 1)[0].replace("/", ".")
    return f"{module}.{node.name}"


