"""HTTP service that runs a mounted Skill Agent inside a Docker container."""

from __future__ import annotations

import argparse
import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic.v1 import BaseModel, Extra, Field, ValidationError

from easm_pipeline.core.control_layer.skill_agent import (
    CONTAINER_SKILL_AGENT_INSTRUCTIONS,
    MountedSkillAgent,
    SkillAgentConfig,
    SkillExecutionBackend,
)
from easm_pipeline.core.llm_infra.clients import (
    RIGHT_CODE_API_KEY_ENV,
    RIGHT_CODE_DEFAULT_BASE_URL,
    RIGHT_CODE_DEFAULT_MODEL,
)
from easm_pipeline.core.logging import configure_logging


DEFAULT_AGENT_SERVICE_HOST = "0.0.0.0"
DEFAULT_AGENT_SERVICE_PORT = 30000
DEFAULT_CONTAINER_SKILLS_DIR = Path("/workspace/skills")
DEFAULT_CONTAINER_INPUT_DIR = Path("/workspace/input")
DEFAULT_CONTAINER_OUTPUT_DIR = Path("/workspace/output")
DEFAULT_CONTAINER_LOGS_DIR = Path("/workspace/logs")
DEFAULT_CONTAINER_WORK_DIR = Path("/workspace/work")


class AgentRunRequest(BaseModel):
    """JSON payload accepted by POST /run."""

    instruction: str = Field(..., min_length=1)
    reset: bool = False

    class Config:
        extra = Extra.forbid


class AgentServiceConfig(BaseModel):
    """Configuration for the in-container agent HTTP service."""

    host: str = DEFAULT_AGENT_SERVICE_HOST
    port: int = Field(DEFAULT_AGENT_SERVICE_PORT, ge=1, le=65535)
    skills_dir: Path = DEFAULT_CONTAINER_SKILLS_DIR
    input_dir: Path = DEFAULT_CONTAINER_INPUT_DIR
    output_dir: Path = DEFAULT_CONTAINER_OUTPUT_DIR
    logs_dir: Path = DEFAULT_CONTAINER_LOGS_DIR
    work_dir: Path = DEFAULT_CONTAINER_WORK_DIR
    model: str = RIGHT_CODE_DEFAULT_MODEL
    base_url: str = RIGHT_CODE_DEFAULT_BASE_URL
    api_key_env: str = RIGHT_CODE_API_KEY_ENV
    validate_skills: bool = True
    script_timeout_seconds: int = Field(120, ge=1)
    tool_timeout_seconds: float = Field(180.0, gt=0)

    class Config:
        extra = Extra.forbid
        arbitrary_types_allowed = True


AgentServiceConfig.update_forward_refs(Path=Path)


class AgentServiceState:
    """Holds the long-lived mounted agent and serializes access to it."""

    def __init__(self, config: AgentServiceConfig) -> None:
        self.config = config
        self.lock = threading.Lock()
        self.agent = MountedSkillAgent(
            SkillAgentConfig(
                skill_directories=(config.skills_dir,),
                model=config.model,
                base_url=config.base_url,
                api_key_env=config.api_key_env,
                instructions=CONTAINER_SKILL_AGENT_INSTRUCTIONS,
                validate_skills=config.validate_skills,
                execution_backend=SkillExecutionBackend.LOCAL,
                script_timeout_seconds=config.script_timeout_seconds,
                tool_timeout_seconds=config.tool_timeout_seconds,
                enable_workspace_tools=True,
            )
        )

    def run_instruction(self, request: AgentRunRequest) -> dict[str, str]:
        """Run one instruction through the mounted agent."""

        with self.lock:
            if request.reset:
                self.agent.reset()
            result = self.agent.run(request.instruction)
            return {"instruction": result.instruction, "output": result.output}

    def reset(self) -> dict[str, str]:
        """Reset conversation history."""

        with self.lock:
            self.agent.reset()
        return {"status": "reset"}

    def health(self) -> dict[str, Any]:
        """Return service and mount metadata."""

        return {
            "status": "ok",
            "model": self.config.model,
            "skills_dir": str(self.config.skills_dir),
            "input_dir": str(self.config.input_dir),
            "output_dir": str(self.config.output_dir),
            "logs_dir": str(self.config.logs_dir),
        }


