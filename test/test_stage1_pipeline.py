import tempfile
import subprocess
import sys
import unittest
from pathlib import Path

from easm_pipeline.core.llm_infra.schemas import CapabilitySlice, ExtractedNode, SkillPayload
from easm_pipeline.extraction.java_miner import JavaMiner
from easm_pipeline.extraction.python_miner import PythonMiner
from easm_pipeline.main_pipeline import EASMPipeline, PipelineConfig
from easm_pipeline.packaging.filesystem_builder import FilesystemBuilder
from easm_pipeline.packaging.validator import SkillValidationError, SkillValidator
from easm_pipeline.synthesis.code_bundler import CodeBundler
from easm_pipeline.synthesis.instruction_writer import SkillInstructions


class ExtractionTests(unittest.TestCase):
    def test_python_miner_extracts_function_metadata_with_ast_fallback(self) -> None:
        source = '''
import math

class Runner:
    @decorator
    def run(self, value: int = 1) -> int:
        """Run the value."""
        return math.floor(value)
'''
        nodes = PythonMiner(prefer_tree_sitter=True, allow_ast_fallback=True).mine_source(
            source,
            file_path="runner.py",
        )

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].name, "run")
        self.assertEqual(nodes[0].docstring, "Run the value.")
        self.assertEqual(nodes[0].scope_path, ("Runner",))
        self.assertIn("@decorator", nodes[0].annotations)
        self.assertIn("import math", nodes[0].imports)
        self.assertIn("value: int = 1", nodes[0].signature)

    def test_java_miner_extracts_javadoc_annotations_and_dependencies(self) -> None:
        source = """
package demo;

import com.example.UserDto;

class Controller {
    /** Fetch a user. */
    @GetMapping("/users/{id}")
    public UserDto getUser(String id) {
        UserDto dto = service.find(id);
        return dto;
    }
}
"""
        nodes = JavaMiner(prefer_tree_sitter=True, allow_regex_fallback=True).mine_source(
            source,
            file_path="Controller.java",
        )

        self.assertEqual(len(nodes), 1)
        self.assertEqual(nodes[0].name, "getUser")
        self.assertEqual(nodes[0].docstring, "Fetch a user.")
        self.assertIn('@GetMapping("/users/{id}")', nodes[0].annotations)
        self.assertIn("com.example.UserDto", nodes[0].dependencies)


