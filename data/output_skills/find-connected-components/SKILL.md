---
name: find-connected-components
description: 'Use when a task needs to compute connected components in an undirected
  graph from an edge list, returning components as sets (or lists) of node IDs. Triggers
  on: graph, connected-components, undirected-graph, algorithm, cli.'
---

# find-connected-components

Compute connected components in an undirected graph from an edge list, returning components as sets (or lists) of node IDs.

## Quick start

1. View help (shows all supported arguments and defaults):

python3 scripts/find_connected_components.py --help

2. Run with a small edge list (JSON string) and get JSON on stdout:

python3 scripts/find_connected_components.py --edges-json '[["a","b"],["b","c"],["d","e"]]' --output json

Normal results are written to stdout. Errors and validation messages are written to stderr.

## Scripts

- scripts/find_connected_components.py

Run it directly with Python:

python3 scripts/find_connected_components.py --help

## Inputs

Provide edges using one of the supported methods:

- --edges-json EDGES_JSON
  - A JSON string containing a list of edges, or an @path to a JSON file.
  - Supported edge formats:
    - [["a","b"], ["b","c"], ...]
    - [{"left":"a","right":"b"}, {"left":"b","right":"c"}, ...]
    - [{"u":"a","v":"b"}, {"u":"b","v":"c"}, ...]

- --edges-file EDGES_FILE
  - Path to a JSON file containing edges in the same formats accepted by --edges-json.

- --edge LEFT,RIGHT
  - Add one edge as a comma-separated pair. Can be provided multiple times.

Optional inputs:

- --include-isolated
  - If set, include isolated nodes (nodes with no edges) as singleton components.

- --node NODE
  - Declare a node ID (useful with --include-isolated). Can be provided multiple times.

- --sort
  - Sort nodes within each component, and sort components by (size descending, then lexicographic) for stable output.

Output formatting:

- --output {json,text}
  - Select output format. Default is json.

## Output

By default (--output json), the script writes a JSON document to stdout describing the connected components.

Example command:

python3 scripts/find_connected_components.py --edges-json '[["a","b"],["b","c"],["d","e"]]' --sort --output json

Example stdout (JSON):

{
  "components": [
    ["a", "b", "c"],
    ["d", "e"]
  ],
  "component_count": 2
}

If you choose --output text, a human-readable listing is printed to stdout instead.

Errors (for example, malformed JSON or invalid --edge values) are printed to stderr and the process exits non-zero.

## When to use

Use when:
- You have an undirected graph as an edge list and need to group nodes into connected components.
- You need a lightweight CLI tool to analyze connectivity without external dependencies.
- You need stable, comparable output for tests or pipelines (use --sort).

Do not use when:
- Your graph is directed and you need strongly connected components (this computes undirected connectivity).
- Your input is too large to fit comfortably in memory as a JSON edge list.
- You need weighted edges or path calculations rather than simple connectivity.
