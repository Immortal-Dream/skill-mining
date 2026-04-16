"""Compatibility wrapper for DAG-based skill mining."""

from __future__ import annotations

from easm_pipeline.skill_mining import (  # noqa: F401
    DAGSkillPipeline,
    DAGSkillPipelineConfig,
    DAGSkillPipelineResult,
    build_arg_parser,
    main,
)

__all__ = [
    "DAGSkillPipeline",
    "DAGSkillPipelineConfig",
    "DAGSkillPipelineResult",
    "build_arg_parser",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
