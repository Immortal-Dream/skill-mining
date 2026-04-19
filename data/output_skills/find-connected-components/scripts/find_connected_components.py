#!/usr/bin/env python3

import argparse
import json
import sys
from typing import Dict, Iterable, List, Sequence, Set, Tuple


def core_function(edges: List[Tuple[str, str]]) -> List[Set[str]]:
    """Find connected components in an undirected graph.

    Args:
        edges: List of (left, right) node pairs. Nodes are treated as strings.
            Self-loops are allowed. Duplicate edges are ignored.

    Returns:
        A list of components, where each component is a set of node IDs.
        Only nodes that appear in at least one edge are included.

    Raises:
        ValueError: If any edge is malformed.
    """
    graph: Dict[str, Set[str]] = {}
    for e in edges:
        if not isinstance(e, tuple) and not isinstance(e, list):
            raise ValueError("Each edge must be a 2-item sequence")
        if len(e) != 2:
            raise ValueError("Each edge must have exactly 2 items")
        left, right = e
        if not isinstance(left, str) or not isinstance(right, str):
            raise ValueError("Edge endpoints must be strings")
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)

    seen: Set[str] = set()
    components: List[Set[str]] = []

    for node in graph:
        if node in seen:
            continue
        stack: List[str] = [node]
        component: Set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            component.add(current)
            stack.extend(graph[current] - seen)
        components.append(component)

    return components


def _parse_edge_strings(edge_strings: Sequence[str], delimiter: str) -> List[Tuple[str, str]]:
    edges: List[Tuple[str, str]] = []
    for s in edge_strings:
        parts = s.split(delimiter)
        if len(parts) != 2:
            raise ValueError(f"Invalid --edge '{s}'. Expected exactly two nodes separated by '{delimiter}'.")
        left = parts[0].strip()
        right = parts[1].strip()
        if left == "" or right == "":
            raise ValueError(f"Invalid --edge '{s}'. Node names cannot be empty.")
        edges.append((left, right))
    return edges


def _load_edges_from_json_text(s: str) -> List[Tuple[str, str]]:
    try:
        obj = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    if not isinstance(obj, list):
        raise ValueError("JSON input must be a list of edges")

    edges: List[Tuple[str, str]] = []
    for item in obj:
        if not isinstance(item, list) and not isinstance(item, tuple):
            raise ValueError("Each edge in JSON must be a 2-item list")
        if len(item) != 2:
            raise ValueError("Each edge in JSON must have exactly 2 items")
        left, right = item
        if not isinstance(left, str) or not isinstance(right, str):
            raise ValueError("Edge endpoints in JSON must be strings")
        edges.append((left, right))
    return edges


def _format_text(components: List[Set[str]], sort_nodes: bool) -> str:
    lines: List[str] = []
    for i, comp in enumerate(components, start=1):
        nodes = list(comp)
        if sort_nodes:
            nodes.sort()
        lines.append(f"component {i}: " + " ".join(nodes))
    return "\n".join(lines)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Find connected components in an undirected graph from an edge list."
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--edge",
        action="append",
        default=None,
        help="An edge specified as 'LEFT,RIGHT' (repeatable).",
    )
    input_group.add_argument(
        "--edges-json",
        default=None,
        help="JSON string representing a list of 2-item edges, e.g. '[[" "\"a\",\"b\"],[\"c\",\"d\"]]'.",
    )
    input_group.add_argument(
        "--edges-json-file",
        default=None,
        help="Path to a JSON file containing a list of 2-item edges.",
    )

    parser.add_argument(
        "--delimiter",
        default=",",
        help="Delimiter used in --edge values (default: ',').",
    )
    parser.add_argument(
        "--sort",
        action="store_true",
        help="Sort nodes within each component for stable output.",
    )
    parser.add_argument(
        "--output",
        choices=["json", "text"],
        default="json",
        help="Output format (default: json).",
    )

    args = parser.parse_args(argv)

    try:
        edges: List[Tuple[str, str]]
        if args.edge is not None:
            edges = _parse_edge_strings(args.edge, args.delimiter)
        elif args.edges_json is not None:
            edges = _load_edges_from_json_text(args.edges_json)
        else:
            try:
                with open(args.edges_json_file, "r", encoding="utf-8") as f:
                    edges = _load_edges_from_json_text(f.read())
            except OSError as e:
                raise ValueError(f"Failed to read JSON file: {e}")

        components = core_function(edges)

        if args.output == "json":
            out_components: List[List[str]] = []
            for comp in components:
                nodes = list(comp)
                if args.sort:
                    nodes.sort()
                out_components.append(nodes)
            sys.stdout.write(json.dumps({"components": out_components}, ensure_ascii=True) + "\n")
        else:
            sys.stdout.write(_format_text(components, args.sort) + ("\n" if components else ""))

        return 0
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