def create_handler(state: AgentServiceState) -> type[BaseHTTPRequestHandler]:
    """Create an HTTP handler bound to one agent service state."""

    class AgentHandler(BaseHTTPRequestHandler):
        server_version = "EASMAgentService/1.0"

        def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP API name
            if self.path == "/health":
                self._write_json(HTTPStatus.OK, state.health())
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP API name
            if self.path == "/run":
                self._handle_run()
                return
            if self.path == "/reset":
                self._write_json(HTTPStatus.OK, state.reset())
                return
            self._write_json(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def log_message(self, format: str, *args: object) -> None:
            logger.info("HTTP {} - " + format, self.address_string(), *args)

        def _handle_run(self) -> None:
            try:
                payload = self._read_json()
                request = AgentRunRequest.parse_obj(payload)
                logger.info("Received agent instruction through HTTP API")
                result = state.run_instruction(request)
            except ValidationError as exc:
                self._write_json(HTTPStatus.BAD_REQUEST, {"error": exc.errors()})
                return
            except Exception as exc:  # pragma: no cover - exercised by integration tests
                logger.exception("Agent instruction failed")
                self._write_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return
            self._write_json(HTTPStatus.OK, result)

        def _read_json(self) -> Any:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0:
                return {}
            raw = self.rfile.read(content_length).decode("utf-8")
            return json.loads(raw)

        def _write_json(self, status: HTTPStatus, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return AgentHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the in-container EASM mounted skill agent HTTP service.")
    parser.add_argument("--host", default=os.getenv("EASM_AGENT_HOST", DEFAULT_AGENT_SERVICE_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("EASM_AGENT_PORT", str(DEFAULT_AGENT_SERVICE_PORT))))
    parser.add_argument("--skills-dir", default=os.getenv("EASM_AGENT_SKILLS_DIR", str(DEFAULT_CONTAINER_SKILLS_DIR)))
    parser.add_argument("--input-dir", default=os.getenv("EASM_AGENT_INPUT_DIR", str(DEFAULT_CONTAINER_INPUT_DIR)))
    parser.add_argument("--output-dir", default=os.getenv("EASM_AGENT_OUTPUT_DIR", str(DEFAULT_CONTAINER_OUTPUT_DIR)))
    parser.add_argument("--logs-dir", default=os.getenv("EASM_AGENT_LOGS_DIR", str(DEFAULT_CONTAINER_LOGS_DIR)))
    parser.add_argument("--work-dir", default=os.getenv("EASM_AGENT_WORK_DIR", str(DEFAULT_CONTAINER_WORK_DIR)))
    parser.add_argument("--model", default=os.getenv("EASM_AGENT_MODEL", RIGHT_CODE_DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.getenv("EASM_AGENT_BASE_URL", RIGHT_CODE_DEFAULT_BASE_URL))
    parser.add_argument("--no-validate-skills", action="store_true")
    parser.add_argument("--script-timeout", type=int, default=int(os.getenv("EASM_AGENT_SCRIPT_TIMEOUT", "120")))
    parser.add_argument("--tool-timeout", type=float, default=float(os.getenv("EASM_AGENT_TOOL_TIMEOUT", "180")))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging()

    config = AgentServiceConfig(
        host=args.host,
        port=args.port,
        skills_dir=Path(args.skills_dir),
        input_dir=Path(args.input_dir),
        output_dir=Path(args.output_dir),
        logs_dir=Path(args.logs_dir),
        work_dir=Path(args.work_dir),
        model=args.model,
        base_url=args.base_url,
        validate_skills=not args.no_validate_skills,
        script_timeout_seconds=args.script_timeout,
        tool_timeout_seconds=args.tool_timeout,
    )
    _prepare_container_workspace(config)
    _configure_file_logging(config.logs_dir)

    state = AgentServiceState(config)
    handler = create_handler(state)
    server = ThreadingHTTPServer((config.host, config.port), handler)
    logger.info("EASM agent service listening on {}:{}", config.host, config.port)
    server.serve_forever()
    return 0


def _prepare_container_workspace(config: AgentServiceConfig) -> None:
    if not config.skills_dir.exists():
        raise FileNotFoundError(f"skills directory does not exist: {config.skills_dir}")
    if not any(path.name == "SKILL.md" for path in config.skills_dir.glob("*/SKILL.md")):
        raise FileNotFoundError(f"skills directory contains no immediate SKILL.md entries: {config.skills_dir}")
    if not config.input_dir.exists():
        raise FileNotFoundError(f"input directory does not exist: {config.input_dir}")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    config.logs_dir.mkdir(parents=True, exist_ok=True)
    config.work_dir.mkdir(parents=True, exist_ok=True)


def _configure_file_logging(logs_dir: Path) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    logger.add(logs_dir / "agent_service.log", rotation="10 MB", retention=5, enqueue=True)


if __name__ == "__main__":
    raise SystemExit(main())
