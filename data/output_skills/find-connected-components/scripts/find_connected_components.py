#!/usr/bin/env python3

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


Edge = Tuple[str, str]


def _eprint(message: str) -> None:
    print(message, file=sys.stderr)


def _load_json_maybe_atpath(value: str) -> Any:
    """Load JSON from a string, or from a file when value starts with '@'."""
    if value.startswith("@"):
        path = value[1:]
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return json.loads(value)


def _parse_edge_string(s: str) -> Edge:
    parts = [p.strip() for p in s.split(",")]
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Invalid --edge value: {s!r}. Expected 'LEFT,RIGHT'.")
    return (parts[0], parts[1])


def _coerce_edges(obj: Any) -> List[Edge]:
    """Coerce JSON-loaded data into a list of (left,right) edges.

    Accepts:
      - [["a","b"], ...]
      - [{"left":"a","right":"b"}, ...]
      - [{"u":"a","v":"b"}, ...]
    """
    edges: List[Edge] = []

    if obj is None:
        return edges

    if not isinstance(obj, list):
        raise ValueError("Edges JSON must be a list.")

    for i, item in enumerate(obj):
        if isinstance(item, (list, tuple)):
            if len(item) != 2:
                raise ValueError(f"Edge at index {i} must have length 2, got {len(item)}")
            left, right = item
            if not isinstance(left, str) or not isinstance(right, str):
                raise ValueError(f"Edge at index {i} must be [str,str]")
            edges.append((left, right))
        elif isinstance(item, dict):
            if "left" in item and "right" in item:
                left = item["left"]
                right = item["right"]
            elif "u" in item and "v" in item:
                left = item["u"]
                right = item["v"]
            else:
                raise ValueError(f"Edge at index {i} dict must contain keys (left,right) or (u,v).")
            if not isinstance(left, str) or not isinstance(right, str):
                raise ValueError(f"Edge at index {i} dict values must be strings.")
            edges.append((left, right))
        else:
            raise ValueError(f"Edge at index {i} must be a list/tuple of 2 strings or an object.")

    return edges


def core_function(
    edges: Sequence[Edge],
    nodes: Optional[Sequence[str]] = None,
    include_isolated: bool = False,
    sort: bool = False,
) -> List[Set[str]]:
    """Find connected components in an undirected graph.

    Args:
        edges: Iterable of (left, right) pairs defining undirected edges.
        nodes: Optional explicit node list. Useful when include_isolated is True.
        include_isolated: If True, include nodes that have no incident edges as singleton components.
        sort: If True, produce stable ordering by sorting nodes within components and sorting components.

    Returns:
        A list of connected components, each represented as a set of node IDs.
    """
    graph: Dict[str, Set[str]] = {}

    for left, right in edges:
        if left == "" or right == "":
            raise ValueError("Edge endpoints must be non-empty strings.")
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)

    if include_isolated and nodes is not None:
        for n in nodes:
            if n == "":
                raise ValueError("Node IDs must be non-empty strings.")
            graph.setdefault(n, set())

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

    if sort:
        sorted_components: List[List[str]] = [sorted(list(c)) for c in components]
        sorted_components.sort(key=lambda c: (-len(c), c))
        return [set(c) for c in sorted_components]

    return components


def _format_text(components: Sequence[Set[str]]) -> str:
    lines: List[str] = []
    for idx, comp in enumerate(components, start=1):
        nodes = sorted(comp)
        lines.append(f"component {idx} ({len(nodes)}): " + ", ".join(nodes))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="find_connected_components",
        description="Compute connected components in an undirected graph from an edge list."
    )
    parser.add_argument(
        "--edges-json",
        dest="edges_json",
        default=None,
        help="Edges as JSON string or '@path'. Formats: [[\"a\",\"b\"], ...] or [{\"left\":\"a\",\"right\":\"b\"}, ...].",
    )
    parser.add_argument(
        "--edges-file",
        dest="edges_file",
        default=None,
        help="Path to a JSON file containing edges. Same formats as --edges-json.",
    )
    parser.add_argument(
        "--edge",
        dest="edge",
        action="append",
        default=[],
        help="Add one edge as 'LEFT,RIGHT'. Can be provided multiple times.",
    )
    parser.add_argument(
        "--include-isolated",
        dest="include_isolated",
        action="store_true",
        help="If set, include isolated nodes (nodes with no edges) as singleton components. Provide nodes via --node.",
    )
    parser.add_argument(
        "--node",
        dest="node",
        action="append",
        default=[],
        help="Declare a node (useful for isolated nodes). Can be provided multiple times.",
    )
    parser.add_argument(
        "--sort",
        dest="sort",
        action="store_true",
        help="Sort nodes within components and sort components by (size desc, lexicographic) for stable output.",
    )
    parser.add_argument(
        "--output",
        dest="output",
        choices=["json", "text"],
        default="json",
        help="Output format: 'json' or 'text'. Default: json.",
    )

    args = parser.parse_args()

    try:
        edges: List[Edge] = []

        if args.edges_json is not None:
            obj = _load_json_maybe_atpath(args.edges_json)
            edges.extend(_coerce_edges(obj))

        if args.edges_file is not None:
            with open(args.edges_file, "r", encoding="utf-8") as f:
                obj = json.load(f)
            edges.extend(_coerce_edges(obj))

        if args.edge:
            for s in args.edge:
                edges.append(_parse_edge_string(s))

        components = core_function(
            edges=edges,
            nodes=args.node if args.node else None,
            include_isolated=bool(args.include_isolated),
            sort=bool(args.sort),
        )

        if args.output == "json":
            out = [[n for n in sorted(list(c))] for c in components]
            print(json.dumps(out, ensure_ascii=True))
        else:
            print(_format_text(components))

    except Exception as exc:
        _eprint(f"Error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
