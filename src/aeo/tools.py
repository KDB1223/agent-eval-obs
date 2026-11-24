"""Tool-call inventory for a saved run, grouped by tool name.

Reads ``trajectory.jsonl`` only. The agent is not re-run. A call id is
paired with the same coercion as :func:`aeo.stats._call_id`.
"""

from __future__ import annotations

import json
from pathlib import Path

from aeo import __version__
from aeo.failures import selected_tasks
from aeo.jsonl import read_jsonl
from aeo.scoreboard import render_table
from aeo.stats import _call_id

_MISSING_TOOL = "(missing)"
_NOTE = "Computed from the JSONL log. The agent was not re-run."
_STAT_WIDTH = 14


def render_tools(
    summary: dict,
    run_dir: Path,
    task_id: str | None = None,
    fmt: str = "text",
) -> str:
    """Render a text or JSON inventory of tool calls for the selected tasks."""
    payload = collect_tools(summary, run_dir, task_id=task_id)
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return _render_text(summary, payload)


def collect_tools(summary: dict, run_dir: Path, task_id: str | None = None) -> dict:
    """Count tool calls by name, in summary order then trajectory order.

    Only ``kind == "tool_call"`` events are calls. An observation counts
    toward a call when it shares that call's id; the last such observation
    in the file decides. The call succeeded only when that observation has
    ``ok is True``. A missing id, no observation, or any other ``ok`` value
    is a failure. Observations with no matching call are ignored.
    """
    selected = selected_tasks(summary, task_id)
    rows: list[dict] = []
    index: dict[str, dict] = {}
    for task in selected:
        name = str(task["task_id"])
        path = run_dir / "tasks" / name / "trajectory.jsonl"
        events = read_jsonl(path) if path.is_file() else []
        _accumulate(index, rows, name, events)
    calls = sum(row["calls"] for row in rows)
    ok = sum(row["ok"] for row in rows)
    failed = sum(row["failed"] for row in rows)
    return {
        "version": __version__,
        "run_id": summary["run_id"],
        "adapter": summary.get("adapter") or "",
        "model": summary.get("model") or "",
        "run_dir": str(run_dir),
        "tools": rows,
        "totals": {
            "tool_kinds": len(rows),
            "calls": calls,
            "ok": ok,
            "failed": failed,
        },
        "note": _NOTE,
    }


def _accumulate(index: dict[str, dict], rows: list[dict], task_id: str, events: list[dict]) -> None:
    last_obs: dict[str, dict] = {}
    calls: list[dict] = []
    for event in events:
        kind = event.get("kind")
        if kind == "observation":
            call_id = _call_id(event)
            if call_id is not None:
                last_obs[call_id] = event
        elif kind == "tool_call":
            calls.append(event)
    for event in calls:
        name = _tool_name(event)
        row = index.get(name)
        if row is None:
            row = {
                "name": name,
                "calls": 0,
                "ok": 0,
                "failed": 0,
                "tasks": [],
                "paths": [],
            }
            index[name] = row
            rows.append(row)
        row["calls"] += 1
        if _succeeded(event, last_obs):
            row["ok"] += 1
        else:
            row["failed"] += 1
        if task_id not in row["tasks"]:
            row["tasks"].append(task_id)
        path = _argument_path(event)
        if path is not None and path not in row["paths"]:
            row["paths"].append(path)


def _tool_name(event: dict) -> str:
    name = event.get("tool")
    if isinstance(name, str) and name:
        return name
    return _MISSING_TOOL


def _succeeded(event: dict, last_obs: dict[str, dict]) -> bool:
    call_id = _call_id(event)
    if call_id is None:
        return False
    observation = last_obs.get(call_id)
    if observation is None:
        return False
    return observation.get("ok") is True


def _argument_path(event: dict) -> str | None:
    arguments = event.get("arguments")
    if not isinstance(arguments, dict):
        return None
    path = arguments.get("path")
    if isinstance(path, str) and path != "":
        return path
    return None


def _render_text(summary: dict, payload: dict) -> str:
    model = summary.get("model") or summary.get("adapter") or ""
    lines = [
        (
            f"agent-eval-obs {__version__}  "
            f"run {summary['run_id']}  "
            f"adapter={summary.get('adapter') or ''}  "
            f"model={model}"
        ),
        "",
    ]
    if not payload["tools"]:
        lines.append("no tools")
        lines.append("")
    else:
        table_rows = [
            [
                str(row["name"]),
                str(row["calls"]),
                str(row["ok"]),
                str(row["failed"]),
                _format_list(row["tasks"]),
                _format_list(row["paths"]),
            ]
            for row in payload["tools"]
        ]
        lines.append(
            render_table(["tool", "calls", "ok", "failed", "tasks", "paths"], table_rows)
        )
        lines.append("")
    totals = payload["totals"]
    lines.extend(
        [
            _stat("tool kinds", str(totals["tool_kinds"])),
            _stat(
                "calls",
                f"{totals['calls']} ({totals['ok']} ok, {totals['failed']} failed)",
            ),
            _stat("run dir", str(payload["run_dir"])),
            "",
            payload["note"],
            "",
        ]
    )
    return "\n".join(lines)


def _format_list(items: list[str]) -> str:
    if not items:
        return "-"
    return ", ".join(items)


def _stat(label: str, value: str) -> str:
    return f"{label:<{_STAT_WIDTH}}{value}"
