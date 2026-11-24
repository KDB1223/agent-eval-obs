"""Tool-call inventory over a saved run. The agent is not re-run."""

import json
from pathlib import Path

import pytest

from aeo.cli import main
from aeo.errors import UsageError
from aeo.jsonl import read_jsonl
from aeo.runner.store import load_summary
from aeo.scoreboard import render_table
from aeo.tools import collect_tools

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
_NOTE = "Computed from the JSONL log. The agent was not re-run."


def test_baseline_and_candidate_fixtures(capsys: pytest.CaptureFixture[str]) -> None:
    baseline = FIXTURES / "baseline"
    candidate = FIXTURES / "candidate"
    before = {
        "baseline": _snapshot(baseline),
        "candidate": _snapshot(candidate),
    }

    exit_code = main(["tools", str(baseline)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    text = captured.out
    assert text.startswith("agent-eval-obs 0.1.0  run baseline  adapter=fixture  model=fixture\n")
    assert "tool" in text.splitlines()[2]
    assert "calls" in text.splitlines()[2]
    assert _row_line(text, "edit_file")
    assert "fix-sum" in _row_line(text, "edit_file")
    assert "math_utils.py" in _row_line(text, "edit_file")
    for task_id in BASELINE_TASKS:
        if task_id != "fix-sum":
            assert task_id not in text
    assert "no tools" not in text
    assert _stat_line(text, "tool kinds").endswith("1")
    assert _stat_line(text, "calls").endswith("1 (1 ok, 0 failed)")
    assert str(baseline) in text
    assert _NOTE in text

    exit_code = main(["tools", str(baseline), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.endswith("\n")
    assert captured.out.startswith("{\n")
    payload = json.loads(captured.out)
    assert payload == collect_tools(load_summary(baseline), baseline)
    assert payload["version"] == "0.1.0"
    assert payload["run_id"] == "baseline"
    assert payload["adapter"] == "fixture"
    assert payload["model"] == "fixture"
    assert payload["run_dir"] == str(baseline)
    assert payload["tools"] == [
        {
            "name": "edit_file",
            "calls": 1,
            "ok": 1,
            "failed": 0,
            "tasks": ["fix-sum"],
            "paths": ["math_utils.py"],
        }
    ]
    assert payload["totals"] == {"tool_kinds": 1, "calls": 1, "ok": 1, "failed": 0}
    assert payload["note"] == _NOTE
    assert "api_key" not in captured.out.lower()
    _assert_text_matches_payload(text, payload)

    exit_code = main(["tools", str(baseline), "--task", "fix-sum"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "edit_file" in captured.out
    assert "math_utils.py" in captured.out
    assert "fizzbuzz" not in captured.out
    assert _stat_line(captured.out, "calls").endswith("1 (1 ok, 0 failed)")

    exit_code = main(["tools", str(baseline), "--task", "fix-sum", "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    filtered = json.loads(captured.out)
    assert filtered["tools"] == payload["tools"]
    assert filtered["totals"] == payload["totals"]

    exit_code = main(["tools", str(baseline), "--task", "fizzbuzz"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "\nno tools\n" in captured.out
    assert "edit_file" not in captured.out
    assert "math_utils.py" not in captured.out
    assert _stat_line(captured.out, "tool kinds").endswith("0")
    assert _stat_line(captured.out, "calls").endswith("0 (0 ok, 0 failed)")
    assert _NOTE in captured.out

    exit_code = main(["tools", str(candidate)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    body = captured.out
    assert body.startswith("agent-eval-obs 0.1.0  run candidate  adapter=fixture  model=fixture\n")
    assert "\nno tools\n" in body
    assert "edit_file" not in body
    assert "math_utils.py" not in body
    assert "read_file" not in body
    assert _stat_line(body, "tool kinds").endswith("0")
    assert _stat_line(body, "calls").endswith("0 (0 ok, 0 failed)")
    assert _NOTE in body

    exit_code = main(["tools", str(candidate), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    candidate_payload = json.loads(captured.out)
    assert candidate_payload["run_id"] == "candidate"
    assert candidate_payload["tools"] == []
    assert candidate_payload["totals"] == {"tool_kinds": 0, "calls": 0, "ok": 0, "failed": 0}
    assert candidate_payload["note"] == _NOTE
    assert "api_key" not in captured.out.lower()
    _assert_text_matches_payload(body, candidate_payload)

    exit_code = main(["tools", str(candidate), "--task", "fix-sum", "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["tools"] == []

    assert {"baseline": _snapshot(baseline), "candidate": _snapshot(candidate)} == before


def test_pairing_rules_on_a_temporary_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = _write_edge_run(tmp_path / "edge")
    before = _snapshot(run_dir)

    exit_code = main(["tools", str(run_dir)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    text = captured.out
    assert text.startswith("agent-eval-obs 0.1.0  run edge  adapter=probe  model=probe\n")
    assert "mystery" not in text
    assert "invented" not in text
    assert "\\u" not in text
    assert "笔记.txt" in text

    exit_code = main(["tools", str(run_dir), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _snapshot(run_dir) == before
    assert captured.out.endswith("\n")
    assert "\\u" not in captured.out
    assert "笔记.txt" in captured.out
    payload = json.loads(captured.out)
    assert payload == collect_tools(load_summary(run_dir), run_dir)
    assert [row["name"] for row in payload["tools"]] == [
        "edit_file",
        "read_file",
        "search",
        "(missing)",
        "write_file",
        "list_dir",
        "list",
        "retry",
        "pre",
    ]
    by_name = {row["name"]: row for row in payload["tools"]}
    # Last observation wins, both directions. Unpaired, missing, and empty
    # call ids fail. ok=1 is not ok is True. The same path string is kept once;
    # ./src/a.py stays distinct from src/a.py.
    assert by_name["edit_file"] == {
        "name": "edit_file",
        "calls": 7,
        "ok": 2,
        "failed": 5,
        "tasks": ["alpha", "beta"],
        "paths": ["src/a.py", "src/b.py", "src/c.py", "truthy.py", "./src/a.py"],
    }
    # Grouped by the tool_call name. A failed observation does not add a success.
    assert by_name["read_file"] == {
        "name": "read_file",
        "calls": 3,
        "ok": 2,
        "failed": 1,
        "tasks": ["alpha", "beta"],
        "paths": ["readme.txt", "other.txt", "笔记.txt"],
    }
    # No arguments.path, a non-string path, and arguments that are not a dict.
    assert by_name["search"] == {
        "name": "search",
        "calls": 3,
        "ok": 2,
        "failed": 1,
        "tasks": ["alpha"],
        "paths": [],
    }
    # A missing tool name and an empty string share the (missing) row.
    assert by_name["(missing)"] == {
        "name": "(missing)",
        "calls": 2,
        "ok": 1,
        "failed": 1,
        "tasks": ["alpha", "beta"],
        "paths": ["orphan.py", "blank-name.txt"],
    }
    assert by_name["write_file"] == {
        "name": "write_file",
        "calls": 2,
        "ok": 1,
        "failed": 1,
        "tasks": ["alpha", "beta"],
        "paths": ["./math_utils.py"],
    }
    # bool is not a call id, even when an observation says ok true.
    assert by_name["list_dir"] == {
        "name": "list_dir",
        "calls": 1,
        "ok": 0,
        "failed": 1,
        "tasks": ["alpha"],
        "paths": ["."],
    }
    # int 0 stringifies and pairs with the observation call id "0".
    assert by_name["list"] == {
        "name": "list",
        "calls": 1,
        "ok": 1,
        "failed": 0,
        "tasks": ["alpha"],
        "paths": ["zero.txt"],
    }
    # Two calls share a call id. The last observation in the file decides both.
    assert by_name["retry"] == {
        "name": "retry",
        "calls": 2,
        "ok": 2,
        "failed": 0,
        "tasks": ["alpha"],
        "paths": ["first.txt", "second.txt"],
    }
    # An observation earlier in the file still pairs. There is no later one.
    assert by_name["pre"] == {
        "name": "pre",
        "calls": 1,
        "ok": 1,
        "failed": 0,
        "tasks": ["alpha"],
        "paths": ["pre.txt"],
    }
    assert payload["totals"] == {"tool_kinds": 9, "calls": 22, "ok": 12, "failed": 10}
    assert payload["note"] == _NOTE
    assert "api_key" not in captured.out.lower()
    _assert_text_matches_payload(text, payload)
    assert _row_line(text, "search").rstrip().endswith("-")
    assert _snapshot(run_dir) == before

    exit_code = main(["tools", str(run_dir), "--task", "alpha"])
    captured = capsys.readouterr()
    assert exit_code == 0
    alpha_text = captured.out
    assert "beta" not in alpha_text
    assert "笔记.txt" not in alpha_text
    assert "./src/a.py" not in alpha_text
    assert "src/a.py" in alpha_text
    assert _stat_line(alpha_text, "tool kinds").endswith("9")
    assert _stat_line(alpha_text, "calls").endswith("17 (9 ok, 8 failed)")

    exit_code = main(["tools", str(run_dir), "--task", "alpha", "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    alpha = json.loads(captured.out)
    assert [row["name"] for row in alpha["tools"]] == [
        "edit_file",
        "read_file",
        "search",
        "(missing)",
        "write_file",
        "list_dir",
        "list",
        "retry",
        "pre",
    ]
    alpha_by = {row["name"]: row for row in alpha["tools"]}
    assert alpha_by["edit_file"]["calls"] == 6
    assert alpha_by["edit_file"]["ok"] == 1
    assert alpha_by["edit_file"]["failed"] == 5
    assert alpha_by["edit_file"]["tasks"] == ["alpha"]
    assert alpha_by["edit_file"]["paths"] == ["src/a.py", "src/b.py", "src/c.py", "truthy.py"]
    assert alpha_by["read_file"] == {
        "name": "read_file",
        "calls": 1,
        "ok": 0,
        "failed": 1,
        "tasks": ["alpha"],
        "paths": ["readme.txt"],
    }
    assert alpha["totals"] == {"tool_kinds": 9, "calls": 17, "ok": 9, "failed": 8}
    _assert_text_matches_payload(alpha_text, alpha)

    exit_code = main(["tools", str(run_dir), "--task", "gamma"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "\nno tools\n" in captured.out
    assert "edit_file" not in captured.out
    assert _stat_line(captured.out, "calls").endswith("0 (0 ok, 0 failed)")
    assert _NOTE in captured.out

    exit_code = main(["tools", str(run_dir), "--task", "not-a-task"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "not-a-task" in captured.err
    with pytest.raises(UsageError):
        collect_tools(load_summary(run_dir), run_dir, task_id="not-a-task")
    assert _snapshot(run_dir) == before


def test_all_failed_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = tmp_path / "all-fail"
    task_dir = run_dir / "tasks" / "only"
    task_dir.mkdir(parents=True)
    _write_jsonl(
        task_dir / "trajectory.jsonl",
        [
            {"kind": "tool_call", "call_id": "1", "tool": "edit_file", "arguments": {"path": "nope.py"}},
            {"kind": "observation", "call_id": "1", "tool": "edit_file", "ok": False},
        ],
    )
    summary = {
        "schema": 1,
        "run_id": "all-fail",
        "adapter": "probe",
        "model": "probe",
        "tasks": [{"task_id": "only", "passed": False, "score": 0}],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")
    before = _snapshot(run_dir)
    exit_code = main(["tools", str(run_dir)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "no tools" not in captured.out
    assert _row_line(captured.out, "edit_file")
    assert _stat_line(captured.out, "tool kinds").endswith("1")
    assert _stat_line(captured.out, "calls").endswith("1 (0 ok, 1 failed)")
    assert _NOTE in captured.out
    assert _snapshot(run_dir) == before

    exit_code = main(["tools", str(run_dir), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["tools"] == [
        {
            "name": "edit_file",
            "calls": 1,
            "ok": 0,
            "failed": 1,
            "tasks": ["only"],
            "paths": ["nope.py"],
        }
    ]
    assert payload["totals"] == {"tool_kinds": 1, "calls": 1, "ok": 0, "failed": 1}


def test_unknown_run_and_usage_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["tools", "missing-run", "--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "run not found" in captured.err

    empty = tmp_path / "empty"
    empty.mkdir()
    exit_code = main(["tools", str(empty)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "run not found" in captured.err

    with pytest.raises(SystemExit) as exc:
        main(["tools"])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        main(["tools", str(FIXTURES / "baseline"), "--format", "yaml"])
    assert exc.value.code == 2

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["tools", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "saved run" in help_text
    assert "tool" in help_text.lower()


def test_cli_tools_mock_run_reads_the_saved_log(
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
            "tools-mock",
            "--task",
            "fix-sum",
            "--task",
            "safe-refusal",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS" in captured.out
    run_dir = root / "tools-mock"
    before = _snapshot(run_dir)

    fix_events = read_jsonl(run_dir / "tasks" / "fix-sum" / "trajectory.jsonl")
    refusal_events = read_jsonl(run_dir / "tasks" / "safe-refusal" / "trajectory.jsonl")
    fix_calls = [event for event in fix_events if event.get("kind") == "tool_call"]
    fix_obs = [event for event in fix_events if event.get("kind") == "observation"]
    assert [event.get("tool") for event in fix_calls] == ["read_file", "edit_file"]
    assert [event.get("arguments", {}).get("path") for event in fix_calls] == [
        "math_utils.py",
        "math_utils.py",
    ]
    assert [event.get("call_id") for event in fix_calls] == [event.get("call_id") for event in fix_obs]
    assert all(event.get("ok") is True for event in fix_obs)
    assert not any(event.get("kind") == "tool_call" for event in refusal_events)

    exit_code = main(["tools", "tools-mock", "--root", str(root), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _snapshot(run_dir) == before
    payload = json.loads(captured.out)
    assert [row["name"] for row in payload["tools"]] == ["read_file", "edit_file"]
    for row in payload["tools"]:
        assert row["calls"] == 1
        assert row["ok"] == 1
        assert row["failed"] == 0
        assert row["tasks"] == ["fix-sum"]
        assert row["paths"] == ["math_utils.py"]
    assert payload["totals"] == {"tool_kinds": 2, "calls": 2, "ok": 2, "failed": 0}
    assert "safe-refusal" not in json.dumps(payload["tools"])
    assert payload["note"] == _NOTE
    assert "api_key" not in captured.out.lower()

    exit_code = main(["tools", "tools-mock", "--root", str(root)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _snapshot(run_dir) == before
    assert "no tools" not in captured.out
    assert "safe-refusal" not in captured.out
    assert "read_file" in captured.out
    assert "edit_file" in captured.out
    assert "math_utils.py" in captured.out
    assert _stat_line(captured.out, "calls").endswith("2 (2 ok, 0 failed)")
    assert _NOTE in captured.out
    _assert_text_matches_payload(captured.out, payload)


def test_missing_model_falls_back_like_stats(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = tmp_path / "no-model"
    run_dir.mkdir()
    summary = {
        "schema": 1,
        "run_id": "no-model",
        "adapter": "probe",
        "tasks": [{"task_id": "empty", "passed": True, "score": 1}],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")
    exit_code = main(["tools", str(run_dir)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.startswith(
        "agent-eval-obs 0.1.0  run no-model  adapter=probe  model=probe\n"
    )
    exit_code = main(["tools", str(run_dir), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["model"] == ""
    assert payload["adapter"] == "probe"
    assert payload["tools"] == []


def _assert_text_matches_payload(text: str, payload: dict) -> None:
    assert text.startswith(
        f"agent-eval-obs {payload['version']}  run {payload['run_id']}  "
        f"adapter={payload['adapter']}  "
    )
    if payload["model"]:
        assert f"model={payload['model']}" in text.splitlines()[0]
    if payload["tools"]:
        assert "\nno tools\n" not in text
        table = render_table(
            ["tool", "calls", "ok", "failed", "tasks", "paths"],
            [
                [
                    row["name"],
                    str(row["calls"]),
                    str(row["ok"]),
                    str(row["failed"]),
                    ", ".join(row["tasks"]) if row["tasks"] else "-",
                    ", ".join(row["paths"]) if row["paths"] else "-",
                ]
                for row in payload["tools"]
            ],
        )
        assert table in text
    else:
        assert "\nno tools\n" in text
    totals = payload["totals"]
    assert _stat_line(text, "tool kinds").endswith(str(totals["tool_kinds"]))
    assert _stat_line(text, "calls").endswith(
        f"{totals['calls']} ({totals['ok']} ok, {totals['failed']} failed)"
    )
    assert payload["run_dir"] in _stat_line(text, "run dir")
    assert payload["note"] in text


def _stat_line(text: str, label: str) -> str:
    for line in text.splitlines():
        if line.split("  ")[0] == label:
            return line
    raise AssertionError(label)


def _row_line(text: str, name: str) -> str:
    for line in text.splitlines():
        if line.split("  ")[0] == name:
            return line
    raise AssertionError(name)


def _write_edge_run(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True)
    summary = {
        "schema": 1,
        "run_id": "edge",
        "adapter": "probe",
        "model": "probe",
        "passed": 3,
        "total": 4,
        "mean_score": 0.75,
        "tasks": [
            {"task_id": "alpha", "category": "coding", "passed": True, "score": 1},
            {"task_id": "beta", "category": "tool-use", "passed": False, "score": 0},
            {"task_id": "gamma", "category": "coding", "passed": True, "score": 1},
            {"task_id": "delta", "category": "coding", "passed": True, "score": 1},
        ],
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    alpha = run_dir / "tasks" / "alpha"
    alpha.mkdir(parents=True)
    _write_jsonl(
        alpha / "trajectory.jsonl",
        [
            {
                "kind": "tool_call",
                "call_id": "e1",
                "tool": "edit_file",
                "arguments": {"path": "src/a.py"},
            },
            {"kind": "observation", "call_id": "e1", "tool": "edit_file", "ok": False},
            {"kind": "observation", "call_id": "e1", "tool": "edit_file", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "e2",
                "tool": "edit_file",
                "arguments": {"path": "src/b.py"},
            },
            {"kind": "observation", "call_id": "e2", "tool": "edit_file", "ok": True},
            {"kind": "observation", "call_id": "e2", "tool": "edit_file", "ok": False},
            {
                "kind": "tool_call",
                "call_id": "e3",
                "tool": "edit_file",
                "arguments": {"path": "src/a.py"},
            },
            {
                "kind": "tool_call",
                "tool": "edit_file",
                "arguments": {"path": "src/c.py"},
            },
            {"kind": "observation", "tool": "edit_file", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "",
                "tool": "edit_file",
                "arguments": {"path": ""},
            },
            {
                "kind": "tool_call",
                "call_id": "num",
                "tool": "edit_file",
                "arguments": {"path": "truthy.py"},
            },
            {"kind": "observation", "call_id": "num", "tool": "edit_file", "ok": 1},
            {
                "kind": "tool_call",
                "call_id": 7,
                "tool": "read_file",
                "arguments": {"path": "readme.txt"},
            },
            {"kind": "observation", "call_id": 7, "tool": "write_file", "ok": False},
            {"kind": "tool_call", "call_id": "s1", "tool": "search", "arguments": {"query": "TODO"}},
            {"kind": "observation", "call_id": "s1", "tool": "search", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "badpath",
                "tool": "search",
                "arguments": {"path": 12, "query": "x"},
            },
            {"kind": "observation", "call_id": "badpath", "tool": "search", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "notdict",
                "tool": "search",
                "arguments": ["math_utils.py"],
            },
            {"kind": "observation", "call_id": "notdict", "tool": "search", "ok": False},
            {"kind": "tool_call", "call_id": "m1", "arguments": {"path": "orphan.py"}},
            {"kind": "observation", "call_id": "m1", "tool": "invented", "ok": True},
            {"kind": "observation", "call_id": "ghost", "tool": "mystery", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "p1",
                "tool": "write_file",
                "arguments": {"path": "./math_utils.py"},
            },
            {"kind": "observation", "call_id": "p1", "tool": "write_file", "ok": True},
            {"kind": "tool_call", "call_id": True, "tool": "list_dir", "arguments": {"path": "."}},
            {"kind": "observation", "call_id": True, "tool": "list_dir", "ok": True},
            {"kind": "tool_call", "call_id": 0, "tool": "list", "arguments": {"path": "zero.txt"}},
            {"kind": "observation", "call_id": "0", "tool": "list", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "dup",
                "tool": "retry",
                "arguments": {"path": "first.txt"},
            },
            {"kind": "observation", "call_id": "dup", "tool": "retry", "ok": False},
            {
                "kind": "tool_call",
                "call_id": "dup",
                "tool": "retry",
                "arguments": {"path": "second.txt"},
            },
            {"kind": "observation", "call_id": "dup", "tool": "retry", "ok": True},
            {"kind": "observation", "call_id": "pre", "tool": "pre", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "pre",
                "tool": "pre",
                "arguments": {"path": "pre.txt"},
            },
            {"kind": "thought", "content": "not a tool call"},
            {"kind": "grade", "id": "g", "passed": True},
            {"kind": "final", "content": "done"},
        ],
    )
    beta = run_dir / "tasks" / "beta"
    beta.mkdir(parents=True)
    _write_jsonl(
        beta / "trajectory.jsonl",
        [
            {"kind": "observation", "call_id": "e2", "tool": "edit_file", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "b1",
                "tool": "read_file",
                "arguments": {"path": "other.txt"},
            },
            {"kind": "observation", "call_id": "b1", "tool": "read_file", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "zh",
                "tool": "read_file",
                "arguments": {"path": "笔记.txt"},
            },
            {"kind": "observation", "call_id": "zh", "tool": "read_file", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "b2",
                "tool": "edit_file",
                "arguments": {"path": "./src/a.py"},
            },
            {"kind": "observation", "call_id": "b2", "tool": "edit_file", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "b3",
                "tool": "write_file",
                "arguments": {"path": "./math_utils.py"},
            },
            {"kind": "observation", "call_id": "b3", "tool": "write_file", "ok": False},
            {
                "kind": "tool_call",
                "call_id": "b4",
                "tool": "",
                "arguments": {"path": "blank-name.txt"},
            },
            {"kind": "observation", "call_id": "b4", "tool": "", "ok": False},
        ],
    )
    delta = run_dir / "tasks" / "delta"
    delta.mkdir(parents=True)
    _write_jsonl(delta / "trajectory.jsonl", [{"kind": "final", "content": "no tools here"}])
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
