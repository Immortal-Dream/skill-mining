"""Pydantic AI control layer for mounting filesystem Agent Skills.

This module intentionally stays above source mining. It consumes already-built
skill directories and creates an agent that can progressively load and execute
those skills through pydantic-ai-skills.
"""

from __future__ import annotations

import asyncio
import importlib
import os
import re
import subprocess
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Sequence

from loguru import logger
from pydantic.v1 import BaseModel, Extra, Field, validator

from easm_pipeline.constants.path_config import DEFAULT_DOMAIN, domain_output_dir
from easm_pipeline.core.llm_infra.clients import (
    RIGHT_CODE_API_KEY_ENV,
    RIGHT_CODE_DEFAULT_BASE_URL,
    RIGHT_CODE_DEFAULT_MODEL,
)
from easm_pipeline.core.logging import configure_logging
from easm_pipeline.core.execution_sandbox_layer import (
    DEFAULT_OPENHANDS_RUNTIME_IMAGE,
    DockerSandboxConfig,
    DockerSkillScriptExecutor,
    SANDBOX_IMAGE_ENV,
)


DEFAULT_SKILL_AGENT_INSTRUCTIONS = """You are an EASM control-layer agent.

Use the mounted skills as executable capabilities. Select skills from their
metadata, load full skill instructions only when relevant, and prefer executing
bundled scripts through the skill tools instead of reimplementing their logic.
Report script stdout as the primary result, mention stderr only when execution
fails, and ask for missing required inputs before running a script.

When a task involves files, treat /workspace as the mounted agent filesystem:
- Read user-provided files from /workspace/input.
- Write durable task outputs to /workspace/output.
- Use /workspace/work for scratch files.
- Do not write results into skill source directories unless the skill explicitly requires it.

When a skill script only returns stdout but the user asks for a file output,
call run_skill_script with an extra `output_file` argument such as
`/workspace/output/result.txt`. The sandbox executor captures stdout into that
host-managed file without requiring every script to implement file writing.
"""

CONTAINER_SKILL_AGENT_INSTRUCTIONS = """You are an EASM control-layer agent running inside a Docker container.

Use the mounted Agent Skills as executable capabilities. Select skills from
their metadata, load full skill instructions only when relevant, and prefer
executing bundled scripts through the skill tools instead of reimplementing
their logic.

Filesystem contract:
- /workspace/input is a read-only mount for user-provided task files.
- /workspace/skills is a read-only mount containing the loaded skill folders.
- /workspace/output is a writable mount for durable results.
- /workspace/logs is a writable mount for logs and diagnostics.
- /workspace/work is container-local scratch space and may disappear when the
  container stops.

When a task needs CLI or filesystem interaction, use the provided workspace
tools to run bash commands, list files, read files, or write output files. Write
final artifacts under /workspace/output unless the user explicitly requests a
different mounted output path.
"""


class SkillAgentError(RuntimeError):
    """Base exception for control-layer skill agent failures."""


class SkillAgentDependencyError(SkillAgentError):
    """Raised when pydantic-ai or pydantic-ai-skills is unavailable."""


class SkillDirectoryError(SkillAgentError):
    """Raised when a configured skill directory is missing or malformed."""


class SkillExecutionBackend(str, Enum):
    """Script execution backend used by mounted skills."""

    LOCAL = "local"
    DOCKER = "docker"


