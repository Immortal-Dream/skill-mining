#!/usr/bin/env python3

import argparse
import json
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence


def core_function(
    rows: Sequence[Mapping[str, Any]],
    *,
    include_counts: bool = False,
) -> Dict[str, Dict[str, float]]:
    """Summarize numeric columns across row dictionaries.

    For each key (column) appearing in the input rows, compute:
      - min: minimum numeric value observed
      - max: maximum numeric value observed
      - mean: arithmetic mean of numeric values observed

    Only values that are instances of int or float are considered numeric.
    Non-numeric values are ignored. Booleans are ignored (bool is a subclass of int).

    Args:
        rows: Sequence of mapping-like row objects (e.g., list of dicts).
        include_counts: If True, includes a "count" field for each column.

    Returns:
        A dict mapping column name to a dict with keys min/max/mean (and optionally count).

    Raises:
        ValueError: If an element of rows is not a mapping/object.
    """
    columns: Dict[str, List[float]] = {}

    for i, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"row at index {i} is not a mapping/object")
        for key, value in row.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                columns.setdefault(str(key), []).append(float(value))

    out: Dict[str, Dict[str, float]] = {}
    for key, values in columns.items():
        if not values:
            continue
        summary: Dict[str, float] = {
            "min": float(min(values)),
            "max": float(max(values)),
            "mean": float(sum(values) / len(values)),
        }
        if include_counts:
            summary["count"] = float(len(values))
        out[key] = summary

    return out


def _read_text_from_path_or_stdin(path: Optional[str]) -> str:
    if path is None or path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _parse_rows_from_json_text(text: str) -> List[Dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON input: {e}")

    if not isinstance(data, list):
        raise ValueError("Input JSON must be a list of objects (rows)")

    rows: List[Dict[str, Any]] = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"Row at index {i} is not an object")
        rows.append(item)
    return rows


def _format_text(summary: Dict[str, Dict[str, float]]) -> str:
    lines: List[str] = []
    for col in sorted(summary.keys()):
        s = summary[col]
        parts: List[str] = [f"min={s['min']}", f"max={s['max']}", f"mean={s['mean']}"]
        if "count" in s:
            parts.append(f"count={int(s['count'])}")
        lines.append(f"{col}: " + ", ".join(parts))
    return "\n".join(lines) + ("\n" if lines else "")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compute min, max, and mean for numeric columns across a list of row dictionaries. "
            "Reads JSON from a file or stdin."
        )
    )
    parser.add_argument(
        "--input",
        help="Path to input JSON file containing rows (list of objects). If omitted or '-', reads from stdin.",
        default=None,
    )
    parser.add_argument(
        "--include-counts",
        action="store_true",
        help="Include per-column count of numeric values used in the summary.",
    )
    parser.add_argument(
        "--output",
        choices=["json", "text"],
        default="json",
        help="Output format: json or text. Default is json.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output with indentation (JSON output only).",
    )

    args = parser.parse_args()

    try:
        text = _read_text_from_path_or_stdin(args.input)
        rows = _parse_rows_from_json_text(text)
        summary = core_function(rows, include_counts=bool(args.include_counts))

        if args.output == "json":
            if args.pretty:
                sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True))
                sys.stdout.write("\n")
            else:
                sys.stdout.write(json.dumps(summary, separators=(",", ":"), sort_keys=True))
                sys.stdout.write("\n")
        else:
            sys.stdout.write(_format_text(summary))

    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
