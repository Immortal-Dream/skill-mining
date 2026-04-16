"""Compatibility exports for DAG/provenance skill mining."""

from __future__ import annotations

__all__ = ["DAGSkillPipeline", "DAGSkillPipelineConfig", "DAGSkillPipelineResult"]


def __getattr__(name: str):
    if name in __all__:
        from easm_pipeline import skill_mining

        return getattr(skill_mining, name)
    raise AttributeError(name)
