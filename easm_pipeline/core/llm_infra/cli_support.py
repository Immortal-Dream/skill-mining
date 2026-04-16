"""Shared CLI helpers for optional structured-LLM configuration."""

from __future__ import annotations

import argparse

from .clients import (
    RIGHT_CODE_DEFAULT_MODEL,
    LLMClientConfig,
    LLMProvider,
    StructuredLLMClient,
)


def add_llm_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Register the standard optional LLM flags on a parser."""

    parser.add_argument(
        "--provider",
        choices=[provider.value for provider in LLMProvider],
        help="Structured-output provider protocol. Defaults to right-code when LLM synthesis is enabled.",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help=f"Enable LLM synthesis. Defaults to right-code with RIGHT_CODE_API_KEY and model {RIGHT_CODE_DEFAULT_MODEL}.",
    )
    parser.add_argument("--model", help=f"LLM model name for synthesis. Defaults to {RIGHT_CODE_DEFAULT_MODEL}.")
    parser.add_argument(
        "--api-key",
        help="Provider API key override. Prefer RIGHT_CODE_API_KEY for right-code.",
    )
    parser.add_argument("--base-url", help="Provider API base URL override.")
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--requests-per-minute", type=float, default=60.0)
    return parser


def build_llm_client_from_args(args: argparse.Namespace) -> StructuredLLMClient | None:
    """Construct a StructuredLLMClient from standard parsed CLI flags."""

    if not args.use_llm and not args.provider and not args.model and not args.api_key and not args.base_url:
        return None
    provider = LLMProvider(args.provider) if args.provider else LLMProvider.RIGHT_CODE
    config = LLMClientConfig(
        provider=provider,
        model=args.model or RIGHT_CODE_DEFAULT_MODEL,
        api_key=args.api_key,
        base_url=args.base_url,
        max_retries=args.max_retries,
        requests_per_minute=args.requests_per_minute,
    )
    return StructuredLLMClient(config)
