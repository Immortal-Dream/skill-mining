"""Clickable real-LLM integration test for mining data/sample_python_source.

Run this test directly from an IDE or with:

    python -m pytest test/test_integration_sample_python_source.py

It calls the Right Code API with model gpt-5.2 and writes generated skills to
the repository-level output_skills directory. Set RIGHT_CODE_API_KEY before
running it.
"""

from __future__ import annotations

import os
from pathlib import Path

from easm_pipeline.core.llm_infra.clients import LLMClientConfig, StructuredLLMClient
from easm_pipeline.main_pipeline import EASMPipeline, PipelineConfig

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "data" / "sample_python_source"
OUTPUT_DIR = REPO_ROOT / "data" / "output_skills"


def test_mine_sample_python_source_to_output_skills() -> None:
    """Mine data/sample_python_source into output_skills using the real Right Code LLM."""

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
    for skill_dir in result.skill_dirs:
        assert skill_dir.is_dir()
        assert skill_dir.parent == OUTPUT_DIR
        skill_md = skill_dir / "SKILL.md"
        assert skill_md.is_file()
        assert not (skill_dir / "LICENSE.txt").exists()
        body = skill_md.read_text(encoding="utf-8")
        assert "\nlicense:" not in body
        assert "## Helper Scripts Available" in body
        assert "## Quick Start" in body
        assert "## Running Bundled Scripts" in body
        assert "--help" in body
        assert "--args-json" in body or "--kwargs-json" in body
        assert not any(ord(char) > 127 for char in body)
        print(f"generated skill: {skill_dir}")

    generated_files = [path for path in OUTPUT_DIR.rglob("*") if path.is_file()]
    assert generated_files, f"Expected generated files under {OUTPUT_DIR}"
