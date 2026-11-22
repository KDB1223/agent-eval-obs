"""Grader inventory over a saved run. The agent is not re-run."""

import json
from pathlib import Path

import pytest

from aeo.cli import main
from aeo.errors import UsageError
from aeo.failures import format_grader_rollup, format_graders
from aeo.grades import collect_grades
from aeo.runner.store import load_summary

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "fixtures" / "runs"
ABSENT = ("llm_judge", "contains", "json_subset", "regex", "exact")


def test_baseline_and_candidate_fixtures_list_every_task_without_inventing_grades(
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = FIXTURES / "baseline"
    candidate = FIXTURES / "candidate"
    before = {_rel: _snapshot(path) for _rel, path in (("baseline", baseline), ("candidate", candidate))}

    exit_code = main(["grades", str(baseline)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    text = captured.out
    assert text.startswith("agent-eval-obs 0.1.0  run baseline  adapter=fixture  model=fixture\n")
    assert "passed graders" in text
    assert "failed graders" in text
    assert "Read from the saved run. The agent was not re-run." in text
    for token in ABSENT:
        assert token not in text
    assert "exit 0" not in text
    summary_tasks = _summary_tasks(baseline)
    ids = [task["task_id"] for task in summary_tasks]
    assert _shown_ids(text, ids) == ids
    assert len(ids) == 8
    fizzbuzz = _row_line(text, "fizzbuzz")
    search = _row_line(text, "search-todo")
    fix_sum = _row_line(text, "fix-sum")
    assert "coding" in fizzbuzz and "FAIL" in fizzbuzz and "0.50" in fizzbuzz
    assert "tool-use" in search and "FAIL" in search and "0.00" in search
    assert "PASS" in fix_sum and "1.00" in fix_sum
    assert "tests:pytest" in fix_sum
    assert fizzbuzz.rstrip().endswith("-")
    assert search.rstrip().endswith("-")
    assert "pytest" not in fizzbuzz
    assert "pytest" not in search
    assert _stat_line(text, "passed").endswith("6/8")
    assert _stat_line(text, "failed").endswith("2/8")
    assert _stat_line(text, "grades").endswith("1 passed, 0 failed, 0 skipped")
    assert not any(line.split("  ")[0] == "graders" for line in text.splitlines())

    exit_code = main(["grades", str(baseline), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.endswith("\n")
    assert captured.out.startswith("{\n")
    payload = json.loads(captured.out)
    assert payload["version"] == "0.1.0"
    assert payload["run_id"] == "baseline"
    assert payload["adapter"] == "fixture"
    assert payload["model"] == "fixture"
    assert payload["passed"] == 6
    assert payload["failed"] == 2
    assert payload["considered"] == 8
    assert payload["grade_totals"] == {"passed": 1, "failed": 0, "skipped": 0}
    assert payload["failed_graders"] == []
    assert "not re-run" in payload["note"]
    assert [row["task_id"] for row in payload["tasks"]] == ids
    by_id = {row["task_id"]: row for row in payload["tasks"]}
    assert by_id["fizzbuzz"]["category"] == "coding"
    assert by_id["fizzbuzz"]["result"] == "FAIL"
    assert by_id["fizzbuzz"]["passed"] is False
    assert by_id["fizzbuzz"]["score"] == 0.5
    assert by_id["fizzbuzz"]["passed_grades"] == []
    assert by_id["fizzbuzz"]["failed_grades"] == []
    assert by_id["fizzbuzz"]["skipped_grades"] == []
    assert by_id["fix-sum"]["result"] == "PASS"
    assert by_id["fix-sum"]["passed"] is True
    assert by_id["fix-sum"]["score"] == 1.0
    assert [grade["id"] for grade in by_id["fix-sum"]["passed_grades"]] == ["tests"]
    assert by_id["fix-sum"]["passed_grades"][0]["type"] == "pytest"
    assert by_id["fix-sum"]["passed_grades"][0]["passed"] is True
    assert by_id["fix-sum"]["passed_grades"][0]["detail"] == "exit 0"
    assert by_id["fix-sum"]["failed_grades"] == []
    assert by_id["fix-sum"]["skipped_grades"] == []
    assert by_id["search-todo"]["category"] == "tool-use"
    assert by_id["search-todo"]["score"] == 0.0
    assert by_id["search-todo"]["passed_grades"] == []
    for row in payload["tasks"]:
        if row["task_id"] != "fix-sum":
            assert row["passed_grades"] == []
            assert row["failed_grades"] == []
            assert row["skipped_grades"] == []
    assert "api_key" not in captured.out.lower()
    _assert_text_matches_payload(text, payload)

    exit_code = main(["grades", str(candidate)])
    captured = capsys.readouterr()
    assert exit_code == 0
    body = captured.out
    candidate_ids = [task["task_id"] for task in _summary_tasks(candidate)]
    assert _shown_ids(body, candidate_ids) == candidate_ids
    edit = _row_line(body, "edit-json")
    assert "FAIL" in edit and "0.00" in edit and "tool-use" in edit
    assert edit.rstrip().endswith("-")
    assert "PASS" in _row_line(body, "fizzbuzz")
    assert "PASS" in _row_line(body, "search-todo")
    assert _row_line(body, "fix-sum").rstrip().endswith("-")
    assert _stat_line(body, "passed").endswith("7/8")
    assert _stat_line(body, "failed").endswith("1/8")
    assert _stat_line(body, "grades").endswith("0 passed, 0 failed, 0 skipped")
    for token in ("pytest", *ABSENT):
        assert token not in body

    exit_code = main(["grades", str(candidate), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    candidate_payload = json.loads(captured.out)
    assert [row["task_id"] for row in candidate_payload["tasks"]] == candidate_ids
    assert candidate_payload["passed"] == 7
    assert candidate_payload["failed"] == 1
    assert candidate_payload["grade_totals"] == {"passed": 0, "failed": 0, "skipped": 0}
    assert all(row["passed_grades"] == [] for row in candidate_payload["tasks"])
    assert all(row["failed_grades"] == [] for row in candidate_payload["tasks"])
    _assert_text_matches_payload(body, candidate_payload)

    assert {_rel: _snapshot(path) for _rel, path in (("baseline", baseline), ("candidate", candidate))} == before


def test_saved_grades_resolution_passed_skipped_and_json(
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

    exit_code = main(["grades", "graded", "--root", str(root)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    text = captured.out
    assert _snapshot(run_dir) == before
    order = ["summary-wins", "result-wins", "trajectory-wins", "error-only", "blank-error", "passed-ok"]
    assert _shown_ids(text, order) == order
    assert "FROM_TRAJECTORY" not in text
    assert "SHOULD_NOT_LIST" not in text
    assert "NOT_A_GRADE" not in text
    assert "PASSING_GRADE" not in text
    assert "SKIPPED_EVEN_THOUGH_PASSED" not in text
    assert "command timed out" not in text
    assert "workspace missing" not in text
    assert "error:" not in text
    assert "期望" not in text
    summary_line = _row_line(text, "summary-wins")
    assert "FAIL" in summary_line and "0.50" in summary_line
    assert "style:contains" in summary_line
    assert "tests:pytest" in summary_line
    assert "judge:llm_judge, soft:contains" in summary_line
    assert summary_line.index("style:contains") < summary_line.index("tests:pytest")
    assert summary_line.index("tests:pytest") < summary_line.index("judge:llm_judge")
    assert summary_line.index("judge:llm_judge") < summary_line.index("soft:contains")
    result_line = _row_line(text, "result-wins")
    assert "answer:exact" in result_line
    assert "FROM_TRAJECTORY" not in result_line
    trajectory_line = _row_line(text, "trajectory-wins")
    assert "note:contains" in trajectory_line
    assert "path:json_subset, tests:pytest" in trajectory_line
    assert "optional:llm_judge" in trajectory_line
    assert trajectory_line.index("note:contains") < trajectory_line.index("path:json_subset")
    assert "debug is still true" not in trajectory_line
    assert "second tests failure" not in trajectory_line
    error_line = _row_line(text, "error-only")
    assert "FAIL" in error_line and "0.00" in error_line
    assert error_line.rstrip().endswith("-")
    blank_line = _row_line(text, "blank-error")
    assert "FAIL" in blank_line
    assert blank_line.rstrip().endswith("-")
    passed_line = _row_line(text, "passed-ok")
    assert "PASS" in passed_line and "1.00" in passed_line
    assert "hidden:exact" in passed_line
    assert _stat_line(text, "passed").endswith("1/6")
    assert _stat_line(text, "failed").endswith("5/6")
    assert _stat_line(text, "grades").endswith("2 passed, 5 failed, 3 skipped")
    assert _stat_line(text, "graders").endswith(
        "tests:pytest x2, answer:exact, path:json_subset, hidden:exact"
    )
    assert "api_key" not in text.lower()

    exit_code = main(["grades", str(run_dir), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _snapshot(run_dir) == before
    assert captured.out.endswith("\n")
    assert "\\u" not in captured.out
    assert "期望" in captured.out
    payload = json.loads(captured.out)
    assert [row["task_id"] for row in payload["tasks"]] == order
    assert payload["passed"] == 1
    assert payload["failed"] == 5
    assert payload["considered"] == 6
    assert payload["grade_totals"] == {"passed": 2, "failed": 5, "skipped": 3}
    assert payload["failed_graders"] == [
        {"id": "tests", "type": "pytest", "count": 2},
        {"id": "answer", "type": "exact", "count": 1},
        {"id": "path", "type": "json_subset", "count": 1},
        {"id": "hidden", "type": "exact", "count": 1},
    ]
    _assert_text_matches_payload(text, payload)
    by_id = {row["task_id"]: row for row in payload["tasks"]}

    summary = by_id["summary-wins"]
    assert summary["category"] == "coding"
    assert summary["result"] == "FAIL"
    assert summary["passed"] is False
    assert summary["score"] == 0.5
    assert [grade["id"] for grade in summary["passed_grades"]] == ["style"]
    assert summary["passed_grades"][0]["detail"] == "PASSING_GRADE"
    assert [grade["id"] for grade in summary["failed_grades"]] == ["tests"]
    assert summary["failed_grades"][0]["detail"] == "assertion failed:\nexpected 3"
    assert [grade["id"] for grade in summary["skipped_grades"]] == ["judge", "soft"]
    assert summary["skipped_grades"][0]["skipped"] is True
    assert summary["skipped_grades"][1]["passed"] is True
    assert summary["skipped_grades"][1]["skipped"] is True
    assert "FROM_TRAJECTORY" not in json.dumps(summary)

    result = by_id["result-wins"]
    assert result["passed_grades"] == []
    assert result["failed_grades"][0]["id"] == "answer"
    assert result["failed_grades"][0]["detail"] == "期望 src/b.py"
    assert result["skipped_grades"] == []
    assert "FROM_TRAJECTORY" not in json.dumps(result)

    trajectory = by_id["trajectory-wins"]
    assert [grade["id"] for grade in trajectory["passed_grades"]] == ["note"]
    assert trajectory["passed_grades"][0]["detail"] == "PASSING_GRADE"
    assert [grade["id"] for grade in trajectory["failed_grades"]] == ["path", "tests"]
    assert trajectory["failed_grades"][0]["kind"] == "grade"
    assert trajectory["failed_grades"][1].get("passed") is None
    assert trajectory["failed_grades"][1]["detail"] == "second tests failure"
    assert [grade["id"] for grade in trajectory["skipped_grades"]] == ["optional"]
    assert "NOT_A_GRADE" not in json.dumps(trajectory)

    error_only = by_id["error-only"]
    assert error_only["result"] == "FAIL"
    assert error_only["passed_grades"] == []
    assert error_only["failed_grades"] == []
    assert error_only["skipped_grades"] == []
    assert "command timed out" not in json.dumps(error_only)
    assert by_id["blank-error"]["result"] == "FAIL"
    assert by_id["blank-error"]["failed_grades"] == []
    assert by_id["passed-ok"]["result"] == "PASS"
    assert by_id["passed-ok"]["passed"] is True
    assert [grade["id"] for grade in by_id["passed-ok"]["failed_grades"]] == ["hidden"]
    assert by_id["passed-ok"]["failed_grades"][0]["detail"] == "SHOULD_NOT_LIST"
    assert by_id["passed-ok"]["passed_grades"] == []


def test_task_filter_pass_fail_and_unknown(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "runs"
    run_dir = _write_graded_run(root / "graded")
    before = _snapshot(run_dir)

    exit_code = main(["grades", "graded", "--root", str(root), "--task", "passed-ok"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "passed-ok" in captured.out
    assert "PASS" in captured.out
    assert "hidden:exact" in captured.out
    assert "SHOULD_NOT_LIST" not in captured.out
    assert "summary-wins" not in captured.out
    assert "result-wins" not in captured.out
    assert _stat_line(captured.out, "passed").endswith("1/1")
    assert _stat_line(captured.out, "failed").endswith("0/1")
    assert _stat_line(captured.out, "grades").endswith("0 passed, 1 failed, 0 skipped")
    assert _stat_line(captured.out, "graders").endswith("hidden:exact")

    exit_code = main(
        ["grades", "graded", "--root", str(root), "--task", "passed-ok", "--format", "json"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["considered"] == 1
    assert payload["passed"] == 1
    assert payload["failed"] == 0
    assert [row["task_id"] for row in payload["tasks"]] == ["passed-ok"]
    assert payload["tasks"][0]["result"] == "PASS"
    assert payload["tasks"][0]["failed_grades"][0]["detail"] == "SHOULD_NOT_LIST"

    exit_code = main(["grades", "graded", "--root", str(root), "--task", "result-wins"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "result-wins" in captured.out
    assert "answer:exact" in captured.out
    assert "期望" not in captured.out
    assert "summary-wins" not in captured.out
    assert "passed-ok" not in captured.out
    assert _stat_line(captured.out, "failed").endswith("1/1")
    assert _stat_line(captured.out, "passed").endswith("0/1")

    exit_code = main(
        ["grades", "graded", "--root", str(root), "--task", "result-wins", "--format", "json"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "\\u" not in captured.out
    payload = json.loads(captured.out)
    assert payload["considered"] == 1
    assert payload["failed"] == 1
    assert payload["passed"] == 0
    assert [row["task_id"] for row in payload["tasks"]] == ["result-wins"]
    assert payload["tasks"][0]["failed_grades"][0]["detail"] == "期望 src/b.py"

    exit_code = main(["grades", str(FIXTURES / "baseline"), "--task", "fix-sum"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _shown_ids(captured.out, ["fix-sum"]) == ["fix-sum"]
    assert "PASS" in _row_line(captured.out, "fix-sum")
    assert "fizzbuzz" not in captured.out
    assert _stat_line(captured.out, "passed").endswith("1/1")
    assert _stat_line(captured.out, "failed").endswith("0/1")
    assert "Read from the saved run. The agent was not re-run." in captured.out

    exit_code = main(["grades", "graded", "--root", str(root), "--task", "not-a-task"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "not-a-task" in captured.err
    with pytest.raises(UsageError):
        collect_grades(load_summary(run_dir), run_dir, task_id="not-a-task")
    assert _snapshot(run_dir) == before


def test_all_failed_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = tmp_path / "all-fail"
    summary = {
        "schema": 1,
        "run_id": "all-fail",
        "adapter": "test",
        "model": "test",
        "tasks": [
            {"task_id": "fizzbuzz", "category": "coding", "passed": False, "score": 0.5, "grades": []},
            {"task_id": "search-todo", "category": "tool-use", "passed": False, "score": 0, "grades": []},
        ],
    }
    run_dir.mkdir()
    (run_dir / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")
    before = _snapshot(run_dir)
    exit_code = main(["grades", str(run_dir)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _shown_ids(captured.out, ["fizzbuzz", "search-todo"]) == ["fizzbuzz", "search-todo"]
    assert _stat_line(captured.out, "passed").endswith("0/2")
    assert _stat_line(captured.out, "failed").endswith("2/2")
    assert "Read from the saved run. The agent was not re-run." in captured.out
    assert _snapshot(run_dir) == before


def test_unknown_run_and_usage_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["grades", "missing-run", "--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "run not found" in captured.err

    empty = tmp_path / "empty"
    empty.mkdir()
    exit_code = main(["grades", str(empty)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "run not found" in captured.err

    with pytest.raises(SystemExit) as exc:
        main(["grades"])
    assert exc.value.code == 2


def _assert_text_matches_payload(text: str, payload: dict) -> None:
    ids = [row["task_id"] for row in payload["tasks"]]
    assert _shown_ids(text, ids) == ids
    for row in payload["tasks"]:
        line = _row_line(text, row["task_id"])
        assert row["result"] in line
        assert row["category"] in line
        assert f"{float(row['score']):.2f}" in line
        for grades in (row["passed_grades"], row["failed_grades"], row["skipped_grades"]):
            label = format_graders(grades)
            if label != "-":
                assert label in line
        if not any((row["passed_grades"], row["failed_grades"], row["skipped_grades"])):
            assert line.rstrip().endswith("-")
    assert f"{payload['passed']}/{payload['considered']}" in text
    assert f"{payload['failed']}/{payload['considered']}" in text
    totals = payload["grade_totals"]
    assert (
        f"{totals['passed']} passed, {totals['failed']} failed, {totals['skipped']} skipped" in text
    )
    rollup = format_grader_rollup(payload["failed_graders"])
    if rollup:
        assert rollup in text
    else:
        assert not any(line.split("  ")[0] == "graders" for line in text.splitlines())
    assert payload["note"] in text


def _stat_line(text: str, label: str) -> str:
    for line in text.splitlines():
        if line.split("  ")[0] == label:
            return line
    raise AssertionError(label)


def _shown_ids(text: str, ids: list[str]) -> list[str]:
    wanted = set(ids)
    return [line.split("  ")[0] for line in text.splitlines() if line.split("  ")[0] in wanted]


def _row_line(text: str, task_id: str) -> str:
    for line in text.splitlines():
        if line.split("  ")[0] == task_id:
            return line
    raise AssertionError(task_id)


def _summary_tasks(run_dir: Path) -> list[dict]:
    payload = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    return list(payload["tasks"])


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
                    {
                        "id": "soft",
                        "type": "contains",
                        "passed": True,
                        "score": 1.0,
                        "detail": "SKIPPED_EVEN_THOUGH_PASSED",
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
