"""Optional provenance-trace capture helpers for DAG skill mining."""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def load_callable(spec: str) -> Any:
    """Load a callable from module:function notation."""

    if ":" not in spec:
        raise ValueError("callable spec must use module:function format")
    module_name, attr_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    callable_obj = getattr(module, attr_name)
    if not callable(callable_obj):
        raise TypeError(f"loaded object is not callable: {spec}")
    return callable_obj


def _load_appworld_provenance_runtime() -> ModuleType:
    try:
        return importlib.import_module("appworld_agents.code.common.provenance_runtime")
    except Exception:
        return _load_appworld_provenance_runtime_from_repo()


def _load_appworld_provenance_runtime_from_repo() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[2]
    appworld_src = repo_root / "appworld" / "src"
    common_dir = repo_root / "appworld" / "experiments" / "code" / "common"
    runtime_path = common_dir / "provenance_runtime.py"
    types_path = common_dir / "provenance_types.py"
    if not runtime_path.is_file() or not types_path.is_file():
        raise ModuleNotFoundError(
            "AppWorld provenance runtime is unavailable. "
            "Make sure the repository contains appworld/experiments/code/common/provenance_runtime.py."
        )
    if appworld_src.is_dir():
        appworld_src_str = str(appworld_src)
        if appworld_src_str not in sys.path:
            sys.path.append(appworld_src_str)
    _ensure_package("appworld_agents")
    _ensure_package("appworld_agents.code")
    _ensure_package("appworld_agents.code.common")
    _load_module_from_path("appworld_agents.code.common.provenance_types", types_path)
    return _load_module_from_path("appworld_agents.code.common.provenance_runtime", runtime_path)


def _ensure_package(name: str) -> ModuleType:
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    module = ModuleType(name)
    module.__path__ = []  # type: ignore[attr-defined]
    sys.modules[name] = module
    return module


def _load_module_from_path(name: str, path: Path) -> ModuleType:
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load module spec for {name} from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def capture_provenance_report(
    *,
    apis_factory_spec: str,
    workflow_spec: str,
    workflow_input: Any = None,
    session_id: str = "skill_mining_trace",
    task_id: str | None = None,
    experiment_name: str | None = None,
    agent_name: str = "skill_mining_trace",
    process_index: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Capture one provenance report by running a workflow against proxied APIs."""

    provenance_runtime = _load_appworld_provenance_runtime()
    apis_factory = load_callable(apis_factory_spec)
    workflow = load_callable(workflow_spec)
    apis = apis_factory()
    proxied_apis, recorder = provenance_runtime.create_instrumented_apis(
        apis,
        session_id=session_id,
        task_id=task_id,
        experiment_name=experiment_name,
        agent_name=agent_name,
        process_index=process_index,
        extra=extra,
    )
    if workflow_input is None:
        workflow(proxied_apis)
    elif isinstance(workflow_input, dict):
        workflow(proxied_apis, **workflow_input)
    elif isinstance(workflow_input, list):
        workflow(proxied_apis, *workflow_input)
    else:
        workflow(proxied_apis, workflow_input)
    return recorder.report()


def capture_provenance_report_to_path(
    *,
    output_path: Path,
    apis_factory_spec: str,
    workflow_spec: str,
    workflow_input: Any = None,
    session_id: str = "skill_mining_trace",
    task_id: str | None = None,
    experiment_name: str | None = None,
    agent_name: str = "skill_mining_trace",
    process_index: int | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Capture a provenance report and write it to disk."""

    report = capture_provenance_report(
        apis_factory_spec=apis_factory_spec,
        workflow_spec=workflow_spec,
        workflow_input=workflow_input,
        session_id=session_id,
        task_id=task_id,
        experiment_name=experiment_name,
        agent_name=agent_name,
        process_index=process_index,
        extra=extra,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return output_path
