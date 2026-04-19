"""Primary CLI for the EASM core control layer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from loguru import logger

from easm_pipeline.constants.path_config import AGENT_LOGS_DIR, AGENT_OUTPUT_DIR, DEFAULT_DOMAIN, domain_output_dir
from easm_pipeline.core.control_layer.agent_container import (
    DEFAULT_AGENT_CONTAINER_NAME,
    AgentContainerConfig,
    AgentContainerError,
    AgentContainerLauncher,
    AgentServiceClient,
)
from easm_pipeline.core.control_layer.agent_service import DEFAULT_AGENT_SERVICE_PORT
from easm_pipeline.core.execution_sandbox_layer import DEFAULT_OPENHANDS_RUNTIME_IMAGE
from easm_pipeline.core.llm_infra.clients import RIGHT_CODE_DEFAULT_BASE_URL, RIGHT_CODE_DEFAULT_MODEL
from easm_pipeline.core.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EASM core CLI for the containerized mounted skill agent.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start-agent", help="Start the Dockerized agent HTTP service.")
    start.add_argument("--input-dir", required=True, help="Host input directory mounted read-only as /workspace/input.")
    skill_group = start.add_mutually_exclusive_group(required=False)
    skill_group.add_argument("--skills-dir", help="Host skill root mounted read-only as /workspace/skills.")
    skill_group.add_argument("--domain", default=None, help="Use data/output_skills/<domain> as the skill root.")
    start.add_argument("--output-dir", default=AGENT_OUTPUT_DIR, help="Host output directory mounted as /workspace/output.")
    start.add_argument("--logs-dir", default=AGENT_LOGS_DIR, help="Host logs directory mounted as /workspace/logs.")
    start.add_argument("--project-root", default=Path.cwd(), help="Host project root mounted read-only as /app.")
    start.add_argument("--image", default=DEFAULT_OPENHANDS_RUNTIME_IMAGE, help="Docker image for the agent service.")
    start.add_argument("--container-name", default=DEFAULT_AGENT_CONTAINER_NAME)
    start.add_argument("--host", default="127.0.0.1", help="Host interface bound to the agent API port.")
    start.add_argument("--port", type=int, default=DEFAULT_AGENT_SERVICE_PORT, help="Host API port.")
    start.add_argument("--model", default=RIGHT_CODE_DEFAULT_MODEL)
    start.add_argument("--base-url", default=RIGHT_CODE_DEFAULT_BASE_URL)
    start.add_argument("--startup-timeout", type=int, default=180)
    start.add_argument("--script-timeout", type=int, default=120)
    start.add_argument("--tool-timeout", type=float, default=180.0)
    start.add_argument("--memory", default="4g")
    start.add_argument("--cpus", type=float, default=None)
    start.add_argument("--no-replace", action="store_true", help="Do not stop an existing container with the same name.")
    start.add_argument("--no-validate-skills", action="store_true")
    start.add_argument("--json", action="store_true")

    stop = subparsers.add_parser("stop-agent", help="Stop the Dockerized agent service.")
    stop.add_argument("--container-name", default=DEFAULT_AGENT_CONTAINER_NAME)
    stop.add_argument("--docker-cli", default="docker")

    status = subparsers.add_parser("status", help="Read /health from the running agent service.")
    status.add_argument("--host", default="127.0.0.1")
    status.add_argument("--port", type=int, default=DEFAULT_AGENT_SERVICE_PORT)

    run = subparsers.add_parser("run", help="Send one instruction to the running agent HTTP service.")
    run.add_argument("--instruction", required=True)
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=DEFAULT_AGENT_SERVICE_PORT)
    run.add_argument("--reset", action="store_true", help="Reset conversation history before this instruction.")
    run.add_argument("--json", action="store_true")

    reset = subparsers.add_parser("reset", help="Reset the running agent service conversation history.")
    reset.add_argument("--host", default="127.0.0.1")
    reset.add_argument("--port", type=int, default=DEFAULT_AGENT_SERVICE_PORT)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)

    try:
        if args.command == "start-agent":
            return _start_agent(args)
        if args.command == "stop-agent":
            return _stop_agent(args)
        if args.command == "status":
            return _status(args)
        if args.command == "run":
            return _run_instruction(args)
        if args.command == "reset":
            return _reset(args)
    except AgentContainerError as exc:
        logger.error("EASM core command failed: {}", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.command}")


def _start_agent(args: argparse.Namespace) -> int:
    skills_dir = Path(args.skills_dir) if args.skills_dir else domain_output_dir(args.domain or DEFAULT_DOMAIN)
    config = AgentContainerConfig(
        input_dir=Path(args.input_dir),
        skills_dir=skills_dir,
        output_dir=Path(args.output_dir),
        logs_dir=Path(args.logs_dir),
        project_root=Path(args.project_root),
        image=args.image,
        container_name=args.container_name,
        host=args.host,
        port=args.port,
        model=args.model,
        base_url=args.base_url,
        replace_existing=not args.no_replace,
        validate_skills=not args.no_validate_skills,
        startup_timeout_seconds=args.startup_timeout,
        script_timeout_seconds=args.script_timeout,
        tool_timeout_seconds=args.tool_timeout,
        memory_limit=args.memory,
        cpus=args.cpus,
    )
    container_id = AgentContainerLauncher(config).start()
    payload = {
        "container_id": container_id,
        "container_name": config.container_name,
        "api": config.base_http_url,
        "input_dir": str(config.input_dir.resolve()),
        "skills_dir": str(config.skills_dir.resolve()),
        "output_dir": str(config.output_dir.resolve()),
        "logs_dir": str(config.logs_dir.resolve()),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Started {payload['container_name']} at {payload['api']}")
        print(f"input:  {payload['input_dir']}")
        print(f"skills: {payload['skills_dir']}")
        print(f"output: {payload['output_dir']}")
        print(f"logs:   {payload['logs_dir']}")
    return 0


def _stop_agent(args: argparse.Namespace) -> int:
    config = AgentContainerConfig(
        input_dir=Path("."),
        skills_dir=domain_output_dir(DEFAULT_DOMAIN),
        docker_cli=args.docker_cli,
        container_name=args.container_name,
    )
    AgentContainerLauncher(config).stop(ignore_missing=True)
    print(f"Stopped {args.container_name}")
    return 0


def _status(args: argparse.Namespace) -> int:
    payload = AgentServiceClient(_base_url(args)).health()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _run_instruction(args: argparse.Namespace) -> int:
    payload = AgentServiceClient(_base_url(args)).run_instruction(args.instruction, reset=args.reset)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(payload.get("output", ""))
    return 0


def _reset(args: argparse.Namespace) -> int:
    payload = AgentServiceClient(_base_url(args)).reset()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _base_url(args: argparse.Namespace) -> str:
    return f"http://{args.host}:{args.port}"


if __name__ == "__main__":
    raise SystemExit(main())
