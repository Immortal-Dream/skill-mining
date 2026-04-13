#!/usr/bin/env python3
"""Skill: summarize-numeric-columns - Compute min, max, and mean for numeric columns in row dictionaries.

Source: table_tools.py:1-16
"""

import argparse
import json
import sys
from typing import Any

def core_function(rows: list[dict[str, float]]) -> dict[str, dict[str, float]]:
    """Compute min, max, and mean for numeric columns in row dictionaries."""
    columns: dict[str, list[float]] = {}
    for row in rows:
        for (key, value) in row.items():
            if isinstance(value, (int, float)):
                columns.setdefault(key, []).append(float(value))
    return {key: {'min': min(values), 'max': max(values), 'mean': sum(values) / len(values)} for (key, values) in columns.items() if values}


def _load_json_argument(raw_value: str, flag_name: str) -> Any:
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{flag_name} must be valid JSON: {exc}") from exc


def _parse_bool(raw_value: str) -> bool:
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected a boolean value")


def _json_safe(value: Any) -> Any:
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute min, max, and mean for numeric columns in row dictionaries.")
    parser.add_argument("--rows-json", dest="rows", required=True, help="JSON value for rows.")
    parser.add_argument("--output", choices=["json", "text"], default="json", help="Output format.")
    args = parser.parse_args()

    try:
        rows = _load_json_argument(args.rows, "--rows-json")
        result = core_function(rows=rows)
        if args.output == "json":
            print(json.dumps(_json_safe(result), ensure_ascii=False, indent=2))
        else:
            print(result)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
