import asyncio
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from easm_pipeline.constants.path_config import DOMAIN_SAMPLE_PYTHON_SOURCE, domain_output_dir
from easm_pipeline.core.control_layer import (
    MountedSkillAgent,
    SkillAgentConfig,
    SkillAgentFactory,
    SkillExecutionBackend,
)


def _write_minimal_skill(root: Path, name: str = "demo-skill") -> None:
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "description: Use when testing mounted skills.\n"
        "---\n\n"
        "# Demo Skill\n",
        encoding="utf-8",
    )


class ControlLayerConfigTests(unittest.TestCase):
    def test_domain_config_mounts_domain_output_directory(self) -> None:
        config = SkillAgentConfig.from_domain(DOMAIN_SAMPLE_PYTHON_SOURCE)

        self.assertEqual(config.skill_directories, (domain_output_dir(DOMAIN_SAMPLE_PYTHON_SOURCE),))
        self.assertIsNone(config.sandbox_workspace_root)

class ControlLayerFactoryTests(unittest.TestCase):
    def test_factory_creates_pydantic_ai_agent_with_right_code_provider_and_skills(self) -> None:
        captured: dict[str, object] = {}

        class FakeProvider:
            def __init__(self, **kwargs: object) -> None:
                captured["provider"] = kwargs

        class FakeModel:
            def __init__(self, model_name: str, *, provider: object) -> None:
                captured["model_name"] = model_name
                captured["model_provider"] = provider

        class FakeSkillsCapability:
            def __init__(self, **kwargs: object) -> None:
                captured["skills"] = kwargs

        class FakeLocalSkillScriptExecutor:
            def __init__(self, **kwargs: object) -> None:
                captured["executor"] = kwargs

            def _extract_shebang_command(self, script_path: Path) -> list[str] | None:
                return None

        class FakeSkillsDirectory:
            def __init__(self, **kwargs: object) -> None:
                captured.setdefault("directories", []).append(kwargs)

        class FakeAgent:
            def __init__(self, **kwargs: object) -> None:
                captured["agent"] = kwargs

        pydantic_ai = types.ModuleType("pydantic_ai")
        pydantic_ai.Agent = FakeAgent
        pydantic_ai_skills = types.ModuleType("pydantic_ai_skills")
        pydantic_ai_skills.SkillsCapability = FakeSkillsCapability
        pydantic_ai_skills.LocalSkillScriptExecutor = FakeLocalSkillScriptExecutor
        pydantic_ai_skills.SkillsDirectory = FakeSkillsDirectory
        models_openai = types.ModuleType("pydantic_ai.models.openai")
        models_openai.OpenAIChatModel = FakeModel
        providers_openai = types.ModuleType("pydantic_ai.providers.openai")
        providers_openai.OpenAIProvider = FakeProvider

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            sys.modules,
            {
                "pydantic_ai": pydantic_ai,
                "pydantic_ai_skills": pydantic_ai_skills,
                "pydantic_ai.models.openai": models_openai,
                "pydantic_ai.providers.openai": providers_openai,
            },
        ), patch.dict(os.environ, {"RIGHT_CODE_API_KEY": "test-key"}):
            root = Path(tmp)
            _write_minimal_skill(root)
            config = SkillAgentConfig(skill_directories=(root,), model="gpt-5.2")

            agent = SkillAgentFactory().create_agent(config)

        self.assertIsInstance(agent, FakeAgent)
        self.assertEqual(captured["provider"], {"base_url": "https://www.right.codes/codex/v1", "api_key": "test-key"})
        self.assertEqual(captured["model_name"], "gpt-5.2")
        self.assertEqual(captured["executor"]["python_executable"], sys.executable)
        self.assertEqual(captured["executor"]["timeout"], 120)
        self.assertEqual(captured["directories"][0]["path"], root.resolve())
        self.assertEqual(captured["directories"][0]["validate"], True)
        self.assertEqual(captured["skills"]["directories"][0].__class__, FakeSkillsDirectory)
        self.assertEqual(captured["skills"]["validate"], True)
        self.assertEqual(captured["agent"]["capabilities"][0].__class__, FakeSkillsCapability)

    def test_factory_uses_docker_script_executor_when_configured(self) -> None:
        captured: dict[str, object] = {}

        class FakeProvider:
            def __init__(self, **kwargs: object) -> None:
                pass

        class FakeModel:
            def __init__(self, model_name: str, *, provider: object) -> None:
                pass

        class FakeSkillsCapability:
            def __init__(self, **kwargs: object) -> None:
                pass

        class FakeSkillsDirectory:
            def __init__(self, **kwargs: object) -> None:
                captured["script_executor"] = kwargs["script_executor"]

        class FakeAgent:
            def __init__(self, **kwargs: object) -> None:
                pass

        pydantic_ai = types.ModuleType("pydantic_ai")
        pydantic_ai.Agent = FakeAgent
        pydantic_ai_skills = types.ModuleType("pydantic_ai_skills")
        pydantic_ai_skills.SkillsCapability = FakeSkillsCapability
        pydantic_ai_skills.SkillsDirectory = FakeSkillsDirectory
        models_openai = types.ModuleType("pydantic_ai.models.openai")
        models_openai.OpenAIChatModel = FakeModel
        providers_openai = types.ModuleType("pydantic_ai.providers.openai")
        providers_openai.OpenAIProvider = FakeProvider

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            sys.modules,
            {
                "pydantic_ai": pydantic_ai,
                "pydantic_ai_skills": pydantic_ai_skills,
                "pydantic_ai.models.openai": models_openai,
                "pydantic_ai.providers.openai": providers_openai,
            },
        ), patch.dict(os.environ, {"RIGHT_CODE_API_KEY": "test-key"}):
            root = Path(tmp)
            _write_minimal_skill(root)
            config = SkillAgentConfig(
                skill_directories=(root,),
                execution_backend=SkillExecutionBackend.DOCKER,
                sandbox_image="example/runtime:latest",
                sandbox_workspace_root=root / "sandbox",
            )

            SkillAgentFactory().create_agent(config)

        self.assertEqual(captured["script_executor"].__class__.__name__, "DockerSkillScriptExecutor")


