---
name: summarize-numeric-columns
description: Use when the user provides a list of row dictionaries and needs min,
  max, and mean computed for each numeric column. Do not use when the task requires
  non-numeric aggregation, grouping/pivoting, missing-value imputation, or statistics
  beyond min, max, and mean.
---

# Summarize Numeric Columns in Row Dictionaries

Compute per-column min, max, and mean for numeric values found in a list of row dictionaries.

## Helper Scripts Available

- scripts/summarize-numeric-columns.py
  - Use to compute min/max/mean per numeric column across a JSON list of row objects.
  - Treat as a black box.
  - Always run with --help first to confirm flags and input expectations.

## Quick Start

1. Get the data into the expected shape: a JSON array of objects (each object is one row). Values that are numbers will be included; other types are ignored.
2. Choose an approach using the decision tree below.
3. Run the helper script:
   - First: python scripts/summarize-numeric-columns.py --help
   - Then run one of the supported invocation forms (see below), and use stdout as the result.

Decision tree (scripts vs manual)
- Do you need an exact numeric summary for more than a couple of rows, or is manual arithmetic error-prone? -> Use the script.
- Is the user asking only for a conceptual explanation, or is there a tiny dataset you can compute reliably by inspection? -> Answer directly without running the script.
- Is the input not already a JSON list of row objects? -> Ask for machine-readable rows or convert it to that shape, then use the script.

## Running Bundled Scripts

1. Check usage first (black box):
   - python scripts/summarize-numeric-columns.py --help

2. Prepare JSON:
   - Top-level must be a JSON list: [ {...}, {...} ]
   - Each row must be a JSON object.
   - Numeric values must be JSON numbers (not quoted strings).
   - Missing keys are fine; each column is summarized from values that are present and numeric.

3. Invoke with JSON arguments (use the form supported by --help):

Args JSON form:
- python scripts/summarize-numeric-columns.py --args-json '[{"a": 1, "b": 2.5}, {"a": 3, "b": 1.5, "c": "x"}]'

Kwargs JSON form:
- python scripts/summarize-numeric-columns.py --kwargs-json '{"rows": [{"a": 1, "b": 2.5}, {"a": 3, "b": 1.5, "c": "x"}]}'

## Reading Results: stdout vs stderr

- stdout: the normal output stream. For these scripts, treat stdout as the result payload to report back to the user (typically JSON).
- stderr: the error output stream. Inspect stderr when the command fails, produces no output, or the output is not valid/expected (common causes: invalid JSON, wrong flags, missing required arguments).

## Best Practices

- Confirm the input shape before running: list of row objects, not a dict-of-columns.
- Be explicit about inclusion rules in your answer:
  - Only int/float values are summarized.
  - Non-numeric values (strings, booleans, nulls, nested objects) are ignored.
  - If a column has no numeric values, it will not appear in the output.
- Watch for edge cases:
  - Empty rows list -> empty summary.
  - Mixed types in a column -> only numeric entries are used.
- When reporting results, include any caveats that may change interpretation (ignored non-numeric fields, missing values, and that mean is the simple arithmetic average of included values).
