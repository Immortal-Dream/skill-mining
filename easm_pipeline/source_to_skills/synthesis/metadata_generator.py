"""Skill metadata synthesis.

This module may call an LLM through the isolated core client. It never parses
source files directly and only consumes deterministic `CapabilitySlice` input.
"""

from __future__ import annotations

from loguru import logger
from pydantic.v1 import BaseModel, Extra, Field, validator

from easm_pipeline.core.llm_infra.clients import StructuredLLMClient
from easm_pipeline.core.llm_infra.schemas import CapabilitySlice
from easm_pipeline.source_to_skills.extraction.common import slugify


class SkillMetadata(BaseModel):
    """Structured metadata returned by metadata generation."""

    name: str = Field(..., min_length=1, max_length=64, regex=r"^[a-z0-9-]+$")
    description: str = Field(..., min_length=1, max_length=1024)

    class Config:
        extra = Extra.forbid

    @validator("description")
    @classmethod
    def _description_must_trigger(cls, value: str) -> str:
        if any(ord(char) > 127 for char in value):
            raise ValueError("description must use ASCII text and punctuation only")
        normalized = value.lower()
        if "use when" not in normalized:
            raise ValueError("description must include an explicit 'Use when' trigger")
        if "do not use" not in normalized:
            raise ValueError("description must include a negative 'Do not use' constraint")
        return value.strip()


class MetadataGenerator:
    """Generate skill name and description from deterministic capability context."""

    def __init__(self, llm_client: StructuredLLMClient | None = None) -> None:
        self._llm_client = llm_client

    async def agenerate(self, capability: CapabilitySlice) -> SkillMetadata:
        if self._llm_client is None:
            logger.info("Generating metadata with deterministic fallback: slice={}", capability.slice_id)
            return self.generate_fallback(capability)
        prompt = build_metadata_prompt(capability)
        logger.info("Generating metadata with LLM: slice={}", capability.slice_id)
        return await self._llm_client.agenerate(
            prompt=prompt,
            response_schema=SkillMetadata,
            system_prompt=(
                "Generate concise Claude Agent Skill metadata. Return only structured fields "
                "through the configured schema."
            ),
        )

    def generate(self, capability: CapabilitySlice) -> SkillMetadata:
        if self._llm_client is None:
            logger.info("Generating metadata with deterministic fallback: slice={}", capability.slice_id)
            return self.generate_fallback(capability)
        prompt = build_metadata_prompt(capability)
        logger.info("Generating metadata with LLM: slice={}", capability.slice_id)
        return self._llm_client.generate(
            prompt=prompt,
            response_schema=SkillMetadata,
            system_prompt=(
                "Generate concise Claude Agent Skill metadata. Return only structured fields "
                "through the configured schema."
            ),
        )

    @staticmethod
    def generate_fallback(capability: CapabilitySlice) -> SkillMetadata:
        base_name = slugify(capability.title or capability.slice_id)
        node_names = ", ".join(node.name for node in capability.nodes[:3])
        focus = node_names or capability.summary or capability.title
        description = (
            f"Use when an agent needs to apply the extracted {capability.title} capability "
            f"from legacy source context focused on {focus}. "
            "Do not use when the task is unrelated to this mined capability or requires "
            "broad repository refactoring."
        )
        return SkillMetadata(name=base_name, description=description[:1024])


def build_metadata_prompt(capability: CapabilitySlice) -> str:
    context = capability.render_llm_context(max_node_code_chars=2500)
    return (
        "Generate YAML frontmatter metadata for one Claude Agent Skill.\n\n"
        "Constraints:\n"
        "- Return a lowercase kebab-case name, max 64 characters.\n"
        "- Description must be objective third-person phrasing.\n"
        "- Description must begin with or clearly include 'Use when'.\n"
        "- Description must include a 'Do not use when' negative trigger to avoid overtriggering.\n"
        "- Do not include XML tags, markdown, code fences, or extra fields.\n"
        "- Use ASCII text and punctuation only. Avoid curly quotes, arrows, emoji, and non-ASCII symbols.\n"
        "- Do not use reserved words such as anthropic or claude in the name.\n\n"
        f"Deterministic capability context:\n{context}"
    )


