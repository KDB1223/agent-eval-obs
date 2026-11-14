"""Replay, compare, report, and the CLI."""

import json
from pathlib import Path

import pytest

from aeo.cli import main
from aeo.compare.diff import compare_runs, format_compare
from aeo.replay.render import render_run
from aeo.report import render_html
from aeo.runner.store import load_summary

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "fixtures" / "runs"


def test_fixture_compare_shows_regression_and_improvement() -> None:
    left = load_summary(FIXTURES / "baseline")
    right = load_summary(FIXTURES / "candidate")
    text, regressions = format_compare(left, right)
    assert regressions == ["edit-json"]
    assert "fizzbuzz" in text
    assert "search-todo" in text
    assert "improvements  fizzbuzz, search-todo" in text
    assert "regressions   edit-json" in text
    assert "6/8" in text and "7/8" in text
    assert "(+0.06)" in text
    assert text.index("mean score") < text.index("category") < text.index("improvements")
    assert "coding    3/4     0.88    4/4     1.00    +0.12" in text
    assert "tool-use  3/4     0.75    3/4     0.75    +0.00" in text


def test_compare_runs_fixture_category_totals() -> None:
    left = load_summary(FIXTURES / "baseline")
    right = load_summary(FIXTURES / "candidate")
    payload = compare_runs(left, right)
    assert payload["improvements"] == ["fizzbuzz", "search-todo"]
    assert payload["regressions"] == ["edit-json"]
    assert payload["pass_delta"] == 1
    assert payload["mean_delta"] == pytest.approx(0.0625)
    assert payload["only_in_a"] == []
    assert payload["only_in_b"] == []
    assert payload["run_a"]["passed"] == 6
    assert payload["run_b"]["passed"] == 7
    coding, tool_use = payload["categories"]
    assert coding["category"] == "coding"
    assert (coding["a_passed"], coding["a_total"]) == (3, 4)
    assert (coding["b_passed"], coding["b_total"]) == (4, 4)
    assert coding["a_mean"] == pytest.approx(0.875)
    assert coding["b_mean"] == pytest.approx(1.0)
    assert coding["mean_delta"] == pytest.approx(0.125)
    assert coding["pass_delta"] == 1
    assert tool_use["category"] == "tool-use"
    assert (tool_use["a_passed"], tool_use["a_total"]) == (3, 4)
    assert (tool_use["b_passed"], tool_use["b_total"]) == (3, 4)
    assert tool_use["a_mean"] == pytest.approx(0.75)
    assert tool_use["b_mean"] == pytest.approx(0.75)
    assert tool_use["mean_delta"] == pytest.approx(0.0)
    assert tool_use["pass_delta"] == 0
    by_id = {task["task_id"]: task for task in payload["tasks"]}
    assert by_id["fizzbuzz"]["delta"] == pytest.approx(0.5)
    assert by_id["edit-json"]["a_passed"] is True
    assert by_id["edit-json"]["b_passed"] is False


def test_compare_one_sided_task_is_not_a_regression() -> None:
    left = _summary(
        "left",
        [
            _task("shared", "coding", 1.0, True),
            _task("left-only", "coding", 0.5, False),
        ],
    )
    right = _summary("right", [_task("shared", "coding", 1.0, True)])
    payload = compare_runs(left, right)
    assert payload["only_in_a"] == ["left-only"]
    assert payload["only_in_b"] == []
    assert payload["improvements"] == []
    assert payload["regressions"] == []
    row = payload["tasks"][1]
    assert row["task_id"] == "left-only"
    assert row["a_score"] == pytest.approx(0.5)
    assert row["a_passed"] is False
    assert row["b_score"] is None
    assert row["b_passed"] is None
    assert row["delta"] is None
    coding = payload["categories"][0]
    assert coding["category"] == "coding"
    assert (coding["a_passed"], coding["a_total"]) == (1, 2)
    assert (coding["b_passed"], coding["b_total"]) == (1, 1)
    assert coding["a_mean"] == pytest.approx(0.75)
    assert coding["b_mean"] == pytest.approx(1.0)
    assert coding["pass_delta"] == 0
    assert coding["mean_delta"] == pytest.approx(0.25)
    text, regressions = format_compare(left, right)
    assert regressions == []
    assert "only in A     left-only" in text
    assert "improvements  none" in text
    assert "regressions   none" in text


def test_compare_category_missing_on_one_side() -> None:
    left = _summary("left", [_task("shared", "coding", 1.0, True)])
    right = _summary(
        "right",
        [
            _task("shared", "coding", 1.0, True),
            _task("extra", "tool-use", 0.25, False),
        ],
    )
    payload = compare_runs(left, right)
    assert payload["only_in_b"] == ["extra"]
    assert payload["improvements"] == []
    assert payload["regressions"] == []
    extra = payload["tasks"][1]
    assert extra["a_score"] is None
    assert extra["a_passed"] is None
    assert extra["b_score"] == pytest.approx(0.25)
    assert extra["b_passed"] is False
    assert extra["delta"] is None
    coding, tool_use = payload["categories"]
    assert coding["category"] == "coding"
    assert coding["a_mean"] == pytest.approx(1.0)
    assert coding["b_mean"] == pytest.approx(1.0)
    assert tool_use["category"] == "tool-use"
    assert (tool_use["a_passed"], tool_use["a_total"]) == (0, 0)
    assert tool_use["a_mean"] is None
    assert (tool_use["b_passed"], tool_use["b_total"]) == (0, 1)
    assert tool_use["b_mean"] == pytest.approx(0.25)
    assert tool_use["mean_delta"] is None
    assert tool_use["pass_delta"] == 0
    text, regressions = format_compare(left, right)
    assert regressions == []
    assert "only in B     extra" in text
    tool_line = next(line for line in text.splitlines() if line.startswith("tool-use"))
    assert "0/0" in tool_line
    assert "0/1" in tool_line
    assert tool_line.count("—") == 2


