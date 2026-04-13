---
name: compute-gc-content
description: 'Use when a task needs to compute GC content (fraction of G/C bases)
  for one or more DNA sequences, with optional FASTA parsing and input validation.
  Triggers on: bioinformatics, sequence, dna, gc-content, text-processing.'
---

# compute-gc-content

Compute GC content (fraction of G/C bases) for one or more DNA sequences, with optional FASTA parsing and input validation.

## Quick start

1. View the CLI help:
   python scripts/compute_gc_content.py --help
2. Run a concrete copy-runnable example using a direct sequence and JSON output:
   python scripts/compute_gc_content.py --sequence ACGTNNGCGC --output json
3. Read the results from stdout for normal output. If the command fails (for example, invalid characters with strict validation, missing inputs, or unsupported options), details are written to stderr.

## Scripts

- scripts/compute_gc_content.py: Compute GC content for one or more sequences provided via --sequence or --input.

Run via Python CLI:

python scripts/compute_gc_content.py --help

## Inputs

Provide sequences in one of these ways:

- --sequence SEQUENCE
  - DNA sequence provided directly on the command line.
  - Can be repeated to compute GC content for multiple sequences.

- --input INPUT
  - Read sequences from a file path, or use "-" to read from stdin.
  - Interpreted according to --format.

Input parsing and validation controls:

- --format {raw,fasta}
  - raw: treat the input as a plain sequence (whitespace ignored).
  - fasta: parse FASTA records (lines starting with ">" start new records).

- --strict
  - If set, error on invalid characters (anything other than A/C/G/T/N, ignoring whitespace).

- --ignore-ambiguous
  - If set, compute GC fraction over only A/C/G/T bases (exclude N and other ambiguous bases from the denominator).

Output control:

- --output {json,text}
  - Select JSON (machine-readable) or text output.

## Output

- stdout:
  - Normal results. With --output json, emits a JSON object containing per-record results and an aggregate summary.

- stderr:
  - Errors (for example, invalid characters when --strict is enabled, missing inputs, or unsupported options).

Example stdout (JSON) for:

python scripts/compute_gc_content.py --sequence ACGTNNGCGC --output json

{
  "results": [
    {
      "header": null,
      "sequence_index": 0,
      "length": 10,
      "gc_fraction": 0.6
    }
  ],
  "summary": {
    "records": 1,
    "total_length": 10,
    "mean_gc_fraction": 0.6
  }
}

## When to use

Use when:
- You need GC fraction for one or more DNA sequences.
- You want to parse FASTA input and compute GC per record.
- You want optional strict validation and/or to exclude ambiguous bases from the denominator.

Do not use when:
- You need GC content for RNA (U) without pre-converting to DNA bases.
- You need sliding-window GC, per-position tracks, or other advanced sequence statistics not supported by this CLI.
- Your inputs include IUPAC ambiguity codes beyond N and you require them to be handled in a specific way (other than excluding them with --ignore-ambiguous).
