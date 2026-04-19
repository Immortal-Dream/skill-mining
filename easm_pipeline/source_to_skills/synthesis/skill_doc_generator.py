"""Generate SKILL.md usage manuals for packaged skill scripts."""

from __future__ import annotations

import re

from loguru import logger
from pydantic.v1 import BaseModel, Extra, Field, validator

from easm_pipeline.core.llm_infra.clients import StructuredLLMClient
from easm_pipeline.source_to_skills.mining.candidate_schema import CandidateDecision
from easm_pipeline.source_to_skills.script_mining.script_schema import GeneratedScript, ScriptCliArgument, ScriptValidationResult


class SkillDoc(BaseModel):
    """SKILL.md body for a generated skill script."""

    instructions: str = Field(..., min_length=1)

    class Config:
        extra = Extra.forbid

    @validator("instructions")
    @classmethod
    def _validate_instructions(cls, value: str) -> str:
        stripped = value.strip()
        required = (
            "# ",
            "## Quick start",
            "## Scripts",
            "## Inputs",
            "## Output",
            "## When to use",
        )
        missing = [item for item in required if item not in stripped]
        if missing:
            raise ValueError(f"SKILL.md body missing required content: {', '.join(missing)}")
        if any(ord(char) > 127 for char in stripped):
            raise ValueError("SKILL.md body must use ASCII text and punctuation only")
        if "../scripts/" in stripped:
            raise ValueError("SKILL.md body must reference skill-local scripts/<filename>, not shared parent scripts")
        if re.search(r"^\s*(none|n/a|not applicable)\.?\s*$", stripped, flags=re.IGNORECASE | re.MULTILINE):
            raise ValueError("SKILL.md body must omit empty sections instead of using None or N/A")
        scripts_section = _section_text(stripped, "## Scripts")
        if "scripts/" not in scripts_section:
            raise ValueError("Scripts section must list the generated script path")
        quick_start = _section_lines(stripped, "## Quick start")
        numbered = [line for line in quick_start if re.match(r"^\d+[\.)]\s+\S", line)]
        if not numbered:
            raise ValueError("Quick start must include numbered steps")
        for expected, line in enumerate(numbered, start=1):
            match = re.match(r"^(?P<number>\d+)\.\s+\S", line)
            if match is None:
                raise ValueError("Quick start steps must use '1.' numbering, not '1)'")
            if int(match.group("number")) != expected:
                raise ValueError("Quick start steps must be numbered without gaps")
        output_section = _section_text(stripped, "## Output")
        if "stdout" not in output_section.lower() or "stderr" not in output_section.lower():
            raise ValueError("Output section must describe stdout and stderr behavior")
        when_section = _section_text(stripped, "## When to use")
        if "Use when:" not in when_section or "Do not use when:" not in when_section:
            raise ValueError("When to use section must include positive and negative triggers")
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
        doc = self._llm_client.generate(
            prompt=build_skill_doc_prompt(script=script, decision=decision, validation=validation),
            response_schema=SkillDoc,
            system_prompt=(
                "Write the usage manual for a packaged source-language skill script. "
                "Return only the SKILL.md body in the schema."
            ),
        )
        _validate_doc_matches_script(doc, script)
        return doc

    @staticmethod
    def generate_fallback(
        *,
        script: GeneratedScript,
        decision: CandidateDecision,
        validation: ScriptValidationResult,
    ) -> SkillDoc:
        del decision, validation
        script_path = f"scripts/{script.filename}"
        title = script.skill_id.replace("-", " ").title()
        inputs = _input_lines(script)
        notes = _notes_section(script)
        quick_start = _quick_start(script, script_path)
        body = f"""# {title}

## Quick start

{quick_start}

## Scripts

- `{script_path}` - {script.description}
- Runtime hint: `{script.runtime_hint}`
{_entry_symbol_line(script)}
- Example command: `{script.example_command}`

## Inputs

{inputs}

## Output

The script writes normal results to stdout. Error details, runtime failures, or sandbox execution failures go to stderr.

```text
stdout: result payload or language-native program output
stderr: runtime or argument errors
```

## When to use

Use when: a task needs to {_lower_first(script.description.rstrip("."))}.

Do not use when: the task requires hidden project state, private infrastructure, or behavior outside the packaged source artifact.
{notes}
"""
        return SkillDoc(instructions=body)


