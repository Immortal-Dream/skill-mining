"""SKILL.md body synthesis from deterministic capability context."""

from __future__ import annotations

import re

from loguru import logger
from pydantic.v1 import BaseModel, Extra, Field, validator

from easm_pipeline.core.llm_infra.clients import StructuredLLMClient
from easm_pipeline.core.llm_infra.schemas import CapabilitySlice


class SkillInstructions(BaseModel):
    """Structured instruction body returned by instruction generation."""

    instructions: str = Field(..., min_length=1)

    class Config:
        extra = Extra.forbid

    @validator("instructions")
    @classmethod
    def _validate_skill_body(cls, value: str) -> str:
        stripped = value.strip()
        lines = [line.strip() for line in stripped.splitlines() if line.strip()]
        if not lines:
            raise ValueError("instructions must be non-empty")
        if len(lines) > 500:
            raise ValueError("instructions must be 500 lines or fewer")
        if any(ord(char) > 127 for char in stripped):
            raise ValueError("instructions must use ASCII text and punctuation only")
        if not any(line.startswith("# ") for line in lines):
            raise ValueError("instructions must include a top-level markdown heading")
        if "## Helper Scripts Available" not in stripped:
            raise ValueError("instructions must include a '## Helper Scripts Available' section")
        if "## Quick Start" not in stripped:
            raise ValueError("instructions must include a '## Quick Start' section")
        if "scripts/" in stripped:
            if "## Running Bundled Scripts" not in stripped:
                raise ValueError("instructions that reference scripts must include a '## Running Bundled Scripts' section")
            if "--help" not in stripped:
                raise ValueError("instructions that reference scripts must tell Claude to run --help first")
            if "--args-json" not in stripped and "--kwargs-json" not in stripped:
                raise ValueError("instructions that reference scripts must include JSON invocation examples")
        quick_start = _section_lines(stripped, "## Quick Start")
        numbered_steps = [line for line in quick_start if re.match(r"^\d+\.\s+\S", line)]
        if not numbered_steps:
            raise ValueError("Quick Start must include chronological numbered steps")
        if numbered_steps:
            for expected, line in enumerate(numbered_steps, start=1):
                match = re.match(r"^(?P<number>\d+)\.\s+\S", line)
                if match and int(match.group("number")) != expected:
                    raise ValueError("instruction steps must be chronologically numbered without gaps")
        if re.search(r"(?<![A-Za-z0-9_/])I(?![A-Za-z0-9_/])", stripped):
            raise ValueError("instructions must avoid first-person phrasing")
        if re.search(r"\b(me|my|mine|we|our|ours|us)\b", stripped, flags=re.IGNORECASE):
            raise ValueError("instructions must avoid first-person phrasing")
        return stripped


def _section_lines(markdown: str, section_heading: str) -> list[str]:
    lines = markdown.splitlines()
    in_section = False
    section: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == section_heading:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if in_section and stripped:
            section.append(stripped)
    return section


