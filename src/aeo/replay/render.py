"""Print a trajectory from JSONL without re-running the agent."""

from __future__ import annotations

import json
from pathlib import Path

from aeo.errors import UsageError
from aeo.jsonl import read_jsonl


def render_run(run_dir: Path, task_id: str | None = None, fmt: str = "text") -> str:
    """Render one task, or every task that has a trajectory."""
    paths = _trajectory_paths(run_dir, task_id)
    if fmt == "json":
        payload = []
        for path in paths:
            payload.append({"task_id": path.parent.name, "events": read_jsonl(path)})
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    parts = [render_trajectory(read_jsonl(path), path.parent.name) for path in paths]
    return "\n".join(parts)


def render_trajectory(events: list[dict], task_id: str) -> str:
    """Render one trajectory as a readable transcript."""
    lines = [f"# task {task_id}"]
    for event in events:
        kind = event.get("kind")
        if kind == "prompt":
            lines.extend(["", "[prompt]", str(event.get("content") or "")])
        elif kind == "thought":
            lines.extend(["", f"[step {event.get('step')} thought]", str(event.get("content") or "")])
        elif kind == "tool_call":
            args = json.dumps(event.get("arguments") or {}, ensure_ascii=False, sort_keys=True)
            lines.extend(["", f"[step {event.get('step')} tool_call] {event.get('tool')} {args}"])
        elif kind == "observation":
            status = "ok" if event.get("ok") else "error"
            lines.append(f"[step {event.get('step')} observation] {event.get('tool')} {status}")
            lines.append(str(event.get("content") or ""))
        elif kind == "final":
            lines.extend(["", "[final]", str(event.get("content") or "")])
        elif kind == "grade":
            if event.get("skipped"):
                flag = "SKIP"
            else:
                flag = "PASS" if event.get("passed") else "FAIL"
            lines.append(
                f"[grade] {event.get('id')} {event.get('type')} {flag} "
                f"score={event.get('score')} weight={event.get('weight')}"
            )
            detail = event.get("detail")
            if detail:
                for detail_line in str(detail).splitlines():
                    lines.append(f"        {detail_line}")
        elif kind == "task_end":
            flag = "PASS" if event.get("passed") else "FAIL"
            lines.extend(["", f"[task_end] {flag} score={float(event.get('score') or 0):.2f}"])
        elif kind == "error":
            lines.extend(["", f"[error] {event.get('content')}"])
        elif kind == "external_start":
            lines.extend(["", "[external] " + " ".join(str(part) for part in event.get("argv") or [])])
        elif kind == "external":
            lines.append(f"[external] {event.get('source')}")
        elif kind in {"task_start"}:
            continue
    lines.extend(["", "# replay complete (events printed from the log; the agent was not re-run)", ""])
    return "\n".join(lines)


def _trajectory_paths(run_dir: Path, task_id: str | None) -> list[Path]:
    tasks_dir = run_dir / "tasks"
    if task_id:
        path = tasks_dir / task_id / "trajectory.jsonl"
        if not path.is_file():
            raise UsageError(f"no trajectory for task {task_id} in {run_dir}")
        return [path]
    if not tasks_dir.is_dir():
        raise UsageError(f"no trajectories in {run_dir}")
    paths = sorted(tasks_dir.glob("*/trajectory.jsonl"))
    if not paths:
        raise UsageError(f"no trajectories in {run_dir}")
    return paths
