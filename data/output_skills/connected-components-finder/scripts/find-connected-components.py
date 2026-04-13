#!/usr/bin/env python3
"""Extracted EASM helper script.

Source: graph_tools.py:1-25
Run with --help before use. Pass function arguments as JSON so the script can
act as a black-box helper without loading source into the agent context.

Usage:
    python scripts/find-connected-components.py --help
    python scripts/find-connected-components.py --args-json '[...]'
    python scripts/find-connected-components.py --kwargs-json '{...}'
"""

def find_connected_components(edges: list[tuple[str, str]]) -> list[set[str]]:
    """Find connected components in an undirected graph."""
    graph: dict[str, set[str]] = {}
    for left, right in edges:
        graph.setdefault(left, set()).add(right)
        graph.setdefault(right, set()).add(left)

    seen: set[str] = set()
    components: list[set[str]] = []

    for node in graph:
        if node in seen:
            continue
        stack = [node]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            component.add(current)
            stack.extend(graph[current] - seen)
        components.append(component)

    return components


def _main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Run extracted function find_connected_components")
    parser.add_argument("--args-json", default="[]", help="JSON array of positional arguments")
    parser.add_argument("--kwargs-json", default="{}", help="JSON object of keyword arguments")
    parsed = parser.parse_args()

    args = json.loads(parsed.args_json)
    kwargs = json.loads(parsed.kwargs_json)
    if not isinstance(args, list):
        raise SystemExit("--args-json must decode to a JSON array")
    if not isinstance(kwargs, dict):
        raise SystemExit("--kwargs-json must decode to a JSON object")

    result = find_connected_components(*args, **kwargs)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    _main()