class InstructionWriter:
    """Generate the SKILL.md body without frontmatter."""

    def __init__(self, llm_client: StructuredLLMClient | None = None) -> None:
        self._llm_client = llm_client

    async def awrite(
        self,
        capability: CapabilitySlice,
        *,
        script_names: tuple[str, ...] = (),
        reference_names: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
    ) -> SkillInstructions:
        if self._llm_client is None:
            logger.info("Generating instructions with deterministic fallback: slice={}", capability.slice_id)
            return self.write_fallback(
                capability,
                script_names=script_names,
                reference_names=reference_names,
                warnings=warnings,
            )
        prompt = build_instruction_prompt(
            capability,
            script_names=script_names,
            reference_names=reference_names,
            warnings=warnings,
        )
        logger.info(
            "Generating instruction draft with LLM: slice={} scripts={} references={} warnings={}",
            capability.slice_id,
            len(script_names),
            len(reference_names),
            len(warnings),
        )
        return await self._llm_client.agenerate(
            prompt=prompt,
            response_schema=SkillInstructions,
            system_prompt="Write only the body of SKILL.md through the configured schema.",
        )

    def write(
        self,
        capability: CapabilitySlice,
        *,
        script_names: tuple[str, ...] = (),
        reference_names: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
    ) -> SkillInstructions:
        if self._llm_client is None:
            logger.info("Generating instructions with deterministic fallback: slice={}", capability.slice_id)
            return self.write_fallback(
                capability,
                script_names=script_names,
                reference_names=reference_names,
                warnings=warnings,
            )
        prompt = build_instruction_prompt(
            capability,
            script_names=script_names,
            reference_names=reference_names,
            warnings=warnings,
        )
        logger.info(
            "Generating instruction draft with LLM: slice={} scripts={} references={} warnings={}",
            capability.slice_id,
            len(script_names),
            len(reference_names),
            len(warnings),
        )
        return self._llm_client.generate(
            prompt=prompt,
            response_schema=SkillInstructions,
            system_prompt="Write only the body of SKILL.md through the configured schema.",
        )

    @staticmethod
    def write_fallback(
        capability: CapabilitySlice,
        *,
        script_names: tuple[str, ...] = (),
        reference_names: tuple[str, ...] = (),
        warnings: tuple[str, ...] = (),
    ) -> SkillInstructions:
        title = capability.title or "Mined Capability"
        lines = [
            f"# {title}",
            "",
            "Use this skill when the task matches the mined source capability and the bundled helpers can perform the deterministic work.",
            "",
            "## Helper Scripts Available",
            "",
        ]
        if script_names:
            lines.extend(f"- `scripts/{name}` - black-box helper; run `--help` before use." for name in sorted(script_names))
        else:
            lines.append("- No executable helper script was approved for this capability.")
        lines.extend(
            [
                "",
                "Do not read helper script source before trying `--help`; scripts are packaged to avoid loading implementation code into context.",
                "",
                "## Quick Start",
                "",
                "1. Confirm the user task matches this skill's YAML description and the mined source behavior.",
                "2. Prefer bundled scripts for deterministic work instead of rewriting the extracted logic.",
            ]
        )
        if reference_names:
            refs = ", ".join(f"`references/{name}`" for name in reference_names)
            lines.append(f"3. Read {refs} only when source signatures, dependency notes, or quarantined logic are needed.")
        else:
            lines.append("3. Use the bundled script docstrings and function signatures as the implementation reference.")
        if script_names:
            lines.append("4. Run the relevant script through a short Python launcher and pass explicit inputs.")
        else:
            lines.append("4. Recreate the behavior directly because no executable script was approved for this skill.")
        final_step = 5
        if warnings:
            lines.append(
                f"{final_step}. Treat the security warnings as blockers until the caller explicitly accepts the risk."
            )
            final_step += 1
        lines.append(f"{final_step}. Report outputs, assumptions, and any source behavior that could not be reproduced.")
        if script_names:
            lines.extend(
                [
                    "",
                    "## Running Bundled Scripts",
                    "",
                    "Treat bundled scripts as black-box helpers. Run `--help` first and do not read script source unless the help output is insufficient and customization is necessary.",
                    "",
                    "```bash",
                    "python scripts/<script-name>.py --help",
                    "python scripts/<script-name>.py --args-json '[...]'",
                    "python scripts/<script-name>.py --kwargs-json '{...}'",
                    "```",
                    "",
                    "Available scripts:",
                ]
            )
            lines.extend(f"- `scripts/{name}`" for name in sorted(script_names))
            lines.extend(
                [
                    "",
                    "## Decision Tree",
                    "",
                    "```text",
                    "Task matches skill description?",
                    "  - No -> Do not use this skill.",
                    "  - Yes -> Is an approved script available?",
                    "      - Yes -> Run --help, then invoke the script with explicit JSON arguments.",
                    "      - No -> Read references only as needed and reproduce behavior manually.",
                    "```",
                ]
            )
        if reference_names:
            lines.extend(["", "## Reference Files", ""])
            lines.extend(f"- `references/{name}`" for name in sorted(reference_names))
        if warnings:
            lines.extend(["", "## Security Review", ""])
            lines.extend(f"- {warning}" for warning in warnings)
        lines.extend(
            [
                "",
                "## Best Practices",
                "",
                "- Treat stdout as the result channel and stderr as invocation or runtime diagnostics.",
                "- Pass explicit inputs; avoid implicit filesystem state unless the user provides paths.",
                "- Report assumptions and any source behavior that could not be reproduced.",
            ]
        )
        return SkillInstructions(instructions="\n".join(lines))


def build_instruction_prompt(
    capability: CapabilitySlice,
    *,
    script_names: tuple[str, ...] = (),
    reference_names: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
) -> str:
    context = capability.render_llm_context(max_node_code_chars=3000)
    scripts = ", ".join(script_names) or "none"
    references = ", ".join(reference_names) or "none"
    warning_text = "\n".join(f"- {warning}" for warning in warnings) or "none"
    return (
        "Write the body of SKILL.md for a Claude Agent Skill generated from mined source code.\n\n"
        "Agent Skill style requirements:\n"
        "- Do not include YAML frontmatter; the packaging layer prepends it.\n"
        "- Start with one top-level markdown heading naming the capability.\n"
        "- Include a short purpose paragraph under the H1.\n"
        "- Include a '## Helper Scripts Available' section before detailed execution guidance.\n"
        "- Include a '## Quick Start' section immediately after helper script summary.\n"
        "- In Quick Start, give chronological numbered steps for Claude to decide when to use scripts, references, and warnings.\n"
        "- Include a compact '## Decision Tree' section when it clarifies when to use scripts or references.\n"
        "- Include a '## Running Bundled Scripts' section when scripts are available.\n"
        "- Explain exactly how Claude should invoke scripts from bash without loading script contents into context.\n"
        "- Require Claude to run `python scripts/<script>.py --help` before using any helper script.\n"
        "- Treat helper scripts as black boxes. Do not read script source unless --help is insufficient and a customized solution is necessary.\n"
        "- Use the generated CLI format: `python scripts/<script>.py --args-json '[...]'` or `--kwargs-json '{...}'`.\n"
        "- Explain that stdout is the result channel and stderr indicates invocation/runtime problems.\n"
        "- Include a '## Reference Files' section only when reference files are available, and say when to read them.\n"
        "- Include a '## Best Practices' section with source-specific operational cautions.\n"
        "- Include a '## Security Review' section when warnings are present; do not approve quarantined or risky code.\n"
        "- Keep the whole body under 500 lines and preferably under 120 lines.\n"
        "- Use ASCII text and punctuation only. Avoid curly quotes, arrows, emoji, and non-ASCII symbols.\n"
        "- Write direct procedural guidance for Claude. Avoid first-person phrasing.\n"
        "- Do not include XML tags or extra JSON fields.\n\n"
        f"Approved scripts: {scripts}\n"
        f"Reference files: {references}\n"
        f"Security warnings:\n{warning_text}\n\n"
        f"Deterministic capability context:\n{context}"
    )
