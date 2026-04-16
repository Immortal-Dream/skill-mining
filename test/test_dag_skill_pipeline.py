import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from easm_pipeline.dag_to_skills.main_pipeline import DAGSkillPipeline as LegacyDAGSkillPipeline
from easm_pipeline.skill_mining import DAGSkillPipeline, DAGSkillPipelineConfig
from easm_pipeline.source_to_skills.synthesis.skill_doc_generator import SkillDoc


class DAGSkillPipelineCompatibilityTests(unittest.TestCase):
    def test_legacy_import_path_reexports_skill_mining_pipeline(self) -> None:
        self.assertIs(LegacyDAGSkillPipeline, DAGSkillPipeline)


class DAGSkillPipelineTests(unittest.TestCase):
    def _write_report(self, target: Path) -> Path:
        report = {
            "session_metadata": {"session_id": target.stem},
            "values": [
                {
                    "value_id": "v_email",
                    "preview": "a@example.com",
                    "structural_hash": "email-hash",
                    "origin": {"producer_call_id": "c1", "value_path": ["email"]},
                },
                {
                    "value_id": "v_password",
                    "preview": "pw",
                    "structural_hash": "password-hash",
                    "origin": {"producer_call_id": "c2", "value_path": ["venmo"]},
                },
                {
                    "value_id": "v_token",
                    "preview": "a@example.com:pw",
                    "structural_hash": "token-hash",
                    "origin": {"producer_call_id": "c3", "value_path": ["access_token"]},
                },
            ],
            "calls": [
                {"call_id": "c1", "tool_name": "supervisor.show_profile", "arg_bindings": [], "metadata": {}},
                {"call_id": "c2", "tool_name": "supervisor.show_passwords", "arg_bindings": [], "metadata": {}},
                {
                    "call_id": "c3",
                    "tool_name": "venmo.login",
                    "arg_bindings": [
                        {"arg_path": "kwargs.username", "value_id": "v_email"},
                        {"arg_path": "kwargs.password", "value_id": "v_password"},
                    ],
                    "metadata": {},
                },
                {
                    "call_id": "c4",
                    "tool_name": "venmo.search_friends",
                    "arg_bindings": [
                        {"arg_path": "kwargs.access_token", "value_id": "v_token"},
                        {"arg_path": "kwargs.query", "literal_value": ""},
                        {"arg_path": "kwargs.page_index", "literal_value": 0},
                        {"arg_path": "kwargs.page_limit", "literal_value": 20},
                    ],
                    "metadata": {},
                },
            ],
            "edges": [
                {"source_value_id": "v_email", "target_call_id": "c3", "arg_path": "kwargs.username"},
                {"source_value_id": "v_password", "target_call_id": "c3", "arg_path": "kwargs.password"},
                {"source_value_id": "v_token", "target_call_id": "c4", "arg_path": "kwargs.access_token"},
            ],
        }
        target.write_text(json.dumps(report), encoding="utf-8")
        return target

    def test_pipeline_builds_skill_from_repeated_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_a = self._write_report(root / "report_a.json")
            report_b = self._write_report(root / "report_b.json")
            output_dir = root / "output_skills"

            result = DAGSkillPipeline(
                DAGSkillPipelineConfig(
                    report_paths=(report_a, report_b),
                    output_dir=output_dir,
                    overwrite=True,
                    max_depth=2,
                    min_support=2,
                )
            ).run()

            self.assertGreaterEqual(len(result.patterns), 2)
            self.assertGreaterEqual(len(result.skill_dirs), 1)
            skill_dir = next(path for path in result.skill_dirs if "venmo-search-friends" in path.name)
            self.assertTrue((skill_dir / "SKILL.md").exists())
            self.assertTrue((skill_dir / "scripts").exists())
            self.assertTrue((skill_dir / "references" / "meta_tool.py").exists())
            self.assertTrue((output_dir / "skills_registry.json").exists())

            skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("--apis-factory", skill_md)
            self.assertIn("## Quick start", skill_md)
            self.assertIn("venmo.search_friends", skill_md)

    def test_pipeline_can_reuse_shared_skill_doc_generator_with_llm_client(self) -> None:
        class FakeLLMClient:
            def generate(self, *, prompt, response_schema, system_prompt=None):
                del prompt, system_prompt
                if response_schema is not SkillDoc:
                    raise AssertionError(f"unexpected schema: {response_schema}")
                return SkillDoc(
                    instructions=(
                        "# Venmo Search Friends\n\n"
                        "## Quick start\n\n"
                        "1. Run `--help` first.\n"
                        "2. Provide --apis-factory and the boundary flags.\n"
                        "3. Read stdout for results and stderr on failure.\n\n"
                        "## Scripts\n\n"
                        "- `scripts/venmo_search_friends_1.py` - Execute the mined DAG workflow ending in venmo search_friends.\n\n"
                        "## Inputs\n\n"
                        "- `--apis-factory` (required): Factory import path.\n"
                        "- `--query` (optional, default: \"\"): Search query.\n"
                        "- `--page-index` (optional, default: 0): Page index.\n"
                        "- `--page-limit` (optional, default: 20): Page limit.\n"
                        "- `--output` (optional, default: json): Output format.\n\n"
                        "## Output\n\n"
                        "stdout contains the result payload and stderr contains errors.\n\n"
                        "## When to use\n\n"
                        "Use when: a mined provenance workflow should be replayed as a skill.\n\n"
                        "Do not use when: the caller cannot provide the expected API factory.\n"
                    )
                )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_a = self._write_report(root / "report_a.json")
            report_b = self._write_report(root / "report_b.json")
            output_dir = root / "output_skills"

            result = DAGSkillPipeline(
                DAGSkillPipelineConfig(
                    report_paths=(report_a, report_b),
                    output_dir=output_dir,
                    overwrite=True,
                    max_depth=2,
                    min_support=2,
                    llm_client=FakeLLMClient(),
                )
            ).run()

            skill_dir = next(path for path in result.skill_dirs if "venmo-search-friends" in path.name)
            skill_md = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
            self.assertIn("a mined provenance workflow should be replayed as a skill", skill_md)

    def test_generated_script_executes_with_factory_module(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_a = self._write_report(root / "report_a.json")
            report_b = self._write_report(root / "report_b.json")
            output_dir = root / "output_skills"
            result = DAGSkillPipeline(
                DAGSkillPipelineConfig(
                    report_paths=(report_a, report_b),
                    output_dir=output_dir,
                    overwrite=True,
                    max_depth=2,
                    min_support=2,
                )
            ).run()
            skill_dir = next(path for path in result.skill_dirs if "venmo-search-friends" in path.name)
            script_path = next((skill_dir / "scripts").glob("*.py"))
            factory_module = root / "demo_factory.py"
            factory_module.write_text(
                "class Supervisor:\n"
                "    @staticmethod\n"
                "    def show_profile():\n"
                "        return {'email': 'user@example.com'}\n\n"
                "    @staticmethod\n"
                "    def show_passwords():\n"
                "        return {'venmo': 'pw'}\n\n"
                "class Venmo:\n"
                "    @staticmethod\n"
                "    def login(username, password):\n"
                "        return {'access_token': f'{username}:{password}'}\n\n"
                "    @staticmethod\n"
                "    def search_friends(access_token, query, page_index, page_limit):\n"
                "        return {'access_token': access_token, 'query': query, 'page_index': page_index, 'page_limit': page_limit}\n\n"
                "class APIs:\n"
                "    supervisor = Supervisor()\n"
                "    venmo = Venmo()\n\n"
                "def create_apis():\n"
                "    return APIs()\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["PYTHONPATH"] = str(root)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script_path),
                    "--apis-factory",
                    "demo_factory:create_apis",
                    "--query",
                    "friends",
                    "--page-index",
                    "1",
                    "--page-limit",
                    "2",
                    "--output",
                    "json",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["access_token"], "user@example.com:pw")
            self.assertEqual(payload["query"], "friends")
            self.assertEqual(payload["page_index"], 1)
            self.assertEqual(payload["page_limit"], 2)


if __name__ == "__main__":
    unittest.main()
