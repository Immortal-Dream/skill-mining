"""Synthesize reusable Python helpers from mined DAG subgraphs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .graph import DataflowGraph
from .library_learning import plan_parallel_execution


@dataclass(frozen=True)
class SynthesizedMetaTool:
    name: str
    code: str
    boundary_inputs: list[dict[str, Any]]
    internal_calls: list[str]
    plan: dict[str, Any]


def _call_var(call_id: str) -> str:
    return "call_" + call_id.replace("-", "_")


def _root_value_expr(graph: DataflowGraph, value_id: str, subgraph_call_ids: set[str]) -> tuple[str | None, bool]:
    value_node = graph.value_nodes.get(value_id)
    if value_node is None:
        return None, False
    if value_node.producer_call_id is None:
        return None, True
    if value_node.producer_call_id not in subgraph_call_ids:
        return None, True
    expr = _call_var(value_node.producer_call_id)
    for path_item in value_node.value_path:
        expr += f"[{path_item!r}]"
    return expr, False


def synthesize_parallel_meta_tool(graph: DataflowGraph, call_ids: set[str], *, name: str) -> SynthesizedMetaTool:
    plan = plan_parallel_execution(graph, call_ids=call_ids)
    subgraph = graph.induced_subgraph(call_ids)
    boundary_inputs: list[dict[str, Any]] = []
    boundary_keys: set[tuple[str, str]] = set()
    lines = [
        "from concurrent.futures import ThreadPoolExecutor",
        "",
        f"def {name}(apis, inputs):",
    ]
    for stage_index, stage in enumerate(plan.stages, start=1):
        if len(stage.call_ids) > 1 and stage.effect_kind == "read":
            lines.append(f"    # parallel stage {stage_index}")
            lines.append(f"    with ThreadPoolExecutor(max_workers={len(stage.call_ids)}) as executor:")
            for call_id in stage.call_ids:
                call_node = subgraph.call_nodes[call_id]
                arg_expressions = []
                for binding in call_node.arg_bindings:
                    if binding.value_id is not None:
                        expr, is_external = _root_value_expr(subgraph, binding.value_id, call_ids)
                        if is_external:
                            key = (call_node.tool_name, binding.arg_path)
                            if key not in boundary_keys:
                                boundary_inputs.append(
                                    {
                                        "tool_name": call_node.tool_name,
                                        "arg_path": binding.arg_path,
                                        "source": "external_tracked",
                                    }
                                )
                                boundary_keys.add(key)
                            expr = f"inputs[{binding.arg_path!r}]"
                        arg_expressions.append((binding.arg_path, expr))
                    else:
                        key = (call_node.tool_name, binding.arg_path)
                        if key not in boundary_keys:
                            boundary_inputs.append(
                                {
                                    "tool_name": call_node.tool_name,
                                    "arg_path": binding.arg_path,
                                    "source": "literal_or_unresolved",
                                    "default": binding.literal_value,
                                }
                            )
                            boundary_keys.add(key)
                        expr = f"inputs[{binding.arg_path!r}]"
                        arg_expressions.append((binding.arg_path, expr))
                kwargs = ", ".join(
                    f"{arg_path.split('.')[-1]}={expr}"
                    for arg_path, expr in arg_expressions
                    if arg_path.startswith("kwargs.")
                )
                tool_expr = f"apis.{call_node.tool_name}"
                lines.append(f"        future_{_call_var(call_id)} = executor.submit({tool_expr}, {kwargs})")
            for call_id in stage.call_ids:
                lines.append(f"        {_call_var(call_id)} = future_{_call_var(call_id)}.result()")
        else:
            lines.append(f"    # stage {stage_index}")
            for call_id in stage.call_ids:
                call_node = subgraph.call_nodes[call_id]
                arg_expressions = []
                for binding in call_node.arg_bindings:
                    if binding.value_id is not None:
                        expr, is_external = _root_value_expr(subgraph, binding.value_id, call_ids)
                        if is_external:
                            key = (call_node.tool_name, binding.arg_path)
                            if key not in boundary_keys:
                                boundary_inputs.append(
                                    {
                                        "tool_name": call_node.tool_name,
                                        "arg_path": binding.arg_path,
                                        "source": "external_tracked",
                                    }
                                )
                                boundary_keys.add(key)
                            expr = f"inputs[{binding.arg_path!r}]"
                        arg_expressions.append((binding.arg_path, expr))
                    else:
                        key = (call_node.tool_name, binding.arg_path)
                        if key not in boundary_keys:
                            boundary_inputs.append(
                                {
                                    "tool_name": call_node.tool_name,
                                    "arg_path": binding.arg_path,
                                    "source": "literal_or_unresolved",
                                    "default": binding.literal_value,
                                }
                            )
                            boundary_keys.add(key)
                        expr = f"inputs[{binding.arg_path!r}]"
                        arg_expressions.append((binding.arg_path, expr))
                kwargs = ", ".join(
                    f"{arg_path.split('.')[-1]}={expr}"
                    for arg_path, expr in arg_expressions
                    if arg_path.startswith("kwargs.")
                )
                tool_expr = f"apis.{call_node.tool_name}"
                lines.append(f"    {_call_var(call_id)} = {tool_expr}({kwargs})")
    root_call_id = plan.stages[-1].call_ids[-1]
    execution_order = [call_id for stage in plan.stages for call_id in stage.call_ids]
    lines.append(f"    return {_call_var(root_call_id)}")
    return SynthesizedMetaTool(
        name=name,
        code="\n".join(lines) + "\n",
        boundary_inputs=boundary_inputs,
        internal_calls=[subgraph.call_nodes[call_id].tool_name for call_id in execution_order],
        plan={
            "sequential_latency_seconds": plan.sequential_latency_seconds,
            "parallel_latency_seconds": plan.parallel_latency_seconds,
            "latency_gain_seconds": plan.latency_gain_seconds,
            "stages": [
                {
                    "call_ids": stage.call_ids,
                    "effect_kind": stage.effect_kind,
                    "estimated_latency_seconds": stage.estimated_latency_seconds,
                }
                for stage in plan.stages
            ],
        },
    )
