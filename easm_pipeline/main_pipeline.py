"""Compatibility entry point for Stage 1 source-to-skills mining."""

from __future__ import annotations

from easm_pipeline.source_to_skills.main_pipeline import (
    EASMPipeline,
    PipelineConfig,
    PipelineResult,
    build_arg_parser,
    main,
)

__all__ = ["EASMPipeline", "PipelineConfig", "PipelineResult", "build_arg_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())

