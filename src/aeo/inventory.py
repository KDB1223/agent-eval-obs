"""Coverage inventory of a task suite. No adapter is called and no run is written."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aeo import __version__
from aeo.models import Task
from aeo.scoreboard import render_table

_NOTE = "Listed from the suite files. No agent was run."
_STAT_WIDTH = 18
_TIMES = "×"


def render_inventory(tasks: list[Task], suite: Path, fmt: str = "text") -> str:
    """Render a text table or one JSON object for ``tasks``."""
    payload = collect_inventory(tasks, suite)
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return _render_text(payload)


def collect_inventory(tasks: list[Task], suite: Path) -> dict[str, Any]:
    """Structured coverage of a suite that has already been loaded.

    Task order is the order ``load_suite`` returned. Category and grader-type
    rollups follow first appearance in that order. Counts include every grader
    entry, including ones with ``required`` false.
    """
    rows = [_task_row(task) for task in tasks]
    return {
        "version": __version__,
        "suite": str(suite),
        "tasks": rows,
        "task_count": len(rows),
        "categories": _category_counts(rows),
        "grader_types": _grader_type_counts(rows),
        "with_mock": sum(1 for row in rows if row["mock"] > 0),
        "optional_graders": sum(
            1 for row in rows for grader in row["graders"] if not grader["required"]
        ),
        "note": _NOTE,
    }


def _task_row(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "category": task.category,
        "graders": [
            {"id": grader.id, "type": grader.type, "required": grader.required}
            for grader in task.graders
        ],
        "tools": list(task.tools),
        "mock": len(task.mock_steps),
        "files": len(task.files),
    }


def _category_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order: list[str] = []
    counts: dict[str, int] = {}
    for row in rows:
        name = str(row["category"])
        if name not in counts:
            counts[name] = 0
            order.append(name)
        counts[name] += 1
    return [{"category": name, "count": counts[name]} for name in order]


def _grader_type_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order: list[str] = []
    counts: dict[str, int] = {}
    for row in rows:
        for grader in row["graders"]:
            name = str(grader["type"])
            if name not in counts:
                counts[name] = 0
                order.append(name)
            counts[name] += 1
    return [{"type": name, "count": counts[name]} for name in order]


def _format_graders(graders: list[dict[str, Any]]) -> str:
    """Types in first-seen order. Repeats collapse; optional types end with ``?``."""
    order: list[str] = []
    required: dict[str, int] = {}
    optional: dict[str, int] = {}
    for grader in graders:
        name = str(grader["type"])
        if name not in required:
            order.append(name)
            required[name] = 0
            optional[name] = 0
        if grader["required"]:
            required[name] += 1
        else:
            optional[name] += 1
    parts: list[str] = []
    for name in order:
        req = required[name]
        opt = optional[name]
        if req and opt:
            parts.append(f"{_times_label(name, req)} ({opt} optional)")
        elif opt:
            parts.append(_times_label(f"{name}?", opt))
        elif req:
            parts.append(_times_label(name, req))
    if not parts:
        return "-"
    return ", ".join(parts)


def _times_label(label: str, count: int) -> str:
    if count <= 1:
        return label
    return f"{label}{_TIMES}{count}"


def _format_tools(tools: list[str]) -> str:
    if not tools:
        return "-"
    return ", ".join(tools)


def _format_categories(items: list[dict[str, Any]]) -> str:
    if not items:
        return "-"
    return ", ".join(f"{item['category']} {item['count']}" for item in items)


def _format_grader_types(items: list[dict[str, Any]]) -> str:
    if not items:
        return "-"
    return ", ".join(f"{item['type']} {item['count']}" for item in items)


def _stat(label: str, value: str) -> str:
    return f"{label:<{_STAT_WIDTH}}{value}"


def _render_text(payload: dict[str, Any]) -> str:
    rows = [
        [
            str(row["id"]),
            str(row["category"]),
            _format_graders(row["graders"]),
            _format_tools(row["tools"]),
            str(row["mock"]),
            str(row["files"]),
        ]
        for row in payload["tasks"]
    ]
    table = render_table(["task", "category", "graders", "tools", "mock", "files"], rows)
    lines = [
        f"agent-eval-obs {payload['version']}  suite {payload['suite']}",
        "",
        table,
        "",
        _stat("tasks", str(payload["task_count"])),
        _stat("categories", _format_categories(payload["categories"])),
        _stat("graders", _format_grader_types(payload["grader_types"])),
        _stat("with mock", f"{payload['with_mock']}/{payload['task_count']}"),
        _stat("optional graders", str(payload["optional_graders"])),
        "",
        str(payload["note"]),
        "",
    ]
    return "\n".join(lines)
