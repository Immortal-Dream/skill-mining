"""Host-side launcher and HTTP client for the containerized EASM agent."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

from loguru import logger
from pydantic.v1 import BaseModel, Extra, Field, validator

from easm_pipeline.constants.path_config import (
    AGENT_LOGS_DIR,
    AGENT_OUTPUT_DIR,
    PROJECT_ROOT,
    ensure_agent_file_system,
)
from easm_pipeline.core.control_layer.agent_service import DEFAULT_AGENT_SERVICE_PORT
from easm_pipeline.core.execution_sandbox_layer import DEFAULT_OPENHANDS_RUNTIME_IMAGE, SANDBOX_IMAGE_ENV
from easm_pipeline.core.llm_infra.clients import (
    RIGHT_CODE_API_KEY_ENV,
    RIGHT_CODE_DEFAULT_BASE_URL,
    RIGHT_CODE_DEFAULT_MODEL,
)


DEFAULT_AGENT_CONTAINER_NAME = "easm-agent-service"
DEFAULT_CONTAINER_APP_DIR = "/app"
DEFAULT_CONTAINER_INPUT_DIR = "/workspace/input"
DEFAULT_CONTAINER_SKILLS_DIR = "/workspace/skills"
DEFAULT_CONTAINER_OUTPUT_DIR = "/workspace/output"
DEFAULT_CONTAINER_LOGS_DIR = "/workspace/logs"
DEFAULT_CONTAINER_WORK_DIR = "/workspace/work"


class AgentContainerError(RuntimeError):
    """Raised when the host-side agent container lifecycle fails."""


class AgentContainerConfig(BaseModel):
    """Configuration for starting the agent service container."""

    input_dir: Path = Field(..., description="Host input directory mounted read-only as /workspace/input.")
    skills_dir: Path = Field(..., description="Host skill root mounted read-only as /workspace/skills.")
    output_dir: Path = Field(default_factory=lambda: AGENT_OUTPUT_DIR)
    logs_dir: Path = Field(default_factory=lambda: AGENT_LOGS_DIR)
    project_root: Path = Field(default_factory=lambda: PROJECT_ROOT)
    image: str = Field(default_factory=lambda: os.getenv(SANDBOX_IMAGE_ENV, DEFAULT_OPENHANDS_RUNTIME_IMAGE))
    docker_cli: str = "docker"
    container_name: str = DEFAULT_AGENT_CONTAINER_NAME
    host: str = "127.0.0.1"
    port: int = Field(DEFAULT_AGENT_SERVICE_PORT, ge=1, le=65535)
    model: str = RIGHT_CODE_DEFAULT_MODEL
    base_url: str = RIGHT_CODE_DEFAULT_BASE_URL
    api_key_env: str = RIGHT_CODE_API_KEY_ENV
    replace_existing: bool = True
    validate_skills: bool = True
    startup_timeout_seconds: int = Field(180, ge=1)
    script_timeout_seconds: int = Field(120, ge=1)
    tool_timeout_seconds: float = Field(180.0, gt=0)
    memory_limit: str | None = "4g"
    cpus: float | None = Field(None, gt=0)
    extra_docker_args: tuple[str, ...] = Field(default_factory=tuple)

    class Config:
        extra = Extra.forbid
        arbitrary_types_allowed = True

    @validator("input_dir", "skills_dir", "output_dir", "logs_dir", "project_root", pre=True)
    @classmethod
    def _coerce_paths(cls, value: Any) -> Path:
        return Path(value).expanduser()

    def validate_host_paths(self) -> None:
        """Validate launch-time host mounts and create output directories."""

        ensure_agent_file_system()
        if shutil.which(self.docker_cli) is None:
            raise AgentContainerError(f"Docker CLI not found: {self.docker_cli}")
        if not os.getenv(self.api_key_env):
            raise AgentContainerError(f"missing API key: set {self.api_key_env} before starting the agent container")
        if not self.input_dir.exists() or not self.input_dir.is_dir():
            raise AgentContainerError(f"input directory does not exist: {self.input_dir}")
        if not self.skills_dir.exists() or not self.skills_dir.is_dir():
            raise AgentContainerError(f"skills directory does not exist: {self.skills_dir}")
        if not any(path.name == "SKILL.md" for path in self.skills_dir.glob("*/SKILL.md")):
            raise AgentContainerError(f"skills directory contains no immediate SKILL.md entries: {self.skills_dir}")
        if not (self.project_root / "easm_pipeline").is_dir():
            raise AgentContainerError(f"project root does not contain easm_pipeline/: {self.project_root}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def base_http_url(self) -> str:
        """Base URL for the host-visible agent service."""

        return f"http://{self.host}:{self.port}"


AgentContainerConfig.update_forward_refs(Path=Path)


class AgentContainerLauncher:
    """Start, stop, and inspect the Dockerized EASM agent service."""

    def __init__(self, config: AgentContainerConfig) -> None:
        self.config = config

    def start(self) -> str:
        """Start the agent container and wait for /health."""

        self.config.validate_host_paths()
        if self.config.replace_existing:
            self.stop(ignore_missing=True)

        command = self.build_docker_run_command()
        logger.info("Starting EASM agent container: {}", self.config.container_name)
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise AgentContainerError(
                f"docker run failed with exit code {result.returncode}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        container_id = result.stdout.strip()
        self.wait_until_ready()
        return container_id

    def stop(self, *, ignore_missing: bool = False) -> None:
        """Force-remove the configured container name if it exists."""

        result = subprocess.run(
            [self.config.docker_cli, "rm", "-f", self.config.container_name],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 and not ignore_missing:
            raise AgentContainerError(result.stderr.strip() or result.stdout.strip())

    def status(self) -> dict[str, Any]:
        """Return /health from the running agent service."""

        return AgentServiceClient(self.config.base_http_url).health()

    def wait_until_ready(self) -> None:
        """Wait until the container's HTTP service responds."""

        client = AgentServiceClient(self.config.base_http_url)
        deadline = time.time() + self.config.startup_timeout_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                client.health()
                return
            except Exception as exc:  # pragma: no cover - timing dependent
                last_error = exc
                if self._container_has_exited():
                    logs = self.tail_logs()
                    raise AgentContainerError(
                        f"agent service container exited before becoming ready; last_error={last_error}\n"
                        f"container_logs:\n{logs}"
                    )
                time.sleep(1)
        logs = self.tail_logs()
        raise AgentContainerError(
            f"agent service did not become ready within {self.config.startup_timeout_seconds}s; "
            f"last_error={last_error}\ncontainer_logs:\n{logs}"
        )

    def _container_has_exited(self) -> bool:
        result = subprocess.run(
            [
                self.config.docker_cli,
                "inspect",
                "-f",
                "{{.State.Running}}",
                self.config.container_name,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            return True
        return result.stdout.strip().lower() != "true"

    def tail_logs(self, lines: int = 200) -> str:
        """Return recent Docker logs for diagnostics."""

        result = subprocess.run(
            [self.config.docker_cli, "logs", "--tail", str(lines), self.config.container_name],
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout + result.stderr

    def build_docker_run_command(self) -> list[str]:
        """Build the Docker command that starts the in-container agent service."""

        cfg = self.config
        port_mapping = f"{cfg.host}:{cfg.port}:{DEFAULT_AGENT_SERVICE_PORT}"
        command = [
            cfg.docker_cli,
            "run",
            "-d",
            "--name",
            cfg.container_name,
            "-p",
            port_mapping,
            "-w",
            DEFAULT_CONTAINER_APP_DIR,
            "-v",
            _volume(cfg.project_root, DEFAULT_CONTAINER_APP_DIR, "ro"),
            "-v",
            _volume(cfg.input_dir, DEFAULT_CONTAINER_INPUT_DIR, "ro"),
            "-v",
            _volume(cfg.skills_dir, DEFAULT_CONTAINER_SKILLS_DIR, "ro"),
            "-v",
            _volume(cfg.output_dir, DEFAULT_CONTAINER_OUTPUT_DIR, "rw"),
            "-v",
            _volume(cfg.logs_dir, DEFAULT_CONTAINER_LOGS_DIR, "rw"),
            "-e",
            cfg.api_key_env,
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            f"EASM_AGENT_PORT={DEFAULT_AGENT_SERVICE_PORT}",
            "-e",
            f"EASM_AGENT_MODEL={cfg.model}",
            "-e",
            f"EASM_AGENT_BASE_URL={cfg.base_url}",
            "-e",
            f"EASM_AGENT_SKILLS_DIR={DEFAULT_CONTAINER_SKILLS_DIR}",
            "-e",
            f"EASM_AGENT_INPUT_DIR={DEFAULT_CONTAINER_INPUT_DIR}",
            "-e",
            f"EASM_AGENT_OUTPUT_DIR={DEFAULT_CONTAINER_OUTPUT_DIR}",
            "-e",
            f"EASM_AGENT_LOGS_DIR={DEFAULT_CONTAINER_LOGS_DIR}",
            "-e",
            f"EASM_AGENT_WORK_DIR={DEFAULT_CONTAINER_WORK_DIR}",
            "-e",
            f"EASM_AGENT_SCRIPT_TIMEOUT={cfg.script_timeout_seconds}",
            "-e",
            f"EASM_AGENT_TOOL_TIMEOUT={cfg.tool_timeout_seconds}",
        ]
        if cfg.memory_limit:
            command.extend(["--memory", cfg.memory_limit])
        if cfg.cpus is not None:
            command.extend(["--cpus", str(cfg.cpus)])
        command.extend(cfg.extra_docker_args)
        command.extend([cfg.image, "python", "-m", "easm_pipeline.core.control_layer.agent_service_bootstrap"])
        return command


class AgentServiceClient:
    """Small stdlib HTTP client for a running EASM agent service."""

    def __init__(self, base_url: str = f"http://127.0.0.1:{DEFAULT_AGENT_SERVICE_PORT}", timeout_seconds: int = 300):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def health(self) -> dict[str, Any]:
        return self._request("GET", "/health")

    def reset(self) -> dict[str, Any]:
        return self._request("POST", "/reset", {})

    def run_instruction(self, instruction: str, *, reset: bool = False) -> dict[str, Any]:
        return self._request("POST", "/run", {"instruction": instruction, "reset": reset})

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except URLError as exc:
            raise AgentContainerError(f"agent service request failed: {exc}") from exc
        return json.loads(raw)


def unique_container_name(prefix: str = DEFAULT_AGENT_CONTAINER_NAME) -> str:
    """Return a unique container name for tests or parallel local runs."""

    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _volume(host_path: Path, container_path: str, mode: str) -> str:
    return f"{host_path.resolve()}:{container_path}:{mode}"
