---
name: find-connected-components
description: 'Use when a task needs to compute connected components of an undirected
  graph from an edge list. Triggers on: graph, connected-components, undirected-graph,
  dfs, utility.'
---

# Find connected components

Compute connected components of an undirected graph from an edge list.

## Quick start
1. View full usage and available flags:
   python scripts/find_connected_components.py --help
2. Run with the Python runtime and provide edges (repeat --edge as needed):
   python scripts/find_connected_components.py --edge a,b --edge b,c --edge d,e --output json
3. Read results from stdout, and check stderr for errors.

Normal results are written to stdout. Errors and invalid input messages are written to stderr.

## Scripts
- scripts/find_connected_components.py: Reads an undirected edge list and prints the connected components.

## Inputs
Provide exactly one of the following input modes:

- --edge LEFT,RIGHT
  - Repeatable flag. Each use adds one undirected edge.
  - By default, endpoints are separated by a comma. Change this with --delimiter.

- --edges-json JSON
  - A JSON string containing a list of 2-item edges.
  - Example shape: [["a","b"],["c","d"]]

- --edges-json-file PATH
  - Path to a JSON file containing a list of 2-item edges.

Additional flags:

- --delimiter DELIM
  - Delimiter used in each --edge value (default is ,).

- --sort
  - Sort nodes within each component for stable output.

- --output {json,text}
  - Select output format.

## Output
Writes connected components to stdout.

- With --output json (default): emits JSON representing the list of components, where each component is a list of node IDs.
- With --output text: emits human-readable lines like:
  component 1: a b c

Errors (for example malformed edges, invalid JSON, or unreadable files) are written to stderr and the process exits non-zero.

## When to use
Use when:
- You have an undirected graph described by an edge list and need its connected components.
- You want a small, deterministic utility with no external dependencies.

Do not use when:
- You need directed connectivity (strongly connected components) or weighted graph analysis.
- Your data model includes isolated nodes that do not appear in any edge and you need them included.
