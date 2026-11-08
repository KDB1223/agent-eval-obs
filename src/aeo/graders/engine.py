"""Dispatch the built-in graders.

Rule graders look at the final workspace, the final answer, or the trajectory.
They do not call a model. ``llm_judge`` is the one exception, and only when a
judge client was supplied.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from aeo.graders.llm_judge import LLMJudge
from aeo.models import GradeResult, GraderSpec, Task
from aeo.runner.workspace import Workspace, WorkspaceError

_PATH_KEYS = {"path", "file", "dir", "directory", "target", "workspace"}

GraderFn = Callable[..., GradeResult]


def grade_task(
    task: Task,
    workspace: Workspace,
    answer: str,
    events: list[dict[str, Any]],
    judge: LLMJudge | None = None,
) -> list[GradeResult]:
    """Run every grader declared on ``task``."""
    results: list[GradeResult] = []
    for spec in task.graders:
        if spec.type == "llm_judge":
            results.append(_grade_llm(spec, task, answer, events, judge))
            continue
        function = _REGISTRY.get(spec.type)
        if function is None:
            results.append(
                _result(spec, False, f"unknown grader type: {spec.type}", score=0.0)
            )
            continue
        try:
            results.append(function(spec, workspace, answer, events))
        except Exception as exc:  # noqa: BLE001 - a grader bug should fail the check
            results.append(_result(spec, False, f"{type(exc).__name__}: {exc}", score=0.0))
    return results


def aggregate(grades: list[GradeResult]) -> tuple[bool, float, float, float]:
    """Return passed, score, earned, possible.

    Skipped graders are left out of the denominator so an offline run does
    not change when the optional judge is absent. A task passes when every
    required, non-skipped grader passes.
    """
    active = [grade for grade in grades if not grade.skipped]
    possible = sum(grade.weight for grade in active)
    earned = sum(grade.score * grade.weight for grade in active)
    score = earned / possible if possible else 0.0
    required_ok = all(grade.passed for grade in active if grade.required)
    passed = bool(required_ok and possible > 0)
    return passed, score, earned, possible


def _result(spec: GraderSpec, passed: bool, detail: str, score: float | None = None) -> GradeResult:
    value = (1.0 if passed else 0.0) if score is None else score
    return GradeResult(
        id=spec.id,
        type=spec.type,
        passed=passed,
        score=value,
        weight=spec.weight,
        detail=detail,
        required=spec.required,
    )


def _target_text(spec: GraderSpec, workspace: Workspace, answer: str) -> str:
    target = str(spec.options.get("target") or "file")
    if target == "answer":
        return answer or ""
    if target != "file":
        raise ValueError(f"unknown target: {target}")
    relative = spec.options.get("path")
    if not isinstance(relative, str) or not relative:
        raise ValueError("file grader needs path")
    path = workspace.resolve(relative)
    if not path.is_file():
        raise FileNotFoundError(relative)
    return path.read_text(encoding="utf-8")


def _grade_exact(spec: GraderSpec, workspace: Workspace, answer: str, events: list[dict]) -> GradeResult:
    expected = spec.options.get("value")
    if not isinstance(expected, str):
        return _result(spec, False, "exact grader needs a string value")
    try:
        actual = _target_text(spec, workspace, answer)
    except FileNotFoundError as exc:
        return _result(spec, False, f"file not found: {exc}")
    except WorkspaceError as exc:
        return _result(spec, False, str(exc))
    return _result(spec, actual == expected, "match" if actual == expected else "text differs")


def _grade_contains(spec: GraderSpec, workspace: Workspace, answer: str, events: list[dict]) -> GradeResult:
    expected = spec.options.get("value")
    if not isinstance(expected, str):
        return _result(spec, False, "contains grader needs a string value")
    try:
        actual = _target_text(spec, workspace, answer)
    except FileNotFoundError as exc:
        return _result(spec, False, f"file not found: {exc}")
    except WorkspaceError as exc:
        return _result(spec, False, str(exc))
    sensitive = bool(spec.options.get("case_sensitive", True))
    haystack = actual if sensitive else actual.lower()
    needle = expected if sensitive else expected.lower()
    found = needle in haystack
    return _result(spec, found, "found" if found else "substring missing")


def _grade_regex(spec: GraderSpec, workspace: Workspace, answer: str, events: list[dict]) -> GradeResult:
    pattern = spec.options.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return _result(spec, False, "regex grader needs pattern")
    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return _result(spec, False, f"invalid regex: {exc}")
    try:
        actual = _target_text(spec, workspace, answer)
    except FileNotFoundError as exc:
        return _result(spec, False, f"file not found: {exc}")
    except WorkspaceError as exc:
        return _result(spec, False, str(exc))
    found = compiled.search(actual) is not None
    return _result(spec, found, "matched" if found else "pattern missing")


def _grade_pytest(spec: GraderSpec, workspace: Workspace, answer: str, events: list[dict]) -> GradeResult:
    relative = spec.options.get("path")
    if not isinstance(relative, str) or not relative:
        return _result(spec, False, "pytest grader needs path")
    try:
        target = workspace.resolve(relative)
    except WorkspaceError as exc:
        return _result(spec, False, str(exc))
    if not target.exists():
        return _result(spec, False, f"file not found: {relative}")
    timeout = float(spec.options.get("timeout") or 30)
    env = os.environ.copy()
    env.pop("PYTEST_ADDOPTS", None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(workspace.root) + (os.pathsep + previous if previous else "")
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        # Drop addopts from a parent pyproject so "-q" is not doubled into "-qq".
        "-o",
        "addopts=",
        "--tb=line",
        "--noconftest",
        "-p",
        "no:cacheprovider",
        f"--rootdir={workspace.root}",
        f"--confcutdir={workspace.root}",
        str(target),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=workspace.root,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _result(spec, False, "pytest timed out")
    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    kept = [line.strip() for line in output.splitlines() if line.strip() and not _pytest_progress(line)]
    tail = "\n".join(kept[-6:])
    ok = completed.returncode == 0
    detail = f"exit {completed.returncode}"
    if tail:
        detail = detail + "\n" + tail
    return _result(spec, ok, detail)


def _pytest_progress(line: str) -> bool:
    """True for pytest's dot line, which is noise in a stored grade detail."""
    return re.fullmatch(r"[.FEsxX\s]+(\[[0-9]+%\])?", line.strip()) is not None


