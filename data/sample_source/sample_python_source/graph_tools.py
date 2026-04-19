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
