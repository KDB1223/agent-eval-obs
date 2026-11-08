"""Run a suite, record trajectories, and write the scoreboard."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any, TextIO

from aeo import __version__
from aeo.adapters.base import BaseAgentAdapter
from aeo.errors import UsageError
from aeo.graders.engine import aggregate, grade_task
from aeo.graders.llm_judge import LLMJudge
from aeo.models import AgentState, Task, TaskResult
from aeo.runner.store import Recorder, new_run_id, utc_now, validate_run_id, write_json
from aeo.runner.workspace import ToolRuntime, Workspace
from aeo.scoreboard import format_scoreboard
from aeo.suites.loader import load_suite


def run_suite(
    suite_dir: Path,
    adapter: BaseAgentAdapter,
    *,
    run_root: Path,
    run_id: str | None = None,
    task_ids: list[str] | None = None,
    force: bool = False,
    judge: LLMJudge | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> dict[str, Any]:
    """Execute ``suite_dir`` and return the summary written to disk."""
    tasks = load_suite(suite_dir, only=task_ids)
    resolved_id = validate_run_id(run_id or new_run_id())
    run_dir = run_root / resolved_id
    if run_dir.exists():
        if not force:
            raise UsageError(f"run already exists: {run_dir} (pass --force to replace it)")
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    created = utc_now()
    manifest = {
        "schema": 1,
        "run_id": resolved_id,
        "created_at": created,
        "adapter": adapter.name,
        "model": adapter.model_label,
        "suite": str(suite_dir),
        "task_ids": [task.id for task in tasks],
        "aeo_version": __version__,
        "python": sys.version.split()[0],
        "llm_judge": judge is not None,
    }
    write_json(run_dir / "manifest.json", manifest)
    err = stderr or sys.stderr
    results: list[TaskResult] = []
    total = len(tasks)
    for index, task in enumerate(tasks, 1):
        result = run_task(task, adapter, run_dir, judge)
        results.append(result)
        flag = "PASS" if result.passed else "FAIL"
        print(f"[{index}/{total}] {task.id}  {flag}  {result.score:.2f}", file=err)
    summary = _summary(resolved_id, adapter, created, results, run_dir, judge is not None)
    write_json(run_dir / "summary.json", {key: value for key, value in summary.items() if key != "run_dir"})
    board = format_scoreboard(summary)
    (run_dir / "scoreboard.txt").write_text(board, encoding="utf-8")
    print(board, file=stdout or sys.stdout, end="")
    return summary


def run_task(
    task: Task,
    adapter: BaseAgentAdapter,
    run_dir: Path,
    judge: LLMJudge | None,
) -> TaskResult:
    """Seed a workspace, drive one task, grade it, and store the trajectory."""
    task_dir = run_dir / "tasks" / task.id
    workspace_path = task_dir / "workspace"
    if workspace_path.exists():
        shutil.rmtree(workspace_path)
    workspace = Workspace(workspace_path)
    workspace.seed(task.files)
    recorder = Recorder(task_dir / "trajectory.jsonl")
    final_answer = ""
    error: str | None = None
    n_steps = 0
    try:
        recorder.write(
            {
                "kind": "task_start",
                "task_id": task.id,
                "title": task.title,
                "category": task.category,
                "adapter": adapter.name,
                "model": adapter.model_label,
            }
        )
        recorder.write({"kind": "prompt", "role": "user", "content": task.prompt})
        if adapter.owns_loop:
            outcome = adapter.run_task(task, workspace, recorder)
            final_answer = outcome.final_answer
            n_steps = outcome.n_steps
            error = outcome.error
        else:
            final_answer, n_steps, error = _in_loop(task, adapter, workspace, recorder)
    except Exception as exc:  # noqa: BLE001 - one task must not abort the suite
        error = f"{type(exc).__name__}: {exc}"
        recorder.write({"kind": "error", "content": error})
    grades = grade_task(task, workspace, final_answer, recorder.events, judge)
    for grade in grades:
        recorder.write({"kind": "grade", **grade.to_dict()})
    passed, score, earned, possible = aggregate(grades)
    recorder.write(
        {
            "kind": "task_end",
            "passed": passed,
            "score": score,
            "earned": earned,
            "possible": possible,
            "error": error,
        }
    )
    result = TaskResult(
        task_id=task.id,
        title=task.title,
        category=task.category,
        passed=passed,
        score=score,
        earned=earned,
        possible=possible,
        final_answer=final_answer,
        n_steps=n_steps,
        error=error,
        grades=grades,
    )
    write_json(task_dir / "result.json", result.to_dict())
    recorder.close()
    return result


def _in_loop(
    task: Task,
    adapter: BaseAgentAdapter,
    workspace: Workspace,
    recorder: Recorder,
) -> tuple[str, int, str | None]:
    runtime = ToolRuntime(workspace, task.tools)
    state = AgentState(task=task, workspace=workspace.root, history=[])
    adapter.begin(task)
    final_answer = ""
    error: str | None = None
    steps = 0
    for step in range(1, task.max_steps + 1):
        action = adapter.step(state)
        steps = step
        state.step = step
        if action.thought:
            recorder.write({"kind": "thought", "step": step, "content": action.thought})
        if action.kind == "final":
            final_answer = action.content
            recorder.write({"kind": "final", "step": step, "content": final_answer})
            break
        if action.kind != "tool":
            error = f"unknown action kind: {action.kind}"
            recorder.write({"kind": "error", "content": error})
            break
        call_id = action.call_id or f"call_{step}"
        arguments = _jsonable(action.arguments)
        recorder.write(
            {
                "kind": "tool_call",
                "step": step,
                "call_id": call_id,
                "tool": action.tool,
                "arguments": arguments if isinstance(arguments, dict) else {"value": arguments},
            }
        )
        observation = runtime.execute(action.tool, action.arguments if isinstance(action.arguments, dict) else {})
        content = observation.content
        if len(content) > 20_000:
            content = content[:20_000] + "\n…(truncated)"
        recorder.write(
            {
                "kind": "observation",
                "step": step,
                "call_id": call_id,
                "tool": action.tool,
                "ok": observation.ok,
                "content": content,
            }
        )
        state.history.append(
            {
                "kind": "tool_call",
                "thought": action.thought,
                "tool": action.tool,
                "arguments": action.arguments if isinstance(action.arguments, dict) else {},
                "call_id": call_id,
            }
        )
        state.history.append(
            {
                "kind": "observation",
                "call_id": call_id,
                "tool": action.tool,
                "ok": observation.ok,
                "content": content,
            }
        )
    else:
        error = f"stopped at max_steps ({task.max_steps})"
        recorder.write({"kind": "error", "content": error})
    return final_answer, steps, error


def _summary(
    run_id: str,
    adapter: BaseAgentAdapter,
    created: str,
    results: list[TaskResult],
    run_dir: Path,
    judge_on: bool,
) -> dict[str, Any]:
    passed = sum(1 for result in results if result.passed)
    total = len(results)
    mean = sum(result.score for result in results) / total if total else 0.0
    return {
        "schema": 1,
        "run_id": run_id,
        "adapter": adapter.name,
        "model": adapter.model_label,
        "created_at": created,
        "llm_judge": judge_on,
        "passed": passed,
        "total": total,
        "mean_score": mean,
        "run_dir": str(run_dir),
        "tasks": [result.to_dict() for result in results],
    }


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value
