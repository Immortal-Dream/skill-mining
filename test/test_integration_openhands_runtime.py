"""Real Docker/OpenHands runtime integration tests for mounted Agent Skills.

These tests intentionally exercise the same path a user would run:
Right Code LLM -> pydantic-ai-skills -> run_skill_script -> Docker sandbox.
They are skipped when Docker, the OpenHands runtime image, or RIGHT_CODE_API_KEY
is unavailable, so the normal unit suite stays fast and deterministic.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from easm_pipeline.constants.path_config import (
    AGENT_OUTPUT_DIR,
    DOMAIN_SAMPLE_PYTHON_SOURCE,
    domain_output_dir,
    domain_source_dir,
)
from easm_pipeline.core.control_layer.agent_container import (
    AgentContainerConfig,
    AgentContainerLauncher,
    AgentServiceClient,
)
from easm_pipeline.core.execution_sandbox_layer import DEFAULT_OPENHANDS_RUNTIME_IMAGE, DockerSandboxConfig
from easm_pipeline.core.execution_sandbox_layer.docker_sandbox import DockerSkillScriptExecutor


SKILLS_DIR = domain_output_dir(DOMAIN_SAMPLE_PYTHON_SOURCE)
INPUT_DIR = domain_source_dir(DOMAIN_SAMPLE_PYTHON_SOURCE)
IMAGE = os.getenv("EASM_SANDBOX_IMAGE", DEFAULT_OPENHANDS_RUNTIME_IMAGE)


def _docker_image_available(image: str) -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "image", "inspect", image],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _sample_skills_available() -> bool:
    return (SKILLS_DIR / "compute-gc-content" / "SKILL.md").exists() and (
        SKILLS_DIR / "reverse-complement" / "scripts" / "reverse_complement.py"
    ).exists()


@unittest.skipUnless(_docker_image_available(IMAGE), f"Docker image is not available locally: {IMAGE}")
@unittest.skipUnless(_sample_skills_available(), f"Sample skills are missing: {SKILLS_DIR}")
class OpenHandsRuntimeScriptTests(unittest.TestCase):
    def test_openhands_runtime_executes_existing_skill_script_directly(self) -> None:
        script = SKILLS_DIR / "reverse-complement" / "scripts" / "reverse_complement.py"
        executor = DockerSkillScriptExecutor(
            DockerSandboxConfig(
                image=IMAGE,
                timeout_seconds=120,
                network_enabled=False,
                memory_limit="1g",
                cpus=1.0,
                keep_workspace=False,
            )
        )

        try:
            output = asyncio.run(
                executor.run(
                    SimpleNamespace(uri=str(script), name="reverse_complement.py"),
                    {"sequence": "ATGC", "output": "text"},
                )
            )
        finally:
            executor.cleanup()

        self.assertEqual(output.strip(), "GCAT")


@unittest.skipUnless(os.getenv("RIGHT_CODE_API_KEY"), "RIGHT_CODE_API_KEY is required for real agent integration")
@unittest.skipUnless(_docker_image_available(IMAGE), f"Docker image is not available locally: {IMAGE}")
@unittest.skipUnless(_sample_skills_available(), f"Sample skills are missing: {SKILLS_DIR}")
class OpenHandsRuntimeAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = AgentContainerConfig(
            input_dir=INPUT_DIR,
            skills_dir=SKILLS_DIR,
            image=IMAGE,
            container_name="easm-agent-service",
            port=30000,
            startup_timeout_seconds=600,
            script_timeout_seconds=120,
            tool_timeout_seconds=180,
        )
        cls.launcher = AgentContainerLauncher(cls.config)
        cls.launcher.start()
        cls.client = AgentServiceClient(cls.config.base_http_url, timeout_seconds=240)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.launcher.stop(ignore_missing=True)

    def test_agent_uses_openhands_runtime_to_execute_gc_content_skill(self) -> None:
        result = self.client.run_instruction(
            "Use the mounted skills to compute GC content for the DNA sequence ATGCATGC. "
            "Return only the script stdout value.",
            reset=True,
        )

        self.assertIn("0.5", result["output"])

    def test_agent_uses_openhands_runtime_to_execute_reverse_complement_skill(self) -> None:
        result = self.client.run_instruction(
            "Use the mounted skills to reverse-complement the DNA sequence ATGC. "
            "Return only the script stdout value.",
            reset=True,
        )

        self.assertIn("GCAT", result["output"])

    def test_agent_can_write_durable_file_to_host_managed_output_directory(self) -> None:
        output_name = f"agent_write_probe_{uuid.uuid4().hex}.txt"
        output_path = AGENT_OUTPUT_DIR / output_name

        result = self.client.run_instruction(
            "Use the mounted reverse-complement skill for the DNA sequence ATGC. "
            f"Ask the script to write its text output to /workspace/output/{output_name}. "
            "Return only the final file path.",
            reset=True,
        )

        self.assertTrue(output_path.exists(), result["output"])
        self.assertEqual(output_path.read_text(encoding="utf-8").strip(), "GCAT")


if __name__ == "__main__":
    unittest.main()
