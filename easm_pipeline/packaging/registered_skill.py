"""Packaging schemas for script-first generated skills."""

from __future__ import annotations

from pydantic.v1 import BaseModel, Extra, Field

from easm_pipeline.mining.candidate_schema import CandidateDecision
from easm_pipeline.script_mining.script_schema import GeneratedScript, ScriptValidationResult
from easm_pipeline.synthesis.skill_doc_generator import SkillDoc


class RegisteredSkillPackage(BaseModel):
    """Complete package for one script-first skill."""

    decision: CandidateDecision
    script: GeneratedScript
    skill_doc: SkillDoc
    validation: ScriptValidationResult
    source_file: str | None = None
    source_span: dict[str, int] = Field(default_factory=dict)
    references_dict: dict[str, str] = Field(default_factory=dict)

    class Config:
        extra = Extra.forbid
