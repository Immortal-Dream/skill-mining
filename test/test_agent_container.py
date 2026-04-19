import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easm_pipeline.core.control_layer.agent_container import AgentContainerConfig, AgentContainerLauncher


def _write_minimal_skill(root: Path) -> None:
    skill = root / "demo-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: demo-skill\n"
        "description: Use when testing container launcher skills.\n"
        "---\n\n"
        "# Demo Skill\n",
        encoding="utf-8",
    )


class AgentContainerCommandTests(unittest.TestCase):
    def test_docker_run_mounts_input_and_skills_read_only_with_output_logs_writable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict("os.environ", {"RIGHT_CODE_API_KEY": "test-key"}):
            root = Path(tmp)
            input_dir = root / "input"
            skills_dir = root / "skills"
            output_dir = root / "output"
            logs_dir = root / "logs"
            project_root = root / "project"
            input_dir.mkdir()
            skills_dir.mkdir()
            project_root.mkdir()
            (project_root / "easm_pipeline").mkdir()
            _write_minimal_skill(skills_dir)

            config = AgentContainerConfig(
                input_dir=input_dir,
                skills_dir=skills_dir,
                output_dir=output_dir,
                logs_dir=logs_dir,
                project_root=project_root,
                image="example/runtime:latest",
                container_name="easm-agent-test",
                port=30000,
            )

            command = AgentContainerLauncher(config).build_docker_run_command()

        self.assertEqual(command[0:3], ["docker", "run", "-d"])
        self.assertIn("127.0.0.1:30000:30000", command)
        self.assertIn(f"{input_dir.resolve()}:/workspace/input:ro", command)
        self.assertIn(f"{skills_dir.resolve()}:/workspace/skills:ro", command)
        self.assertIn(f"{output_dir.resolve()}:/workspace/output:rw", command)
        self.assertIn(f"{logs_dir.resolve()}:/workspace/logs:rw", command)
        self.assertIn("RIGHT_CODE_API_KEY", command)
        self.assertIn("python", command)
        self.assertIn("easm_pipeline.core.control_layer.agent_service_bootstrap", command)


if __name__ == "__main__":
    unittest.main()
