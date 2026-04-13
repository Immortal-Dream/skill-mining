---
name: reverse-complement-dna
description: 'Use when a task needs to return the reverse complement of a DNA sequence.
  Triggers on: bioinformatics, dna, string-processing, sequence, cli-candidate.'
---

# reverse-complement-dna

Return the reverse complement of a DNA sequence.

## Quick start
1. View help (prints usage to stdout):
python3 scripts/reverse_complement_dna.py --help

2. Run with a DNA sequence (normal results go to stdout; errors go to stderr):
python3 scripts/reverse_complement_dna.py --sequence ACGTtgca --output json

## Scripts
- scripts/reverse_complement_dna.py: CLI for computing the reverse complement of a DNA sequence.

## Inputs
- --sequence (required, string): DNA sequence to reverse-complement. Characters outside A,C,G,T (case-insensitive) are not validated; they will be passed through unchanged except for reversal.
- --output (optional): Output format.
  - json (default): JSON-encoded value to stdout.
  - text: Plain text value to stdout.

## Output
On success, writes the reverse-complemented sequence to stdout.

Example stdout (JSON output):
{"reverse_complement":"tgcaACGT"}

On failure, writes an error message prefixed with "Error:" to stderr and exits with code 1.

## When to use
Use when:
- You need the reverse complement of a DNA string for downstream analyses (primer checks, alignment preparation, k-mer workflows).
- You want a simple, dependency-free CLI step in a pipeline.

Do not use when:
- You need strict validation of ambiguous bases (for example, N, R, Y) or IUPAC-aware complementation.
- Your input is RNA (U) and you require RNA-specific handling.
