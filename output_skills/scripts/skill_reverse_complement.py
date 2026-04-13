#!/usr/bin/env python3

import argparse
import json
import sys
from typing import Dict, Optional


def core_function(sequence: str, allow_ambiguous: bool = False, strip_whitespace: bool = False) -> str:
    """Return the reverse complement of a DNA sequence.

    By default, only canonical DNA bases A/C/G/T (case-insensitive) are accepted.
    If allow_ambiguous is True, common IUPAC ambiguous DNA codes are supported.

    Args:
        sequence: Input DNA sequence.
        allow_ambiguous: Whether to allow and complement IUPAC ambiguous DNA codes.
        strip_whitespace: Whether to remove whitespace from the input before processing.

    Returns:
        The reverse-complemented sequence.

    Raises:
        ValueError: If the input contains invalid characters.
    """
    if strip_whitespace:
        sequence = "".join(sequence.split())

    if not sequence:
        return ""

    if allow_ambiguous:
        # IUPAC DNA complements (includes canonical + ambiguous). Preserve case.
        comp: Dict[str, str] = {
            "A": "T",
            "C": "G",
            "G": "C",
            "T": "A",
            "R": "Y",  # A/G
            "Y": "R",  # C/T
            "S": "S",  # G/C
            "W": "W",  # A/T
            "K": "M",  # G/T
            "M": "K",  # A/C
            "B": "V",  # C/G/T
            "D": "H",  # A/G/T
            "H": "D",  # A/C/T
            "V": "B",  # A/C/G
            "N": "N"
        }
        comp.update({k.lower(): v.lower() for k, v in list(comp.items()) if k.isupper()})
        invalid = sorted({ch for ch in sequence if ch not in comp})
        if invalid:
            raise ValueError(
                "Invalid character(s) in sequence: "
                + ", ".join(repr(ch) for ch in invalid)
                + ". Use --allow-ambiguous for IUPAC codes or provide only A/C/G/T."
            )
        return "".join(comp[ch] for ch in reversed(sequence))

    # Canonical-only behavior, distilled from source logic.
    table = str.maketrans("ACGTacgt", "TGCAtgca")

    allowed = set("ACGTacgt")
    invalid = sorted({ch for ch in sequence if ch not in allowed})
    if invalid:
        raise ValueError(
            "Invalid character(s) in sequence: "
            + ", ".join(repr(ch) for ch in invalid)
            + ". Provide only A/C/G/T (case-insensitive), or use --allow-ambiguous."
        )

    return sequence.translate(table)[::-1]


def _read_sequence_from_stdin() -> str:
    data = sys.stdin.read()
    return data


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute the reverse complement of a DNA sequence from an argument or stdin."
    )
    parser.add_argument(
        "--sequence",
        help="Input DNA sequence. If omitted, read from stdin.",
        default=None,
    )
    parser.add_argument(
        "--allow-ambiguous",
        action="store_true",
        help=(
            "Allow IUPAC ambiguous DNA codes (e.g., N, R, Y). If set, ambiguous codes are "
            "complemented where defined; otherwise input must contain only A/C/G/T (case-insensitive)."
        ),
    )
    parser.add_argument(
        "--strip-whitespace",
        action="store_true",
        help="Remove all whitespace characters from the input sequence before processing.",
    )
    parser.add_argument(
        "--output",
        choices=["json", "text"],
        default="json",
        help="Output format: json or text.",
    )

    args = parser.parse_args()

    try:
        seq: Optional[str] = args.sequence
        if seq is None:
            seq = _read_sequence_from_stdin()
        result = core_function(
            seq,
            allow_ambiguous=bool(args.allow_ambiguous),
            strip_whitespace=bool(args.strip_whitespace),
        )

        if args.output == "text":
            sys.stdout.write(result)
            if not result.endswith("\n"):
                sys.stdout.write("\n")
        else:
            payload = {
                "input": seq if args.sequence is not None else None,
                "reverse_complement": result,
                "allow_ambiguous": bool(args.allow_ambiguous),
                "strip_whitespace": bool(args.strip_whitespace)
            }
            sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")

    except Exception as e:
        sys.stderr.write(f"Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
