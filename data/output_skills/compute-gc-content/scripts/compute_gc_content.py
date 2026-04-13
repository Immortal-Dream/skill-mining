#!/usr/bin/env python3

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Tuple


def _parse_fasta(text: str) -> List[Tuple[Optional[str], str]]:
    """Parse a minimal FASTA string into a list of (header, sequence) tuples.

    Rules:
    - Lines starting with '>' begin a new record; the remainder of the line is the header.
    - Sequence lines are concatenated (whitespace trimmed).
    - Empty lines are ignored.

    If the input contains no header lines, returns one record with header=None and
    the entire text (with whitespace/newlines removed) as the sequence.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not any(ln.startswith(">") for ln in lines):
        seq = "".join(lines)
        return [(None, seq)]

    records: List[Tuple[Optional[str], str]] = []
    header: Optional[str] = None
    seq_parts: List[str] = []

    def flush() -> None:
        nonlocal header, seq_parts
        if header is None and not seq_parts:
            return
        records.append((header, "".join(seq_parts)))
        header = None
        seq_parts = []

    for ln in lines:
        if ln.startswith(">"):
            flush()
            header = ln[1:].strip() or ""
        else:
            seq_parts.append(ln)
    flush()

    return records


def _compute_gc_fraction_single(sequence: str) -> float:
    """Compute the GC fraction of a DNA sequence.

    This mirrors the extracted source logic:
    - Uppercases the input
    - Returns 0.0 for empty sequence
    - Counts 'G' and 'C' and divides by sequence length

    Note: This function does not validate characters.
    """
    cleaned = sequence.upper()
    if not cleaned:
        return 0.0
    gc = cleaned.count("G") + cleaned.count("C")
    return gc / len(cleaned)


def core_function(
    sequences: List[str],
    *,
    input_format: str = "raw",
    strict: bool = False,
    ignore_ambiguous: bool = False,
) -> Dict[str, Any]:
    """Compute GC content for one or more sequences.

    Args:
        sequences: List of sequence strings. If input_format is 'fasta', each
            element may contain one or more FASTA records.
        input_format: 'raw' or 'fasta'.
        strict: If True, error on invalid characters (anything other than A/C/G/T/N
            plus whitespace/newlines in FASTA input).
        ignore_ambiguous: If True, compute GC fraction over only A/C/G/T bases.
            When enabled, 'N' and other ambiguous bases are excluded from the
            denominator. If the filtered length is 0, GC fraction is 0.0.

    Returns:
        A dict with:
          - results: list of per-record results (each includes gc_fraction, length, header)
          - summary: aggregated stats across records

    Raises:
        ValueError: If inputs are invalid or strict validation fails.
    """
    if input_format not in ("raw", "fasta"):
        raise ValueError("input_format must be 'raw' or 'fasta'")

    if not sequences:
        raise ValueError("At least one sequence must be provided")

    allowed = set("ACGTNacgtn")

    records: List[Tuple[Optional[str], str]] = []
    if input_format == "raw":
        for s in sequences:
            records.append((None, "".join(s.split())))
    else:
        for blob in sequences:
            for header, seq in _parse_fasta(blob):
                records.append((header, "".join(seq.split())))

    if not records:
        raise ValueError("No sequences found")

    results: List[Dict[str, Any]] = []
    total_len = 0
    total_gc = 0.0

    for idx, (header, seq) in enumerate(records):
        if strict:
            for ch in seq:
                if ch not in allowed:
                    label = header if header is not None else str(idx)
                    raise ValueError("Invalid character in sequence record " + str(label) + ": " + repr(ch))

        if ignore_ambiguous:
            cleaned = seq.upper()
            filtered = "".join([c for c in cleaned if c in ("A", "C", "G", "T")])
            gc_fraction = _compute_gc_fraction_single(filtered)
            length = len(filtered)
            gc_count = gc_fraction * float(length) if length > 0 else 0.0
        else:
            cleaned = seq.upper()
            gc_fraction = _compute_gc_fraction_single(cleaned)
            length = len(cleaned)
            gc_count = gc_fraction * float(length) if length > 0 else 0.0

        results.append(
            {
                "header": header,
                "sequence_index": idx,
                "length": length,
                "gc_fraction": gc_fraction,
            }
        )

        total_len += length
        total_gc += gc_count

    summary_gc_fraction = (total_gc / float(total_len)) if total_len > 0 else 0.0

    return {
        "results": results,
        "summary": {
            "records": len(results),
            "total_length": total_len,
            "gc_fraction": summary_gc_fraction,
        },
    }


def _read_input_blob(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _to_text(payload: Dict[str, Any]) -> str:
    lines: List[str] = []
    for r in payload.get("results", []):
        header = r.get("header")
        label = header if header not in (None, "") else str(r.get("sequence_index"))
        lines.append("record=" + str(label) + " length=" + str(r.get("length")) + " gc_fraction=" + ("{:.6f}".format(float(r.get("gc_fraction")))))
    summary = payload.get("summary", {})
    lines.append("summary records=" + str(summary.get("records")) + " total_length=" + str(summary.get("total_length")) + " gc_fraction=" + ("{:.6f}".format(float(summary.get("gc_fraction")))))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="compute_gc_content",
        description="Compute GC content (fraction of G/C bases) for one or more DNA sequences.",
    )
    parser.add_argument(
        "--sequence",
        action="append",
        default=[],
        help="DNA sequence provided directly on the command line. Can be repeated.",
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Read sequences from a file path, or '-' to read from stdin. Supports raw or FASTA based on --format.",
    )
    parser.add_argument(
        "--format",
        dest="input_format",
        choices=["raw", "fasta"],
        default="raw",
        help="Input format: raw or fasta.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="If set, error on invalid characters (anything other than A/C/G/T/N, ignoring whitespace).",
    )
    parser.add_argument(
        "--ignore-ambiguous",
        action="store_true",
        help="If set, compute GC fraction over only A/C/G/T bases (exclude N/ambiguous from denominator).",
    )
    parser.add_argument(
        "--output",
        choices=["json", "text"],
        default="json",
        help="Output format: json or text.",
    )

    args = parser.parse_args()

    try:
        blobs: List[str] = []
        if args.input is not None:
            blobs.append(_read_input_blob(str(args.input)))
        if args.sequence:
            blobs.extend([str(s) for s in args.sequence])

        if not blobs:
            raise ValueError("Provide --sequence and/or --input")

        result = core_function(
            blobs,
            input_format=str(args.input_format),
            strict=bool(args.strict),
            ignore_ambiguous=bool(args.ignore_ambiguous),
        )

        if args.output == "json":
            sys.stdout.write(json.dumps(result, indent=2, sort_keys=True))
            sys.stdout.write("\n")
        else:
            sys.stdout.write(_to_text(result))
            sys.stdout.write("\n")

    except Exception as e:
        sys.stderr.write("Error: " + str(e) + "\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
