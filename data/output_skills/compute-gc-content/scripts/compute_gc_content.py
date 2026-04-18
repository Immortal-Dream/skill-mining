#!/usr/bin/env python3

import argparse
import json
import sys


def core_function(sequence: str) -> float:
    """Compute the GC content (fraction) of a DNA sequence.

    The GC content is defined as:
        (count('G') + count('C')) / len(sequence)

    The input is normalized to uppercase before counting.

    Args:
        sequence: DNA sequence string.

    Returns:
        GC fraction as a float in the range [0.0, 1.0]. Returns 0.0 for an empty string.
    """
    cleaned = sequence.upper()
    if not cleaned:
        return 0.0
    gc = cleaned.count("G") + cleaned.count("C")
    return gc / len(cleaned)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compute GC content (fraction) of a DNA sequence."
    )
    parser.add_argument(
        "--sequence",
        required=True,
        help="DNA sequence string to analyze (e.g., ACGTACGT).",
    )
    parser.add_argument(
        "--output",
        choices=["json", "text"],
        default="json",
        help="Output format.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        gc_fraction = core_function(args.sequence)
        if args.output == "json":
            payload = {
                "sequence_length": len(args.sequence),
                "gc_fraction": gc_fraction,
            }
            sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
        else:
            sys.stdout.write(f"{gc_fraction}\n")
        return 0
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
