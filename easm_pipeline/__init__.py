"""Evolutionary Agent Skill Mining pipeline package."""

__all__ = ["EASMPipeline", "PipelineConfig", "PipelineResult"]


def __getattr__(name: str):
    """Lazily expose source-to-skills symbols without importing heavy deps at package import time."""

    if name in __all__:
        from easm_pipeline.source_to_skills import EASMPipeline, PipelineConfig, PipelineResult

        values = {
            "EASMPipeline": EASMPipeline,
            "PipelineConfig": PipelineConfig,
            "PipelineResult": PipelineResult,
        }
        return values[name]
    raise AttributeError(f"module 'easm_pipeline' has no attribute {name!r}")
