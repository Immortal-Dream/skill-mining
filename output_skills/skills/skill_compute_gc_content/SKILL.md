---
name: skill_compute_gc_content
description: Compute the GC content of a DNA sequence.
---

# skill_compute_gc_content

Compute the GC content of a DNA sequence.

## Helper Scripts Available

- ../../scripts/skill_compute_gc_content.py: Compute the GC content of a DNA sequence.

## Quick Start

1. Always view help before execution:

python3 ../../scripts/skill_compute_gc_content.py --help

2. Run with the required input flag:

python3 ../../scripts/skill_compute_gc_content.py --sequence ACGTACGT

3. Choose an output format (optional). The only supported values are json and text:

python3 ../../scripts/skill_compute_gc_content.py --sequence ACGTACGT --output json
python3 ../../scripts/skill_compute_gc_content.py --sequence ACGTACGT --output text

Normal results are written to stdout. Errors and failures are written to stderr.

## Running Bundled Scripts

Run the script directly via the Python CLI from the skill documentation folder using this relative path:

python3 ../../scripts/skill_compute_gc_content.py --help

Then execute with inputs:

python3 ../../scripts/skill_compute_gc_content.py --sequence GCGCGCAAATTT --output json

Normal results are printed to stdout. If an error occurs (for example, missing required inputs), the script prints an error message to stderr and exits with a non-zero status.

## Inputs

- --sequence (required, str)
  - DNA sequence string to evaluate.

- --output (optional)
  - Output format for the result.
  - Allowed values: json, text.
  - Default: json.

## Output

The script returns the GC content as a fraction between 0.0 and 1.0, computed as:

(number of G plus number of C) divided by (sequence length)

- With --output json (default), stdout will contain a JSON number.
- With --output text, stdout will contain the raw numeric value.

Errors are written to stderr.
