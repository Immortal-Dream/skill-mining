---
name: skill_summarize_numeric_columns
description: Compute min, max, and mean for numeric columns across a list of row dictionaries;
  supports JSON input of rows (list[dict]) and emits JSON or text output.
---

# skill_summarize_numeric_columns

Compute min, max, and mean for numeric columns across a list of row dictionaries. Input is JSON rows (a list of objects) read from a file or stdin. Output is either JSON or plain text.

## Helper Scripts Available

- ../../scripts/skill_summarize_numeric_columns.py

## Quick Start

1. View help first:

python3 ../../scripts/skill_summarize_numeric_columns.py --help

2. Create a JSON file containing a list of row objects, for example rows.json:

[
  {"a": 1, "b": 2.5, "c": "x"},
  {"a": 3, "b": 4.5, "c": "y"},
  {"a": 2, "b": null, "c": "z"}
]

3. Run on a file input (default output is JSON to stdout):

python3 ../../scripts/skill_summarize_numeric_columns.py --input rows.json

4. Run with text output:

python3 ../../scripts/skill_summarize_numeric_columns.py --input rows.json --output text

Notes:
- Normal results are written to stdout.
- Errors and diagnostics are written to stderr.

## Running Bundled Scripts

Always check usage first:

python3 ../../scripts/skill_summarize_numeric_columns.py --help

Run with input from a file:

python3 ../../scripts/skill_summarize_numeric_columns.py --input path/to/rows.json

Run with input from stdin (use --input -):

cat path/to/rows.json | python3 ../../scripts/skill_summarize_numeric_columns.py --input -

Include per-column counts:

python3 ../../scripts/skill_summarize_numeric_columns.py --input rows.json --include-counts

Pretty-print JSON output:

python3 ../../scripts/skill_summarize_numeric_columns.py --input rows.json --pretty

Select output format explicitly (only use the values supported by --output):

python3 ../../scripts/skill_summarize_numeric_columns.py --input rows.json --output json
python3 ../../scripts/skill_summarize_numeric_columns.py --input rows.json --output text

## Inputs

- --input
  - Path to a JSON file containing rows as a list of objects.
  - If omitted or set to -, the script reads all input JSON from stdin.

Input JSON requirements:
- The top-level JSON value must be a list.
- Each element of the list must be an object (a row dictionary).
- Only numeric values (int or float) are summarized.
- Booleans are ignored.
- Non-numeric values are ignored.

## Output

- Normal output is written to stdout.
- Errors (for example invalid JSON, wrong types, unreadable files) are written to stderr.

Output formats:
- JSON (default): a JSON object mapping column name to a summary object containing min, max, and mean (and count when requested).
- Text (--output text): one line per summarized column, sorted by column name, formatted as:
  column: min=..., max=..., mean=..., count=...

Control output using:
- --output {json,text}
- --pretty (JSON output only)
- --include-counts
