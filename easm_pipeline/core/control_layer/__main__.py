"""Command-line entry point for the mounted skill agent control layer."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from loguru import logger

from easm_pipeline.constants.path_config import AGENT_FILE_SYSTEM_DIR, DEFAULT_DOMAIN, SUPPORTED_DOMAINS, domain_output_dir
from easm_pipeline.core.llm_infra.clients import RIGHT_CODE_DEFAULT_BASE_URL, RIGHT_CODE_DEFAULT_MODEL
from easm_pipeline.core.execution_sandbox_layer import DEFAULT_OPENHANDS_RUNTIME_IMAGE, SANDBOX_IMAGE_ENV

from .skill_agent import MountedSkillAgent, SkillAgentConfig, SkillAgentError, SkillExecutionBackend


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Start a Pydantic AI agent with filesystem Agent Skills mounted.",
    )
    source_group = parser.add_mutually_exclusive_group()
    source_group.add_argument(
        "--domain",
        default=None,
        choices=SUPPORTED_DOMAINS,
        help="Load skills from data/output_skills/<domain>.",
    )
    source_group.add_argument(
        "--skills-dir",
        action="append",
        default=None,
        help="Skill root to mount. Can be repeated. Each root contains skill folders with SKILL.md.",
    )
    parser.add_argument("--instruction", help="Run one instruction and exit. Omit for interactive mode.")
    parser.add_argument("--model", default=RIGHT_CODE_DEFAULT_MODEL, help="Right Code/OpenAI-compatible model name.")
    parser.add_argument("--base-url", default=RIGHT_CODE_DEFAULT_BASE_URL, help="OpenAI-compatible API base URL.")
    parser.add_argument("--no-validate-skills", action="store_true", help="Disable pydantic-ai-skills validation.")
    parser.add_argument("--auto-reload", action="store_true", help="Reload skills when files change if supported.")
    parser.add_argument(
        "--execution-backend",
        choices=[backend.value for backend in SkillExecutionBackend],
        default=SkillExecutionBackend.LOCAL.value,
        help="Backend used when skills call run_skill_script.",
    )
    parser.add_argument(
        "--sandbox-image",
        default=os.getenv(SANDBOX_IMAGE_ENV, DEFAULT_OPENHANDS_RUNTIME_IMAGE),
        help="Docker image used when --execution-backend docker.",
    )
    parser.add_argument(
        "--sandbox-workspace",
        default=AGENT_FILE_SYSTEM_DIR,
        help="Host workspace mounted into Docker as /workspace.",
    )
    parser.add_argument(
        "--sandbox-network",
        action="store_true",
        help="Allow network access inside Docker sandbox. Disabled by default.",
    )
    parser.add_argument(
        "--sandbox-keep-workspace",
        action="store_true",
        default=True,
        help="Keep the sandbox workspace after the process exits.",
    )
    parser.add_argument("--sandbox-memory", default="1g", help="Docker memory limit for script execution.")
    parser.add_argument("--sandbox-cpus", type=float, default=1.0, help="Docker CPU limit for script execution.")
    parser.add_argument("--script-timeout", type=int, default=120, help="Timeout in seconds for each script run.")
    parser.add_argument(
        "--tool-timeout",
        type=float,
        default=None,
        help="Pydantic AI tool timeout. Defaults to script timeout plus 10 seconds.",
    )
    parser.add_argument("--json", action="store_true", help="Print single-instruction output as JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    skill_directories = _resolve_skill_directories(args.domain, args.skills_dir)
    config = SkillAgentConfig(
        skill_directories=skill_directories,
        model=args.model,
        base_url=args.base_url,
        validate_skills=not args.no_validate_skills,
        auto_reload=args.auto_reload,
        execution_backend=SkillExecutionBackend(args.execution_backend),
        sandbox_image=args.sandbox_image,
        sandbox_workspace_root=args.sandbox_workspace,
        sandbox_network_enabled=args.sandbox_network,
        sandbox_keep_workspace=args.sandbox_keep_workspace,
        sandbox_memory_limit=args.sandbox_memory,
        sandbox_cpus=args.sandbox_cpus,
        script_timeout_seconds=args.script_timeout,
        tool_timeout_seconds=args.tool_timeout or float(args.script_timeout + 10),
    )
    session = MountedSkillAgent(config)

    try:
        if args.instruction:
            result = session.run(args.instruction)
            if args.json:
                print(result.json(ensure_ascii=False, indent=2))
            else:
                print(result.output)
            return 0
        return asyncio.run(_interactive_loop(session))
    except SkillAgentError as exc:
        logger.error("Skill agent failed: {}", exc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _resolve_skill_directories(domain: str | None, skills_dir: list[str] | None) -> tuple[Path, ...]:
    if skills_dir:
        return tuple(Path(item) for item in skills_dir)
    selected_domain = domain or DEFAULT_DOMAIN
    return (domain_output_dir(selected_domain),)


async def _interactive_loop(session: MountedSkillAgent) -> int:
    print("EASM skill agent ready. Type /exit to quit, /reset to clear conversation history.")
    while True:
        try:
            instruction = input("> ").strip()
        except EOFError:
            print()
            return 0

        if not instruction:
            continue
        if instruction in {"/exit", "/quit"}:
            return 0
        if instruction == "/reset":
            session.reset()
            print("History reset.")
            continue

        try:
            result = await session.arun(instruction)
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue
        print(result.output)


if __name__ == "__main__":
    raise SystemExit(main())
