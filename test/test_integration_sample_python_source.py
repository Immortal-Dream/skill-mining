"""Clickable real-LLM integration test for mining data/sample_python_source.

Run this test directly from an IDE or with:

    python -m pytest test/test_integration_sample_python_source.py

It calls the Right Code API with model gpt-5.2 and writes generated skills to
a dynamic output directory. Set EASM_INTEGRATION_OUTPUT_DIR to choose a
persistent destination, or omit it to use pytest's temporary directory. Set
RIGHT_CODE_API_KEY before running it.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from easm_pipeline.core.llm_infra.clients import LLMClientConfig, StructuredLLMClient
from easm_pipeline.source_to_skills.main_pipeline import EASMPipeline, PipelineConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "data" / "sample_python_source"
OUTPUT_DIR = REPO_ROOT / "data" / "output_skills"


def test_mine_sample_python_source_to_output_skills(tmp_path: Path) -> None:
    """Mine data/sample_python_source into a caller-provided output directory."""

    assert SOURCE_DIR.is_dir(), f"Source directory does not exist: {SOURCE_DIR}"
    assert any(SOURCE_DIR.glob("*.py")), f"Expected at least one .py file under {SOURCE_DIR}"

    api_key = os.getenv("RIGHT_CODE_API_KEY")
    assert api_key, "RIGHT_CODE_API_KEY must be set; this test calls the real Right Code API"

    llm_client = StructuredLLMClient(
        LLMClientConfig.right_code(
            model="gpt-5.2",
            api_key=api_key,
            requests_per_minute=30,
            timeout_seconds=120,
        )
    )

    pipeline = EASMPipeline(
        PipelineConfig(
            source_dir=SOURCE_DIR,
            output_dir=OUTPUT_DIR,
            overwrite=True,
            prefer_tree_sitter=True,
            allow_parser_fallback=True,
            llm_client=llm_client,
        )
    )

    result = pipeline.run()

    assert result.capabilities, "Expected at least one mined capability"
    assert result.skill_dirs, "Expected at least one generated skill directory"
    assert (OUTPUT_DIR / "skills_registry.json").is_file()
    assert not (OUTPUT_DIR / "scripts").exists(), "scripts must be skill-local, not root-level"
    assert not (
            OUTPUT_DIR / "skills").exists(), "skills must be direct child folders, not nested under output_skills/skills"
    for skill_dir in result.skill_dirs:
        assert skill_dir.is_dir()
        assert skill_dir.parent == OUTPUT_DIR.resolve()
        skill_md = skill_dir / "SKILL.md"
        scripts_dir = skill_dir / "scripts"
        assert skill_md.is_file()
        script_paths = tuple(scripts_dir.glob("*.py"))
        assert script_paths
        assert not skill_dir.name.startswith("skill_")
        assert all(not script_path.name.startswith("skill_") for script_path in script_paths)
        assert not (skill_dir / "LICENSE.txt").exists()
        body = skill_md.read_text(encoding="utf-8")
        assert "\nlicense:" not in body
        assert "## Quick start" in body
        assert "## Scripts" in body
        assert "## Inputs" in body
        assert "## Output" in body
        assert "## When to use" in body
        assert "--help" in body
        assert "None." not in body
        assert "../../scripts/" not in body
        assert not re.search(r"^\d+\)", body, flags=re.MULTILINE)
        assert not any(ord(char) > 127 for char in body)
        print(f"generated skill: {skill_dir}")

    generated_files = [path for path in OUTPUT_DIR.rglob("*") if path.is_file()]
    assert generated_files, f"Expected generated files under {OUTPUT_DIR}"
