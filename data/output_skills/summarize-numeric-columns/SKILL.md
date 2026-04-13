---
name: summarize-numeric-columns
description: 'Use when a task needs to compute min, max, and mean for numeric columns
  in row dictionaries. Triggers on: data-processing, statistics, tables, aggregation,
  cli-candidate.'
---

# summarize-numeric-columns

Compute per-column min, max, and mean for numeric fields found in a list of row dictionaries.

## Quick start

1. From this skill folder, view CLI help first:

python scripts/summarize_numeric_columns.py --help

2. Run with a JSON-encoded list of row objects:

python scripts/summarize_numeric_columns.py --rows-json "[{\"temperature_c\": 21.5, \"humidity\": 0.45, \"city\": \"Austin\"}, {\"temperature_c\": 24.0, \"humidity\": 0.40, \"city\": \"Austin\"}, {\"temperature_c\": 19.0, \"humidity\": 0.55, \"city\": \"Dallas\"}]" --output json

Normal results are printed to stdout. Errors (for example invalid JSON) are printed to stderr.

## Scripts

- scripts/summarize_numeric_columns.py: CLI wrapper that accepts rows as JSON and prints summary statistics.

## Inputs

- --rows-json (required, JSON): A JSON array of objects (row dictionaries). For each row, only numeric values (int or float) are included in the aggregation; non-numeric values are ignored.

- --output (optional): Output format.
  - json (default): Pretty-printed JSON to stdout.
  - text: Python dict string representation to stdout.

## Output

On success, stdout contains a per-column summary object keyed by column name, with min, max, and mean.

Example stdout (JSON):

{
  "temperature_c": {
    "min": 19.0,
    "max": 24.0,
    "mean": 21.5
  },
  "humidity": {
    "min": 0.4,
    "max": 0.55,
    "mean": 0.4666666666666666
  }
}

On failure, stderr contains an error message prefixed with "Error:" and the process exits with code 1.

## When to use

Use when:
- You have row-oriented data (list of dictionaries) and want quick numeric column profiling (min, max, mean).
- You need a deterministic, dependency-free summary you can embed in shell pipelines or automation.

Do not use when:
- You need weighted statistics, medians/quantiles, standard deviation, or grouped aggregation.
- Your input is not readily representable as JSON on the command line (for example very large datasets better handled via files or streaming).