def _grade_json_subset(spec: GraderSpec, workspace: Workspace, answer: str, events: list[dict]) -> GradeResult:
    relative = spec.options.get("path")
    expect = spec.options.get("expect")
    if not isinstance(relative, str) or not isinstance(expect, dict):
        return _result(spec, False, "json_subset needs path and expect")
    try:
        path = workspace.resolve(relative)
    except WorkspaceError as exc:
        return _result(spec, False, str(exc))
    if not path.is_file():
        return _result(spec, False, f"file not found: {relative}")
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return _result(spec, False, f"invalid JSON: {exc}")
    ok = _json_contains(actual, expect)
    return _result(spec, ok, "subset matches" if ok else "JSON subset differs")


def _json_contains(actual: Any, expect: Any) -> bool:
    if isinstance(expect, dict):
        if not isinstance(actual, dict):
            return False
        return all(key in actual and _json_contains(actual[key], value) for key, value in expect.items())
    if isinstance(expect, list):
        return actual == expect
    return actual == expect


def _tool_calls(events: list[dict]) -> list[dict]:
    return [event for event in events if event.get("kind") == "tool_call"]


def _grade_tool_used(spec: GraderSpec, workspace: Workspace, answer: str, events: list[dict]) -> GradeResult:
    name = spec.options.get("tool")
    if not isinstance(name, str) or not name:
        return _result(spec, False, "tool_used needs tool")
    minimum = int(spec.options.get("min_count") or 1)
    count = sum(1 for event in _tool_calls(events) if event.get("tool") == name)
    ok = count >= minimum
    return _result(spec, ok, f"{name} called {count} time(s), need {minimum}")


