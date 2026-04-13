---
name: connected-components-finder
description: Use when identifying connected components in an undirected graph from
  a list of node-pair edges; do not use when the graph is directed, weighted, or requires
  shortest paths or traversal order outputs.
---

# Find Connected Components in an Undirected Graph

Use this skill to group node IDs into connected components from an undirected edge list.

## Helper Scripts Available

- scripts/find-connected-components.py
  - Computes connected components from an undirected edge list.
  - Treat this script as a black box. Always run it with --help first to learn the accepted flags and JSON shapes.

## Quick Start

1. Run help to confirm required flags and JSON formats:
   - python scripts/find-connected-components.py --help
2. Prepare the edge list as JSON (typically a list of 2-item lists of strings), then invoke the script using the format shown by --help. Common patterns are:
   - python scripts/find-connected-[find-connected-components.py](scripts%2Ffind-connected-components.py)components.py --args-json '[["a","b"],["b","c"],["d","e"]]'
   - python scripts/find-connected-components.py --kwargs-json '{"edges":[["a","b"],["b","c"],["d","e"]]}'
3. Read results from stdout. If the command fails or the output looks wrong, inspect stderr for parsing errors, missing/invalid arguments, or runtime failures, then adjust inputs/flags and retry.

Stdout means the program's normal output stream (the expected results). Stderr means the error stream (warnings, stack traces, and invocation problems). If stderr is non-empty, treat it as a signal to verify arguments and JSON quoting.

## Running Bundled Scripts

- Always start by running:
  - python scripts/find-connected-components.py --help
- Prefer bash-safe JSON quoting:
  - Use double quotes inside JSON.
  - Wrap the full JSON argument in single quotes.
- Example invocations (use the one that matches --help output):
  - python scripts/find-connected-components.py --args-json '[["a","b"],["b","c"],["d","e"]]'
  - python scripts/find-connected-components.py --kwargs-json '{"edges":[["a","b"],["b","c"],["d","e"]]}'
- Output handling:
  - Expected results are printed to stdout.
  - If anything looks off, check stderr for JSON parsing errors, missing/invalid arguments, or runtime failures.

## Decision Tree (script vs. manual)

- Do you need actual computed components from user-provided edges?
  - Yes -> Use scripts/find-connected-components.py (run --help first).
  - No, only a tiny illustrative example -> Compute manually in the response.
- Did the user ask for directed connectivity, strongly connected components, or path/weight details?
  - Yes -> Clarify requirements; this skill/script is for undirected connected components.

## How to Use the Helper Script

1. Always start with:
   - python scripts/find-connected-components.py --help
2. Choose the invocation style the help text supports:
   - Positional via --args-json (when the script expects positional arguments).
   - Named via --kwargs-json (when the script expects a parameter like "edges").
3. Provide edges as JSON. Use double quotes inside JSON and wrap the whole JSON in single quotes for bash.
4. Validate output handling:
   - Results should come from stdout.
   - If stderr shows JSON parsing errors, check quoting/escaping.
   - If stderr shows missing arguments, align your keys/positions to what --help requires.

Only consider inspecting or customizing the script if --help is insufficient and a change is necessary for the user task.

## Best Practices

- Treat edges as undirected: an edge (u,v) connects u <-> v.
- Node IDs should be consistent types (prefer strings everywhere).
- Isolated nodes (nodes that never appear in any edge) will not appear in the computed components. If the user needs them included, request a full node list and add singleton components.
- Duplicate edges and self-loops should not change component membership; you can typically pass them as-is.
- Output ordering is not guaranteed. If the user needs deterministic presentation, sort nodes within each component and sort components by a stable key (for example, by size then lexicographic minimum).
