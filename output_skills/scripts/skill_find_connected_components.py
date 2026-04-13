#!/usr/bin/env python3

import argparse
import json
import sys
from typing import Dict, List, Optional, Sequence, Set, Tuple


def core_function(
    edges: List[Tuple[str, str]],
    nodes: Optional[Sequence[str]] = None,
    include_isolated: bool = False,
    dedupe: bool = False,
    sort_output: bool = False,
) -> List[Set[str]]:
    """Find connected components in an undirected graph.

    Args:
        edges: List of (left, right) edges. Node ids are strings.
        nodes: Optional sequence of known nodes. Used only when include_isolated=True.
        include_isolated: If True, include nodes that are not present in any edge as
            singleton components (based on `nodes`).
        dedupe: If True, remove duplicate undirected edges.
        sort_output: If True, return deterministically ordered components: nodes within
            each component are sorted during post-processing, and components are sorted
            by (size, lexical signature).

    Returns:
        A list of components, each a set of node ids.

    Raises:
        ValueError: If an edge endpoint is empty.
    """
    normalized_edges: List[Tuple[str, str]] = []
    if dedupe:
        seen_edges: Set[Tuple[str, str]] = set()
        for left, right in edges:
            if not left or not right:
                raise ValueError("Edge endpoints must be non-empty strings")
            a, b = (left, right) if left <= right else (right, left)
            if (a, b) in seen_edges:
                continue
            seen_edges.add((a, b))
            normalized_edges.append((left, right))
    else:
        for left, right in edges:
            if not left or not right:
                raise ValueError("Edge endpoints must be non-empty strings")
            normalized_edges.append((left, right))

    graph: Dict[str, Set[str]] = {}
    for left, right in normalized_edges:
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)

    if include_isolated and nodes is not None:
        for n in nodes:
            if not n:
                continue
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
            stack.extend(list(graph[current] - seen))
        components.append(component)

    if sort_output:
        def comp_key(c: Set[str]) -> Tuple[int, List[str]]:
            ordered = sorted(c)
            return (len(ordered), ordered)

        components = sorted(components, key=comp_key)

    return components


def _parse_nodes_csv(value: Optional[str]) -> Optional[List[str]]:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return []
    parts = [p.strip() for p in value.split(",")]
    return [p for p in parts if p]


def _read_text_edges(data: str, fmt: str) -> List[Tuple[str, str]]:
    edges: List[Tuple[str, str]] = []
    for raw_line in data.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if fmt == "tsv":
            parts = line.split("\t")
        elif fmt == "csv":
            parts = line.split(",")
        elif fmt == "space":
            parts = line.split()
        else:
            raise ValueError("Unsupported text format: " + fmt)
        if len(parts) != 2:
            raise ValueError("Each edge line must have exactly 2 columns")
        left = parts[0].strip()
        right = parts[1].strip()
        edges.append((left, right))
    return edges


def _load_edges_from_input(path: Optional[str], fmt: str) -> List[Tuple[str, str]]:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            data = f.read()
    else:
        data = sys.stdin.read()

    if fmt == "json":
        obj = json.loads(data) if data.strip() else []
        if not isinstance(obj, list):
            raise ValueError("JSON input must be an array of [left, right] pairs")
        edges: List[Tuple[str, str]] = []
        for item in obj:
            if (
                not isinstance(item, (list, tuple))
                or len(item) != 2
            ):
                raise ValueError("Each JSON edge must be a 2-item array")
            left, right = item
            if not isinstance(left, str) or not isinstance(right, str):
                raise ValueError("Edge endpoints must be strings")
            edges.append((left, right))
        return edges

    if fmt in ("tsv", "csv", "space"):
        return _read_text_edges(data, fmt)

    raise ValueError("Unsupported input format: " + fmt)


def _format_output(components: List[Set[str]], output: str, sort_output: bool) -> str:
    if output == "json":
        payload: List[List[str]]
        if sort_output:
            payload = [sorted(list(c)) for c in components]
        else:
            payload = [list(c) for c in components]
        return json.dumps(payload, ensure_ascii=True)
    if output == "text":
        lines: List[str] = []
        for c in components:
            nodes = sorted(c) if sort_output else list(c)
            lines.append(" ".join(nodes))
        return "\n".join(lines)
    raise ValueError("Unsupported output format: " + output)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="skill_find_connected_components",
        description="Compute connected components in an undirected graph from an edge list.",
    )
    parser.add_argument(
        "--input",
        dest="input",
        default=None,
        help="Path to an input file. If omitted, read from stdin.",
    )
    parser.add_argument(
        "--format",
        dest="format",
        choices=["json", "tsv", "csv", "space"],
        default="json",
        help="Input format.",
    )
    parser.add_argument(
        "--dedupe",
        dest="dedupe",
        action="store_true",
        help="Remove duplicate undirected edges.",
    )
    parser.add_argument(
        "--include-isolated",
        dest="include_isolated",
        action="store_true",
        help="Include isolated nodes provided via --nodes as singleton components.",
    )
    parser.add_argument(
        "--nodes",
        dest="nodes",
        default=None,
        help="Comma-separated list of nodes (used with --include-isolated).",
    )
    parser.add_argument(
        "--sort",
        dest="sort_output",
        action="store_true",
        help="Sort nodes within components and sort components for stable output.",
    )
    parser.add_argument(
        "--output",
        dest="output",
        choices=["json", "text"],
        default="json",
        help="Output format.",
    )

    args = parser.parse_args()

    try:
        edges = _load_edges_from_input(args.input, args.format)
        nodes = _parse_nodes_csv(args.nodes)
        components = core_function(
            edges=edges,
            nodes=nodes,
            include_isolated=bool(args.include_isolated),
            dedupe=bool(args.dedupe),
            sort_output=bool(args.sort_output),
        )
        out = _format_output(components, args.output, bool(args.sort_output))
        sys.stdout.write(out)
        if not out.endswith("\n"):
            sys.stdout.write("\n")
    except Exception as e:
        sys.stderr.write(str(e) + "\n")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
