---
name: reverse-complement-dna
description: 'Use when a task needs to compute the reverse complement of a DNA sequence
  (A,C,G,T; preserves case) using a fast translation table. Triggers on: bioinformatics,
  dna, sequence, string-processing.'
---

# reverse-complement-dna

Compute the reverse complement of a DNA sequence (A,C,G,T; preserves case) using a fast translation table.

## Quick start

1. Show help (recommended before first use):

python scripts/reverse_complement_dna.py --help

2. Run the script with a sequence:

python scripts/reverse_complement_dna.py --sequence ACGTacgt

Runtime hint: python

Normal results are written to stdout. Errors and failures are written to stderr.

## Scripts

- scripts/reverse_complement_dna.py
  - CLI entrypoint for computing a reverse complement.
  - Also exposes a reusable function named core_function(sequence: str) -> str inside the script.

## Inputs

Command-line flags:

- --sequence SEQUENCE (required)
  - Input DNA sequence.
  - Standard bases are complemented with case preserved:
    - A <-> T, C <-> G
    - a <-> t, c <-> g

- --output {json,text} (optional)
  - Output format.
  - Default: json

## Output

Written to stdout:

- If --output json (default): a JSON object:
  - {"reverse_complement": "..."}

- If --output text: the reverse-complement sequence followed by a newline.

Errors are written to stderr and the process exits non-zero.

## When to use

Use when:
- You need the reverse complement of a DNA sequence containing only A,C,G,T (or lowercase equivalents).
- You want a fast, deterministic string transformation suitable for pipelines.

Do not use when:
- Your input includes ambiguous or extended IUPAC bases (for example N, R, Y); these characters will not be complemented and may produce incorrect biological results.
- You need validation, cleaning, or parsing of FASTA/FASTQ files (this script expects a sequence string provided via --sequence).