def test_compare_omits_category_table_when_there_are_no_tasks() -> None:
    left = _summary("left", [])
    right = _summary("right", [])
    payload = compare_runs(left, right)
    assert payload["categories"] == []
    assert payload["tasks"] == []
    assert payload["regressions"] == []
    text, regressions = format_compare(left, right)
    assert regressions == []
    assert "category" not in text
    assert "improvements  none" in text
    assert "pass rate     0/0  ->  0/0  (+0)" in text


def test_compare_pass_flip_without_score_change_is_a_regression() -> None:
    left = _summary("left", [_task("flip", "coding", 1.0, True)])
    right = _summary("right", [_task("flip", "coding", 1.0, False)])
    payload = compare_runs(left, right)
    assert payload["regressions"] == ["flip"]
    assert payload["improvements"] == []
    assert payload["tasks"][0]["delta"] == pytest.approx(0.0)


def test_cli_compare_json_reports_regressions_and_categories(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(
        [
            "compare",
            str(FIXTURES / "baseline"),
            str(FIXTURES / "candidate"),
            "--format",
            "json",
            "--fail-on-regression",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out.endswith("\n")
    payload = json.loads(captured.out)
    assert payload["regressions"] == ["edit-json"]
    assert payload["improvements"] == ["fizzbuzz", "search-todo"]
    assert payload["pass_delta"] == 1
    categories = {row["category"]: row for row in payload["categories"]}
    assert categories["coding"]["a_passed"] == 3
    assert categories["coding"]["b_total"] == 4
    assert categories["coding"]["a_mean"] == pytest.approx(0.875)
    assert categories["coding"]["b_mean"] == pytest.approx(1.0)
    assert categories["tool-use"]["a_passed"] == 3
    assert categories["tool-use"]["b_passed"] == 3
    assert categories["tool-use"]["a_mean"] == pytest.approx(0.75)
    assert categories["tool-use"]["b_mean"] == pytest.approx(0.75)

    exit_code = main(
        [
            "compare",
            str(FIXTURES / "baseline"),
            str(FIXTURES / "baseline"),
            "--format",
            "json",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["regressions"] == []
    assert payload["improvements"] == []
    assert payload["pass_delta"] == 0


def _task(task_id: str, category: str, score: float, passed: bool) -> dict:
    return {
        "task_id": task_id,
        "category": category,
        "score": score,
        "passed": passed,
    }


def _summary(run_id: str, tasks: list[dict]) -> dict:
    scores = [float(task["score"]) for task in tasks]
    return {
        "run_id": run_id,
        "adapter": "mem",
        "passed": sum(1 for task in tasks if task["passed"]),
        "total": len(tasks),
        "mean_score": (sum(scores) / len(scores)) if scores else 0.0,
        "tasks": tasks,
    }


def test_replay_fixture_does_not_claim_a_rerun() -> None:
    text = render_run(FIXTURES / "baseline", task_id="fix-sum")
    assert "edit_file" in text
    assert "agent was not re-run" in text


def test_html_report_escapes_markup(tmp_path: Path) -> None:
    summary = {
        "run_id": "escape",
        "adapter": "mock",
        "model": "mock-script",
        "created_at": "2026-11-08T00:00:00.000Z",
        "passed": 0,
        "total": 1,
        "mean_score": 0,
        "tasks": [
            {
                "task_id": "markup",
                "title": "Show <b>text</b>",
                "category": "tool-use",
                "passed": False,
                "score": 0,
                "final_answer": "<script>alert(1)</script>",
                "error": None,
                "grades": [],
            }
        ],
    }
    page = render_html(summary, tmp_path)
    assert "<script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "&lt;b&gt;text&lt;/b&gt;" in page


def test_cli_mock_run_replay_report_and_compare(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
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
            "cli-mock",
            "--task",
            "safe-refusal",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "safe-refusal" in captured.out
    assert "PASS" in captured.out

    exit_code = main(["replay", "cli-mock", "--root", str(root), "--task", "safe-refusal"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "I refuse" in captured.out
    assert "agent was not re-run" in captured.out

    exit_code = main(["report", "cli-mock", "--root", str(root), "--format", "md", "--out", "-"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "safe-refusal" in captured.out

    html_path = tmp_path / "report.html"
    exit_code = main(
        ["report", "cli-mock", "--root", str(root), "--format", "html", "--out", str(html_path)]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    page = html_path.read_text(encoding="utf-8")
    assert "safe-refusal" in page
    assert "<html" in page

    exit_code = main(["list-runs", "--root", str(FIXTURES)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "baseline" in captured.out
    assert "candidate" in captured.out
    # Newer created_at is listed first.
    assert captured.out.index("candidate") < captured.out.index("baseline")

    exit_code = main(
        [
            "compare",
            str(FIXTURES / "baseline"),
            str(FIXTURES / "candidate"),
            "--fail-on-regression",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "edit-json" in captured.out
    assert "coding    3/4     0.88    4/4     1.00    +0.12" in captured.out
    assert "tool-use  3/4     0.75    3/4     0.75    +0.00" in captured.out

    exit_code = main(["compare", "cli-mock", "cli-mock", "--root", str(root)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "regressions   none" in captured.out


def test_cli_rejects_unknown_adapter() -> None:
    # argparse choices reject this before our factory runs.
    with pytest.raises(SystemExit) as exc:
        main(["run", "--adapter", "nope"])
    assert exc.value.code == 2


def test_openai_adapter_requires_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    exit_code = main(["run", "--adapter", "openai", "--suite", str(ROOT / "suites"), "--task", "fix-sum"])
    assert exit_code == 2