class SkillAgentConfig(BaseModel):
    """Configuration for a Pydantic AI agent with mounted Agent Skills."""

    skill_directories: tuple[Path, ...] = Field(
        ...,
        description="Directories containing skill subdirectories with SKILL.md files.",
    )
    model: str = Field(RIGHT_CODE_DEFAULT_MODEL, min_length=1)
    base_url: str = Field(RIGHT_CODE_DEFAULT_BASE_URL, min_length=1)
    api_key_env: str = Field(RIGHT_CODE_API_KEY_ENV, min_length=1)
    api_key: str | None = Field(None, description="Optional explicit API key; env var is preferred.")
    instructions: str = Field(DEFAULT_SKILL_AGENT_INSTRUCTIONS, min_length=1)
    validate_skills: bool = True
    max_depth: int = Field(3, ge=1)
    auto_reload: bool = False
    defer_model_check: bool = True
    execution_backend: SkillExecutionBackend = SkillExecutionBackend.LOCAL
    script_timeout_seconds: int = Field(120, ge=1)
    sandbox_image: str = Field(
        default_factory=lambda: os.getenv(SANDBOX_IMAGE_ENV, DEFAULT_OPENHANDS_RUNTIME_IMAGE),
        min_length=1,
    )
    sandbox_workspace_root: Path | None = None
    sandbox_network_enabled: bool = False
    sandbox_keep_workspace: bool = True
    sandbox_memory_limit: str | None = "1g"
    sandbox_cpus: float | None = Field(1.0, gt=0)
    tool_timeout_seconds: float | None = Field(120.0, gt=0)
    enable_workspace_tools: bool = False

    class Config:
        extra = Extra.forbid
        validate_assignment = True
        arbitrary_types_allowed = True

    @validator("skill_directories", pre=True)
    @classmethod
    def _coerce_skill_directories(cls, value: Any) -> tuple[Path, ...]:
        if isinstance(value, (str, Path)):
            raw_values: Sequence[str | Path] = (value,)
        else:
            raw_values = tuple(value or ())
        directories = tuple(Path(item).expanduser() for item in raw_values)
        if not directories:
            raise ValueError("at least one skill directory is required")
        return directories

    @validator("model")
    @classmethod
    def _validate_model(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("model must be non-empty")
        return stripped

    @validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        stripped = value.rstrip("/")
        if not re.match(r"^https?://", stripped):
            raise ValueError("base_url must start with http:// or https://")
        return stripped

    @validator("sandbox_workspace_root", pre=True)
    @classmethod
    def _coerce_sandbox_workspace_root(cls, value: Any) -> Path | None:
        if value in {None, ""}:
            return None
        return Path(value).expanduser()

    @classmethod
    def from_domain(cls, domain_name: str = DEFAULT_DOMAIN, **overrides: Any) -> "SkillAgentConfig":
        """Build config that mounts data/output_skills/<domain_name>."""

        return cls(skill_directories=(domain_output_dir(domain_name),), **overrides)

    @property
    def resolved_skill_directories(self) -> tuple[Path, ...]:
        """Return absolute skill directory roots."""

        return tuple(directory.resolve() for directory in self.skill_directories)

    def api_key_value(self) -> str:
        """Resolve the Right Code API key from config or environment."""

        if self.api_key:
            return self.api_key
        value = os.getenv(self.api_key_env)
        if not value:
            raise SkillAgentError(f"missing API key: set {self.api_key_env} before creating the agent")
        return value

    def validate_mounts(self) -> tuple[Path, ...]:
        """Ensure every configured root exists and contains at least one skill."""

        resolved = self.resolved_skill_directories
        for directory in resolved:
            if not directory.exists():
                raise SkillDirectoryError(f"skill directory does not exist: {directory}")
            if not directory.is_dir():
                raise SkillDirectoryError(f"skill path is not a directory: {directory}")
            if not any(path.name == "SKILL.md" for path in directory.glob("*/SKILL.md")):
                raise SkillDirectoryError(f"skill directory contains no immediate SKILL.md entries: {directory}")
        return resolved


class SkillAgentFactory:
    """Factory for Pydantic AI agents configured with pydantic-ai-skills."""

    def create_agent(self, config: SkillAgentConfig) -> Any:
        """Create a pydantic-ai Agent with all configured skill directories mounted."""

        configure_logging()
        skill_roots = config.validate_mounts()
        logger.info(
            "Creating skill agent: model={} skill_roots={} validate_skills={}",
            config.model,
            [str(path) for path in skill_roots],
            config.validate_skills,
        )

        pydantic_ai = _import_required("pydantic_ai", "pip install pydantic-ai")
        skills_module = _import_required("pydantic_ai_skills", "pip install pydantic-ai-skills")
        openai_models = _import_required("pydantic_ai.models.openai", "pip install pydantic-ai")
        openai_providers = _import_required("pydantic_ai.providers.openai", "pip install pydantic-ai")

        provider = openai_providers.OpenAIProvider(
            base_url=config.base_url,
            api_key=config.api_key_value(),
        )
        model = openai_models.OpenAIChatModel(config.model, provider=provider)
        script_executor = _build_script_executor(config, skills_module)
        skill_directories = [
            skills_module.SkillsDirectory(
                path=skill_root,
                validate=config.validate_skills,
                max_depth=config.max_depth,
                script_executor=script_executor,
            )
            for skill_root in skill_roots
        ]
        capability = skills_module.SkillsCapability(
            directories=skill_directories,
            validate=config.validate_skills,
            max_depth=config.max_depth,
            auto_reload=config.auto_reload,
        )

        agent = pydantic_ai.Agent(
            model=model,
            instructions=config.instructions,
            capabilities=[capability],
            defer_model_check=config.defer_model_check,
            tool_timeout=config.tool_timeout_seconds,
        )
        if config.enable_workspace_tools:
            _register_workspace_tools(agent, config.tool_timeout_seconds)
        return agent


class SkillAgentRunResult(BaseModel):
    """Serializable result for one incoming instruction."""

    instruction: str
    output: str

    class Config:
        extra = Extra.forbid


SkillAgentConfig.update_forward_refs(Path=Path, Sequence=Sequence)
SkillAgentRunResult.update_forward_refs()


class MountedSkillAgent:
    """Long-lived control-layer session around a mounted Pydantic AI agent."""

    def __init__(
        self,
        config: SkillAgentConfig,
        *,
        factory: SkillAgentFactory | None = None,
        agent: Any | None = None,
    ) -> None:
        self.config = config
        self._factory = factory or SkillAgentFactory()
        self._agent = agent
        self._message_history: list[Any] | None = None

    @property
    def agent(self) -> Any:
        """Create the underlying agent lazily so CLI validation errors are clear."""

        if self._agent is None:
            self._agent = self._factory.create_agent(self.config)
        return self._agent

    async def arun(self, instruction: str) -> SkillAgentRunResult:
        """Run one natural-language instruction while preserving conversation state."""

        cleaned = instruction.strip()
        if not cleaned:
            raise ValueError("instruction must be non-empty")
        logger.info("Running incoming instruction through mounted skill agent")

        result = await self.agent.run(cleaned, message_history=self._message_history)
        self._message_history = list(result.all_messages())
        return SkillAgentRunResult(instruction=cleaned, output=str(result.output))

    def run(self, instruction: str) -> SkillAgentRunResult:
        """Synchronous wrapper for command-line and notebook usage."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.arun(instruction))
        raise RuntimeError("MountedSkillAgent.run cannot run inside an active event loop")

    def reset(self) -> None:
        """Clear conversation history without recreating the mounted agent."""

        self._message_history = None
        logger.info("Reset mounted skill agent conversation history")


def _import_required(module_name: str, install_hint: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise SkillAgentDependencyError(f"missing optional dependency {module_name}: {install_hint}") from exc


def _build_script_executor(config: SkillAgentConfig, skills_module: Any) -> Any:
    if config.execution_backend is SkillExecutionBackend.DOCKER:
        return DockerSkillScriptExecutor(
            DockerSandboxConfig(
                image=config.sandbox_image,
                workspace_root=config.sandbox_workspace_root,
                timeout_seconds=config.script_timeout_seconds,
                network_enabled=config.sandbox_network_enabled,
                keep_workspace=config.sandbox_keep_workspace,
                memory_limit=config.sandbox_memory_limit,
                cpus=config.sandbox_cpus,
            )
        )
    return _build_current_python_executor(skills_module, config.script_timeout_seconds)


def _build_current_python_executor(skills_module: Any, timeout_seconds: int) -> Any:
    """Create a local script executor that runs Python scripts with this interpreter.

    pydantic-ai-skills honors a script shebang before its extension fallback. On
    Windows, generated `#!/usr/bin/env python3` shebangs can resolve to the
    Windows Store alias instead of the active conda interpreter. This executor
    keeps shell and JavaScript shebangs intact but routes Python shebangs through
    `sys.executable`.
    """

    base_executor = skills_module.LocalSkillScriptExecutor

    class CurrentPythonSkillScriptExecutor(base_executor):  # type: ignore[misc, valid-type]
        def _extract_shebang_command(self, script_path: Path) -> list[str] | None:  # type: ignore[override]
            command = super()._extract_shebang_command(script_path)
            if command and _looks_like_python_interpreter(command[0]):
                return [sys.executable, *command[1:]]
            return command

    return CurrentPythonSkillScriptExecutor(
        python_executable=sys.executable,
        timeout=timeout_seconds,
    )


def _register_workspace_tools(agent: Any, default_timeout_seconds: float | None) -> None:
    """Register direct container workspace tools on a Pydantic AI agent."""

    workspace_root = Path("/workspace")
    max_output_chars = 24000

    def resolve_workspace_path(path: str | None, *, default: str = "/workspace") -> Path:
        raw = (path or default).strip() or default
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(workspace_root)
        except ValueError as exc:
            raise ValueError(f"path must stay under /workspace: {path}") from exc
        return resolved

    def trim_output(value: str) -> str:
        if len(value) <= max_output_chars:
            return value
        return value[:max_output_chars] + f"\n...[truncated after {max_output_chars} characters]"

    @agent.tool_plain(
        name="run_bash",
        description=(
            "Run a bash command inside the agent container. Use for CLI workflows, "
            "script execution, file inspection, and data processing under /workspace."
        ),
        timeout=default_timeout_seconds,
    )
    def run_bash(command: str, cwd: str = "/workspace", timeout_seconds: int = 120) -> str:
        """Run one bash command in the container workspace."""

        working_dir = resolve_workspace_path(cwd)
        working_dir.mkdir(parents=True, exist_ok=True)
        logger.info("Agent workspace tool executing bash command in {}", working_dir)
        try:
            completed = subprocess.run(
                ["bash", "-lc", command],
                cwd=working_dir,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or ""
            return trim_output(
                f"Command timed out after {timeout_seconds} seconds.\n"
                f"stdout:\n{stdout}\n\nstderr:\n{stderr}"
            )

        output = [
            f"exit_code: {completed.returncode}",
            f"stdout:\n{completed.stdout.rstrip()}",
        ]
        if completed.stderr:
            output.append(f"stderr:\n{completed.stderr.rstrip()}")
        return trim_output("\n\n".join(output))

    @agent.tool_plain(
        name="list_workspace_files",
        description="List files under a /workspace path. Use before reading unknown input or output files.",
    )
    def list_workspace_files(path: str = "/workspace", max_entries: int = 200) -> str:
        """List files under one workspace directory."""

        root = resolve_workspace_path(path)
        if not root.exists():
            return f"path does not exist: {root}"
        if root.is_file():
            return str(root)

        lines: list[str] = []
        for index, item in enumerate(sorted(root.rglob("*"))):
            if index >= max_entries:
                lines.append(f"...[truncated after {max_entries} entries]")
                break
            relative = item.relative_to(root)
            suffix = "/" if item.is_dir() else ""
            lines.append(f"{relative.as_posix()}{suffix}")
        return "\n".join(lines) if lines else "(empty)"

    @agent.tool_plain(
        name="read_workspace_text_file",
        description="Read a UTF-8 text file under /workspace/input, /workspace/output, /workspace/logs, or skills.",
    )
    def read_workspace_text_file(path: str, max_chars: int = 24000) -> str:
        """Read a workspace text file with output truncation."""

        target = resolve_workspace_path(path)
        if not target.exists():
            return f"path does not exist: {target}"
        if not target.is_file():
            return f"path is not a file: {target}"
        content = target.read_text(encoding="utf-8", errors="replace")
        if len(content) <= max_chars:
            return content
        return content[:max_chars] + f"\n...[truncated after {max_chars} characters]"

    @agent.tool_plain(
        name="write_workspace_text_file",
        description="Write a UTF-8 text file under /workspace/output or /workspace/logs.",
    )
    def write_workspace_text_file(path: str, content: str) -> str:
        """Write a workspace output or log text file."""

        target = resolve_workspace_path(path)
        allowed_roots = (workspace_root / "output", workspace_root / "logs")
        if not any(_is_relative_to(target, root) for root in allowed_roots):
            raise ValueError("write path must stay under /workspace/output or /workspace/logs")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} characters to {target}"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _looks_like_python_interpreter(command: str) -> bool:
    executable_name = Path(command).name.lower()
    return executable_name in {"python", "python.exe", "python3", "python3.exe"} or executable_name.startswith(
        "python3."
    )