def _validate_doc_matches_script(doc: SkillDoc, script: GeneratedScript) -> None:
    instructions = doc.instructions
    script_path = f"scripts/{script.filename}"
    if script_path not in instructions:
        raise ValueError(f"SKILL.md must mention generated script path {script_path}")
    if script.example_command not in instructions:
        raise ValueError("SKILL.md must mention the example execution command")
    if script.skill_id.startswith("skill_"):
        raise ValueError("SKILL.md must not use a skill_ prefixed skill name")
    if script.supports_help and "--help" not in instructions:
        raise ValueError("SKILL.md must mention --help for scripts that support it")
    for argument in script.cli_arguments:
        if argument.flag not in instructions:
            raise ValueError(f"SKILL.md must document CLI flag {argument.flag}")
    if script.cli_arguments and "--output" not in instructions:
        raise ValueError("SKILL.md must document --output for CLI-driven scripts")


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
        "Write SKILL.md body text for a packaged source-language Agent Skill.\n\n"
        "Rules:\n"
        "- Do not include YAML frontmatter.\n"
        "- Start with one H1.\n"
        "- Use these required headings: '## Quick start', '## Scripts', '## Inputs', '## Output', and '## When to use'.\n"
        "- Omit empty optional sections. Do not write None, N/A, TBD, placeholder, or empty Notes/See also sections.\n"
        "- Explain how to execute the packaged script with its runtime_hint and example_command.\n"
        "- The script path from the skill doc folder is scripts/<filename>.\n"
        "- Do not use ../../scripts or any parent-directory script path.\n"
        "- Mention stdout for normal results and stderr for errors.\n"
        "- Include a concrete copy-runnable example command using example_command.\n"
        "- Include 'Use when:' and 'Do not use when:' in the When to use section.\n"
        "- If supports_help is true, mention --help before other execution.\n"
        "- If cli_arguments exist, document only those flags plus --output.\n"
        "- Use ASCII text and punctuation only.\n\n"
        f"Generated script metadata:\n{script.json(indent=2)[:5000]}\n\n"
        f"Candidate decision:\n{decision.json(indent=2)}\n\n"
        f"Validation result:\n{validation.json(indent=2)}"
    )


def _quick_start(script: GeneratedScript, script_path: str) -> str:
    if script.supports_help:
        return (
            "1. Run help:\n"
            "   ```bash\n"
            f"   python {script_path} --help\n"
            "   ```\n\n"
            "2. Run with example input:\n"
            "   ```bash\n"
            f"   {script.example_command}\n"
            "   ```\n\n"
            "3. Read stdout as result. Check stderr only on failure."
        )
    return (
        "1. Inspect the packaged source file and confirm the runtime hint matches the target sandbox.\n\n"
        "2. Execute the script with the matching runtime or sandbox command:\n"
        "   ```bash\n"
        f"   {script.example_command}\n"
        "   ```\n\n"
        "3. Read stdout as result. Check stderr for runtime or compilation failures."
    )


def _input_lines(script: GeneratedScript) -> str:
    if script.cli_arguments:
        inputs = "\n".join(_input_line(argument) for argument in script.cli_arguments)
        return (
            f"{inputs}\n"
            "- `--output` (optional, default: json): Output format. Use `json` for machine-readable stdout or `text` for human-readable stdout."
        )
    entry = script.entry_symbol or "the file entrypoint"
    return (
        f"- Pass task-specific inputs through the `{script.runtime_hint}` runtime or sandbox targeting `{entry}`.\n"
        "- Preserve the packaged source file path under `scripts/` so the runtime can compile or interpret it directly."
    )


def _input_line(argument: ScriptCliArgument) -> str:
    requirement = "required" if argument.required else f"optional, default: {argument.default or _default_for_argument(argument)}"
    return f"- `{argument.flag}` ({requirement}): {argument.help} Example: `{_example_value(argument)}`."


def _example_value(argument: ScriptCliArgument) -> str:
    if argument.value_type == "json":
        return _json_example(argument.name)
    if argument.value_type == "int":
        return "10"
    if argument.value_type == "float":
        return "1.0"
    if argument.value_type == "bool":
        return "true"
    return _string_example(argument.name)


def _json_example(name: str) -> str:
    if "edge" in name:
        return '[["A","B"],["B","C"],["D","E"]]'
    if "row" in name or "table" in name:
        return '[{"value": 1}, {"value": 2}]'
    if "sequence" in name or "dna" in name:
        return '"ACGTACGT"'
    return "{}"


def _string_example(name: str) -> str:
    if "sequence" in name or "dna" in name:
        return "ACGTACGT"
    if "path" in name or "file" in name:
        return "input.json"
    if "column" in name:
        return "value"
    return "sample"


def _default_for_argument(argument: ScriptCliArgument) -> str:
    if argument.value_type == "bool":
        return "false"
    return "none"


def _notes_section(script: GeneratedScript) -> str:
    notes: list[str] = []
    if any(argument.value_type == "json" for argument in script.cli_arguments):
        notes.append("Quote JSON argument values correctly for the active shell before passing them to `--*-json` flags.")
    if script.entry_symbol and not script.cli_arguments:
        notes.append(f"The packaged source artifact preserves the original entry symbol `{script.entry_symbol}` for sandbox invocation.")
    if not notes:
        return ""
    bullets = "\n".join(f"- {note}" for note in notes)
    return f"\n## Notes\n\n{bullets}\n"


def _entry_symbol_line(script: GeneratedScript) -> str:
    if not script.entry_symbol:
        return ""
    return f"- Entry symbol: `{script.entry_symbol}`"


def _lower_first(value: str) -> str:
    return value[:1].lower() + value[1:] if value else value
