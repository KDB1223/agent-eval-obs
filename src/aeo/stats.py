"""Tool-use totals for a saved run, read from JSONL. The agent is not re-run."""

from __future__ import annotations

import json
from pathlib import Path

from aeo import __version__
from aeo.errors import UsageError
from aeo.jsonl import read_jsonl
from aeo.scoreboard import render_table

_EDIT_TOOLS = frozenset({"edit_file", "write_file"})
_NOTE = "Computed from the JSONL log. The agent was not re-run."


def render_stats(
    summary: dict,
    run_dir: Path,
    task_id: str | None = None,
    fmt: str = "text",
) -> str:
    """Render text or JSON stats for the tasks selected from ``summary``."""
    payload = summarize_run(summary, run_dir, task_id=task_id)
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return _render_text(summary, payload)


def summarize_run(summary: dict, run_dir: Path, task_id: str | None = None) -> dict:
    """Count tool calls, successful edits, and final events for one saved run."""
    selected = _selected_tasks(summary, task_id)
    rows = [_task_row(task, run_dir) for task in selected]
    return {
        "version": __version__,
        "run_id": summary["run_id"],
        "adapter": summary.get("adapter") or "",
        "model": summary.get("model") or "",
        "run_dir": str(run_dir),
        "tasks": rows,
        "tool_calls": sum(row["tool_calls"] for row in rows),
        "with_final": sum(1 for row in rows if row["final"]),
        "tasks_shown": len(rows),
        "note": _NOTE,
    }


def _selected_tasks(summary: dict, task_id: str | None) -> list[dict]:
    tasks = list(summary["tasks"])
    if task_id is None:
        return tasks
    selected = [task for task in tasks if task.get("task_id") == task_id]
    if not selected:
        raise UsageError(f"task not found in run: {task_id}")
    return selected


def _task_row(task: dict, run_dir: Path) -> dict:
    path = run_dir / "tasks" / str(task["task_id"]) / "trajectory.jsonl"
    events = read_jsonl(path) if path.is_file() else []
    tools, files, ended, n_calls = _trajectory_stats(events)
    passed = bool(task.get("passed"))
    return {
        "task_id": task["task_id"],
        "category": task.get("category") or "",
        "result": "PASS" if passed else "FAIL",
        "passed": passed,
        "score": float(task["score"]),
        "tools": tools,
        "tool_calls": n_calls,
        "files": files,
        "final": ended,
    }


def _trajectory_stats(events: list[dict]) -> tuple[dict[str, int], list[str], bool, int]:
    """Named tool counts, edited paths, a final event, and the call total."""
    counts: dict[str, int] = {}
    calls: dict[str, dict] = {}
    files: list[str] = []
    seen: set[str] = set()
    ended = False
    n_calls = 0
    for event in events:
        kind = event.get("kind")
        if kind == "tool_call":
            n_calls += 1
            name = event.get("tool")
            if isinstance(name, str) and name:
                counts[name] = counts.get(name, 0) + 1
            call_id = _call_id(event)
            if call_id is not None:
                calls[call_id] = event
        elif kind == "final":
            ended = True
        elif kind == "observation":
            edited = _edited_path(event, calls)
            if edited is not None and edited not in seen:
                seen.add(edited)
                files.append(edited)
    tools = {name: counts[name] for name in sorted(counts)}
    return tools, files, ended, n_calls


def _edited_path(observation: dict, calls: dict[str, dict]) -> str | None:
    """Path from a successful edit_file or write_file observation, else None."""
    if observation.get("ok") is not True:
        return None
    if observation.get("tool") not in _EDIT_TOOLS:
        return None
    call_id = _call_id(observation)
    if call_id is None:
        return None
    call = calls.get(call_id)
    if call is None or call.get("tool") not in _EDIT_TOOLS:
        return None
    arguments = call.get("arguments")
    if not isinstance(arguments, dict):
        return None
    path = arguments.get("path")
    if not isinstance(path, str) or path == "":
        return None
    return path


def _call_id(event: dict) -> str | None:
    call_id = event.get("call_id")
    if isinstance(call_id, str) and call_id:
        return call_id
    if isinstance(call_id, int) and not isinstance(call_id, bool):
        return str(call_id)
    return None


def _render_text(summary: dict, payload: dict) -> str:
    rows = [
        [
            str(row["task_id"]),
            str(row["result"]),
            f"{float(row['score']):.2f}",
            _format_tools(row["tools"]),
            _format_files(row["files"]),
            "yes" if row["final"] else "no",
        ]
        for row in payload["tasks"]
    ]
    table = render_table(["task", "result", "score", "tools", "files", "final"], rows)
    model = summary.get("model") or summary.get("adapter") or ""
    lines = [
        (
            f"agent-eval-obs {__version__}  "
            f"run {summary['run_id']}  "
            f"adapter={summary.get('adapter') or ''}  "
            f"model={model}"
        ),
        "",
        table,
        "",
        f"tool calls    {payload['tool_calls']}",
        f"with final    {payload['with_final']}/{payload['tasks_shown']}",
        f"trajectories  {payload['run_dir']}",
        "",
        _NOTE,
        "",
    ]
    return "\n".join(lines)


def _format_tools(tools: dict[str, int]) -> str:
    if not tools:
        return "-"
    return ", ".join(f"{name}:{tools[name]}" for name in sorted(tools))


def _format_files(files: list[str]) -> str:
    if not files:
        return "-"
    return ", ".join(files)
