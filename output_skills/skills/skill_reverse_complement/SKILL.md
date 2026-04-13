---
name: skill_reverse_complement
description: Compute the reverse complement of a DNA sequence from an argument or
  stdin, returning text or JSON.
---

# skill_reverse_complement

Compute the reverse complement of a DNA sequence from a command line argument or stdin. Output can be JSON (default) or plain text.

Normal results are written to stdout. Errors and validation messages are written to stderr and the process exits non-zero.

## Helper Scripts Available

This skill is implemented as a single bundled Python script:

- ../../scripts/skill_reverse_complement.py

## Quick Start

1. View help (run --help before any execution):

python3 ../../scripts/skill_reverse_complement.py --help

2. Run with an explicit sequence (default output is JSON):

python3 ../../scripts/skill_reverse_complement.py --sequence ACGT

3. Run and return plain text:

python3 ../../scripts/skill_reverse_complement.py --sequence ACGT --output text

4. Run from stdin (omit --sequence):

echo ACGT | python3 ../../scripts/skill_reverse_complement.py

## Running Bundled Scripts

Run the script directly with Python from the skill documentation folder using the relative path:

python3 ../../scripts/skill_reverse_complement.py --help

Then execute with supported arguments.

- Provide input via --sequence, or omit --sequence to read from stdin.
- Use --output to select json or text.
- If input contains whitespace and you want it ignored, use --strip-whitespace.
- If input may include IUPAC ambiguous DNA codes (for example N, R, Y), use --allow-ambiguous.

## Inputs

Accepted inputs are:

- --sequence SEQUENCE
  - Optional. DNA sequence to reverse-complement.
  - If omitted, the script reads all of stdin as the sequence.

- stdin
  - Used only when --sequence is not provided.

Validation rules:

- By default, only A, C, G, T (case-insensitive) are allowed.
- If --allow-ambiguous is provided, common IUPAC ambiguous DNA codes are accepted and complemented where defined.
- If --strip-whitespace is provided, all whitespace characters are removed before validation and processing.

## Output

All successful outputs are written to stdout.

- --output json (default): prints a single JSON object containing:
  - input: the value passed via --sequence, or null if read from stdin
  - reverse_complement: the computed reverse complement
  - allow_ambiguous: true or false
  - strip_whitespace: true or false

- --output text: prints only the reverse complement sequence followed by a newline.

All errors (for example invalid characters in the sequence) are written to stderr.
