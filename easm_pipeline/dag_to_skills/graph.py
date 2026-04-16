"""Minimal provenance DAG structures reused by DAG-to-skill mining."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ArgBinding:
    arg_path: str
    value_id: str | None = None
    unresolved_preview: str | None = None
    literal_value: Any | None = None


@dataclass
class ProvenanceEdge:
    source_value_id: str
    target_call_id: str
    arg_path: str


@dataclass
class CallNode:
    call_id: str
    tool_name: str
    started_at: str | None = None
    finished_at: str | None = None
    arg_bindings: list[ArgBinding] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> float | None:
        if self.started_at is None or self.finished_at is None:
            return None
        try:
            return (datetime.fromisoformat(self.finished_at) - datetime.fromisoformat(self.started_at)).total_seconds()
        except ValueError:
            return None


@dataclass
class ValueNode:
    value_id: str
    producer_call_id: str | None
    parent_value_id: str | None
    value_path: list[str]
    preview: str
    structural_hash: str


@dataclass
class CallDependencyEdge:
    source_call_id: str
    target_call_id: str
    via_value_id: str
    arg_path: str


@dataclass
class DataflowGraph:
    call_nodes: dict[str, CallNode]
    value_nodes: dict[str, ValueNode]
    value_edges: list[ProvenanceEdge]
    call_edges: list[CallDependencyEdge]

    @classmethod
    def from_report_dict(cls, report: dict[str, Any]) -> "DataflowGraph":
        call_nodes = {
            call["call_id"]: CallNode(
                call_id=call["call_id"],
                tool_name=call["tool_name"],
                started_at=call.get("started_at"),
                finished_at=call.get("finished_at"),
                arg_bindings=[ArgBinding(**binding) for binding in call.get("arg_bindings", [])],
                metadata=call.get("metadata", {}),
            )
            for call in report.get("calls", [])
        }
        value_nodes = {
            value["value_id"]: ValueNode(
                value_id=value["value_id"],
                producer_call_id=value.get("origin", {}).get("producer_call_id"),
                parent_value_id=value.get("origin", {}).get("parent_value_id"),
                value_path=list(value.get("origin", {}).get("value_path", [])),
                preview=value.get("preview", ""),
                structural_hash=value.get("structural_hash", ""),
            )
            for value in report.get("values", [])
        }
        value_edges = [ProvenanceEdge(**edge) for edge in report.get("edges", [])]
        call_edges: list[CallDependencyEdge] = []
        for edge in value_edges:
            value_node = value_nodes.get(edge.source_value_id)
            if value_node is None or value_node.producer_call_id is None:
                continue
            call_edges.append(
                CallDependencyEdge(
                    source_call_id=value_node.producer_call_id,
                    target_call_id=edge.target_call_id,
                    via_value_id=edge.source_value_id,
                    arg_path=edge.arg_path,
                )
            )
        return cls(
            call_nodes=call_nodes,
            value_nodes=value_nodes,
            value_edges=value_edges,
            call_edges=call_edges,
        )

    def parents_of(self, call_id: str) -> list[CallDependencyEdge]:
        return [edge for edge in self.call_edges if edge.target_call_id == call_id]

    def children_of(self, call_id: str) -> list[CallDependencyEdge]:
        return [edge for edge in self.call_edges if edge.source_call_id == call_id]

    def rooted_subgraph_call_ids(self, root_call_id: str, max_depth: int = 2) -> set[str]:
        active = {root_call_id}
        frontier = {root_call_id}
        for _ in range(max_depth):
            next_frontier: set[str] = set()
            for call_id in frontier:
                for parent in self.parents_of(call_id):
                    next_frontier.add(parent.source_call_id)
            next_frontier -= active
            if not next_frontier:
                break
            active |= next_frontier
            frontier = next_frontier
        return active

    def ancestors_of(self, call_id: str) -> set[str]:
        active: set[str] = set()
        frontier = {call_id}
        while frontier:
            next_frontier: set[str] = set()
            for current in frontier:
                for edge in self.parents_of(current):
                    if edge.source_call_id not in active:
                        next_frontier.add(edge.source_call_id)
            active |= next_frontier
            frontier = next_frontier
        return active

    def descendants_of(self, call_id: str) -> set[str]:
        active: set[str] = set()
        frontier = {call_id}
        while frontier:
            next_frontier: set[str] = set()
            for current in frontier:
                for edge in self.children_of(current):
                    if edge.target_call_id not in active:
                        next_frontier.add(edge.target_call_id)
            active |= next_frontier
            frontier = next_frontier
        return active

    def induced_subgraph(self, call_ids: set[str]) -> "DataflowGraph":
        call_nodes = {call_id: self.call_nodes[call_id] for call_id in call_ids}
        relevant_value_ids = {
            edge.via_value_id
            for edge in self.call_edges
            if edge.source_call_id in call_ids and edge.target_call_id in call_ids
        }
        value_nodes = {
            value_id: self.value_nodes[value_id]
            for value_id in relevant_value_ids
            if value_id in self.value_nodes
        }
        value_edges = [
            edge
            for edge in self.value_edges
            if edge.source_value_id in relevant_value_ids and edge.target_call_id in call_ids
        ]
        call_edges = [
            edge
            for edge in self.call_edges
            if edge.source_call_id in call_ids and edge.target_call_id in call_ids
        ]
        return DataflowGraph(
            call_nodes=call_nodes,
            value_nodes=value_nodes,
            value_edges=value_edges,
            call_edges=call_edges,
        )
