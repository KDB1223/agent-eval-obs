"""Wall-clock timing for a saved run, read from trajectory timestamps.

Reads ``trajectory.jsonl`` only. The agent is not re-run. A timestamp counts
only when ``ts`` parses as an aware datetime. The original string is kept.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from aeo import __version__
from aeo.failures import selected_tasks
from aeo.jsonl import read_jsonl
from aeo.scoreboard import render_table

_NOTE = "Computed from the JSONL log. The agent was not re-run."
_STAT_WIDTH = 14
_COLUMNS = ["task", "result", "score", "events", "started", "ended", "duration_ms", "unparsed"]


def render_timing(
    summary: dict,
    run_dir: Path,
    task_id: str | None = None,
    fmt: str = "text",
) -> str:
    """Render a text or JSON timing report for the selected tasks."""
    payload = collect_timing(summary, run_dir, task_id=task_id)
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return _render_text(summary, payload)


def collect_timing(summary: dict, run_dir: Path, task_id: str | None = None) -> dict:
    """Span each selected task, then the selection, from saved ``ts`` values.

    Tasks stay in summary order. Inside a trajectory, events stay in file
    order. ``started`` and ``ended`` are the original strings of the first
    and last parseable timestamps in that walk, not the earliest and latest
    instants. ``duration_ms`` is ``0`` when the end is earlier than or equal
    to the start, and ``None`` when either end is missing. A missing or
    empty trajectory has no timing and is not an error.
    """
    selected = selected_tasks(summary, task_id)
    rows: list[dict] = []
    run_start: tuple[str, datetime] | None = None
    run_end: tuple[str, datetime] | None = None
    for task in selected:
        row, started, ended = _task_timing(task, run_dir)
        rows.append(row)
        if started is not None and run_start is None:
            run_start = started
        if ended is not None:
            run_end = ended
    return {
        "version": __version__,
        "run_id": summary["run_id"],
        "adapter": summary.get("adapter") or "",
        "model": summary.get("model") or "",
        "run_dir": str(run_dir),
        "tasks": rows,
        "totals": {
            "tasks_shown": len(rows),
            "events": sum(row["events"] for row in rows),
            "unparsed_ts": sum(row["unparsed_ts"] for row in rows),
            "with_timing": sum(1 for row in rows if row["duration_ms"] is not None),
            "started": None if run_start is None else run_start[0],
            "ended": None if run_end is None else run_end[0],
            "duration_ms": None
            if run_start is None or run_end is None
            else _duration_ms(run_start[1], run_end[1]),
        },
        "note": _NOTE,
    }


def _task_timing(
    task: dict,
    run_dir: Path,
) -> tuple[dict, tuple[str, datetime] | None, tuple[str, datetime] | None]:
    name = str(task["task_id"])
    path = run_dir / "tasks" / name / "trajectory.jsonl"
    started: tuple[str, datetime] | None = None
    ended: tuple[str, datetime] | None = None
    if path.is_file():
        events = read_jsonl(path)
        unparsed = 0
        for event in events:
            parsed = _parse_ts(event.get("ts"))
            if parsed is None:
                unparsed += 1
                continue
            mark = (event["ts"], parsed)
            if started is None:
                started = mark
            ended = mark
        has_trajectory = True
        n_events = len(events)
    else:
        unparsed = 0
        has_trajectory = False
        n_events = 0
    passed = bool(task.get("passed"))
    duration = None
    if started is not None and ended is not None:
        duration = _duration_ms(started[1], ended[1])
    row = {
        "task_id": task["task_id"],
        "category": str(task.get("category") or ""),
        "result": "PASS" if passed else "FAIL",
        "passed": passed,
        "score": float(task["score"]),
        "events": n_events,
        "unparsed_ts": unparsed,
        "started": None if started is None else started[0],
        "ended": None if ended is None else ended[0],
        "duration_ms": duration,
        "has_trajectory": has_trajectory,
    }
    return row, started, ended


def _parse_ts(value: object) -> datetime | None:
    """Parse an aware ISO-8601 ``ts``. Anything else is unusable."""
    if not isinstance(value, str) or value == "":
        return None
    text = value[:-1] + "+00:00" if value.endswith(("Z", "z")) else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return None
    return parsed


def _duration_ms(start: datetime, end: datetime) -> int:
    """Whole milliseconds from ``start`` to ``end``, or 0 when not positive."""
    delta = end - start
    micros = (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds
    if micros <= 0:
        return 0
    return micros // 1_000


def _render_text(summary: dict, payload: dict) -> str:
    model = summary.get("model") or summary.get("adapter") or ""
    rows = [
        [
            str(row["task_id"]),
            str(row["result"]),
            f"{float(row['score']):.2f}",
            str(row["events"]),
            _dash(row["started"]),
            _dash(row["ended"]),
            _dash_duration(row["duration_ms"]),
            str(row["unparsed_ts"]),
        ]
        for row in payload["tasks"]
    ]
    totals = payload["totals"]
    lines = [
        (
            f"agent-eval-obs {__version__}  "
            f"run {summary['run_id']}  "
            f"adapter={summary.get('adapter') or ''}  "
            f"model={model}"
        ),
        "",
        render_table(_COLUMNS, rows),
        "",
        _stat("with timing", f"{totals['with_timing']}/{totals['tasks_shown']}"),
        _stat("events", str(totals["events"])),
        _stat("unparsed_ts", str(totals["unparsed_ts"])),
        _stat("started", _dash(totals["started"])),
        _stat("ended", _dash(totals["ended"])),
        _stat("duration_ms", _dash_duration(totals["duration_ms"])),
        _stat("run dir", str(payload["run_dir"])),
        "",
        payload["note"],
        "",
    ]
    return "\n".join(lines)


def _dash(value: object) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _dash_duration(value: object) -> str:
    """``0`` is a computed duration. A missing duration stays ``-``."""
    if value is None:
        return "-"
    return str(value)


def _stat(label: str, value: str) -> str:
    return f"{label:<{_STAT_WIDTH}}{value}"
