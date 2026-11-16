"""Category rollups on the single-run scoreboard and reports."""

from pathlib import Path

import pytest

from aeo.report import render_html, render_markdown
from aeo.runner.store import load_summary
from aeo.scoreboard import category_totals, format_scoreboard

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "fixtures" / "runs"


def test_category_totals_keep_first_seen_order_and_means() -> None:
    tasks = [
        _task("search", "tool-use", 1.0, True),
        _task("fizzbuzz", "coding", 0.5, False),
        _task("edit", "tool-use", 0.0, False),
        _task("fix-sum", "coding", 1.0, True),
    ]
    rows = category_totals(tasks)
    assert [row["category"] for row in rows] == ["tool-use", "coding"]
    tool_use, coding = rows
    assert (tool_use["passed"], tool_use["total"]) == (1, 2)
    assert tool_use["mean"] == pytest.approx(0.5)
    assert (coding["passed"], coding["total"]) == (1, 2)
    assert coding["mean"] == pytest.approx(0.75)

    text = format_scoreboard(_summary("mixed", tasks))
    section = _totals_section(text)
    assert section.index("tool-use") < section.index("coding")
    assert "tool-use  1/2   0.50" in section
    assert "coding    1/2   0.75" in section


def test_category_totals_empty_or_missing_category_is_blank() -> None:
    tasks = [
        _task("gone", None, 1.0, True),
        _task("blank", "", 0.0, False),
        {"task_id": "absent", "score": 0.5, "passed": True},
    ]
    rows = category_totals(tasks)
    assert len(rows) == 1
    assert rows[0]["category"] == ""
    assert (rows[0]["passed"], rows[0]["total"]) == (2, 3)
    assert rows[0]["mean"] == pytest.approx(0.5)

    text = format_scoreboard(_summary("blank", tasks))
    section = _totals_section(text)
    assert "task" not in section
    assert "          2/3   0.50" in section


def test_scoreboard_omits_category_totals_when_there_are_no_tasks() -> None:
    assert category_totals([]) == []
    text = format_scoreboard(_summary("empty", []))
    assert "category  pass  mean" not in text
    assert "task  category  score  result" in text
    assert "pass rate     0/0 (0%)\nmean score    0.00\ntrajectories  .aeo/runs/empty\n" in text


def test_format_scoreboard_baseline_category_totals() -> None:
    text = format_scoreboard(load_summary(FIXTURES / "baseline"))
    assert "pass rate     6/8 (75%)" in text
    assert text.index("mean score") < text.index("category  pass  mean") < text.index("trajectories")
    assert "coding    3/4   0.88" in text
    assert "tool-use  3/4   0.75\n\ntrajectories" in text
    coding = category_totals(load_summary(FIXTURES / "baseline")["tasks"])[0]
    assert coding["mean"] == pytest.approx(0.875)


def test_markdown_and_html_include_baseline_category_totals() -> None:
    summary = load_summary(FIXTURES / "baseline")
    markdown = render_markdown(summary, FIXTURES / "baseline")
    assert markdown.index("| task | category | score | result |") < markdown.index(
        "| category | pass | mean |"
    )
    assert markdown.index("| category | pass | mean |") < markdown.index("## fix-sum")
    assert "| --- | --- | ---: |" in markdown
    assert "| coding | 3/4 | 0.88 |" in markdown
    assert "| tool-use | 3/4 | 0.75 |" in markdown

    page = render_html(summary, FIXTURES / "baseline")
    assert page.index("<h2>Scoreboard</h2>") < page.index("<h2>Categories</h2>")
    assert page.index("<h2>Categories</h2>") < page.index("<h2>Trajectories</h2>")
    assert "<td>coding</td><td>3/4</td><td>0.88</td>" in page
    assert "<td>tool-use</td><td>3/4</td><td>0.75</td>" in page


def test_reports_omit_category_totals_when_there_are_no_tasks(tmp_path: Path) -> None:
    summary = _summary("empty", [])
    markdown = render_markdown(summary, tmp_path)
    assert "| task | category | score | result |" in markdown
    assert "| category | pass | mean |" not in markdown

    page = render_html(summary, tmp_path)
    assert "<h2>Categories</h2>" not in page
    assert "<th>category</th>" in page
    assert "<h2>Trajectories</h2>" in page


def test_html_category_totals_escape_markup(tmp_path: Path) -> None:
    summary = _summary("escape", [_task("markup", "<b>coding</b>", 1.0, True)])
    summary["tasks"][0]["title"] = "Show <b>text</b>"
    summary["tasks"][0]["final_answer"] = "<script>alert(1)</script>"
    page = render_html(summary, tmp_path)
    assert "<b>coding</b>" not in page
    assert "<script>" not in page
    assert page.count("&lt;b&gt;coding&lt;/b&gt;") == 2
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def _totals_section(text: str) -> str:
    start = text.index("category  pass  mean")
    end = text.index("trajectories")
    return text[start:end]


def _task(task_id: str, category: str | None, score: float, passed: bool) -> dict:
    row = {
        "task_id": task_id,
        "score": score,
        "passed": passed,
    }
    if category is not None:
        row["category"] = category
    return row


def _summary(run_id: str, tasks: list[dict]) -> dict:
    scores = [float(task["score"]) for task in tasks]
    return {
        "run_id": run_id,
        "adapter": "mock",
        "passed": sum(1 for task in tasks if task["passed"]),
        "total": len(tasks),
        "mean_score": (sum(scores) / len(scores)) if scores else 0.0,
        "run_dir": f".aeo/runs/{run_id}",
        "tasks": tasks,
    }
