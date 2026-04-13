---
name: dna-sequence-gc-and-revcomp
description: Use when a user needs to compute GC content or generate the reverse complement
  for a DNA sequence. Do not use when the input is not a DNA sequence or when the
  task requires advanced bioinformatics analysis beyond simple GC content and reverse
  complementation.
---

# Sequence Tools (GC Content and Reverse Complement)

Use the helper scripts to compute GC content (as a fraction) and to generate the reverse complement of a DNA sequence.

## Helper Scripts Available

- scripts/compute-gc-content.py: Computes GC content of a DNA sequence.
- scripts/reverse-complement.py: Produces the reverse complement of a DNA sequence.

Treat scripts as black boxes. Run each relevant script with --help first to confirm flags and JSON argument shape.

## Quick Start

1. Choose the operation:
   - GC content / GC fraction / percent GC -> compute-gc-content
   - Reverse complement / RC / reverse strand complement -> reverse-complement
2. Check the CLI for the script you will use:
   - python scripts/compute-gc-content.py --help
   - python scripts/reverse-complement.py --help
3. Run the script with JSON arguments and report stdout as the result:
   - python scripts/compute-gc-content.py --args-json '["ACGTACGT"]'
   - python scripts/reverse-complement.py --args-json '["ACGTACGT"]'

Stdout is the script's normal output (the answer you should return). If something fails, inspect stderr for errors like invalid JSON, missing arguments, or runtime issues, then fix inputs/quoting and rerun.

## Running Bundled Scripts

- Always run the relevant script with --help first:
  - python scripts/compute-gc-content.py --help
  - python scripts/reverse-complement.py --help
- Invoke scripts via python and pass inputs as JSON when supported:
  - python scripts/compute-gc-content.py --args-json '["ACGTACGT"]'
  - python scripts/reverse-complement.py --args-json '["ACGTACGT"]'
- Stdout is the primary result to return to the user. Stderr is where warnings and errors appear; check stderr when the command fails or output looks incomplete.

## Decision Tree

- Need GC content (fraction) -> run scripts/compute-gc-content.py
- Need percent GC -> run scripts/compute-gc-content.py, then multiply stdout by 100 only if the user asked for percent
- Need reverse complement -> run scripts/reverse-complement.py
- Need both -> run both scripts
- Many sequences / batch style request -> prefer scripts; if the CLI only accepts one sequence at a time, run per sequence and label outputs or ask how to aggregate

## Usage Notes and Best Practices

- Input expectations:
  - These tools are for DNA strings. Confirm whether input is A/C/G/T only.
  - If ambiguous bases (N, R, Y, etc.) or non-letters appear, do not guess behavior. Use the script output, and note any assumptions based on observed behavior.
- GC content definition:
  - Output is a fraction in [0.0, 1.0]. Convert to percent only when requested.
  - Empty sequence should return 0.0.
- Reverse complement output:
  - Typically preserves case for A/C/G/T and a/c/g/t. If other characters are present, verify behavior by running the script and report what happened.
- Reproducibility:
  - Prefer scripts over manual in-context calculation when sequences are long, when formatting must be exact, or when multiple sequences are involved.

## Security Review

No security warnings are present for this skill. Only run the approved helper scripts above. Avoid passing sensitive sequences unless required, and do not attempt to inspect or modify script source unless --help is insufficient and customization is necessary.
