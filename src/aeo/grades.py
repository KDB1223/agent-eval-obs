"""Grader inventory for every task in a saved run. The agent is not re-run."""

from __future__ import annotations

import json
from pathlib import Path

from aeo import __version__
from aeo.failures import (
    classify_grades,
    format_grader_rollup,
    format_graders,
    resolve_grades,
    rollup_failed_graders,
    selected_tasks,
)
from aeo.scoreboard import render_table

_NOTE = "Read from the saved run. The agent was not re-run."
_STAT_WIDTH = 14


def render_grades(
    summary: dict,
    run_dir: Path,
    task_id: str | None = None,
    fmt: str = "text",
) -> str:
    """Render a text or JSON inventory of grader outcomes for every task."""
    payload = collect_grades(summary, run_dir, task_id=task_id)
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return _render_text(summary, payload)


def collect_grades(summary: dict, run_dir: Path, task_id: str | None = None) -> dict:
    """List every selected task in summary order, including tasks that passed.

    Grades come from :func:`aeo.failures.resolve_grades`. Passed, failed, and
    skipped follow :func:`aeo.failures.classify_grades`. Nothing is re-graded.
    """
    selected = selected_tasks(summary, task_id)
    rows = [_task_row(task, run_dir) for task in selected]
    passed_tasks = sum(1 for row in rows if row["passed"])
    return {
        "version": __version__,
        "run_id": summary["run_id"],
        "adapter": summary.get("adapter") or "",
        "model": summary.get("model") or "",
        "run_dir": str(run_dir),
        "tasks": rows,
        "passed": passed_tasks,
        "failed": len(rows) - passed_tasks,
        "considered": len(selected),
        "grade_totals": {
            "passed": sum(len(row["passed_grades"]) for row in rows),
            "failed": sum(len(row["failed_grades"]) for row in rows),
            "skipped": sum(len(row["skipped_grades"]) for row in rows),
        },
        "failed_graders": rollup_failed_graders(rows),
        "note": _NOTE,
    }


def _task_row(task: dict, run_dir: Path) -> dict:
    passed_grades, failed, skipped = classify_grades(resolve_grades(task, run_dir))
    passed = bool(task.get("passed"))
    return {
        "task_id": task["task_id"],
        "category": str(task.get("category") or ""),
        "result": "PASS" if passed else "FAIL",
        "passed": passed,
        "score": float(task["score"]),
        "passed_grades": passed_grades,
        "failed_grades": failed,
        "skipped_grades": skipped,
    }


def _render_text(summary: dict, payload: dict) -> str:
    model = summary.get("model") or summary.get("adapter") or ""
    rows = [
        [
            str(row["task_id"]),
            str(row["category"]),
            str(row["result"]),
            f"{float(row['score']):.2f}",
            format_graders(row["passed_grades"]),
            format_graders(row["failed_grades"]),
            format_graders(row["skipped_grades"]),
        ]
        for row in payload["tasks"]
    ]
    totals = payload["grade_totals"]
    lines = [
        (
            f"agent-eval-obs {__version__}  "
            f"run {summary['run_id']}  "
            f"adapter={summary.get('adapter') or ''}  "
            f"model={model}"
        ),
        "",
        render_table(
            ["task", "category", "result", "score", "passed graders", "failed graders", "skipped"],
            rows,
        ),
        "",
        _stat("passed", f"{payload['passed']}/{payload['considered']}"),
        _stat("failed", f"{payload['failed']}/{payload['considered']}"),
        _stat(
            "grades",
            f"{totals['passed']} passed, {totals['failed']} failed, {totals['skipped']} skipped",
        ),
    ]
    rollup = format_grader_rollup(payload["failed_graders"])
    if rollup:
        lines.append(_stat("graders", rollup))
    lines.extend(
        [
            _stat("run dir", str(payload["run_dir"])),
            "",
            _NOTE,
            "",
        ]
    )
    return "\n".join(lines)


def _stat(label: str, value: str) -> str:
    return f"{label:<{_STAT_WIDTH}}{value}"
