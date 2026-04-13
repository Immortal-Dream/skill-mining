"""Async rate limiting and retry utilities for isolated LLM clients."""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from loguru import logger


T = TypeVar("T")


class RateLimitExceeded(RuntimeError):
    """Raised when a token request can never fit in the configured bucket."""


class AsyncTokenBucket:
    """Simple async token bucket for bulk LLM calls."""

    def __init__(
        self,
        *,
        capacity: float,
        refill_rate_per_second: float,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        if refill_rate_per_second <= 0:
            raise ValueError("refill_rate_per_second must be positive")
        self._capacity = float(capacity)
        self._refill_rate_per_second = float(refill_rate_per_second)
        self._tokens = float(capacity)
        self._clock = clock or time.monotonic
        self._last_refill = self._clock()
        self._lock = asyncio.Lock()

    @property
    def capacity(self) -> float:
        return self._capacity

    @property
    def refill_rate_per_second(self) -> float:
        return self._refill_rate_per_second

    async def acquire(self, tokens: float = 1.0) -> None:
        """Wait until the requested number of tokens is available."""

        if tokens <= 0:
            raise ValueError("tokens must be positive")
        if tokens > self._capacity:
            raise RateLimitExceeded("requested tokens exceed bucket capacity")

        while True:
            async with self._lock:
                self._refill_unlocked()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                missing = tokens - self._tokens
                wait_seconds = missing / self._refill_rate_per_second

            await asyncio.sleep(wait_seconds)

    def _refill_unlocked(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate_per_second)
        self._last_refill = now


@dataclass(frozen=True)
class BackoffConfig:
    """Exponential backoff settings for transient LLM failures."""

    max_retries: int = 3
    initial_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    multiplier: float = 2.0
    jitter_ratio: float = 0.1

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.initial_delay_seconds < 0:
            raise ValueError("initial_delay_seconds must be non-negative")
        if self.max_delay_seconds < 0:
            raise ValueError("max_delay_seconds must be non-negative")
        if self.multiplier < 1:
            raise ValueError("multiplier must be at least 1")
        if not 0 <= self.jitter_ratio <= 1:
            raise ValueError("jitter_ratio must be between 0 and 1")


async def retry_with_backoff(
    operation: Callable[[], Awaitable[T]],
    *,
    retry_on: tuple[type[BaseException], ...],
    config: BackoffConfig | None = None,
    on_retry: Callable[[BaseException, int, float], None] | None = None,
) -> T:
    """Run an async operation with exponential backoff for retryable errors."""

    if not retry_on:
        raise ValueError("retry_on must contain at least one exception type")

    settings = config or BackoffConfig()
    attempt = 0
    delay = settings.initial_delay_seconds

    while True:
        try:
            return await operation()
        except retry_on as exc:
            if attempt >= settings.max_retries:
                raise
            sleep_for = min(delay, settings.max_delay_seconds)
            if settings.jitter_ratio and sleep_for > 0:
                jitter = sleep_for * settings.jitter_ratio
                sleep_for = random.uniform(max(0.0, sleep_for - jitter), sleep_for + jitter)
            if on_retry is not None:
                on_retry(exc, attempt + 1, sleep_for)
            else:
                logger.warning(
                    "Retryable operation failed; backing off: attempt={} sleep_seconds={:.2f} error={}",
                    attempt + 1,
                    sleep_for,
                    exc.__class__.__name__,
                )
            await asyncio.sleep(sleep_for)
            delay = delay * settings.multiplier if delay > 0 else settings.initial_delay_seconds
            attempt += 1


