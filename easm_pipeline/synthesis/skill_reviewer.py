"""LLM review pass for Claude Agent Skill authoring quality."""

from __future__ import annotations

from loguru import logger
from pydantic.v1 import BaseModel, Extra, Field, validator

from easm_pipeline.core.llm_infra.clients import StructuredLLMClient
from easm_pipeline.core.llm_infra.schemas import CapabilitySlice
from easm_pipeline.synthesis.instruction_writer import SkillInstructions


class ReviewedSkillInstructions(BaseModel):
    """Reviewed and revised SKILL.md body."""

    instructions: str = Field(..., min_length=1)
    review_notes: tuple[str, ...] = Field(default_factory=tuple)

    class Config:
        extra = Extra.forbid

    @validator("instructions")
    @classmethod
    def _validate_body_shape(cls, value: str) -> str:
        stripped = value.strip()
        SkillInstructions(instructions=stripped)
        if "scripts/" in stripped and "--help" not in stripped:
            raise ValueError("reviewed instructions must tell Claude to run scripts with --help first")
        return stripped


class SkillInstructionReviewer:
    """Ask the LLM to revise generated instructions into Claude Skill style."""

    def __init__(self, llm_client: StructuredLLMClient | None = None) -> None:
        self._llm_client = llm_client

    def review(
        self,
        capability: CapabilitySlice,
        *,
        draft_instructions: str,
        script_names: tuple[str, ...] = (),
        reference_names: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
    ) -> ReviewedSkillInstructions:
        if self._llm_client is None:
            logger.info("Skipping LLM instruction review; no client configured: slice={}", capability.slice_id)
            return ReviewedSkillInstructions(
                instructions=draft_instructions,
                review_notes=("LLM review skipped because no client was configured.",),
            )
        prompt = build_skill_review_prompt(
            capability,
            draft_instructions=draft_instructions,
            script_names=script_names,
            reference_names=reference_names,
            warnings=warnings,
        )
        logger.info(
            "Reviewing instructions with LLM: slice={} scripts={} references={} warnings={}",
            capability.slice_id,
            len(script_names),
            len(reference_names),
            len(warnings),
        )
        return self._llm_client.generate(
            prompt=prompt,
            response_schema=ReviewedSkillInstructions,
            system_prompt=(
                "Review and revise a Claude Agent Skill body. Return only the revised instructions "
                "and concise review notes in the requested JSON schema."
            ),
        )


def build_skill_review_prompt(
    capability: CapabilitySlice,
    *,
    draft_instructions: str,
    script_names: tuple[str, ...] = (),
    reference_names: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> str:
    scripts = "\n".join(f"- scripts/{name}" for name in script_names) or "- none"
    references = "\n".join(f"- references/{name}" for name in reference_names) or "- none"
    warning_text = "\n".join(f"- {warning}" for warning in warnings) or "- none"
    return (
        "Revise this SKILL.md body so it follows Claude Agent Skills progressive disclosure.\n\n"
        "Required Claude Skill style:\n"
        "- Keep YAML frontmatter out of the body.\n"
        "- Start with one H1 title.\n"
        "- Include a short purpose paragraph only if it helps usage.\n"
        "- Include '## Helper Scripts Available' near the top.\n"
        "- Include '## Quick Start' immediately after helper script summary.\n"
        "- Quick Start steps must use `1.`, `2.`, `3.` numbering, never `1)` numbering.\n"
        "- Include a compact decision tree when it helps Claude choose scripts versus references.\n"
        "- Mention helper scripts as black boxes. Claude should run each relevant script with --help first.\n"
        "- Do NOT tell Claude to read script source unless --help is insufficient and customization is necessary.\n"
        "- Include exact bash examples for invoking scripts with JSON arguments when scripts exist.\n"
        "- Explain what stdout means and when to inspect stderr.\n"
        "- Include a '## Reference Files' section only when reference files exist; omit it when there are no references.\n"
        "- Include best practices specific to the mined capability.\n"
        "- Include Security Review guidance when warnings or quarantined references exist.\n"
        "- Keep the body concise, under 500 lines, and preferably under 120 lines.\n\n"
        "- Use ASCII text and punctuation only. Replace arrows with '->' and curly quotes with straight quotes.\n\n"
        f"Available scripts:\n{scripts}\n\n"
        f"Reference files:\n{references}\n\n"
        f"Security warnings:\n{warning_text}\n\n"
        f"Capability context:\n{capability.render_llm_context(max_node_code_chars=2500)}\n\n"
        "Draft SKILL.md body to revise:\n"
        f"{draft_instructions}"
    )