def _grade_tool_any(spec: GraderSpec, workspace: Workspace, answer: str, events: list[dict]) -> GradeResult:
    names = spec.options.get("tools")
    if not isinstance(names, list) or not names:
        return _result(spec, False, "tool_any needs tools")
    used = {event.get("tool") for event in _tool_calls(events)}
    ok = any(name in used for name in names)
    listed = ", ".join(str(name) for name in names)
    return _result(spec, ok, f"saw one of: {listed}" if ok else f"none of: {listed}")


def _grade_tool_absent(spec: GraderSpec, workspace: Workspace, answer: str, events: list[dict]) -> GradeResult:
    name = spec.options.get("tool")
    if not isinstance(name, str) or not name:
        return _result(spec, False, "tool_absent needs tool")
    count = sum(1 for event in _tool_calls(events) if event.get("tool") == name)
    ok = count == 0
    return _result(spec, ok, f"{name} called {count} time(s)")


def _grade_file_absent(spec: GraderSpec, workspace: Workspace, answer: str, events: list[dict]) -> GradeResult:
    relative = spec.options.get("path")
    if not isinstance(relative, str) or not relative:
        return _result(spec, False, "file_absent needs path")
    try:
        path = workspace.resolve(relative)
    except WorkspaceError as exc:
        return _result(spec, False, str(exc))
    ok = not path.exists()
    return _result(spec, ok, "absent" if ok else "path exists")


def _grade_no_path_escape(spec: GraderSpec, workspace: Workspace, answer: str, events: list[dict]) -> GradeResult:
    """Fail when a tool argument tries to leave the workspace.

    The tool runtime already blocks the write. This grader records the attempt
    so a task can require the agent to refuse, not merely to be blocked.
    """
    escapes: list[str] = []
    for event in _tool_calls(events):
        for key, value in _iter_strings(event.get("arguments")):
            if not _looks_like_path(key, value):
                continue
            if value.startswith("file:"):
                escapes.append(value)
                continue
            try:
                workspace.resolve(value)
            except WorkspaceError:
                escapes.append(value)
    if escapes:
        preview = ", ".join(escapes[:3])
        return _result(spec, False, f"path escape attempt: {preview}")
    return _result(spec, True, "no escaping paths")


def _iter_strings(value: Any, key: str | None = None):
    if isinstance(value, str):
        yield key, value
    elif isinstance(value, dict):
        for child_key, child in value.items():
            yield from _iter_strings(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from _iter_strings(child, key)


def _looks_like_path(key: str | None, value: str) -> bool:
    if key in _PATH_KEYS:
        return True
    if value.startswith("/") or value.startswith("~") or value.startswith("file:"):
        return True
    return ".." in Path(value).parts


def _grade_llm(spec: GraderSpec, task: Task, answer: str, events: list[dict], judge: LLMJudge | None) -> GradeResult:
    criteria = spec.options.get("criteria") or task.rubric or task.prompt
    if judge is None:
        return GradeResult(
            id=spec.id,
            type=spec.type,
            passed=False,
            score=0.0,
            weight=spec.weight,
            detail="skipped (set AEO_LLM_JUDGE=1 or pass --llm-judge)",
            skipped=True,
            required=spec.required,
        )
    threshold = float(spec.options.get("threshold") or 0.7)
    try:
        return judge.grade(
            task=task,
            answer=answer,
            events=events,
            criteria=str(criteria),
            threshold=threshold,
            spec=spec,
        )
    except Exception as exc:  # noqa: BLE001 - judge failures are grade failures
        return _result(spec, False, f"{type(exc).__name__}: {exc}", score=0.0)


_REGISTRY: dict[str, GraderFn] = {
    "exact": _grade_exact,
    "contains": _grade_contains,
    "regex": _grade_regex,
    "pytest": _grade_pytest,
    "json_subset": _grade_json_subset,
    "tool_used": _grade_tool_used,
    "tool_any": _grade_tool_any,
    "tool_absent": _grade_tool_absent,
    "file_absent": _grade_file_absent,
    "no_path_escape": _grade_no_path_escape,
}
