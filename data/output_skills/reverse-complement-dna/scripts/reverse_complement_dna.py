#!/usr/bin/env python3
"""Reverse complement of a DNA sequence.

This script provides a reusable function and a small CLI for computing the reverse
complement of a DNA sequence using a translation table.
"""

import argparse
import json
import sys
from typing import Optional


def core_function(sequence: str) -> str:
    """Return the reverse complement of a DNA sequence.

    This function complements A<->T and C<->G while preserving letter case for
    standard bases (A,C,G,T and a,c,g,t), then reverses the resulting string.

    Args:
        sequence: Input DNA sequence.

    Returns:
        The reverse-complemented DNA sequence.
    """
    table = str.maketrans("ACGTacgt", "TGCAtgca")
    return sequence.translate(table)[::-1]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reverse_complement_dna",
        description="Compute the reverse complement of a DNA sequence.",
    )
    parser.add_argument(
        "--sequence",
        required=True,
        help="Input DNA sequence (A,C,G,T; case preserved for these bases).",
    )
    parser.add_argument(
        "--output",
        choices=["json", "text"],
        default="json",
        help="Output format.",
    )
    return parser


def _emit_result(result: str, output: str) -> None:
    if output == "text":
        sys.stdout.write(result + "\n")
    else:
        payload = {"reverse_complement": result}
        sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")


def main(argv: Optional[list[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = core_function(args.sequence)
        _emit_result(result, args.output)
        return 0
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
