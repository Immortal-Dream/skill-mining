---
name: compute-gc-content
description: 'Use when a task needs to compute GC fraction for a DNA sequence string
  (G and C count divided by sequence length). Triggers on: bioinformatics, dna, sequence,
  gc-content, utility.'
---

# compute-gc-content

Compute GC fraction for a DNA sequence string (G and C count divided by sequence length).

## Quick start
1. Show help (supports --help):
   python scripts/compute_gc_content.py --help
2. Run the script with a DNA sequence (example is copy-runnable):
   python scripts/compute_gc_content.py --sequence ACGTACGT --output json
3. Read results from stdout. If an error occurs, read the error message from stderr.

## Scripts
- scripts/compute_gc_content.py: CLI wrapper around the core function that computes GC fraction from an input DNA sequence string.

## Inputs
CLI flags:
- --sequence (required): DNA sequence string to analyze (for example, ACGTACGT). The script normalizes to uppercase before counting.
- --output (optional): Output format. Allowed values: json, text. Default: json.

## Output
- stdout (normal):
  - If --output json (default): a JSON object with:
    - sequence_length: length of the provided sequence string
    - gc_fraction: GC fraction as a float in the range 0.0 to 1.0 (0.0 for an empty string)
  - If --output text: a single line containing the gc_fraction value.
- stderr (errors): a line starting with "Error:" describing the failure.

## When to use
Use when:
- You need a deterministic GC fraction for a DNA sequence string as a quick CLI utility.
- You want machine-readable output (JSON) for piping into other tools.

Do not use when:
- You need validation or cleaning of sequence characters beyond uppercasing (for example, handling ambiguous bases like N, or ignoring whitespace).
- You need GC content over sliding windows, per-contig summaries, or FASTA/FASTQ file parsing (this script expects a single sequence string via --sequence).
