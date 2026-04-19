# Agent File System

This directory stores durable host-managed artifacts produced by the
containerized control-layer agent.

- `logs/` - optional execution logs.
- `output/` - durable outputs produced by agent-triggered skill executions.

Input directories and skill directories are no longer stored here. Each agent
container launch receives explicit host paths for input and skills, then mounts
them read-only as `/workspace/input` and `/workspace/skills`.

Do not store mined skill packages here. Mined skills belong in `data/output_skills/`.
