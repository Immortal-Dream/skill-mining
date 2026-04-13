#!/usr/bin/env python3
"""Extracted EASM helper script.

Source: sequence_tools.py:1-7
Run with --help before use. Pass function arguments as JSON so the script can
act as a black-box helper without loading source into the agent context.

Usage:
    python scripts/compute-gc-content.py --help
    python scripts/compute-gc-content.py --args-json '[...]'
    python scripts/compute-gc-content.py --kwargs-json '{...}'
"""

def compute_gc_content(sequence: str) -> float:
    """Compute the GC content of a DNA sequence."""
    cleaned = sequence.upper()
    if not cleaned:
        return 0.0
    gc = cleaned.count("G") + cleaned.count("C")
    return gc / len(cleaned)


def _main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Run extracted function compute_gc_content")
    parser.add_argument("--args-json", default="[]", help="JSON array of positional arguments")
    parser.add_argument("--kwargs-json", default="{}", help="JSON object of keyword arguments")
    parsed = parser.parse_args()

    args = json.loads(parsed.args_json)
    kwargs = json.loads(parsed.kwargs_json)
    if not isinstance(args, list):
        raise SystemExit("--args-json must decode to a JSON array")
    if not isinstance(kwargs, dict):
        raise SystemExit("--kwargs-json must decode to a JSON object")

    result = compute_gc_content(*args, **kwargs)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    _main()
