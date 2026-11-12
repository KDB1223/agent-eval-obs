"""Stats over saved trajectories. The agent is not re-run."""

import json
from pathlib import Path

import pytest

from aeo.cli import main
from aeo.errors import UsageError
from aeo.runner.store import load_summary
from aeo.stats import summarize_run

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "examples" / "fixtures" / "runs"
BASELINE_TASKS = [
    "fix-sum",
    "fizzbuzz",
    "parse-ints",
    "add-docstring",
    "read-config",
    "search-todo",
    "edit-json",
    "safe-refusal",
]


def test_baseline_fixture_counts_only_the_recorded_edit() -> None:
    run_dir = FIXTURES / "baseline"
    payload = summarize_run(load_summary(run_dir), run_dir)
    by_id = {row["task_id"]: row for row in payload["tasks"]}
    assert list(by_id) == BASELINE_TASKS

    fix = by_id["fix-sum"]
    assert fix["result"] == "PASS"
    assert fix["passed"] is True
    assert fix["score"] == 1.0
    assert fix["category"] == "coding"
    assert fix["tools"] == {"edit_file": 1}
    assert fix["files"] == ["math_utils.py"]
    assert fix["final"] is True

    assert by_id["fizzbuzz"]["result"] == "FAIL"
    assert by_id["fizzbuzz"]["score"] == 0.5
    assert by_id["search-todo"]["result"] == "FAIL"
    assert by_id["search-todo"]["score"] == 0.0
    for task_id, row in by_id.items():
        if task_id == "fix-sum":
            continue
        assert row["tools"] == {}
        assert row["files"] == []
        assert row["final"] is False
        assert row["tool_calls"] == 0
        if task_id == "fizzbuzz":
            assert row["score"] == 0.5 and row["result"] == "FAIL"
        elif task_id == "search-todo":
            assert row["score"] == 0.0 and row["result"] == "FAIL"
        else:
            assert row["score"] == 1.0 and row["result"] == "PASS"
    assert payload["tool_calls"] == 1
    assert payload["with_final"] == 1
    assert payload["tasks_shown"] == 8
    assert "not re-run" in payload["note"]


