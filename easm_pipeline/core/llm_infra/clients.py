"""Structured-output LLM client wrapper isolated from extraction logic.

The default provider is Right Codes, using the OpenAI-style chat completions
endpoint shown in project configuration:

POST https://www.right.codes/codex/v1/chat/completions
Authorization: Bearer $RIGHT_CODE_API_KEY
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Awaitable, Callable, Mapping
from enum import Enum
from typing import Any, TypeVar

from loguru import logger
from pydantic.v1 import BaseModel, Extra, Field, SecretStr, ValidationError, validator

from easm_pipeline.core.logging import configure_logging

from .rate_limiter import AsyncTokenBucket, BackoffConfig, retry_with_backoff


SchemaT = TypeVar("SchemaT", bound=BaseModel)
AsyncTransport = Callable[[str, Mapping[str, str], Mapping[str, Any], float], Awaitable[Mapping[str, Any]]]

RIGHT_CODE_API_KEY_ENV = "RIGHT_CODE_API_KEY"
RIGHT_CODE_DEFAULT_BASE_URL = "https://www.right.codes/codex/v1"
RIGHT_CODE_DEFAULT_MODEL = "gpt-5.2"


class LLMClientError(RuntimeError):
    """Base exception for LLM client failures."""


class LLMConfigurationError(LLMClientError):
    """Raised when the client is missing required provider configuration."""


class LLMRateLimitError(LLMClientError):
    """Raised for provider HTTP 429 responses."""


class LLMTransientError(LLMClientError):
    """Raised for retryable provider or network failures."""


class LLMResponseValidationError(LLMClientError):
    """Raised when model output fails strict Pydantic validation."""


class LLMProvider(str, Enum):
    """Supported chat-completions provider protocols."""

    RIGHT_CODE = "right-code"
    OPENAI_COMPATIBLE = "openai-compatible"


class LLMClientConfig(BaseModel):
    """Runtime configuration for structured LLM requests."""

    provider: LLMProvider = Field(LLMProvider.RIGHT_CODE, description="Provider protocol.")
    model: str = Field(RIGHT_CODE_DEFAULT_MODEL, min_length=1)
    api_key: SecretStr | None = Field(
        None,
        description="Provider API key. If absent, provider-specific environment variables are used.",
    )
    base_url: str | None = Field(
        None,
        description="API base URL or full /chat/completions endpoint override.",
    )
    timeout_seconds: float = Field(60.0, gt=0)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(None, gt=0)
    max_retries: int = Field(3, ge=0)
    validation_repair_attempts: int = Field(1, ge=0, le=3)
    requests_per_minute: float = Field(60.0, gt=0)

    class Config:
        extra = Extra.forbid
        validate_assignment = True

    @validator("model")
    @classmethod
    def _validate_model(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("model must be non-empty")
        return stripped

    @validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.rstrip("/")
        if not re.match(r"^https?://", stripped):
            raise ValueError("base_url must start with http:// or https://")
        return stripped

    @classmethod
    def right_code(
        cls,
        *,
        model: str = RIGHT_CODE_DEFAULT_MODEL,
        api_key: str | None = None,
        base_url: str | None = None,
        **overrides: Any,
    ) -> "LLMClientConfig":
        """Build a Right Codes config while keeping call sites provider-agnostic."""

        return cls(
            provider=LLMProvider.RIGHT_CODE,
            model=model,
            api_key=api_key,
            base_url=base_url,
            **overrides,
        )


class StructuredLLMClient:
    """Provider wrapper that only returns validated Pydantic objects."""

    def __init__(
        self,
        config: LLMClientConfig | None = None,
        *,
        rate_limiter: AsyncTokenBucket | None = None,
        transport: AsyncTransport | None = None,
    ) -> None:
        configure_logging()
        self._config = config or LLMClientConfig.right_code()
        self._rate_limiter = rate_limiter or AsyncTokenBucket(
            capacity=max(1.0, self._config.requests_per_minute),
            refill_rate_per_second=self._config.requests_per_minute / 60.0,
        )
        self._transport = transport

    async def agenerate(
        self,
        *,
        prompt: str,
        response_schema: type[SchemaT],
        system_prompt: str | None = None,
    ) -> SchemaT:
        """Call the configured provider and validate the structured response."""

        if not prompt or not prompt.strip():
            raise ValueError("prompt must be non-empty")
        self._validate_schema_type(response_schema)
        strict_schema = _strict_json_schema(response_schema)
        logger.info(
            "Requesting structured LLM output: provider={} model={} schema={}",
            self._config.provider.value,
            self._config.model,
            _schema_name(response_schema),
        )

        async def attempt() -> Mapping[str, Any]:
            await self._rate_limiter.acquire()
            return await self._call_chat_completions(
                prompt=prompt,
                system_prompt=system_prompt,
                response_schema=response_schema,
                strict_schema=strict_schema,
            )

        raw_response = await retry_with_backoff(
            attempt,
            retry_on=(LLMRateLimitError, LLMTransientError),
            config=BackoffConfig(max_retries=self._config.max_retries),
        )
        try:
            payload = _extract_chat_completion_json_payload(raw_response)
            validated = self._validate_payload(payload, response_schema)
            logger.info("Validated structured LLM output: schema={}", _schema_name(response_schema))
            return validated
        except LLMResponseValidationError as exc:
            if self._config.validation_repair_attempts <= 0:
                raise
            logger.warning(
                "Structured LLM output failed validation; requesting repair: schema={} error={}",
                _schema_name(response_schema),
                str(exc).splitlines()[0],
            )
            return await self._repair_and_validate(
                original_prompt=prompt,
                original_response=_chat_completion_content(raw_response),
                validation_error=str(exc),
                response_schema=response_schema,
                strict_schema=strict_schema,
            )

    def generate(
        self,
        *,
        prompt: str,
        response_schema: type[SchemaT],
        system_prompt: str | None = None,
    ) -> SchemaT:
        """Synchronous wrapper for contexts that do not already run an event loop."""

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(
                self.agenerate(
                    prompt=prompt,
                    response_schema=response_schema,
                    system_prompt=system_prompt,
                )
            )
        raise RuntimeError("StructuredLLMClient.generate cannot run inside an active event loop")

    async def _call_chat_completions(
        self,
        *,
        prompt: str,
        system_prompt: str | None,
        response_schema: type[BaseModel],
        strict_schema: dict[str, Any],
        ) -> Mapping[str, Any]:
        # Do not log request bodies or prompts; they may contain source code or
        # user data. Provider, model, and schema are enough for tracing.
        body: dict[str, Any] = {
            "model": self._config.model,
            "messages": _build_messages(
                prompt=prompt,
                system_prompt=system_prompt,
                response_schema=response_schema,
                strict_schema=strict_schema,
            ),
            "stream": False,
        }
        if self._config.temperature is not None:
            body["temperature"] = self._config.temperature
        if self._config.max_tokens is not None:
            body["max_tokens"] = self._config.max_tokens

        headers = {
            "Authorization": _RedactedSecret(f"Bearer {self._api_key()}"),
            "Content-Type": "application/json",
        }
        url = _chat_completions_url(self._base_url())
        logger.debug("Posting chat completion request: provider={} url={}", self._config.provider.value, url)
        return await self._post_json(url, headers, body)

    async def _repair_and_validate(
        self,
        *,
        original_prompt: str,
        original_response: str,
        validation_error: str,
        response_schema: type[SchemaT],
        strict_schema: dict[str, Any],
    ) -> SchemaT:
        repair_prompt = _build_repair_prompt(
            original_prompt=original_prompt,
            original_response=original_response,
            validation_error=validation_error,
        )

        async def attempt() -> Mapping[str, Any]:
            await self._rate_limiter.acquire()
            return await self._call_chat_completions(
                prompt=repair_prompt,
                system_prompt=(
                    "Repair a failed structured response. Return only one corrected JSON object "
                    "that satisfies the schema exactly."
                ),
                response_schema=response_schema,
                strict_schema=strict_schema,
            )

        repaired_response = await retry_with_backoff(
            attempt,
            retry_on=(LLMRateLimitError, LLMTransientError),
            config=BackoffConfig(max_retries=self._config.max_retries),
        )
        payload = _extract_chat_completion_json_payload(repaired_response)
        validated = self._validate_payload(payload, response_schema)
        logger.info("Validated repaired LLM output: schema={}", _schema_name(response_schema))
        return validated

    async def _post_json(
        self,
        url: str,
        headers: Mapping[str, str],
        body: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if self._transport is not None:
            return await self._transport(url, headers, body, self._config.timeout_seconds)

        try:
            import aiohttp
        except ImportError as exc:
            return await asyncio.to_thread(
                _post_json_with_stdlib,
                url,
                headers,
                body,
                self._config.timeout_seconds,
            )

        timeout = aiohttp.ClientTimeout(total=self._config.timeout_seconds)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=dict(headers), json=dict(body)) as response:
                    response_text = await response.text()
                    try:
                        response_json = json.loads(response_text) if response_text else {}
                    except json.JSONDecodeError as exc:
                        raise LLMTransientError("provider returned non-JSON response") from exc
                    if response.status == 429:
                        logger.warning("Provider rate limited request: status=429")
                        raise LLMRateLimitError(_format_http_error(response.status, response_json))
                    if 500 <= response.status < 600:
                        logger.warning("Provider transient server error: status={}", response.status)
                        raise LLMTransientError(_format_http_error(response.status, response_json))
                    if response.status >= 400:
                        logger.error("Provider returned client error: status={}", response.status)
                        raise LLMClientError(_format_http_error(response.status, response_json))
                    if not isinstance(response_json, Mapping):
                        raise LLMTransientError("provider returned a non-object JSON response")
                    return response_json
        except aiohttp.ClientError:
            logger.warning("Provider request failed with aiohttp client error")
            raise LLMTransientError("provider request failed") from None

    def _api_key(self) -> str:
        if self._config.api_key is not None:
            return self._config.api_key.get_secret_value()

        env_name = RIGHT_CODE_API_KEY_ENV
        if self._config.provider is LLMProvider.OPENAI_COMPATIBLE:
            env_name = "OPENAI_API_KEY"
        value = os.getenv(env_name)
        if not value:
            raise LLMConfigurationError(f"missing API key: set config.api_key or {env_name}")
        return value

    def _base_url(self) -> str:
        if self._config.base_url:
            return self._config.base_url
        if self._config.provider is LLMProvider.RIGHT_CODE:
            return RIGHT_CODE_DEFAULT_BASE_URL
        if self._config.provider is LLMProvider.OPENAI_COMPATIBLE:
            return "https://api.openai.com/v1"
        raise LLMConfigurationError(f"unsupported provider: {self._config.provider}")

    @staticmethod
    def _validate_schema_type(response_schema: type[BaseModel]) -> None:
        if not isinstance(response_schema, type):
            raise TypeError("response_schema must be a pydantic BaseModel subclass")
        if not (
            issubclass(response_schema, BaseModel)
            or hasattr(response_schema, "model_json_schema")
            or hasattr(response_schema, "schema")
        ):
            raise TypeError("response_schema must be a pydantic BaseModel subclass")

    @staticmethod
    def _validate_payload(payload: Mapping[str, Any], response_schema: type[SchemaT]) -> SchemaT:
        fields = getattr(response_schema, "model_fields", None) or getattr(response_schema, "__fields__", {})
        allowed_keys = set(fields)
        extra_keys = set(payload) - allowed_keys
        if extra_keys:
            joined = ", ".join(sorted(extra_keys))
            raise LLMResponseValidationError(f"provider returned unexpected fields: {joined}")
        try:
            if hasattr(response_schema, "model_validate"):
                return response_schema.model_validate(dict(payload))
            return response_schema.parse_obj(dict(payload))
        except ValidationError as exc:
            raise LLMResponseValidationError(str(exc)) from exc
        except Exception as exc:
            if exc.__class__.__name__ == "ValidationError":
                raise LLMResponseValidationError(str(exc)) from exc
            raise


def _build_messages(
    *,
    prompt: str,
    system_prompt: str | None,
    response_schema: type[BaseModel],
    strict_schema: dict[str, Any],
) -> list[dict[str, str]]:
    system_parts = [
        "Return exactly one JSON object that validates against the requested schema.",
        "Do not include markdown, code fences, commentary, or extra keys.",
        "Use double-quoted JSON strings and no trailing commas.",
    ]
    if system_prompt:
        system_parts.insert(0, system_prompt.strip())

    user_content = (
        f"{prompt.strip()}\n\n"
        f"Required response schema name: {_schema_name(response_schema)}\n"
        "Required JSON schema:\n"
        f"{json.dumps(strict_schema, ensure_ascii=False, sort_keys=True)}"
    )
    return [
        {"role": "system", "content": "\n".join(system_parts)},
        {"role": "user", "content": user_content},
    ]


def _extract_chat_completion_json_payload(response: Mapping[str, Any]) -> Mapping[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMResponseValidationError("chat completion response missing choices")
    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        raise LLMResponseValidationError("chat completion choice must be an object")
    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        raise LLMResponseValidationError("chat completion choice missing message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMResponseValidationError("chat completion message missing JSON content")

    stripped = content.strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise LLMResponseValidationError("chat completion content was not strict JSON") from exc
    if not isinstance(parsed, Mapping):
        raise LLMResponseValidationError("chat completion JSON content must be an object")
    return parsed


def _chat_completion_content(response: Mapping[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return json.dumps(response, ensure_ascii=False)[:4000]
    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        return json.dumps(response, ensure_ascii=False)[:4000]
    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        return json.dumps(response, ensure_ascii=False)[:4000]
    content = message.get("content")
    if isinstance(content, str):
        return content[:4000]
    return json.dumps(response, ensure_ascii=False)[:4000]


def _build_repair_prompt(
    *,
    original_prompt: str,
    original_response: str,
    validation_error: str,
) -> str:
    return (
        "The previous model response failed local structured validation.\n\n"
        "Repair task:\n"
        "- Return the same intended answer as one valid JSON object.\n"
        "- Preserve useful domain-specific wording from the previous response.\n"
        "- Satisfy every schema and validator requirement.\n"
        "- Remove markdown, code fences, comments, and extra keys.\n\n"
        f"Validation error:\n{validation_error[:2000]}\n\n"
        f"Original prompt excerpt:\n{original_prompt[:3000]}\n\n"
        f"Previous response:\n{original_response[:4000]}"
    )


def _strict_json_schema(response_schema: type[BaseModel]) -> dict[str, Any]:
    if hasattr(response_schema, "model_json_schema"):
        schema = response_schema.model_json_schema()
    else:
        schema = response_schema.schema()
    _forbid_additional_properties(schema)
    return schema


def _forbid_additional_properties(node: Any) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            node.setdefault("additionalProperties", False)
        for value in node.values():
            _forbid_additional_properties(value)
    elif isinstance(node, list):
        for item in node:
            _forbid_additional_properties(item)


def _schema_name(response_schema: type[BaseModel]) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]", "_", response_schema.__name__)
    return name[:64] or "StructuredResponse"


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _format_http_error(status: int, body: Mapping[str, Any]) -> str:
    message = body.get("error", body)
    return f"provider returned HTTP {status}: {message}"


class _RedactedSecret(str):
    """String that keeps its runtime value but redacts traceback/local repr."""

    def __repr__(self) -> str:
        return "'<redacted>'"


def _post_json_with_stdlib(
    url: str,
    headers: Mapping[str, str],
    body: Mapping[str, Any],
    timeout_seconds: float,
) -> Mapping[str, Any]:
    data = json.dumps(dict(body)).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=dict(headers), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            response_text = response.read().decode("utf-8")
            response_json = json.loads(response_text) if response_text else {}
            if not isinstance(response_json, Mapping):
                raise LLMTransientError("provider returned a non-object JSON response")
            return response_json
    except urllib.error.HTTPError as exc:
        response_text = exc.read().decode("utf-8", errors="replace")
        try:
            response_json = json.loads(response_text) if response_text else {}
        except json.JSONDecodeError:
            response_json = {"error": response_text}
        if exc.code == 429:
            logger.warning("Provider rate limited request: status=429")
            raise LLMRateLimitError(_format_http_error(exc.code, response_json)) from None
        if 500 <= exc.code < 600:
            logger.warning("Provider transient server error: status={}", exc.code)
            raise LLMTransientError(_format_http_error(exc.code, response_json)) from None
        logger.error("Provider returned client error: status={}", exc.code)
        raise LLMClientError(_format_http_error(exc.code, response_json)) from None
    except urllib.error.URLError:
        logger.warning("Provider request failed with urllib URL error")
        raise LLMTransientError("provider request failed") from None
    except json.JSONDecodeError:
        logger.warning("Provider returned non-JSON response")
        raise LLMTransientError("provider returned non-JSON response") from None


