"""Central loguru configuration for the EASM pipeline."""

from __future__ import annotations

import os
import sys
from typing import Final

from loguru import logger


DEFAULT_LOG_LEVEL: Final[str] = "INFO"
_CONFIGURED = False


def configure_logging(level: str | None = None) -> None:
    """Configure process-wide logging once.

    The pipeline can carry source code and provider credentials in memory, so
    callers must log identifiers and counts instead of raw prompts or payloads.
    """

    global _CONFIGURED
    if _CONFIGURED:
        return

    resolved_level = (level or os.getenv("EASM_LOG_LEVEL") or DEFAULT_LOG_LEVEL).upper()
    logger.remove()
    logger.add(
        sys.stderr,
        level=resolved_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        backtrace=False,
        diagnose=False,
    )
    _CONFIGURED = True


configure_logging()