class MountedSkillAgentTests(unittest.TestCase):
    def test_session_preserves_message_history_between_instructions(self) -> None:
        calls: list[tuple[str, object]] = []

        class FakeResult:
            def __init__(self, output: str, messages: list[str]) -> None:
                self.output = output
                self._messages = messages

            def all_messages(self) -> list[str]:
                return self._messages

        class FakeAgent:
            async def run(self, instruction: str, *, message_history: object = None) -> FakeResult:
                calls.append((instruction, message_history))
                return FakeResult(f"done: {instruction}", [f"message:{len(calls)}"])

        config = SkillAgentConfig(skill_directories=(Path("."),))
        session = MountedSkillAgent(config, agent=FakeAgent())

        first = asyncio.run(session.arun("first task"))
        second = asyncio.run(session.arun("second task"))

        self.assertEqual(first.output, "done: first task")
        self.assertEqual(second.output, "done: second task")
        self.assertEqual(calls[0], ("first task", None))
        self.assertEqual(calls[1], ("second task", ["message:1"]))

    def test_reset_clears_message_history(self) -> None:
        calls: list[object] = []

        class FakeAgent:
            async def run(self, instruction: str, *, message_history: object = None) -> SimpleNamespace:
                calls.append(message_history)
                return SimpleNamespace(output="ok", all_messages=lambda: ["history"])

        session = MountedSkillAgent(SkillAgentConfig(skill_directories=(Path("."),)), agent=FakeAgent())
        asyncio.run(session.arun("one"))
        session.reset()
        asyncio.run(session.arun("two"))

        self.assertEqual(calls, [None, None])


if __name__ == "__main__":
    unittest.main()
