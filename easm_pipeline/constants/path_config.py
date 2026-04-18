"""Project path and domain constants for source-to-skills mining."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

# Source material is organized by mining domain:
# data/sample_source/<domain_name>/
SAMPLE_SOURCE_DIR = DATA_DIR / "sample_source"

# Generated Agent Skills are written by domain:
# data/output_skills/<domain_name>/
OUTPUT_SKILLS_DIR = DATA_DIR / "output_skills"

# Agent task files are organized as a host-managed filesystem that is mounted
# into Docker as /workspace. Inputs and outputs stay visible outside the
# container while scripts execute inside the sandbox.
AGENT_FILE_SYSTEM_DIR = DATA_DIR / "agent_file_system"
AGENT_INPUT_DIR = AGENT_FILE_SYSTEM_DIR / "input"
AGENT_OUTPUT_DIR = AGENT_FILE_SYSTEM_DIR / "output"
AGENT_WORK_DIR = AGENT_FILE_SYSTEM_DIR / "work"
AGENT_RUNS_DIR = AGENT_FILE_SYSTEM_DIR / "runs"
AGENT_LOGS_DIR = AGENT_FILE_SYSTEM_DIR / "logs"
AGENT_SKILLS_DIR = AGENT_FILE_SYSTEM_DIR / "skills"

# Domain names are plain strings so callers can use them in CLI args,
# config files, test parametrization, and future orchestration manifests.
DOMAIN_SAMPLE_PYTHON_SOURCE = "sample_python_source"
DOMAIN_BIOINFORMATICS = "bioinformatics"
DOMAIN_COMPUTER_SCIENCE = "computer_science"
DOMAIN_DATA_SCIENCE = "data_science"

DEFAULT_DOMAIN = DOMAIN_SAMPLE_PYTHON_SOURCE
SUPPORTED_DOMAINS = (
    DOMAIN_SAMPLE_PYTHON_SOURCE,
    DOMAIN_BIOINFORMATICS,
    DOMAIN_COMPUTER_SCIENCE,
    DOMAIN_DATA_SCIENCE,
)


def domain_source_dir(domain_name: str) -> Path:
    """Return the configured input directory for one mining domain."""

    return SAMPLE_SOURCE_DIR / domain_name


def domain_output_dir(domain_name: str) -> Path:
    """Return the configured output directory for one mining domain."""

    return OUTPUT_SKILLS_DIR / domain_name


def ensure_agent_file_system() -> Path:
    """Create host-managed agent input/output directories if missing."""

    for directory in (
        AGENT_FILE_SYSTEM_DIR,
        AGENT_INPUT_DIR,
        AGENT_OUTPUT_DIR,
        AGENT_WORK_DIR,
        AGENT_RUNS_DIR,
        AGENT_LOGS_DIR,
        AGENT_SKILLS_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return AGENT_FILE_SYSTEM_DIR
