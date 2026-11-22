"""Failed tasks in a saved run, with the graders that failed. The agent is not re-run."""

from __future__ import annotations

import json
from pathlib import Path

from aeo import __version__
from aeo.errors import RunError, UsageError
from aeo.jsonl import read_jsonl
from aeo.scoreboard import render_table

_NOTE = "Read from the saved run. The agent was not re-run."
_STAT_WIDTH = 14


def render_failures(
    summary: dict,
    run_dir: Path,
    task_id: str | None = None,
    fmt: str = "text",
) -> str:
    """Render a text or JSON inventory of tasks that did not pass."""
    payload = collect_failures(summary, run_dir, task_id=task_id)
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return _render_text(summary, payload)


def collect_failures(summary: dict, run_dir: Path, task_id: str | None = None) -> dict:
    """List failed tasks in summary order. Passing tasks are omitted."""
    selected = selected_tasks(summary, task_id)
    rows = [_task_row(task, run_dir) for task in selected if not task.get("passed")]
    return {
        "version": __version__,
        "run_id": summary["run_id"],
        "adapter": summary.get("adapter") or "",
        "model": summary.get("model") or "",
        "run_dir": str(run_dir),
        "tasks": rows,
        "failed": len(rows),
        "considered": len(selected),
        "passed": len(selected) - len(rows),
        "failed_graders": rollup_failed_graders(rows),
        "note": _NOTE,
    }


def selected_tasks(summary: dict, task_id: str | None) -> list[dict]:
    """Tasks in summary order, or the one named by ``task_id``.

    An unknown id is a usage error. ``aeo grades`` uses the same selection.
    """
    tasks = list(summary["tasks"])
    if task_id is None:
        return tasks
    selected = [task for task in tasks if task.get("task_id") == task_id]
    if not selected:
        raise UsageError(f"task not found in run: {task_id}")
    return selected


def _task_row(task: dict, run_dir: Path) -> dict:
    grades = resolve_grades(task, run_dir)
    failed, skipped = _split_grades(grades)
    error = _task_error(task)
    return {
        "task_id": task["task_id"],
        "category": str(task.get("category") or ""),
        "score": float(task["score"]),
        "error": error,
        "detail": _detail_text(failed, error),
        "failed_grades": failed,
        "skipped_grades": skipped,
    }


def resolve_grades(task: dict, run_dir: Path) -> list[dict]:
    """First non-empty source wins: summary, then result.json, then trajectory.

    An empty ``grades`` list does not count. When none of the sources has
    grades, the list is empty and no grader id is invented.
    """
    from_summary = _take_grades(task.get("grades"))
    if from_summary is not None:
        return from_summary
    task_dir = run_dir / "tasks" / str(task["task_id"])
    result_path = task_dir / "result.json"
    if result_path.is_file():
        payload = _read_json(result_path)
        if isinstance(payload, dict):
            from_result = _take_grades(payload.get("grades"))
            if from_result is not None:
                return from_result
    trajectory = task_dir / "trajectory.jsonl"
    if trajectory.is_file():
        return [event for event in read_jsonl(trajectory) if event.get("kind") == "grade"]
    return []


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RunError(f"{path}: invalid JSON ({exc})") from exc


def _take_grades(value: object) -> list[dict] | None:
    """A non-empty grade list stops the search. Other values try the next source."""
    if not isinstance(value, list) or not value:
        return None
    return [item for item in value if isinstance(item, dict)]


def classify_grades(grades: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split grades into passed, failed, and skipped.

    A grade is skipped when ``skipped`` is true, even if ``passed`` is also
    true. A remaining grade is passed only when ``passed`` is true. Anything
    else failed. ``aeo failures`` drops the passed list; ``aeo grades`` keeps it.
    """
    passed: list[dict] = []
    failed: list[dict] = []
    skipped: list[dict] = []
    for grade in grades:
        if grade.get("skipped"):
            skipped.append(grade)
            continue
        if grade.get("passed") is True:
            passed.append(grade)
            continue
        failed.append(grade)
    return passed, failed, skipped


def _split_grades(grades: list[dict]) -> tuple[list[dict], list[dict]]:
    """Skipped grades are separate. Anything else whose ``passed`` is not true failed."""
    _passed, failed, skipped = classify_grades(grades)
    return failed, skipped


def _task_error(task: dict) -> str | None:
    error = task.get("error")
    if not isinstance(error, str):
        return None
    stripped = error.strip()
    if not stripped:
        return None
    return stripped


def _detail_text(failed: list[dict], error: str | None) -> str | None:
    """One line for the table: first failed detail, plus a task error when present.

    ``None`` means there is nothing saved to show. The text view prints ``-``.
    """
    detail = ""
    if failed:
        raw = failed[0].get("detail")
        if raw is not None:
            detail = " ".join(str(raw).split())
    error_text = " ".join(error.split()) if error else ""
    if detail and error_text:
        return f"{detail}; error: {error_text}"
    if detail:
        return detail
    if error_text:
        return f"error: {error_text}"
    return None


def rollup_failed_graders(rows: list[dict]) -> list[dict]:
    """Failed grader ids and types in first-seen order, with counts."""
    order: list[tuple[str | None, str | None]] = []
    counts: dict[tuple[str | None, str | None], int] = {}
    for row in rows:
        for grade in row["failed_grades"]:
            key = (_grade_name(grade.get("id")), _grade_name(grade.get("type")))
            if key == (None, None):
                continue
            if key not in counts:
                counts[key] = 0
                order.append(key)
            counts[key] += 1
    return [
        {"id": gid, "type": gtype, "count": counts[(gid, gtype)]}
        for gid, gtype in order
    ]


def _grade_name(value: object) -> str | None:
    if isinstance(value, str) and value != "":
        return value
    return None


def _grader_label(gid: str | None, gtype: str | None) -> str | None:
    if gid and gtype:
        return f"{gid}:{gtype}"
    return gid or gtype


def format_graders(grades: list[dict]) -> str:
    """``id:type`` labels in first-seen order. An empty list renders as ``-``.

    A repeated id and type is listed again. The footer rollup is what
    collapses those repeats.
    """
    labels: list[str] = []
    for grade in grades:
        label = _grader_label(_grade_name(grade.get("id")), _grade_name(grade.get("type")))
        if label is not None:
            labels.append(label)
    if not labels:
        return "-"
    return ", ".join(labels)


def format_grader_rollup(items: list[dict]) -> str:
    parts: list[str] = []
    for item in items:
        label = _grader_label(item.get("id"), item.get("type"))
        if label is None:
            continue
        count = int(item["count"])
        if count > 1:
            parts.append(f"{label} x{count}")
        else:
            parts.append(label)
    return ", ".join(parts)


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
    if not payload["tasks"]:
        lines.append("no failures")
        lines.append("")
        lines.append(_stat("passed", f"{payload['passed']}/{payload['considered']}"))
    else:
        rows = [
            [
                str(row["task_id"]),
                str(row["category"]),
                f"{float(row['score']):.2f}",
                format_graders(row["failed_grades"]),
                format_graders(row["skipped_grades"]),
                row["detail"] or "-",
            ]
            for row in payload["tasks"]
        ]
        lines.append(
            render_table(
                ["task", "category", "score", "failed graders", "skipped", "detail"],
                rows,
            )
        )
        lines.append("")
        lines.append(_stat("failed", f"{payload['failed']}/{payload['considered']}"))
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
