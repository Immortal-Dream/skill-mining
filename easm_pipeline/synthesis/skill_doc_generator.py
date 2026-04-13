"""Generate SKILL.md usage manuals for validated CLI scripts."""

from __future__ import annotations

import re

from loguru import logger
from pydantic.v1 import BaseModel, Extra, Field, validator

from easm_pipeline.core.llm_infra.clients import StructuredLLMClient
from easm_pipeline.mining.candidate_schema import CandidateDecision
from easm_pipeline.script_mining.script_schema import GeneratedScript, ScriptValidationResult


class SkillDoc(BaseModel):
    """SKILL.md body for a generated CLI script."""

    instructions: str = Field(..., min_length=1)

    class Config:
        extra = Extra.forbid

    @validator("instructions")
    @classmethod
    def _validate_instructions(cls, value: str) -> str:
        stripped = value.strip()
        required = (
            "# ",
            "## Helper Scripts Available",
            "## Quick Start",
            "## Running Bundled Scripts",
            "--help",
        )
        missing = [item for item in required if item not in stripped]
        if missing:
            raise ValueError(f"SKILL.md body missing required content: {', '.join(missing)}")
        if any(ord(char) > 127 for char in stripped):
            raise ValueError("SKILL.md body must use ASCII text and punctuation only")
        helper_section = _section_text(stripped, "## Helper Scripts Available")
        if "scripts/" not in helper_section or re.search(r"^\s*none\.?\s*$", helper_section, flags=re.IGNORECASE):
            raise ValueError("Helper Scripts Available must list the generated script path")
        quick_start = _section_lines(stripped, "## Quick Start")
        numbered = [line for line in quick_start if re.match(r"^\d+[\.)]\s+\S", line)]
        if not numbered:
            raise ValueError("Quick Start must include numbered steps")
        for expected, line in enumerate(numbered, start=1):
            match = re.match(r"^(?P<number>\d+)\.\s+\S", line)
            if match is None:
                raise ValueError("Quick Start steps must use '1.' numbering, not '1)'")
            if int(match.group("number")) != expected:
                raise ValueError("Quick Start steps must be numbered without gaps")
        return stripped


class SkillDocGenerator:
    """Generate script-first SKILL.md usage documentation."""

    def __init__(self, llm_client: StructuredLLMClient | None = None) -> None:
        self._llm_client = llm_client

    def generate(
        self,
        *,
        script: GeneratedScript,
        decision: CandidateDecision,
        validation: ScriptValidationResult,
    ) -> SkillDoc:
        if self._llm_client is None:
            logger.info("Generating SKILL.md with deterministic fallback: skill_id={}", script.skill_id)
            return self.generate_fallback(script=script, decision=decision, validation=validation)

        logger.info("Generating SKILL.md with LLM: skill_id={}", script.skill_id)
        return self._llm_client.generate(
            prompt=build_skill_doc_prompt(script=script, decision=decision, validation=validation),
            response_schema=SkillDoc,
            system_prompt=(
                "Write the usage manual for a generated CLI script skill. "
                "Return only the SKILL.md body in the schema."
            ),
        )

    @staticmethod
    def generate_fallback(
        *,
        script: GeneratedScript,
        decision: CandidateDecision,
        validation: ScriptValidationResult,
    ) -> SkillDoc:
        script_path = f"../../scripts/{script.filename}"
        registry_path = f"scripts/{script.filename}"
        example = _example_command(script)
        inputs = "\n".join(
            f"- `{argument.flag}`: {argument.help}{' Required.' if argument.required else ' Optional.'}"
            for argument in script.cli_arguments
        )
        tags = ", ".join(script.tags) or "utility"
        body = f"""# {script.skill_id}

Use this skill when the task matches the mined reusable logic: {script.description}

## Helper Scripts Available

- `{script_path}` - standalone CLI script registered as `{registry_path}`.

## Quick Start

1. Run the script help before using it:
   ```bash
   python {script_path} --help
   ```
2. Prepare explicit CLI arguments for the user input.
3. Execute the script and read stdout as the result:
   ```bash
   {example}
   ```
4. If the command exits non-zero, inspect stderr, fix the input or flags, and rerun.

## Running Bundled Scripts

- Treat `{script_path}` as the source of execution truth.
- Do not read or rewrite the script unless `--help` is insufficient for a required customization.
- Use `--output json` when the result will be consumed by another tool or agent.
- stdout contains normal results. stderr contains invocation or runtime errors.

## Inputs

{inputs or "- No required domain inputs were detected."}
- `--output`: Output format, either `json` or `text`.

## Output

- JSON mode prints machine-readable output to stdout.
- Text mode prints a human-readable representation to stdout.

## Decision Notes

- Extraction decision: {decision.reason}
- Source: `{decision.source}`
- Tags: {tags}
- Validation: {'passed' if validation.passed else 'failed'}
"""
        return SkillDoc(instructions=body)


def _section_lines(markdown: str, section_heading: str) -> list[str]:
    section = _section_text(markdown, section_heading)
    return [line.strip() for line in section.splitlines() if line.strip()]


def _section_text(markdown: str, section_heading: str) -> str:
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
        if in_section:
            section.append(line)
    return "\n".join(section).strip()


def build_skill_doc_prompt(
    *,
    script: GeneratedScript,
    decision: CandidateDecision,
    validation: ScriptValidationResult,
) -> str:
    return (
        "Write SKILL.md body text for a script-first Agent Skill.\n\n"
        "Rules:\n"
        "- Do not include YAML frontmatter.\n"
        "- Start with one H1.\n"
        "- Include '## Helper Scripts Available', '## Quick Start', '## Running Bundled Scripts', '## Inputs', and '## Output'.\n"
        "- Explain exactly how to run the generated script through Python CLI.\n"
        "- The script path from the skill doc folder is ../../scripts/<filename>.\n"
        "- Mention --help before any execution.\n"
        "- Mention stdout for normal results and stderr for errors.\n"
        "- Do not invent CLI flags; use only cli_arguments and --output.\n"
        "- Use ASCII text and punctuation only.\n\n"
        f"Generated script metadata:\n{script.json(indent=2)[:5000]}\n\n"
        f"Candidate decision:\n{decision.json(indent=2)}\n\n"
        f"Validation result:\n{validation.json(indent=2)}"
    )


def _example_command(script: GeneratedScript) -> str:
    parts = [f"python ../../scripts/{script.filename}"]
    for argument in script.cli_arguments:
        if argument.value_type == "json":
            value = _json_example(argument.name)
        elif argument.value_type == "int":
            value = "10"
        elif argument.value_type == "float":
            value = "1.0"
        elif argument.value_type == "bool":
            value = "true"
        else:
            value = "example"
        parts.append(f"{argument.flag} '{value}'")
    parts.append("--output json")
    return " ".join(parts)


def _json_example(name: str) -> str:
    if "edge" in name:
        return '[["A","B"],["B","C"],["D","E"]]'
    if "row" in name or "table" in name:
        return '[{"value": 1}, {"value": 2}]'
    if "sequence" in name or "dna" in name:
        return '"ACGTACGT"'
    return "{}"
