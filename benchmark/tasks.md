# Benchmark Tasks JSONL Schema

Each line in `tasks.jsonl` is one task object.

Required fields:

- `task_id`: Stable task identifier.
- `split`: One of `train` or `test`.
- `domain`: High-level domain label.
- `codebase`: Human-readable codebase name.
- `codebase_path`: Relative path to the local benchmark codebase.
- `title`: Short task title.
- `prompt`: User-facing task statement.
- `grounding`: Flat list of repo APIs, classes, files, or bundled assets that justify the task.
- `scope_guardrails`: Flat list of "do not exceed the repo boundary" constraints.
- `dataset_id`: Stable dataset binding identifier.
- `dataset_status`: One of `ready` or `planned_vendor`.
- `input_spec`: Flat list describing the intended inputs.
- `input_paths`: Flat list of canonical local paths the runner should mount for the task.
- `deliverables`: Flat list of expected output artifacts.
- `evaluation`: Task-level grading contract with these required keys:
  - `primary_metric`
  - `artifact_checks`
  - `reference_strategy`

Split policy:

- `train` tasks are visible to Stage 2 skill refinement.
- `test` tasks are held out and used only for final evaluation.
- Benchmark v1 targets `9` train tasks and `20` test tasks.
- Each domain contributes `3` train tasks.

Design intent:

- Tasks should stay close to capabilities already present in the codebase.
- Tasks should be skill-mining friendly: multi-step enough to reward reusable workflow skills, but not so open-ended that they become generic coding tasks.
- Input bindings should be explicit and local-path based.
- `planned_vendor` means the benchmark path is fixed, but the file still needs to be vendored into `benchmark/datasets/`.
