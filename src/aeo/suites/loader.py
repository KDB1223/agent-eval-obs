"""Load task YAML (or JSON) files from a directory."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from aeo.errors import SuiteError
from aeo.models import GraderSpec, MockStep, Task

_TASK_ID = __import__("re").compile(r"^[a-z][a-z0-9-]{0,40}$")
_RESERVED = {"id", "type", "weight", "required"}


def load_suite(path: Path, only: list[str] | None = None) -> list[Task]:
    """Load every task file under ``path``, in filename order."""
    if not path.is_dir():
        raise SuiteError(f"suite directory not found: {path}")
    files = sorted(
        item
        for item in path.iterdir()
        if item.is_file() and item.suffix in {".yaml", ".yml", ".json"}
    )
    if not files:
        raise SuiteError(f"no task files in {path}")
    tasks = [load_task(item) for item in files]
    seen: set[str] = set()
    for task in tasks:
        if task.id in seen:
            raise SuiteError(f"duplicate task id: {task.id}")
        seen.add(task.id)
    if only:
        wanted = set(only)
        missing = wanted - seen
        if missing:
            names = ", ".join(sorted(missing))
            raise SuiteError(f"unknown task id: {names}")
        tasks = [task for task in tasks if task.id in wanted]
    return tasks


def load_task(path: Path) -> Task:
    """Parse one task file."""
    data = _read_mapping(path)
    task_id = _require_str(data, "id", path)
    if not _TASK_ID.match(task_id):
        raise SuiteError(f"{path}: id must be lowercase letters, digits, and hyphens")
    title = _require_str(data, "title", path)
    prompt = _require_str(data, "prompt", path)
    files = data.get("files") or {}
    if not isinstance(files, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in files.items()):
        raise SuiteError(f"{path}: files must be a mapping of path to text")
    tools = data.get("tools") or []
    if not isinstance(tools, list) or not all(isinstance(item, str) for item in tools):
        raise SuiteError(f"{path}: tools must be a list of names")
    graders_raw = data.get("graders")
    if not isinstance(graders_raw, list) or not graders_raw:
        raise SuiteError(f"{path}: graders must be a non-empty list")
    graders = [_parse_grader(item, index, path) for index, item in enumerate(graders_raw, 1)]
    mock_steps = [_parse_mock(item, path) for item in data.get("mock") or []]
    category = str(data.get("category") or "task")
    rubric = str(data.get("rubric") or "")
    max_steps = int(data.get("max_steps") or 8)
    timeout_s = float(data.get("timeout_s") or 30)
    if max_steps < 1:
        raise SuiteError(f"{path}: max_steps must be >= 1")
    return Task(
        id=task_id,
        title=title,
        category=category,
        prompt=prompt.strip(),
        files=dict(files),
        tools=list(tools),
        graders=graders,
        mock_steps=mock_steps,
        rubric=rubric.strip(),
        max_steps=max_steps,
        timeout_s=timeout_s,
        source=str(path),
    )


def _read_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data = json.loads(text)
    else:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise SuiteError(f"{path}: task file must be a mapping")
    return data


def _require_str(data: dict[str, Any], key: str, path: Path) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SuiteError(f"{path}: {key} is required")
    return value


def _parse_grader(raw: Any, index: int, path: Path) -> GraderSpec:
    if not isinstance(raw, dict):
        raise SuiteError(f"{path}: grader {index} must be a mapping")
    grader_type = raw.get("type")
    if not isinstance(grader_type, str) or not grader_type.strip():
        raise SuiteError(f"{path}: grader {index} needs a type")
    grader_id = str(raw.get("id") or f"g{index}")
    weight = float(raw.get("weight") or 1)
    if weight <= 0:
        raise SuiteError(f"{path}: grader {grader_id} weight must be > 0")
    required = bool(raw.get("required", True))
    options = {key: value for key, value in raw.items() if key not in _RESERVED}
    return GraderSpec(
        id=grader_id,
        type=grader_type.strip(),
        weight=weight,
        required=required,
        options=options,
    )


def _parse_mock(raw: Any, path: Path) -> MockStep:
    if not isinstance(raw, dict):
        raise SuiteError(f"{path}: each mock step must be a mapping")
    thought = str(raw.get("thought") or "")
    has_tool = "tool" in raw
    has_final = "final" in raw
    if has_tool and has_final:
        raise SuiteError(f"{path}: a mock step has both tool and final")
    if has_final:
        return MockStep(kind="final", thought=thought, content=str(raw.get("final") or ""))
    if has_tool:
        arguments = raw.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise SuiteError(f"{path}: mock arguments must be a mapping")
        return MockStep(
            kind="tool",
            thought=thought,
            tool=str(raw["tool"]),
            arguments=dict(arguments),
        )
    raise SuiteError(f"{path}: a mock step needs tool or final")
