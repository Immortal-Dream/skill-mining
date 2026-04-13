#!/usr/bin/env python3
"""Extracted EASM helper script.

Source: sequence_tools.py:10-13
Run with --help before use. Pass function arguments as JSON so the script can
act as a black-box helper without loading source into the agent context.

Usage:
    python scripts/reverse-complement.py --help
    python scripts/reverse-complement.py --args-json '[...]'
    python scripts/reverse-complement.py --kwargs-json '{...}'
"""

def reverse_complement(sequence: str) -> str:
    """Return the reverse complement of a DNA sequence."""
    table = str.maketrans("ACGTacgt", "TGCAtgca")
    return sequence.translate(table)[::-1]


def _main():
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Run extracted function reverse_complement")
    parser.add_argument("--args-json", default="[]", help="JSON array of positional arguments")
    parser.add_argument("--kwargs-json", default="{}", help="JSON object of keyword arguments")
    parsed = parser.parse_args()

    args = json.loads(parsed.args_json)
    kwargs = json.loads(parsed.kwargs_json)
    if not isinstance(args, list):
        raise SystemExit("--args-json must decode to a JSON array")
    if not isinstance(kwargs, dict):
        raise SystemExit("--kwargs-json must decode to a JSON object")

    result = reverse_complement(*args, **kwargs)
    if result is not None:
        print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    _main()
