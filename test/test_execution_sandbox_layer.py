import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from easm_pipeline.core.execution_sandbox_layer import (
    DEFAULT_OPENHANDS_RUNTIME_IMAGE,
    DockerSandboxConfig,
    DockerSandboxRunResult,
    DockerSkillScriptExecutor,
)


class DockerSandboxTests(unittest.TestCase):
    def test_default_workspace_is_temporary_legacy_sandbox(self) -> None:
        executor = DockerSkillScriptExecutor(DockerSandboxConfig(image="example/runtime:latest", keep_workspace=False))

        self.assertTrue(executor.workspace_root.exists())
        for child in ("input", "output", "work", "runs", "logs", "skills"):
            self.assertTrue((executor.workspace_root / child).is_dir())
        executor.cleanup()

    def test_builds_docker_command_for_python_skill_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "demo-skill"
            scripts = skill / "scripts"
            scripts.mkdir(parents=True)
            script = scripts / "run.py"
            script.write_text("print('ok')\n", encoding="utf-8")
            workspace = root / "workspace"

            executor = DockerSkillScriptExecutor(
                DockerSandboxConfig(
                    workspace_root=workspace,
                    image="example/runtime:latest",
                    network_enabled=False,
                    memory_limit="512m",
                    cpus=0.5,
                )
            )
            sandbox_skill_root = executor._prepare_skill_workspace(skill)
            command = executor.build_docker_command(
                sandbox_skill_root=sandbox_skill_root,
                relative_script=Path("scripts/run.py"),
                args={"input_json": {"value": 1}, "verbose": True},
            )

        self.assertEqual(command[0:2], ("docker", "run"))
        self.assertIn("--network", command)
        self.assertIn("none", command)
        self.assertIn("--memory", command)
        self.assertIn("512m", command)
        self.assertIn("example/runtime:latest", command)
        self.assertIn("python", command)
        self.assertIn("/workspace/skills/demo-skill/scripts/run.py", command)
        self.assertIn("--input-json", command)
        self.assertIn('{"value": 1}', command)
        self.assertIn("--verbose", command)

    def test_executor_output_file_arg_captures_stdout_without_passing_to_script(self) -> None:
        async def fake_run(command: tuple[str, ...]) -> DockerSandboxRunResult:
            captured["command"] = command
            return DockerSandboxRunResult(command=command, return_code=0, stdout="captured\n")

        captured: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "capture"
            scripts = skill / "scripts"
            scripts.mkdir(parents=True)
            script = scripts / "run.py"
            script.write_text("print('captured')\n", encoding="utf-8")

            executor = DockerSkillScriptExecutor(
                DockerSandboxConfig(workspace_root=root / "workspace", image="example/runtime:latest")
            )
            executor._ensure_docker_available = lambda: None  # type: ignore[method-assign]
            executor._run_docker_command = fake_run  # type: ignore[method-assign]

            output = asyncio.run(
                executor.run(
                    SimpleNamespace(uri=str(script), name="run.py"),
                    {"value": "abc", "output_file": "/workspace/output/result.txt"},
                )
            )
            host_output = executor.workspace_root / "output" / "result.txt"
            host_output_text = host_output.read_text(encoding="utf-8")

        self.assertEqual(output, "captured")
        self.assertEqual(host_output_text, "captured\n")
        self.assertNotIn("--output-file", captured["command"])
        self.assertIn("--value", captured["command"])

    def test_run_copies_skill_and_returns_stdout_from_docker_result(self) -> None:
        async def fake_run(command: tuple[str, ...]) -> DockerSandboxRunResult:
            captured["command"] = command
            return DockerSandboxRunResult(command=command, return_code=0, stdout="42\n")

        captured: dict[str, object] = {}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill = root / "calc"
            scripts = skill / "scripts"
            scripts.mkdir(parents=True)
            script = scripts / "calculate.py"
            script.write_text("print(42)\n", encoding="utf-8")

            executor = DockerSkillScriptExecutor(
                DockerSandboxConfig(workspace_root=root / "workspace", image=DEFAULT_OPENHANDS_RUNTIME_IMAGE)
            )
            executor._ensure_docker_available = lambda: None  # type: ignore[method-assign]
            executor._run_docker_command = fake_run  # type: ignore[method-assign]

            output = asyncio.run(executor.run(SimpleNamespace(uri=str(script), name="calculate.py"), {"value": 1}))

            copied_script = executor.workspace_root / "skills" / "calc" / "scripts" / "calculate.py"
            copied_script_exists = copied_script.exists()

        self.assertEqual(output, "42")
        self.assertTrue(copied_script_exists)
        self.assertIn("/workspace/skills/calc/scripts/calculate.py", captured["command"])

    def test_formats_nonzero_exit_with_stderr(self) -> None:
        result = DockerSandboxRunResult(
            command=("docker", "run"),
            return_code=2,
            stdout="partial\n",
            stderr="bad input\n",
        )

        formatted = result.format_for_agent()

        self.assertIn("exit code 2", formatted)
        self.assertIn("stdout:\npartial", formatted)
        self.assertIn("stderr:\nbad input", formatted)


if __name__ == "__main__":
    unittest.main()
