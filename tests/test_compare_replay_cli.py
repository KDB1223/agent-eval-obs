"""Replay, compare, report, and the CLI."""

import json
from pathlib import Path

import pytest

from aeo.cli import main
from aeo.compare.diff import format_compare
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
