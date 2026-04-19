"""Dependency bootstrapper for the containerized EASM agent service.

The OpenHands runtime image is intentionally generic. This module uses only the
standard library, installs the small runtime dependency set when missing, and
then starts `easm_pipeline.core.control_layer.agent_service`.
"""

from __future__ import annotations

import importlib
import runpy
import subprocess
import sys


REQUIRED_PACKAGES = {
    "loguru": "loguru>=0.7.0",
    "pydantic": "pydantic>=2.9.0",
    "pydantic_ai": "pydantic-ai>=1.71",
    "pydantic_ai_skills": "pydantic-ai-skills>=0.7.0",
    "yaml": "PyYAML>=6.0.1",
}


def main() -> int:
    missing = [package for module, package in REQUIRED_PACKAGES.items() if not _module_available(module)]
    if missing:
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--quiet",
                "--no-cache-dir",
                *missing,
            ]
        )
    runpy.run_module("easm_pipeline.core.control_layer.agent_service", run_name="__main__")
    return 0


def _module_available(module_name: str) -> bool:
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