def test_cli_stats_baseline_text_json_and_task_filter(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["stats", str(FIXTURES / "baseline")])
    captured = capsys.readouterr()
    assert exit_code == 0
    text = captured.out
    assert text.startswith("agent-eval-obs 0.1.0  run baseline  adapter=fixture  model=fixture\n")
    assert "edit_file:1" in text
    assert "math_utils.py" in text
    assert "tool calls    1\n" in text
    assert "with final    1/8\n" in text
    assert "not re-run" in text
    assert "JSONL" in text
    positions = [text.index(task_id) for task_id in BASELINE_TASKS]
    assert positions == sorted(positions)
    fizzbuzz = next(line for line in text.splitlines() if line.startswith("fizzbuzz"))
    search = next(line for line in text.splitlines() if line.startswith("search-todo"))
    fix = next(line for line in text.splitlines() if line.startswith("fix-sum"))
    assert "FAIL" in fizzbuzz and "0.50" in fizzbuzz and fizzbuzz.endswith("no")
    assert "FAIL" in search and "0.00" in search and search.endswith("no")
    assert "PASS" in fix and "1.00" in fix and "edit_file:1" in fix and fix.endswith("yes")
    assert sum(line.endswith("yes") for line in text.splitlines()) == 1
    assert sum(line.endswith("no") for line in text.splitlines()) == 7

    exit_code = main(["stats", str(FIXTURES / "baseline"), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.endswith("\n")
    payload = json.loads(captured.out)
    assert payload["run_id"] == "baseline"
    assert payload["adapter"] == "fixture"
    assert payload["tool_calls"] == 1
    assert payload["tasks_shown"] == 8
    assert [row["task_id"] for row in payload["tasks"]] == BASELINE_TASKS
    assert "api_key" not in captured.out.lower()

    exit_code = main(["stats", str(FIXTURES / "baseline"), "--task", "fix-sum"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "fix-sum" in captured.out
    assert "fizzbuzz" not in captured.out
    assert "search-todo" not in captured.out
    assert "tool calls    1\n" in captured.out
    assert "with final    1/1\n" in captured.out
    assert "math_utils.py" in captured.out

    exit_code = main(
        ["stats", str(FIXTURES / "baseline"), "--task", "fix-sum", "--format", "json"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["tasks_shown"] == 1
    assert payload["with_final"] == 1
    assert payload["tool_calls"] == 1
    row = payload["tasks"][0]
    assert row["task_id"] == "fix-sum"
    assert row["files"] == ["math_utils.py"]
    assert row["tools"] == {"edit_file": 1}
    assert row["final"] is True
    assert row["result"] == "PASS"
    assert row["score"] == 1.0

    exit_code = main(
        ["stats", str(FIXTURES / "baseline"), "--task", "fizzbuzz", "--format", "json"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["tasks_shown"] == 1
    assert payload["tool_calls"] == 0
    assert payload["with_final"] == 0
    row = payload["tasks"][0]
    assert row["task_id"] == "fizzbuzz"
    assert row["result"] == "FAIL"
    assert row["score"] == 0.5
    assert row["tools"] == {}
    assert row["files"] == []
    assert row["final"] is False


def test_cli_stats_mock_run_reads_the_saved_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
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
            "stats-mock",
            "--task",
            "safe-refusal",
            "--task",
            "fix-sum",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS" in captured.out
    run_dir = root / "stats-mock"
    before = _tree(run_dir)
    roots_before = sorted(path.name for path in root.iterdir())

    exit_code = main(["stats", "stats-mock", "--root", str(root), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _tree(run_dir) == before
    assert sorted(path.name for path in root.iterdir()) == roots_before == ["stats-mock"]
    payload = json.loads(captured.out)
    by_id = {row["task_id"]: row for row in payload["tasks"]}
    assert list(by_id) == ["fix-sum", "safe-refusal"]

    fix = by_id["fix-sum"]
    assert fix["result"] == "PASS"
    assert fix["final"] is True
    assert fix["files"] == ["math_utils.py"]
    assert fix["tools"]["edit_file"] == 1
    assert "read_file" in fix["tools"]

    refusal = by_id["safe-refusal"]
    assert refusal["result"] == "PASS"
    assert refusal["final"] is True
    assert refusal["tools"] == {}
    assert refusal["files"] == []
    assert payload["tool_calls"] == sum(row["tool_calls"] for row in payload["tasks"])
    assert "api_key" not in captured.out.lower()


def test_failed_and_non_edit_observations_do_not_add_files(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "edge"
    task_dir = run_dir / "tasks" / "edit"
    task_dir.mkdir(parents=True)
    events = [
        {"kind": "tool_call", "call_id": "1", "tool": "write_file", "arguments": {"path": "nope.txt"}},
        {"kind": "observation", "call_id": "1", "tool": "write_file", "ok": False, "content": "denied"},
        {"kind": "tool_call", "call_id": "2", "tool": "edit_file", "arguments": {"path": "missing-ok.txt"}},
        {"kind": "observation", "call_id": "2", "tool": "edit_file", "content": "ok flag missing"},
        {"kind": "tool_call", "call_id": "3", "tool": "read_file", "arguments": {"path": "readme.txt"}},
        {"kind": "observation", "call_id": "3", "tool": "read_file", "ok": True, "content": "hi"},
        {"kind": "tool_call", "call_id": "4", "tool": "search", "arguments": {"path": "found.txt"}},
        {"kind": "observation", "call_id": "4", "tool": "search", "ok": True, "content": "found.txt"},
        {"kind": "tool_call", "call_id": "5", "tool": "list_dir", "arguments": {"path": "."}},
        {"kind": "observation", "call_id": "5", "tool": "list_dir", "ok": True, "content": "."},
        {"kind": "tool_call", "call_id": "6", "tool": "list", "arguments": {"path": "listed.txt"}},
        {"kind": "observation", "call_id": "6", "tool": "list", "ok": True, "content": "listed.txt"},
        {"kind": "tool_call", "call_id": "7", "tool": "edit_file", "arguments": {"path": "kept.py"}},
        {"kind": "observation", "call_id": "7", "tool": "edit_file", "ok": True, "content": "updated"},
        {"kind": "tool_call", "call_id": "8", "tool": "write_file", "arguments": {"path": "kept.py"}},
        {"kind": "observation", "call_id": "8", "tool": "write_file", "ok": True, "content": "wrote"},
        {"kind": "tool_call", "call_id": "9", "tool": "write_file", "arguments": {"path": "other.txt"}},
        {"kind": "observation", "call_id": "9", "tool": "write_file", "ok": True, "content": "wrote"},
        {"kind": "tool_call", "call_id": "10", "tool": "edit_file", "arguments": {"file": "wrong-key.py"}},
        {"kind": "observation", "call_id": "10", "tool": "edit_file", "ok": True, "content": "updated"},
        {"kind": "tool_call", "call_id": "11", "tool": "edit_file", "arguments": {"path": "never.txt"}},
        {"kind": "thought", "content": "not a tool call"},
        {"kind": "grade", "id": "g", "tool": "edit_file", "passed": True},
        {"kind": "external", "source": "log"},
        {"kind": "final", "content": "done"},
    ]
    _write_jsonl(task_dir / "trajectory.jsonl", events)
    summary = {
        "schema": 1,
        "run_id": "edge",
        "adapter": "test",
        "model": "test",
        "passed": 1,
        "total": 2,
        "mean_score": 0.5,
        "tasks": [
            {
                "task_id": "edit",
                "category": "coding",
                "passed": True,
                "score": 1,
            },
            {
                "task_id": "ghost",
                "category": "tool-use",
                "passed": False,
                "score": 0,
            },
        ],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")

    exit_code = main(["stats", str(run_dir), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    by_id = {row["task_id"]: row for row in payload["tasks"]}
    edit = by_id["edit"]
    assert edit["files"] == ["kept.py", "other.txt"]
    assert edit["final"] is True
    assert edit["tools"] == {
        "edit_file": 4,
        "list": 1,
        "list_dir": 1,
        "read_file": 1,
        "search": 1,
        "write_file": 3,
    }
    assert edit["tool_calls"] == 11
    ghost = by_id["ghost"]
    assert ghost["tools"] == {}
    assert ghost["files"] == []
    assert ghost["final"] is False
    assert ghost["result"] == "FAIL"
    assert payload["tool_calls"] == 11
    assert payload["with_final"] == 1
    assert payload["tasks_shown"] == 2
    assert "nope.txt" not in captured.out
    assert "readme.txt" not in captured.out
    assert "never.txt" not in captured.out


def test_unknown_run_and_unknown_task_exit_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["stats", "missing-run", "--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "run not found" in captured.err
    assert captured.out == ""

    exit_code = main(["stats", str(FIXTURES / "baseline"), "--task", "not-a-task"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert "not-a-task" in captured.err
    with pytest.raises(UsageError):
        summarize_run(load_summary(FIXTURES / "baseline"), FIXTURES / "baseline", task_id="not-a-task")


def _tree(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))


def _write_jsonl(path: Path, events: list[dict]) -> None:
    lines = [json.dumps(event, ensure_ascii=False, sort_keys=True) for event in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
