"""Failure inventory over a saved run. The agent is not re-run."""

import json
import re
from pathlib import Path

import pytest

from aeo.cli import main
from aeo.errors import UsageError
from aeo.failures import collect_failures
from aeo.runner.store import load_summary

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "fixtures" / "runs"
BASELINE_FAILURES = ["fizzbuzz", "search-todo"]
PASSING_BASELINE = [
    "fix-sum",
    "parse-ints",
    "add-docstring",
    "read-config",
    "edit-json",
    "safe-refusal",
]


def test_baseline_and_candidate_fixtures_list_failures_without_inventing_grades(
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = FIXTURES / "baseline"
    candidate = FIXTURES / "candidate"
    before = {_rel: _snapshot(path) for _rel, path in (("baseline", baseline), ("candidate", candidate))}

    exit_code = main(["failures", str(baseline)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    text = captured.out
    assert text.startswith("agent-eval-obs 0.1.0  run baseline  adapter=fixture  model=fixture\n")
    assert "no failures" not in text
    assert "failed graders" in text
    assert "Read from the saved run. The agent was not re-run." in text
    assert "pytest" not in text
    assert "exit 0" not in text
    assert "llm_judge" not in text
    positions = [text.index(task_id) for task_id in BASELINE_FAILURES]
    assert positions == sorted(positions)
    for task_id in PASSING_BASELINE:
        assert task_id not in text
    fizzbuzz = next(line for line in text.splitlines() if line.startswith("fizzbuzz"))
    search = next(line for line in text.splitlines() if line.startswith("search-todo"))
    assert "coding" in fizzbuzz and "0.50" in fizzbuzz
    assert "tool-use" in search and "0.00" in search
    assert fizzbuzz.rstrip().endswith("-")
    assert search.rstrip().endswith("-")
    failed_line = next(line for line in text.splitlines() if line.startswith("failed"))
    assert failed_line.endswith("2/8")
    assert not any(line.startswith("graders") for line in text.splitlines())

    exit_code = main(["failures", str(baseline), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.endswith("\n")
    assert captured.out.startswith("{\n")
    payload = json.loads(captured.out)
    assert payload["version"] == "0.1.0"
    assert payload["run_id"] == "baseline"
    assert payload["adapter"] == "fixture"
    assert payload["model"] == "fixture"
    assert payload["failed"] == 2
    assert payload["considered"] == 8
    assert payload["passed"] == 6
    assert payload["failed_graders"] == []
    assert "not re-run" in payload["note"]
    assert [row["task_id"] for row in payload["tasks"]] == BASELINE_FAILURES
    assert payload["tasks"][0]["category"] == "coding"
    assert payload["tasks"][0]["score"] == 0.5
    assert payload["tasks"][0]["error"] is None
    assert payload["tasks"][0]["detail"] is None
    assert payload["tasks"][0]["failed_grades"] == []
    assert payload["tasks"][0]["skipped_grades"] == []
    assert payload["tasks"][1]["category"] == "tool-use"
    assert payload["tasks"][1]["score"] == 0.0
    assert payload["tasks"][1]["failed_grades"] == []
    assert "api_key" not in captured.out.lower()

    exit_code = main(["failures", str(candidate)])
    captured = capsys.readouterr()
    assert exit_code == 0
    body = captured.out
    assert "edit-json" in body
    assert "0.00" in body
    assert "tool-use" in body
    edit = next(line for line in body.splitlines() if line.startswith("edit-json"))
    assert edit.rstrip().endswith("-")
    assert next(line for line in body.splitlines() if line.startswith("failed")).endswith("1/8")
    for task_id in ["fix-sum", "fizzbuzz", "search-todo", "safe-refusal"]:
        assert task_id not in body
    assert "pytest" not in body

    assert {_rel: _snapshot(path) for _rel, path in (("baseline", baseline), ("candidate", candidate))} == before


def test_saved_grades_resolution_skipped_error_and_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AEO_LLM_JUDGE", raising=False)
    root = tmp_path / "runs"
    run_dir = _write_graded_run(root / "graded")
    before = _snapshot(run_dir)

    exit_code = main(["failures", "graded", "--root", str(root)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    text = captured.out
    assert _snapshot(run_dir) == before
    order = ["summary-wins", "result-wins", "trajectory-wins", "error-only", "blank-error"]
    positions = [text.index(task_id) for task_id in order]
    assert positions == sorted(positions)
    assert "passed-ok" not in text
    assert "FROM_TRAJECTORY" not in text
    assert "SHOULD_NOT_LIST" not in text
    assert "NOT_A_GRADE" not in text
    assert "PASSING_GRADE" not in text
    assert "no failures" not in text
    summary_line = next(line for line in text.splitlines() if line.startswith("summary-wins"))
    assert "0.50" in summary_line
    assert "tests:pytest" in summary_line
    assert "judge:llm_judge" in summary_line
    assert summary_line.index("tests:pytest") < summary_line.index("judge:llm_judge")
    assert "assertion failed: expected 3; error: workspace missing" in summary_line
    result_line = next(line for line in text.splitlines() if line.startswith("result-wins"))
    assert "answer:exact" in result_line
    assert "期望 src/b.py" in result_line
    assert "FROM_TRAJECTORY" not in result_line
    trajectory_line = next(line for line in text.splitlines() if line.startswith("trajectory-wins"))
    assert "path:json_subset, tests:pytest" in trajectory_line
    assert "optional:llm_judge" in trajectory_line
    assert "debug is still true" in trajectory_line
    assert "second tests failure" not in trajectory_line
    error_line = next(line for line in text.splitlines() if line.startswith("error-only"))
    assert re.search(r"0\.00\s+-\s+-\s+error: command timed out$", error_line)
    blank_line = next(line for line in text.splitlines() if line.startswith("blank-error"))
    assert "error:" not in blank_line
    assert blank_line.rstrip().endswith("-")
    assert next(line for line in text.splitlines() if line.startswith("failed")).endswith("5/6")
    assert next(line for line in text.splitlines() if line.startswith("graders")).endswith(
        "tests:pytest x2, answer:exact, path:json_subset"
    )
    assert "api_key" not in text.lower()

    exit_code = main(["failures", str(run_dir), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _snapshot(run_dir) == before
    assert captured.out.endswith("\n")
    assert "\\u" not in captured.out
    assert "期望" in captured.out
    payload = json.loads(captured.out)
    assert [row["task_id"] for row in payload["tasks"]] == order
    assert payload["failed"] == 5
    assert payload["considered"] == 6
    assert payload["passed"] == 1
    assert payload["failed_graders"] == [
        {"id": "tests", "type": "pytest", "count": 2},
        {"id": "answer", "type": "exact", "count": 1},
        {"id": "path", "type": "json_subset", "count": 1},
    ]
    by_id = {row["task_id"]: row for row in payload["tasks"]}

    summary = by_id["summary-wins"]
    assert summary["category"] == "coding"
    assert summary["score"] == 0.5
    assert summary["error"] == "workspace missing"
    assert summary["detail"] == "assertion failed: expected 3; error: workspace missing"
    assert [grade["id"] for grade in summary["failed_grades"]] == ["tests"]
    assert summary["failed_grades"][0]["detail"] == "assertion failed:\nexpected 3"
    assert summary["failed_grades"][0]["passed"] is False
    assert summary["failed_grades"][0]["type"] == "pytest"
    assert [grade["id"] for grade in summary["skipped_grades"]] == ["judge"]
    assert summary["skipped_grades"][0]["skipped"] is True
    assert summary["skipped_grades"][0]["passed"] is False
    assert summary["skipped_grades"][0]["type"] == "llm_judge"

    result = by_id["result-wins"]
    assert result["failed_grades"][0]["id"] == "answer"
    assert result["failed_grades"][0]["detail"] == "期望 src/b.py"
    assert result["skipped_grades"] == []
    assert "FROM_TRAJECTORY" not in json.dumps(result)

    trajectory = by_id["trajectory-wins"]
    assert [grade["id"] for grade in trajectory["failed_grades"]] == ["path", "tests"]
    assert trajectory["failed_grades"][0]["kind"] == "grade"
    assert trajectory["failed_grades"][1].get("passed") is None
    assert [grade["id"] for grade in trajectory["skipped_grades"]] == ["optional"]
    assert trajectory["detail"] == "debug is still true"
    assert "NOT_A_GRADE" not in json.dumps(trajectory)
    assert "PASSING_GRADE" not in json.dumps(trajectory)

    error_only = by_id["error-only"]
    assert error_only["error"] == "command timed out"
    assert error_only["detail"] == "error: command timed out"
    assert error_only["failed_grades"] == []
    assert error_only["skipped_grades"] == []
    assert by_id["blank-error"]["error"] is None
    assert by_id["blank-error"]["detail"] is None
    assert by_id["blank-error"]["failed_grades"] == []


def test_task_filter_pass_fail_and_unknown(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "runs"
    run_dir = _write_graded_run(root / "graded")
    before = _snapshot(run_dir)

    exit_code = main(["failures", "graded", "--root", str(root), "--task", "result-wins"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "result-wins" in captured.out
    assert "期望 src/b.py" in captured.out
    assert "summary-wins" not in captured.out
    assert "trajectory-wins" not in captured.out
    assert next(line for line in captured.out.splitlines() if line.startswith("failed")).endswith("1/1")

    exit_code = main(
        ["failures", "graded", "--root", str(root), "--task", "result-wins", "--format", "json"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["considered"] == 1
    assert payload["failed"] == 1
    assert payload["passed"] == 0
    assert [row["task_id"] for row in payload["tasks"]] == ["result-wins"]
    assert payload["tasks"][0]["failed_grades"][0]["detail"] == "期望 src/b.py"

    exit_code = main(["failures", "graded", "--root", str(root), "--task", "passed-ok"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "no failures\n" in captured.out
    assert "failed graders" not in captured.out
    assert "SHOULD_NOT_LIST" not in captured.out
    assert next(line for line in captured.out.splitlines() if line.startswith("passed")).endswith("1/1")
    assert "Read from the saved run. The agent was not re-run." in captured.out

    exit_code = main(
        ["failures", str(FIXTURES / "baseline"), "--task", "fix-sum", "--format", "json"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["tasks"] == []
    assert payload["failed"] == 0
    assert payload["considered"] == 1
    assert payload["passed"] == 1
    assert "no failures" not in captured.out

    exit_code = main(["failures", "graded", "--root", str(root), "--task", "not-a-task"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "not-a-task" in captured.err
    with pytest.raises(UsageError):
        collect_failures(load_summary(run_dir), run_dir, task_id="not-a-task")
    assert _snapshot(run_dir) == before


def test_all_pass_run_prints_no_failures(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "clean"
    summary = {
        "schema": 1,
        "run_id": "clean",
        "adapter": "test",
        "model": "test",
        "tasks": [
            {"task_id": "fix-sum", "category": "coding", "passed": True, "score": 1, "grades": []},
            {"task_id": "read-config", "category": "tool-use", "passed": True, "score": 1, "grades": []},
        ],
    }
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")
    before = _snapshot(run_dir)
    exit_code = main(["failures", str(run_dir)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "no failures\n" in captured.out
    assert "failed graders" not in captured.out
    assert next(line for line in captured.out.splitlines() if line.startswith("passed")).endswith("2/2")
    assert "fix-sum" not in captured.out
    assert "Read from the saved run. The agent was not re-run." in captured.out
    assert _snapshot(run_dir) == before


def test_unknown_run_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["failures", "missing-run", "--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "run not found" in captured.err


def test_mock_run_failures_are_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AEO_LLM_JUDGE", raising=False)
    root = tmp_path / "runs"
    exit_code = main(
        [
            "run",
            "--adapter",
            "mock",
            "--suite",
            str(ROOT / "suites"),
            "--root",
            str(root),
            "--run-id",
            "failures-mock",
            "--task",
            "fix-sum",
            "--task",
            "safe-refusal",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS" in captured.out
    run_dir = root / "failures-mock"
    before = _snapshot(run_dir)

    exit_code = main(["failures", "failures-mock", "--root", str(root), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _snapshot(run_dir) == before
    payload = json.loads(captured.out)
    assert payload["tasks"] == []
    assert payload["failed"] == 0
    assert payload["passed"] == 2
    assert payload["considered"] == 2
    assert "api_key" not in captured.out.lower()

    exit_code = main(["failures", "failures-mock", "--root", str(root)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "no failures\n" in captured.out
    assert _snapshot(run_dir) == before


def _write_graded_run(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True)
    summary = {
        "schema": 1,
        "run_id": "graded",
        "adapter": "test",
        "model": "test",
        "passed": 1,
        "total": 6,
        "mean_score": 0.25,
        "tasks": [
            {
                "task_id": "summary-wins",
                "category": "coding",
                "passed": False,
                "score": 0.5,
                "error": "  workspace missing  ",
                "grades": [
                    "not-a-grade",
                    {
                        "id": "style",
                        "type": "contains",
                        "passed": True,
                        "score": 1.0,
                        "weight": 1,
                        "detail": "PASSING_GRADE",
                        "skipped": False,
                        "required": False,
                    },
                    {
                        "id": "tests",
                        "type": "pytest",
                        "passed": False,
                        "score": 0.0,
                        "weight": 1,
                        "detail": "assertion failed:\nexpected 3",
                        "skipped": False,
                        "required": True,
                    },
                    {
                        "id": "judge",
                        "type": "llm_judge",
                        "passed": False,
                        "score": 0.0,
                        "weight": 0.2,
                        "detail": "skipped (set AEO_LLM_JUDGE=1 or pass --llm-judge)",
                        "skipped": True,
                        "required": False,
                    },
                ],
            },
            {
                "task_id": "result-wins",
                "category": "tool-use",
                "passed": False,
                "score": 0.0,
                "error": None,
                "grades": [],
            },
            {
                "task_id": "trajectory-wins",
                "category": "tool-use",
                "passed": False,
                "score": 0.0,
                "error": None,
                "grades": [],
            },
            {
                "task_id": "error-only",
                "category": "coding",
                "passed": False,
                "score": 0.0,
                "error": "command timed out",
                "grades": [],
            },
            {
                "task_id": "blank-error",
                "category": "coding",
                "passed": False,
                "score": 0.0,
                "error": "   \n",
                "grades": [],
            },
            {
                "task_id": "passed-ok",
                "category": "coding",
                "passed": True,
                "score": 1.0,
                "error": None,
                "grades": [
                    {
                        "id": "hidden",
                        "type": "exact",
                        "passed": False,
                        "detail": "SHOULD_NOT_LIST",
                        "skipped": False,
                        "required": True,
                    }
                ],
            },
        ],
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary_dir = run_dir / "tasks" / "summary-wins"
    summary_dir.mkdir(parents=True)
    (summary_dir / "result.json").write_text("NOT JSON\n", encoding="utf-8")
    _write_jsonl(
        summary_dir / "trajectory.jsonl",
        [
            {
                "kind": "grade",
                "id": "decoy",
                "type": "pytest",
                "passed": False,
                "detail": "FROM_TRAJECTORY",
            }
        ],
    )
    result_dir = run_dir / "tasks" / "result-wins"
    result_dir.mkdir(parents=True)
    (result_dir / "result.json").write_text(
        json.dumps(
            {
                "task_id": "result-wins",
                "grades": [
                    {
                        "id": "answer",
                        "type": "exact",
                        "passed": False,
                        "score": 0,
                        "weight": 1,
                        "detail": "期望 src/b.py",
                        "skipped": False,
                        "required": True,
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_jsonl(
        result_dir / "trajectory.jsonl",
        [
            {
                "kind": "grade",
                "id": "decoy",
                "type": "exact",
                "passed": False,
                "detail": "FROM_TRAJECTORY",
            }
        ],
    )
    trajectory_dir = run_dir / "tasks" / "trajectory-wins"
    trajectory_dir.mkdir(parents=True)
    (trajectory_dir / "result.json").write_text(
        json.dumps({"task_id": "trajectory-wins", "grades": []}) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(
        trajectory_dir / "trajectory.jsonl",
        [
            {"kind": "tool_call", "tool": "edit_file", "detail": "NOT_A_GRADE"},
            {"kind": "grades", "id": "nope", "passed": False, "detail": "NOT_A_GRADE"},
            {
                "kind": "grade",
                "id": "path",
                "type": "json_subset",
                "passed": False,
                "detail": "debug is still true",
                "skipped": False,
                "required": True,
            },
            {
                "kind": "grade",
                "id": "note",
                "type": "contains",
                "passed": True,
                "detail": "PASSING_GRADE",
                "skipped": False,
            },
            {
                "kind": "grade",
                "id": "tests",
                "type": "pytest",
                "detail": "second tests failure",
                "skipped": False,
            },
            {
                "kind": "grade",
                "id": "optional",
                "type": "llm_judge",
                "passed": False,
                "detail": "skipped optional",
                "skipped": True,
                "required": False,
            },
        ],
    )
    return run_dir


def _snapshot(root: Path) -> dict[str, bytes | None]:
    snap: dict[str, bytes | None] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        snap[rel] = path.read_bytes() if path.is_file() else None
    return snap


def _write_jsonl(path: Path, events: list[dict]) -> None:
    lines = [json.dumps(event, ensure_ascii=False, sort_keys=True) for event in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
