import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from easm_pipeline import skill_mining
from easm_pipeline.provenance_trace import capture_provenance_report


class _FakeRecorder:
    def __init__(self, session_id: str):
        self._session_id = session_id

    def report(self) -> dict:
        return {
            "session_metadata": {"session_id": self._session_id},
            "calls": [{"call_id": "call_1", "tool_name": "demo.echo", "arg_bindings": [], "metadata": {}}],
            "values": [],
            "edges": [],
            "unresolved_origins": [],
        }


class _FakeRuntimeModule:
    @staticmethod
    def create_instrumented_apis(
        apis,
        *,
        session_id: str,
        task_id=None,
        experiment_name=None,
        agent_name=None,
        process_index=None,
        extra=None,
    ):
        del task_id, experiment_name, agent_name, process_index, extra
        return apis, _FakeRecorder(session_id)


class ProvenanceTraceCaptureTests(unittest.TestCase):
    def test_capture_provenance_report_runs_workflow_with_loaded_specs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            module_path = root / "demo_trace_module.py"
            module_path.write_text(
                "class DemoApp:\n"
                "    def __init__(self):\n"
                "        self.calls = []\n\n"
                "    def echo(self, query=None):\n"
                "        self.calls.append(query)\n"
                "        return {'query': query}\n\n"
                "class DemoApis:\n"
                "    def __init__(self):\n"
                "        self.demo = DemoApp()\n\n"
                "def create_apis():\n"
                "    return DemoApis()\n\n"
                "def run_workflow(apis, query):\n"
                "    apis.demo.echo(query=query)\n",
                encoding="utf-8",
            )
            with patch("easm_pipeline.provenance_trace._load_appworld_provenance_runtime", return_value=_FakeRuntimeModule()):
                with patch("sys.path", [str(root), *list(__import__('sys').path)]):
                    report = capture_provenance_report(
                        apis_factory_spec="demo_trace_module:create_apis",
                        workflow_spec="demo_trace_module:run_workflow",
                        workflow_input={"query": "hello"},
                        session_id="trace-session",
                    )

        self.assertEqual(report["session_metadata"]["session_id"], "trace-session")
        self.assertEqual(report["calls"][0]["tool_name"], "demo.echo")

    def test_skill_mining_main_accepts_trace_capture_without_report_paths(self) -> None:
        synthetic_report = {
            "session_metadata": {"session_id": "trace-session"},
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

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_dir = root / "output_skills"

            def _write_report(*, output_path: Path, **kwargs):
                del kwargs
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(json.dumps(synthetic_report), encoding="utf-8")
                return output_path

            with patch("easm_pipeline.skill_mining.capture_provenance_report_to_path", side_effect=_write_report):
                exit_code = skill_mining.main(
                    [
                        "--trace-apis-factory",
                        "demo_trace_module:create_apis",
                        "--trace-workflow",
                        "demo_trace_module:run_workflow",
                        "--output-dir",
                        str(output_dir),
                        "--overwrite",
                        "--min-support",
                        "1",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "skills_registry.json").exists())


if __name__ == "__main__":
    unittest.main()
