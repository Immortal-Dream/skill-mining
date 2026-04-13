#!/usr/bin/env python3
"""Extracted EASM helper script.

Source: table_tools.py:1-16
Run with --help before use. Pass function arguments as JSON so the script can
act as a black-box helper without loading source into the agent context.

Usage:
    python scripts/summarize-numeric-columns.py --help
    python scripts/summarize-numeric-columns.py --args-json '[...]'
    python scripts/summarize-numeric-columns.py --kwargs-json '{...}'
"""

def summarize_numeric_columns(rows: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    """Compute min, max, and mean for numeric columns in row dictionaries."""
    columns: dict[str, list[float]] = {}
    for row in rows:
        for key, value in row.items():
            if isinstance(value, (int, float)):
                columns.setdefault(key, []).append(float(value))
    return {
        key: {
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / len(values),
        }
        for key, values in columns.items()
        if values
    }


def _main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Run extracted function summarize_numeric_columns")
    parser.add_argument("--args-json", default="[]", help="JSON array of positional arguments")
    parser.add_argument("--kwargs-json", default="{}", help="JSON object of keyword arguments")
    parsed = parser.parse_args()

    args = json.loads(parsed.args_json)
    kwargs = json.loads(parsed.kwargs_json)
    if not isinstance(args, list):
        raise SystemExit("--args-json must decode to a JSON array")
    if not isinstance(kwargs, dict):
        raise SystemExit("--kwargs-json must decode to a JSON object")

    result = summarize_numeric_columns(*args, **kwargs)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    _main()
