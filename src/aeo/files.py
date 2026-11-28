"""Path inventory for a saved run, grouped by recorded path.

Reads ``trajectory.jsonl`` only. The agent is not re-run, and files left
in a task workspace are not scanned. A call id is paired with the same
coercion as :func:`aeo.stats._call_id`. The path is the same non-empty
``arguments.path`` string :func:`aeo.tools._argument_path` returns.
"""

from __future__ import annotations

import json
from pathlib import Path

from aeo import __version__
from aeo.failures import selected_tasks
from aeo.jsonl import read_jsonl
from aeo.scoreboard import render_table
from aeo.stats import _call_id
from aeo.tools import _argument_path, _succeeded, _tool_name

_MISSING_PATH = "(missing)"
_NOTE = "Computed from the JSONL log. The agent was not re-run."
_STAT_WIDTH = 14


def render_files(
    summary: dict,
    run_dir: Path,
    task_id: str | None = None,
    fmt: str = "text",
) -> str:
    """Render a text or JSON inventory of recorded paths for the selected tasks."""
    payload = collect_files(summary, run_dir, task_id=task_id)
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return _render_text(summary, payload)


def collect_files(summary: dict, run_dir: Path, task_id: str | None = None) -> dict:
    """Count tool calls by recorded path, in summary order then trajectory order.

    Only ``kind == "tool_call"`` events are calls. An observation counts
    toward a call when it shares that call's id; the last such observation
    in the file decides. The call succeeded only when that observation has
    ``ok is True``. A missing id, no observation, or any other ``ok`` value
    is a failure. Observations with no matching call are ignored.

    The path is ``arguments.path`` when that value is a non-empty string,
    kept exactly as written. A missing, empty, or non-string path is
    ``(missing)``. Rows, tool names, and task ids stay in first-seen order.
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
        "files": rows,
        "totals": {
            "path_kinds": len(rows),
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
        path = _argument_path(event)
        if path is None:
            path = _MISSING_PATH
        row = index.get(path)
        if row is None:
            row = {
                "path": path,
                "calls": 0,
                "ok": 0,
                "failed": 0,
                "tools": [],
                "tasks": [],
            }
            index[path] = row
            rows.append(row)
        row["calls"] += 1
        if _succeeded(event, last_obs):
            row["ok"] += 1
        else:
            row["failed"] += 1
        tool = _tool_name(event)
        if tool not in row["tools"]:
            row["tools"].append(tool)
        if task_id not in row["tasks"]:
            row["tasks"].append(task_id)


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
    if not payload["files"]:
        lines.append("no files")
        lines.append("")
    else:
        table_rows = [
            [
                str(row["path"]),
                str(row["calls"]),
                str(row["ok"]),
                str(row["failed"]),
                _format_list(row["tools"]),
                _format_list(row["tasks"]),
            ]
            for row in payload["files"]
        ]
        lines.append(
            render_table(["path", "calls", "ok", "failed", "tools", "tasks"], table_rows)
        )
        lines.append("")
    totals = payload["totals"]
    lines.extend(
        [
            _stat("path kinds", str(totals["path_kinds"])),
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
