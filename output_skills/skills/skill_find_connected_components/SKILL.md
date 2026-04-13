---
name: skill_find_connected_components
description: CLI utility to compute connected components in an undirected graph from
  an edge list input, returning components as JSON or text.
---

# skill_find_connected_components

CLI utility to compute connected components in an undirected graph from an edge list input, returning components as JSON or text.

## Helper Scripts Available

- ../../scripts/skill_find_connected_components.py

## Quick Start

1. View help (run this before any execution):

python ../../scripts/skill_find_connected_components.py --help

2. Provide an edge list on stdin and print components to stdout:

- JSON input on stdin (array of 2-item arrays):

python ../../scripts/skill_find_connected_components.py --format json --output json

- TSV input on stdin (two columns per line):

python ../../scripts/skill_find_connected_components.py --format tsv --output text

Normal results are written to stdout. Errors and validation messages are written to stderr.

## Running Bundled Scripts

From this skill documentation folder, run the script via the Python CLI using the relative path:

python ../../scripts/skill_find_connected_components.py --help

Then run with your chosen input and output format. The script can read from a file path or from stdin.

## Inputs

You may provide input in one of the supported formats via a file or stdin.

- --input INPUT
  - Path to an input file.
  - If omitted, the script reads from stdin.

- --format {json,tsv,csv,space}
  - json: a JSON array of edges, where each edge is a 2-item array [left, right].
  - tsv: one edge per line, two tab-separated columns.
  - csv: one edge per line, two comma-separated columns.
  - space: one edge per line, two whitespace-separated tokens.

Optional processing arguments (use only as needed):

- --dedupe
  - Remove duplicate undirected edges.

- --include-isolated
  - Include isolated nodes provided via --nodes as singleton components.

- --nodes NODES
  - Comma-separated list of node ids.
  - Used only when --include-isolated is set.

- --sort
  - Sort nodes within each component and sort components for stable output.

## Output

- --output {json,text}
  - json: prints a JSON representation of the connected components to stdout.
  - text: prints a human-readable text representation to stdout.

Normal results are printed to stdout. If the input cannot be parsed or is invalid (for example, a line does not have exactly two columns, or JSON is not an array of pairs), the script reports the error on stderr and exits non-zero.
