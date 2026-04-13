#!/usr/bin/env python3
"""Skill: skill_compute_gc_content - Compute the GC content of a DNA sequence.

Source: sequence_tools.py:1-7
"""

import argparse
import json
import sys
from typing import Any

def core_function(sequence: str) -> float:
    """Compute the GC content of a DNA sequence."""
    cleaned = sequence.upper()
    if not cleaned:
        return 0.0
    gc = cleaned.count('G') + cleaned.count('C')
    return gc / len(cleaned)


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
    parser = argparse.ArgumentParser(description="Compute the GC content of a DNA sequence.")
    parser.add_argument("--sequence", dest="sequence", required=True, help="str value for sequence.")
    parser.add_argument("--output", choices=["json", "text"], default="json", help="Output format.")
    args = parser.parse_args()

    try:
        sequence = args.sequence
        result = core_function(sequence=sequence)
        if args.output == "json":
            print(json.dumps(_json_safe(result), ensure_ascii=False, indent=2))
        else:
            print(result)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
