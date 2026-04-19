#!/usr/bin/env python3

import argparse
import json
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union


Number = Union[int, float]
Row = Mapping[str, Any]
SummaryStats = Dict[str, float]
Summary = Dict[str, SummaryStats]


def core_function(
    rows: List[Row],
    *,
    include: Optional[List[str]] = None,
    exclude: Optional[List[str]] = None,
    allow_numeric_strings: bool = False,
) -> Summary:
    """Summarize numeric columns across row dictionaries.

    This function scans each row (a mapping of column name to value), collects
    numeric values (int/float; optionally numeric strings), and returns per-column
    summary statistics: min, max, mean.

    Args:
        rows: List of row mappings.
        include: Optional list of column names to include. If provided, only these
            columns are considered.
        exclude: Optional list of column names to exclude.
        allow_numeric_strings: If True, also treat strings like "3.14" or "10"
            as numeric values.

    Returns:
        A dict mapping column name to a dict with keys: "min", "max", "mean".
        Columns with no numeric values are omitted.

    Raises:
        TypeError: If rows is not a list of mappings.
        ValueError: If include/exclude overlap.
    """

    if not isinstance(rows, list):
        raise TypeError("rows must be a list of mappings")

    include_set = set(include) if include else None
    exclude_set = set(exclude) if exclude else set()

    if include_set is not None:
        overlap = include_set.intersection(exclude_set)
        if overlap:
            raise ValueError(f"include and exclude overlap: {sorted(overlap)}")

    columns: Dict[str, List[float]] = {}

    def _should_consider_column(col: str) -> bool:
        if include_set is not None and col not in include_set:
            return False
        if col in exclude_set:
            return False
        return True

    def _maybe_number(v: Any) -> Optional[float]:
        if isinstance(v, bool):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if allow_numeric_strings and isinstance(v, str):
            s = v.strip()
            if not s:
                return None
            try:
                return float(s)
            except ValueError:
                return None
        return None

    for idx, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TypeError(f"rows[{idx}] must be a mapping")
        for key, value in row.items():
            if not isinstance(key, str):
                continue
            if not _should_consider_column(key):
                continue
            num = _maybe_number(value)
            if num is None:
                continue
            columns.setdefault(key, []).append(num)

    out: Summary = {}
    for key, values in columns.items():
        if not values:
            continue
        out[key] = {
            "min": min(values),
            "max": max(values),
            "mean": sum(values) / float(len(values)),
        }
    return out


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Summarize numeric columns across a JSON array of row objects. "
            "Reads from --input-json or stdin."
        )
    )

    p.add_argument(
        "--input-json",
        default="",
        help=(
            "JSON string representing a list of row objects (list[dict]). "
            "If omitted or empty, read JSON from stdin."
        ),
    )
    p.add_argument(
        "--include",
        default="",
        help="Comma-separated list of column names to include (optional).",
    )
    p.add_argument(
        "--exclude",
        default="",
        help="Comma-separated list of column names to exclude (optional).",
    )
    p.add_argument(
        "--allow-numeric-strings",
        action="store_true",
        help="Treat numeric-looking strings (e.g., '3.14') as numbers.",
    )
    p.add_argument(
        "--output",
        choices=["json", "text"],
        default="json",
        help="Output format.",
    )
    p.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output (only applies to --output json).",
    )

    return p.parse_args(argv)


def _split_csv(s: str) -> Optional[List[str]]:
    s = s.strip()
    if not s:
        return None
    parts = [p.strip() for p in s.split(",")]
    parts = [p for p in parts if p]
    return parts or None


def _read_rows_from_input(input_json: str) -> List[Row]:
    if input_json.strip():
        raw = input_json
    else:
        raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON input: {e}")
    if not isinstance(data, list):
        raise TypeError("Input JSON must be a list of row objects")
    return data  # type: ignore[return-value]


def _format_text(summary: Summary) -> str:
    if not summary:
        return "(no numeric columns found)"
    keys = sorted(summary.keys())
    lines: List[str] = []
    for k in keys:
        stats = summary[k]
        lines.append(f"{k}: min={stats['min']}, max={stats['max']}, mean={stats['mean']}")
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        rows = _read_rows_from_input(args.input_json)
        include = _split_csv(args.include)
        exclude = _split_csv(args.exclude)

        result = core_function(
            rows,
            include=include,
            exclude=exclude,
            allow_numeric_strings=bool(args.allow_numeric_strings),
        )

        if args.output == "json":
            if args.pretty:
                sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
                sys.stdout.write("\n")
            else:
                sys.stdout.write(json.dumps(result, separators=(",", ":"), sort_keys=True))
                sys.stdout.write("\n")
        else:
            sys.stdout.write(_format_text(result))
            sys.stdout.write("\n")
        return 0
    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
