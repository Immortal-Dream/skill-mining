# Benchmark Datasets

This directory holds the canonical small fixed datasets used by `benchmark/tasks.jsonl`.

Current policy:

- `ready`: file already exists locally at the bound path.
- `planned_vendor`: path is fixed for benchmark stability, but the file still needs to be vendored into this directory before running the final benchmark.

Directory layout:

- `biology/`
- `chemistry/`
- `astronomy/`
