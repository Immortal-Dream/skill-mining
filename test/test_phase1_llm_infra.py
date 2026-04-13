import asyncio
import json
import unittest
from typing import Any, Mapping
from unittest.mock import patch

from pydantic.v1 import BaseModel, Extra, ValidationError

from easm_pipeline.core.llm_infra import (
    AsyncTokenBucket,
    BackoffConfig,
    CapabilitySlice,
    ExtractedNode,
    LLMClientConfig,
    LLMProvider,
    LLMResponseValidationError,
    RateLimitExceeded,
    SkillPayload,
    StructuredLLMClient,
    retry_with_backoff,
)


class DemoResponse(BaseModel):
    value: str

    class Config:
        extra = Extra.forbid


class Phase1SchemaTests(unittest.TestCase):
    def test_extracted_node_and_capability_context_are_deterministic(self) -> None:
        node = ExtractedNode(
            node_id="src/demo.py:0-24:run",
            language="python",
            node_type="function",
            name="run",
            signature="def run()",
            raw_code="def run():\n    return 1\n",
            file_path="src/demo.py",
            start_byte=0,
            end_byte=24,
            start_line=1,
            end_line=2,
            scope_path=("demo",),
        )
        capability = CapabilitySlice(slice_id="demo-run", title="Demo Run", nodes=(node,))

        context = capability.render_llm_context()

        self.assertIn("# Capability Slice: Demo Run", context)
        self.assertIn("Signature: def run()", context)
        self.assertIn("```python", context)

    def test_skill_payload_rejects_reserved_names_and_unsafe_paths(self) -> None:
        with self.assertRaises(ValidationError):
            SkillPayload(
                name="claude-parser",
                description="Parse source files into skill context.",
                instructions="1. Inspect the source files.",
            )

        with self.assertRaises(ValidationError):
            SkillPayload(
                name="source-parser",
                description="Parse source files into skill context.",
                instructions="1. Inspect the source files.",
                scripts_dict={"../escape.py": "print('bad')"},
            )


class Phase1ClientTests(unittest.TestCase):
    def test_right_code_client_uses_chat_completions_and_env_key(self) -> None:
        captured: dict[str, Any] = {}

        async def transport(
            url: str,
            headers: Mapping[str, str],
            body: Mapping[str, Any],
            timeout_seconds: float,
        ) -> Mapping[str, Any]:
            captured["url"] = url
            captured["headers"] = dict(headers)
            captured["body"] = dict(body)
            captured["timeout"] = timeout_seconds
            return {"choices": [{"message": {"content": json.dumps({"value": "ok"})}}]}

        with patch.dict("os.environ", {"RIGHT_CODE_API_KEY": "env-test-key"}):
            client = StructuredLLMClient(LLMClientConfig(), transport=transport)
            response = asyncio.run(client.agenerate(prompt="Return JSON.", response_schema=DemoResponse))

        self.assertEqual(response.value, "ok")
        self.assertEqual(captured["url"], "https://www.right.codes/codex/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer env-test-key")
        self.assertEqual(captured["body"]["model"], "gpt-5.2")
        self.assertFalse(captured["body"]["stream"])
        self.assertNotIn("response_format", captured["body"])
        self.assertIn("Required JSON schema", captured["body"]["messages"][1]["content"])

    def test_client_rejects_extra_fields_from_provider(self) -> None:
        async def transport(
            url: str,
            headers: Mapping[str, str],
            body: Mapping[str, Any],
            timeout_seconds: float,
        ) -> Mapping[str, Any]:
            return {"choices": [{"message": {"content": json.dumps({"value": "ok", "extra": "bad"})}}]}

        client = StructuredLLMClient(
            LLMClientConfig(
                provider=LLMProvider.RIGHT_CODE,
                model="test-model",
                api_key="test-key",
            ),
            transport=transport,
        )

        with self.assertRaises(LLMResponseValidationError):
            asyncio.run(client.agenerate(prompt="Return JSON.", response_schema=DemoResponse))

    def test_openai_compatible_override_still_uses_chat_completions_url(self) -> None:
        captured: dict[str, Any] = {}

        async def transport(
            url: str,
            headers: Mapping[str, str],
            body: Mapping[str, Any],
            timeout_seconds: float,
        ) -> Mapping[str, Any]:
            captured["url"] = url
            captured["headers"] = dict(headers)
            captured["body"] = dict(body)
            return {"choices": [{"message": {"content": json.dumps({"value": "ok"})}}]}

        client = StructuredLLMClient(
            LLMClientConfig(
                provider=LLMProvider.OPENAI_COMPATIBLE,
                model="test-model",
                api_key="test-key",
                base_url="https://llm.example/v1",
            ),
            transport=transport,
        )

        response = asyncio.run(client.agenerate(prompt="Return JSON.", response_schema=DemoResponse))

        self.assertEqual(response.value, "ok")
        self.assertEqual(captured["url"], "https://llm.example/v1/chat/completions")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer test-key")


class Phase1RateLimiterTests(unittest.TestCase):
    def test_token_bucket_rejects_impossible_request(self) -> None:
        bucket = AsyncTokenBucket(capacity=1, refill_rate_per_second=10)

        with self.assertRaises(RateLimitExceeded):
            asyncio.run(bucket.acquire(tokens=2))

    def test_retry_with_backoff_retries_transient_operation(self) -> None:
        class RetryableError(RuntimeError):
            pass

        attempts = {"count": 0}

        async def operation() -> str:
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise RetryableError("try again")
            return "done"

        result = asyncio.run(
            retry_with_backoff(
                operation,
                retry_on=(RetryableError,),
                config=BackoffConfig(max_retries=2, initial_delay_seconds=0, jitter_ratio=0),
            )
        )

        self.assertEqual(result, "done")
        self.assertEqual(attempts["count"], 2)


if __name__ == "__main__":
    unittest.main()


