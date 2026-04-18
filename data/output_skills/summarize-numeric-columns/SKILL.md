---
name: summarize-numeric-columns
description: 'Use when a task needs to compute per-column min, max, and mean across
  numeric values found in a list of row dictionaries. Triggers on: python, data-processing,
  tables, statistics, utility.'
---

# Summarize numeric columns

Compute per-column min, max, and mean across numeric values found in a list of row dictionaries.

## Quick start
1. If you are unsure about flags, run --help first:
   python scripts/summarize_numeric_columns.py --help
2. Run the script with python using a copy-runnable example command:
   python scripts/summarize_numeric_columns.py --input-json '[{"a":1,"b":2},{"a":3,"b":4},{"a":-1,"b":"5"}]' --allow-numeric-strings --output json --pretty
3. Read normal results from stdout. If something goes wrong (invalid JSON, wrong input types, include/exclude overlap), check stderr for the error message and a non-zero exit code.

## Scripts
- scripts/summarize_numeric_columns.py

## Inputs
Provide rows as JSON representing a list of objects (list of dictionaries). Each object is a row mapping column names to values.

Accepted input methods:
- --input-json: JSON string containing the full list of rows.
- stdin: If --input-json is omitted or empty, the script reads JSON from stdin.

Filtering columns:
- --include: Comma-separated list of column names to consider. If provided, only these columns are scanned.
- --exclude: Comma-separated list of column names to ignore.
- --include and --exclude must not overlap.

Value handling:
- Numeric values (int, float) are included.
- Booleans are ignored.
- With --allow-numeric-strings, strings like "3.14" or "10" are also treated as numbers; non-numeric strings are ignored.
- Columns with no numeric values are omitted from the output.

## Output
Use --output to choose the output format:
- --output json (default): Writes a JSON object to stdout mapping each column name to an object with keys min, max, mean.
  - With --pretty, the JSON is pretty-printed.
- --output text: Writes a human-readable text summary to stdout.

Any errors (invalid JSON, wrong input types, include/exclude overlap) are reported to stderr with a non-zero exit code.

## When to use
Use when:
- You have row-oriented JSON data and want quick per-column numeric summaries (min, max, mean).
- You need lightweight profiling of numeric fields before cleaning, normalization, or feature engineering.
- You want to restrict summarization to specific columns via --include or omit columns via --exclude.

Do not use when:
- You need statistics beyond min, max, mean (e.g., median, quantiles, variance).
- Your data is not naturally represented as a JSON array of objects (or is too large to conveniently pass as a single JSON string without streaming/partitioning).
- You need strict schema enforcement rather than ignoring non-numeric values.
