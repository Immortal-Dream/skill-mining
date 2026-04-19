# Benchmark Evaluation Plan

## Goal

Evaluate whether a system can mine repo-grounded skills from a scientific codebase, refine those skills with `train` tasks, and then solve held-out `test` tasks more reliably and efficiently.

## Benchmark Splits

- `train`: visible to Stage 2 skill refinement.
- `test`: held out for final evaluation.
- v1 target:
  - `9` train tasks total
  - `20` test tasks total
  - `3` train tasks per domain

## Compared Settings

- `No Skill`
  - The agent receives no external skill library.
- `K-Dense Skill`
  - The agent receives a high-coverage curated skill library.
- `Stage-1-Only Skill`
  - The agent receives only codebase-mined Stage 1 skills.
- `Train-Driven Mined Skill`
  - The agent receives Stage 1 skills plus Stage 2 refinement driven by `train` tasks.

## Allowed Inputs By Stage

### Stage 1

- May access the target codebase.
- May not access `test` task prompts or reference outputs.

### Stage 2

- May access the target codebase.
- May access `train` task prompts and input data.
- May refine skills, add wrappers, improve docs, and tune routing.
- May not access `test` task prompts or reference outputs.

### Final Evaluation

- Uses a frozen skill library and frozen routing policy.
- Runs only on held-out `test` tasks.

## Primary Metrics

- `test_success_rate`
  - Fraction of held-out test tasks that pass hard artifact checks.
- `pass_at_k`
  - Fraction of held-out test tasks solved in at least one of `k` attempts.
- `skill_invocation_success_rate`
  - Fraction of skill calls that return usable outputs without execution failure.
- `token_usage`
  - Report total tokens and mean tokens per successful test task.
- `runtime_seconds`
  - Report total wall-clock time and mean runtime per successful test task.

## Secondary Metrics

- `repo_grounded_rate`
  - Fraction of successful tasks that remain aligned with repo-native workflows.
- `artifact_validity_rate`
  - Fraction of produced outputs that satisfy the task artifact contract.
- `task_specific_metric`
  - Optional numeric task metric such as F1, nDCG, or relative error.

## Scoring Layers

### 1. Artifact validity

This is the hard gate.

- Required files must exist.
- File formats must match the task contract.
- Required columns, keys, or HDU names must be present.
- Outputs must be parseable without manual cleanup.

If artifact validity fails, the task is counted as unsuccessful.

### 2. Repo-grounded workflow compliance

This is a lightweight anti-overreach check.

- The solution should use the designated codebase and repo-native workflow.
- The output schema should align with repo-native concepts such as scPSS score columns, Rxn-INSIGHT reaction annotations, or Photutils segmentation and photometry outputs.
- The task should not be solved by swapping in a different model family or unrelated pipeline.

## Task Metrics

### Biology

- Ranking tasks: Spearman correlation between participant and reference score vectors.
- Selection tasks: F1 or Jaccard on significant-cell sets.
- Parameter tasks: exact match or tolerance-based match on selected configuration.

### Chemistry

- Structured annotation tasks: exact match or macro-F1 over class and name fields.
- Retrieval tasks: recall@k or nDCG@k against a reference top-k precedent list.
- Suggestion tasks: top-k overlap or weighted nDCG over ranked solvents, catalysts, and reagents.

### Astronomy

- Map outputs: mean absolute error or relative error on background maps and RMS maps.
- Detection tasks: precision, recall, and F1 using source matching within a fixed pixel tolerance.
- Photometry tasks: relative flux error or median absolute percentage error on matched sources.

## Reference Generation

- Each task should have one canonical reference run produced with the target repo on the fixed dataset.
- Reference artifacts should be stored under `benchmark/reference/<task_id>/`.
- Stochastic tasks should set a fixed random seed.
- Threshold-based tasks should freeze tolerances and matching radius in the task config.

## Recommended Reporting

Main table:

- `No Skill`
- `K-Dense Skill`
- `Stage-1-Only Skill`
- `Train-Driven Mined Skill`

Columns:

- `Test Success`
- `Pass@k`
- `Skill Invocation Success`
- `Tokens`
- `Runtime`

Supplementary analysis:

- `repo_grounded_rate`
- `artifact_validity_rate`
- domain-wise breakdown
- train-to-test transfer case studies

## What This Benchmark Should Not Reward

- Solving tasks with unrelated external models.
- Hand-written outputs that skip the codebase workflow.
- Large runtime or huge data movement that is unnecessary for the small fixed datasets.
