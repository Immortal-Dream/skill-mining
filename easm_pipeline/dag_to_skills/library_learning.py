"""Lightweight DAG mining helpers adapted for skill packaging."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from .graph import DataflowGraph


@dataclass(frozen=True)
class AUVariable:
    name: str


def antiunify_terms(left: Any, right: Any, path: str = "v") -> Any:
    if left == right:
        return left
    if isinstance(left, dict) and isinstance(right, dict):
        keys = set(left.keys()) | set(right.keys())
        return {key: antiunify_terms(left.get(key), right.get(key), f"{path}.{key}") for key in sorted(keys)}
    if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
        return [
            antiunify_terms(left_item, right_item, f"{path}[{index}]")
            for index, (left_item, right_item) in enumerate(zip(left, right, strict=True))
        ]
    if isinstance(left, tuple) and isinstance(right, tuple) and len(left) == len(right):
        return tuple(
            antiunify_terms(left_item, right_item, f"{path}[{index}]")
            for index, (left_item, right_item) in enumerate(zip(left, right, strict=True))
        )
    return AUVariable(path.replace(".", "_").replace("[", "_").replace("]", ""))


def antiunify_many(terms: list[Any]) -> Any:
    if not terms:
        raise ValueError("antiunify_many requires at least one term")
    pattern = terms[0]
    for index, term in enumerate(terms[1:], start=1):
        pattern = antiunify_terms(pattern, term, f"v{index}")
    return pattern


def to_jsonable_term(term: Any) -> Any:
    if isinstance(term, AUVariable):
        return {"type": "variable", "name": term.name}
    if isinstance(term, dict):
        return {key: to_jsonable_term(value) for key, value in term.items()}
    if isinstance(term, list):
        return [to_jsonable_term(value) for value in term]
    if isinstance(term, tuple):
        return [to_jsonable_term(value) for value in term]
    return term


@dataclass(frozen=True)
class ParallelStage:
    call_ids: list[str]
    effect_kind: str
    estimated_latency_seconds: float


@dataclass(frozen=True)
class ExecutionPlan:
    sequential_latency_seconds: float
    parallel_latency_seconds: float
    latency_gain_seconds: float
    stages: list[ParallelStage]


READ_HINTS = ("show_", "search_", "get_", "load_")
WRITE_HINTS = (
    "create_",
    "update_",
    "delete_",
    "remove_",
    "add_",
    "mark_",
    "approve_",
    "deny_",
    "complete_",
    "send_",
    "play",
    "pause",
    "stop",
)


def infer_effect_kind(tool_name: str) -> str:
    api_name = tool_name.split(".")[-1]
    if api_name.startswith(READ_HINTS):
        return "read"
    if api_name.startswith(WRITE_HINTS):
        return "write"
    if api_name in {"login", "logout"}:
        return "mixed"
    return "unknown"


def _duration_or_default(graph: DataflowGraph, call_id: str, default: float = 1.0) -> float:
    duration = graph.call_nodes[call_id].duration_seconds
    if duration is None or duration <= 0:
        return default
    return duration


def _can_parallelize(group: list[str], graph: DataflowGraph) -> bool:
    if len(group) <= 1:
        return True
    effect_kinds = {infer_effect_kind(graph.call_nodes[call_id].tool_name) for call_id in group}
    if any(effect_kind in {"write", "mixed", "external", "unknown"} for effect_kind in effect_kinds):
        return False
    for index, call_id in enumerate(group):
        descendants = graph.descendants_of(call_id)
        ancestors = graph.ancestors_of(call_id)
        for other_call_id in group[index + 1 :]:
            if other_call_id in descendants or other_call_id in ancestors:
                return False
    return True


def plan_parallel_execution(graph: DataflowGraph, call_ids: set[str] | None = None) -> ExecutionPlan:
    active_call_ids = set(call_ids or graph.call_nodes.keys())
    subgraph = graph.induced_subgraph(active_call_ids)
    indegree = {call_id: 0 for call_id in subgraph.call_nodes}
    for edge in subgraph.call_edges:
        indegree[edge.target_call_id] += 1
    ready = sorted(call_id for call_id, degree in indegree.items() if degree == 0)
    stages: list[ParallelStage] = []
    sequential_latency = sum(_duration_or_default(subgraph, call_id) for call_id in subgraph.call_nodes)
    while ready:
        parallel_group = list(ready)
        if not _can_parallelize(parallel_group, subgraph):
            parallel_group = [ready[0]]
        estimated_latency = max(_duration_or_default(subgraph, call_id) for call_id in parallel_group)
        effect_kind = infer_effect_kind(subgraph.call_nodes[parallel_group[0]].tool_name) if len(parallel_group) == 1 else "read"
        stages.append(
            ParallelStage(
                call_ids=parallel_group,
                effect_kind=effect_kind,
                estimated_latency_seconds=estimated_latency,
            )
        )
        consumed = set(parallel_group)
        next_ready: list[str] = [call_id for call_id in ready if call_id not in consumed]
        for call_id in parallel_group:
            for edge in subgraph.children_of(call_id):
                indegree[edge.target_call_id] -= 1
                if indegree[edge.target_call_id] == 0:
                    next_ready.append(edge.target_call_id)
        ready = sorted(set(next_ready))
    parallel_latency = sum(stage.estimated_latency_seconds for stage in stages)
    return ExecutionPlan(
        sequential_latency_seconds=sequential_latency,
        parallel_latency_seconds=parallel_latency,
        latency_gain_seconds=max(sequential_latency - parallel_latency, 0.0),
        stages=stages,
    )


@dataclass(frozen=True)
class SubgraphPattern:
    root_tool_name: str
    shape_signature: tuple[tuple[str, tuple[tuple[str, str], ...]], ...]
    generalized_arguments: Any
    support: int
    occurrences: int
    compression_gain: int
    sequential_latency_seconds: float
    parallel_latency_seconds: float
    latency_gain_seconds: float


@dataclass(frozen=True)
class PatternOccurrence:
    graph_index: int
    root_call_id: str
    call_ids: frozenset[str]


@dataclass(frozen=True)
class RepresentativePattern:
    pattern: SubgraphPattern
    occurrence: PatternOccurrence


def shape_signature(graph: DataflowGraph, call_ids: set[str]) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    node_signatures = []
    for call_id in sorted(call_ids):
        call_node = graph.call_nodes[call_id]
        parent_signature = tuple(
            sorted(
                (graph.call_nodes[edge.source_call_id].tool_name, edge.arg_path)
                for edge in graph.parents_of(call_id)
                if edge.source_call_id in call_ids
            )
        )
        node_signatures.append((call_node.tool_name, parent_signature))
    return tuple(sorted(node_signatures))


def argument_signature(graph: DataflowGraph, call_ids: set[str]) -> dict[str, Any]:
    signature: dict[str, Any] = {}
    tool_name_to_count: Counter[str] = Counter()
    for call_id in sorted(call_ids):
        call_node = graph.call_nodes[call_id]
        tool_name_to_count[call_node.tool_name] += 1
        tool_key = f"{call_node.tool_name}#{tool_name_to_count[call_node.tool_name]}"
        parents = sorted(
            (
                edge.arg_path,
                graph.call_nodes[edge.source_call_id].tool_name,
                graph.value_nodes[edge.via_value_id].structural_hash,
            )
            for edge in graph.parents_of(call_id)
            if edge.source_call_id in call_ids and edge.via_value_id in graph.value_nodes
        )
        signature[tool_key] = parents
    return signature


def enumerate_rooted_call_subgraphs(graph: DataflowGraph, *, max_depth: int = 2) -> list[tuple[str, set[str]]]:
    return [(call_id, graph.rooted_subgraph_call_ids(call_id, max_depth=max_depth)) for call_id in sorted(graph.call_nodes)]


def mine_representative_patterns(
    graphs: list[DataflowGraph],
    *,
    max_depth: int = 2,
    min_support: int = 2,
) -> list[RepresentativePattern]:
    by_shape: dict[tuple[str, tuple[tuple[str, tuple[tuple[str, str], ...]], ...]], list[PatternOccurrence]] = defaultdict(list)
    for graph_index, graph in enumerate(graphs):
        for root_call_id, call_ids in enumerate_rooted_call_subgraphs(graph, max_depth=max_depth):
            if len(call_ids) < 2:
                continue
            signature = shape_signature(graph, call_ids)
            if not signature:
                continue
            root_tool_name = graph.call_nodes[root_call_id].tool_name
            by_shape[(root_tool_name, signature)].append(
                PatternOccurrence(graph_index=graph_index, root_call_id=root_call_id, call_ids=frozenset(call_ids))
            )
    patterns: list[RepresentativePattern] = []
    for (root_tool_name, signature), members in by_shape.items():
        support = len({member.graph_index for member in members})
        if support < min_support:
            continue
        argument_signatures = [argument_signature(graphs[member.graph_index], set(member.call_ids)) for member in members]
        plans = [plan_parallel_execution(graphs[member.graph_index], set(member.call_ids)) for member in members]
        occurrences = len(members)
        compression_gain = max(len(signature) - 1, 0) * occurrences
        pattern = SubgraphPattern(
            root_tool_name=root_tool_name,
            shape_signature=signature,
            generalized_arguments=antiunify_many(argument_signatures),
            support=support,
            occurrences=occurrences,
            compression_gain=compression_gain,
            sequential_latency_seconds=sum(plan.sequential_latency_seconds for plan in plans) / len(plans),
            parallel_latency_seconds=sum(plan.parallel_latency_seconds for plan in plans) / len(plans),
            latency_gain_seconds=sum(plan.latency_gain_seconds for plan in plans) / len(plans),
        )
        patterns.append(RepresentativePattern(pattern=pattern, occurrence=members[0]))
    patterns.sort(
        key=lambda item: (
            item.pattern.latency_gain_seconds,
            item.pattern.compression_gain,
            item.pattern.support,
        ),
        reverse=True,
    )
    return patterns
