"""Source miner dispatch helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from easm_pipeline.core.llm_infra.schemas import ExtractedNode


class SourceMiner(Protocol):
    """Interface shared by dedicated and fallback miners."""

    def mine_file(self, path: Path, *, project_root: Path | None = None) -> list[ExtractedNode]:
        ...


class SourceMinerRegistry:
    """Dispatch files to the best available miner."""

    def __init__(self, *, python_miner: SourceMiner, java_miner: SourceMiner, generic_miner: SourceMiner) -> None:
        self._by_suffix: dict[str, SourceMiner] = {
            ".py": python_miner,
            ".java": java_miner,
        }
        self._generic_miner = generic_miner

    def mine_file(self, path: Path, *, project_root: Path | None = None) -> list[ExtractedNode]:
        miner = self._by_suffix.get(path.suffix.lower(), self._generic_miner)
        return miner.mine_file(path, project_root=project_root)
