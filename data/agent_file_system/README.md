# Agent File System

This directory is the host-managed filesystem mounted into Docker as `/workspace`
when the control-layer agent executes skill scripts.

- `input/` - user-provided files that the agent and scripts should read.
- `output/` - durable outputs produced by agent-triggered skill executions.
- `work/` - scratch files for a task run.
- `runs/` - benchmark or ad hoc run records.
- `logs/` - optional execution logs.
- `skills/` - runtime copies of skill folders used inside the sandbox.

Do not store mined skill packages here. Mined skills belong in `data/output_skills/`.
