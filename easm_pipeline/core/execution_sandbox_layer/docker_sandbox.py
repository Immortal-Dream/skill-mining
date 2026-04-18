"""Docker-backed execution sandbox for filesystem Agent Skill scripts.

The control layer hands pydantic-ai-skills a script executor. This module
implements that executor with `docker run`: skill files are copied into a
workspace, the workspace is mounted into a short-lived container, and the script
is invoked with the named CLI arguments supplied by the agent.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path, PurePosixPath
from typing import Any

from loguru import logger
from pydantic.v1 import BaseModel, Extra, Field, validator


DEFAULT_OPENHANDS_RUNTIME_IMAGE = "ghcr.io/all-hands-ai/runtime:0.39-nikolaik"
SANDBOX_IMAGE_ENV = "EASM_SANDBOX_IMAGE"
DEFAULT_CONTAINER_WORKSPACE = PurePosixPath("/workspace")


class DockerSandboxError(RuntimeError):
    """Base exception for Docker sandbox failures."""


class DockerUnavailableError(DockerSandboxError):
    """Raised when the Docker CLI is unavailable."""


class DockerSandboxConfig(BaseModel):
    """Runtime configuration for Docker-based skill script execution."""

    image: str = Field(
        default_factory=lambda: os.getenv(SANDBOX_IMAGE_ENV, DEFAULT_OPENHANDS_RUNTIME_IMAGE),
        min_length=1,
        description="Docker image used to execute skill scripts.",
    )
    docker_cli: str = Field(default="docker", min_length=1)
    workspace_root: Path | None = Field(
        default=None,
        description="Host directory used as persistent sandbox workspace. A temp dir is used when omitted.",
    )
    container_workspace: str = Field(default=str(DEFAULT_CONTAINER_WORKSPACE), min_length=1)
    timeout_seconds: int = Field(default=120, ge=1)
    network_enabled: bool = False
    memory_limit: str | None = Field(default="1g")
    cpus: float | None = Field(default=1.0, gt=0)
    pids_limit: int | None = Field(default=256, ge=1)
    cap_drop_all: bool = True
    no_new_privileges: bool = True
    remove_container: bool = True
    keep_workspace: bool = False
    extra_docker_args: tuple[str, ...] = Field(default_factory=tuple)

    class Config:
        extra = Extra.forbid
        validate_assignment = True
        arbitrary_types_allowed = True

    @validator("image", "docker_cli", "container_workspace")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must be non-empty")
        return stripped

    @validator("workspace_root", pre=True)
    @classmethod
    def _coerce_workspace_root(cls, value: Any) -> Path | None:
        if value in {None, ""}:
            return None
        return Path(value).expanduser()


class DockerSandboxRunResult(BaseModel):
    """Raw process result from one sandbox execution."""

    command: tuple[str, ...]
    return_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False

    class Config:
        extra = Extra.forbid

    def format_for_agent(self) -> str:
        """Return a compact tool result that preserves stdout, stderr, and status."""

        stdout = self.stdout.strip()
        stderr = self.stderr.strip()
        if self.timed_out:
            return _format_sections(
                f"Sandbox execution timed out after command start.",
                stdout=stdout,
                stderr=stderr,
            )
        if self.return_code == 0 and not stderr:
            return stdout
        if self.return_code == 0:
            return _format_sections("Sandbox execution succeeded with stderr output.", stdout=stdout, stderr=stderr)
        return _format_sections(
            f"Sandbox execution failed with exit code {self.return_code}.",
            stdout=stdout,
            stderr=stderr,
        )


class DockerSkillScriptExecutor:
    """pydantic-ai-skills compatible executor that runs scripts in Docker."""

    def __init__(self, config: DockerSandboxConfig | None = None) -> None:
        self.config = config or DockerSandboxConfig()
        self._temp_workspace: tempfile.TemporaryDirectory[str] | None = None
        self._workspace_root = self._resolve_workspace_root()

    @property
    def workspace_root(self) -> Path:
        """Host-side sandbox workspace mounted into Docker."""

        return self._workspace_root

    async def run(self, script: Any, args: dict[str, Any] | None = None) -> str:
        """Run one skill script in a short-lived Docker container."""

        self._ensure_docker_available()
        if getattr(script, "uri", None) is None:
            raise DockerSandboxError(f"script {getattr(script, 'name', '<unknown>')} has no filesystem URI")

        script_path = Path(script.uri).resolve()
        source_skill_root = _infer_skill_root(script_path)
        sandbox_skill_root = self._prepare_skill_workspace(source_skill_root)
        relative_script = script_path.relative_to(source_skill_root)
        command = self.build_docker_command(
            sandbox_skill_root=sandbox_skill_root,
            relative_script=relative_script,
            args=args or {},
        )

        logger.info(
            "Executing skill script in Docker sandbox: image={} skill={} script={}",
            self.config.image,
            source_skill_root.name,
            relative_script.as_posix(),
        )
        result = await self._run_docker_command(command)
        return result.format_for_agent()

    def build_docker_command(
        self,
        *,
        sandbox_skill_root: Path,
        relative_script: Path,
        args: dict[str, Any],
    ) -> tuple[str, ...]:
        """Build the docker CLI command for a copied skill script."""

        container_name = f"easm-skill-{uuid.uuid4().hex[:12]}"
        container_workspace = PurePosixPath(self.config.container_workspace)
        container_skill_root = container_workspace / "skills" / sandbox_skill_root.name
        container_script = container_skill_root / relative_script.as_posix()
        script_command = _script_command(container_script, relative_script)
        _append_named_args(script_command, args)

        cmd: list[str] = [self.config.docker_cli, "run"]
        if self.config.remove_container:
            cmd.append("--rm")
        cmd.extend(["--name", container_name])
        cmd.extend(["--workdir", container_skill_root.as_posix()])
        cmd.extend(["--volume", f"{self.workspace_root.resolve()}:{container_workspace.as_posix()}:rw"])
        cmd.extend(["--env", "PYTHONUNBUFFERED=1"])
        if not self.config.network_enabled:
            cmd.extend(["--network", "none"])
        if self.config.memory_limit:
            cmd.extend(["--memory", self.config.memory_limit])
        if self.config.cpus is not None:
            cmd.extend(["--cpus", str(self.config.cpus)])
        if self.config.pids_limit is not None:
            cmd.extend(["--pids-limit", str(self.config.pids_limit)])
        if self.config.cap_drop_all:
            cmd.extend(["--cap-drop", "ALL"])
        if self.config.no_new_privileges:
            cmd.extend(["--security-opt", "no-new-privileges"])
        cmd.extend(self.config.extra_docker_args)
        cmd.append(self.config.image)
        cmd.extend(script_command)
        return tuple(cmd)

    def cleanup(self) -> None:
        """Remove a temporary workspace when configured to do so."""

        if self.config.keep_workspace:
            return
        if self._temp_workspace is not None:
            self._temp_workspace.cleanup()
            self._temp_workspace = None

    def _resolve_workspace_root(self) -> Path:
        if self.config.workspace_root is not None:
            root = self.config.workspace_root.resolve()
            root.mkdir(parents=True, exist_ok=True)
            return root
        self._temp_workspace = tempfile.TemporaryDirectory(prefix="easm-sandbox-")
        return Path(self._temp_workspace.name).resolve()

    def _prepare_skill_workspace(self, source_skill_root: Path) -> Path:
        skills_root = self.workspace_root / "skills"
        skills_root.mkdir(parents=True, exist_ok=True)
        target = skills_root / source_skill_root.name
        if target.exists():
            return target
        shutil.copytree(
            source_skill_root,
            target,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"),
        )
        return target

    def _ensure_docker_available(self) -> None:
        if shutil.which(self.config.docker_cli) is None:
            raise DockerUnavailableError(f"Docker CLI not found: {self.config.docker_cli}")

    async def _run_docker_command(self, command: tuple[str, ...]) -> DockerSandboxRunResult:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=self.config.timeout_seconds,
            )
            timed_out = False
        except asyncio.TimeoutError:
            process.kill()
            stdout_bytes, stderr_bytes = await process.communicate()
            timed_out = True

        return DockerSandboxRunResult(
            command=command,
            return_code=process.returncode if process.returncode is not None else 124,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
            timed_out=timed_out,
        )


def _infer_skill_root(script_path: Path) -> Path:
    """Infer the skill directory from a script path discovered by pydantic-ai-skills."""

    if script_path.parent.name == "scripts":
        return script_path.parent.parent
    return script_path.parent


def _script_command(container_script: PurePosixPath, relative_script: Path) -> list[str]:
    suffix = relative_script.suffix.lower()
    script = container_script.as_posix()
    if suffix == ".py":
        return ["python", script]
    if suffix in {".sh", ".bash"}:
        return ["bash", script]
    if suffix == ".js":
        return ["node", script]
    if suffix == ".ps1":
        return ["pwsh", "-File", script]
    if suffix in {".bat", ".cmd"}:
        return ["cmd", "/c", script]
    return [script]


def _append_named_args(command: list[str], args: dict[str, Any]) -> None:
    for key, value in args.items():
        flag = f"--{key.replace('_', '-')}"
        if isinstance(value, bool):
            if value:
                command.append(flag)
        elif isinstance(value, list):
            if flag.endswith("-json"):
                command.extend([flag, json.dumps(value, ensure_ascii=False)])
                continue
            for item in value:
                command.extend([flag, str(item)])
        elif isinstance(value, dict):
            command.extend([flag, json.dumps(value, ensure_ascii=False)])
        elif value is not None:
            command.extend([flag, str(value)])


def _format_sections(header: str, *, stdout: str, stderr: str) -> str:
    sections = [header]
    if stdout:
        sections.append(f"stdout:\n{stdout}")
    if stderr:
        sections.append(f"stderr:\n{stderr}")
    return "\n\n".join(sections)