class SynthesisPackagingTests(unittest.TestCase):
    def test_instruction_schema_rejects_non_chronological_steps(self) -> None:
        with self.assertRaises(ValueError):
            SkillInstructions(
                instructions="# Demo\n\n## Helper Scripts Available\n\n- none\n\n## Quick Start\n\n1. Inspect source.\n3. Execute script."
            )

    def test_instruction_schema_rejects_first_person(self) -> None:
        with self.assertRaises(ValueError):
            SkillInstructions(
                instructions="# Demo\n\n## Helper Scripts Available\n\n- none\n\n## Quick Start\n\n1. I inspect the source."
            )

    def test_instruction_schema_allows_io_technical_abbreviation(self) -> None:
        instructions = SkillInstructions(
            instructions=(
                "# Demo\n\n"
                "## Helper Scripts Available\n\n"
                "- none\n\n"
                "## Quick Start\n\n"
                "1. Prepare explicit I/O examples before running the helper."
            )
        )

        self.assertIn("I/O", instructions.instructions)

    def test_instruction_schema_accepts_skill_style_markdown(self) -> None:
        instructions = SkillInstructions(
            instructions=(
                "# Demo Skill\n\n"
                "## Helper Scripts Available\n\n"
                "- `scripts/run.py` - black-box helper.\n\n"
                "## Quick Start\n\n"
                "1. Confirm the task matches the skill description.\n"
                "2. Execute the relevant bundled script.\n\n"
                "## Running Bundled Scripts\n\n"
                "```bash\n"
                "python scripts/run.py --help\n"
                "python scripts/run.py --args-json '[1]'\n"
                "```\n"
            )
        )

        self.assertIn("## Quick Start", instructions.instructions)

    def test_code_bundler_quarantines_dangerous_python_code(self) -> None:
        node = ExtractedNode(
            node_id="demo",
            language="python",
            node_type="function",
            name="wipe",
            signature="def wipe(path)",
            raw_code="def wipe(path):\n    import shutil\n    shutil.rmtree(path)\n",
            file_path="danger.py",
            start_byte=0,
            end_byte=58,
            start_line=1,
            end_line=3,
        )
        capability = CapabilitySlice(slice_id="danger", title="Danger", nodes=(node,))

        bundle = CodeBundler().bundle(capability)

        self.assertEqual(bundle.scripts_dict, {})
        self.assertEqual(len(bundle.findings), 1)
        self.assertIn("quarantined-wipe.md", bundle.references_dict)

    def test_code_bundler_keeps_bound_methods_as_references(self) -> None:
        node = ExtractedNode(
            node_id="method-demo",
            language="python",
            node_type="function",
            name="build_title",
            signature="def build_title(self, project: str) -> str",
            raw_code="    def build_title(self, project: str) -> str:\n        return self.prefix + project\n",
            file_path="report.py",
            start_byte=0,
            end_byte=78,
            start_line=2,
            end_line=3,
            scope_path=("ReportBuilder",),
        )
        capability = CapabilitySlice(slice_id="report", title="Report", nodes=(node,))

        bundle = CodeBundler().bundle(capability)

        self.assertEqual(bundle.scripts_dict, {})
        self.assertIn("method-build-title.md", bundle.references_dict)

    def test_generated_python_script_supports_help_and_json_args(self) -> None:
        node = ExtractedNode(
            node_id="script-demo",
            language="python",
            node_type="function",
            name="add",
            signature="def add(left: int, right: int) -> int",
            raw_code="def add(left: int, right: int) -> int:\n    return left + right\n",
            file_path="math_tools.py",
            start_byte=0,
            end_byte=61,
            start_line=1,
            end_line=2,
        )
        capability = CapabilitySlice(slice_id="math", title="Math", nodes=(node,))
        bundle = CodeBundler().bundle(capability)

        with tempfile.TemporaryDirectory() as tmp:
            script_path = Path(tmp) / "add.py"
            script_path.write_text(bundle.scripts_dict["add.py"], encoding="utf-8")

            help_result = subprocess.run(
                [sys.executable, str(script_path), "--help"],
                check=False,
                capture_output=True,
                text=True,
            )
            run_result = subprocess.run(
                [sys.executable, str(script_path), "--args-json", "[2, 3]"],
                check=False,
                capture_output=True,
                text=True,
            )

        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--args-json", help_result.stdout)
        self.assertEqual(run_result.returncode, 0)
        self.assertEqual(run_result.stdout.strip(), "5")

    def test_validator_rejects_missing_reference_link(self) -> None:
        payload = SkillPayload(
            name="valid-skill",
            description="Use when testing validation. Do not use when references are missing.",
            instructions="# Valid Skill\n\n## Helper Scripts Available\n\n- none\n\n## Quick Start\n\n1. Read `references/missing.md`.",
        )

        with self.assertRaises(SkillValidationError):
            SkillValidator().validate(payload)

    def test_validator_ignores_sentence_punctuation_after_script_reference(self) -> None:
        payload = SkillPayload(
            name="valid-skill",
            description="Use when testing validation. Do not use when references are missing.",
            instructions=(
                "# Valid Skill\n\n"
                "## Helper Scripts Available\n\n"
                "- `scripts/run.py` - black-box helper.\n\n"
                "## Quick Start\n\n"
                "1. Execute `scripts/run.py`.\n\n"
                "## Running Bundled Scripts\n\n"
                "```bash\n"
                "python scripts/run.py --help\n"
                "python scripts/run.py --args-json '[]'\n"
                "```"
            ),
            scripts_dict={"run.py": "print('ok')\n"},
        )

        validated = SkillValidator().validate(payload)

        self.assertEqual(validated.name, "valid-skill")

    def test_validator_rejects_script_without_running_guidance(self) -> None:
        payload = SkillPayload(
            name="valid-skill",
            description="Use when testing validation. Do not use when script guidance is missing.",
            instructions=(
                "# Valid Skill\n\n"
                "## Helper Scripts Available\n\n"
                "- `scripts/run.py` - black-box helper.\n\n"
                "## Quick Start\n\n"
                "1. Execute `scripts/run.py` after review."
            ),
            scripts_dict={"run.py": "print('ok')\n"},
        )

        with self.assertRaises(SkillValidationError) as raised:
            SkillValidator().validate(payload)

        self.assertIn("## Running Bundled Scripts", str(raised.exception))

    def test_validator_rejects_parenthesized_quick_start_numbering(self) -> None:
        payload = SkillPayload(
            name="valid-skill",
            description="Use when testing validation. Do not use when numbering is invalid.",
            instructions=(
                "# Valid Skill\n\n"
                "## Helper Scripts Available\n\n"
                "- `scripts/run.py` - black-box helper.\n\n"
                "## Quick Start\n\n"
                "1) Execute `scripts/run.py` after review.\n\n"
                "## Running Bundled Scripts\n\n"
                "```bash\n"
                "python scripts/run.py --help\n"
                "python scripts/run.py --args-json '[]'\n"
                "```"
            ),
            scripts_dict={"run.py": "print('ok')\n"},
        )

        with self.assertRaises(SkillValidationError) as raised:
            SkillValidator().validate(payload)

        self.assertIn("must use '1.' numbering", str(raised.exception))

    def test_filesystem_builder_writes_valid_flat_skill(self) -> None:
        payload = SkillPayload(
            name="valid-skill",
            description="Use when testing filesystem writes. Do not use when no write is needed.",
            instructions=(
                "# Valid Skill\n\n"
                "## Helper Scripts Available\n\n"
                "- `scripts/run.py` - black-box helper.\n\n"
                "## Quick Start\n\n"
                "1. Execute `scripts/run.py` after review.\n\n"
                "## Running Bundled Scripts\n\n"
                "```bash\n"
                "python scripts/run.py --help\n"
                "python scripts/run.py --args-json '[]'\n"
                "```"
            ),
            scripts_dict={"run.py": "print('ok')\n"},
            references_dict={"notes.md": "Reference notes.\n"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            target = FilesystemBuilder().build(payload, Path(tmp))

            self.assertTrue((target / "SKILL.md").exists())
            self.assertFalse((target / "LICENSE.txt").exists())
            self.assertTrue((target / "scripts" / "run.py").exists())
            self.assertTrue((target / "references" / "notes.md").exists())


class PipelineTests(unittest.TestCase):
    def test_pipeline_builds_skill_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source_dir = root / "src"
            output_dir = root / "output_skills"
            source_dir.mkdir()
            (source_dir / "legacy.py").write_text(
                'def run(value: int) -> int:\n    """Return a value."""\n    return value\n',
                encoding="utf-8",
            )

            result = EASMPipeline(
                PipelineConfig(source_dir=source_dir, output_dir=output_dir)
            ).run()

            self.assertEqual(len(result.capabilities), 1)
            self.assertEqual(len(result.skill_dirs), 1)
            self.assertTrue((result.skill_dirs[0] / "SKILL.md").exists())
            self.assertTrue((result.skill_dirs[0] / "scripts" / "run.py").exists())


if __name__ == "__main__":
    unittest.main()
