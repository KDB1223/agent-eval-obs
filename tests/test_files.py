"""Path inventory over a saved run. The agent is not re-run."""

import json
from pathlib import Path

import pytest

from aeo.cli import main
from aeo.errors import RunError, UsageError
from aeo.files import collect_files
from aeo.jsonl import read_jsonl
from aeo.runner.store import load_summary
from aeo.scoreboard import render_table

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
_COLUMNS = ["path", "calls", "ok", "failed", "tools", "tasks"]


def test_baseline_and_candidate_fixtures(capsys: pytest.CaptureFixture[str]) -> None:
    baseline = FIXTURES / "baseline"
    candidate = FIXTURES / "candidate"
    before = {
        "baseline": _snapshot(baseline),
        "candidate": _snapshot(candidate),
    }

    exit_code = main(["files", str(baseline)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    text = captured.out
    assert text.startswith("agent-eval-obs 0.1.0  run baseline  adapter=fixture  model=fixture\n")
    assert "path" in text.splitlines()[2]
    assert "calls" in text.splitlines()[2]
    assert _row_line(text, "math_utils.py")
    assert "edit_file" in _row_line(text, "math_utils.py")
    assert "fix-sum" in _row_line(text, "math_utils.py")
    for task_id in BASELINE_TASKS:
        if task_id != "fix-sum":
            assert task_id not in text
    assert "no files" not in text
    assert "(missing)" not in text
    assert _stat_line(text, "path kinds").endswith("1")
    assert _stat_line(text, "calls").endswith("1 (1 ok, 0 failed)")
    assert str(baseline) in text
    assert _NOTE in text

    exit_code = main(["files", str(baseline), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.endswith("\n")
    assert captured.out.startswith("{\n")
    payload = json.loads(captured.out)
    assert payload == collect_files(load_summary(baseline), baseline)
    assert payload["version"] == "0.1.0"
    assert payload["run_id"] == "baseline"
    assert payload["adapter"] == "fixture"
    assert payload["model"] == "fixture"
    assert payload["run_dir"] == str(baseline)
    assert payload["files"] == [
        {
            "path": "math_utils.py",
            "calls": 1,
            "ok": 1,
            "failed": 0,
            "tools": ["edit_file"],
            "tasks": ["fix-sum"],
        }
    ]
    assert payload["totals"] == {"path_kinds": 1, "calls": 1, "ok": 1, "failed": 0}
    assert payload["note"] == _NOTE
    assert "api_key" not in captured.out.lower()
    _assert_text_matches_payload(text, payload)

    exit_code = main(["files", "baseline", "--root", str(FIXTURES), "--task", "fix-sum"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "math_utils.py" in captured.out
    assert "edit_file" in captured.out
    assert "fizzbuzz" not in captured.out
    assert _stat_line(captured.out, "calls").endswith("1 (1 ok, 0 failed)")

    exit_code = main(["files", str(baseline), "--task", "fix-sum", "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    filtered = json.loads(captured.out)
    assert filtered["files"] == payload["files"]
    assert filtered["totals"] == payload["totals"]

    exit_code = main(["files", str(baseline), "--task", "fizzbuzz"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "\nno files\n" in captured.out
    assert "math_utils.py" not in captured.out
    assert "edit_file" not in captured.out
    assert _stat_line(captured.out, "path kinds").endswith("0")
    assert _stat_line(captured.out, "calls").endswith("0 (0 ok, 0 failed)")
    assert _NOTE in captured.out

    exit_code = main(["files", str(baseline), "--task", "not-a-task"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "not-a-task" in captured.err
    with pytest.raises(UsageError):
        collect_files(load_summary(baseline), baseline, task_id="not-a-task")

    exit_code = main(["files", str(candidate)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    body = captured.out
    assert body.startswith("agent-eval-obs 0.1.0  run candidate  adapter=fixture  model=fixture\n")
    assert "\nno files\n" in body
    assert "math_utils.py" not in body
    assert "edit_file" not in body
    assert "read_file" not in body
    assert _stat_line(body, "path kinds").endswith("0")
    assert _stat_line(body, "calls").endswith("0 (0 ok, 0 failed)")
    assert _NOTE in body

    exit_code = main(["files", str(candidate), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    candidate_payload = json.loads(captured.out)
    assert candidate_payload["run_id"] == "candidate"
    assert candidate_payload["files"] == []
    assert candidate_payload["totals"] == {"path_kinds": 0, "calls": 0, "ok": 0, "failed": 0}
    assert candidate_payload["note"] == _NOTE
    assert "api_key" not in captured.out.lower()
    _assert_text_matches_payload(body, candidate_payload)

    exit_code = main(["files", str(candidate), "--task", "fix-sum", "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["files"] == []

    assert {"baseline": _snapshot(baseline), "candidate": _snapshot(candidate)} == before


def test_pairing_rules_on_a_temporary_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = _write_edge_run(tmp_path / "edge")
    before = _snapshot(run_dir)

    exit_code = main(["files", str(run_dir)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    text = captured.out
    assert text.startswith("agent-eval-obs 0.1.0  run edge  adapter=probe  model=probe\n")
    assert "mystery" not in text
    assert "invented" not in text
    assert "leftover.py" not in text
    assert "not-in-log.py" not in text
    assert "only-on-disk.py" not in text
    assert "\\u" not in text
    assert "笔记.txt" in text
    assert _row_line(text, "src/a.py")
    assert _row_line(text, "./src/a.py")
    assert _row_line(text, "(missing)")
    assert not any(line.split("  ")[0] == "math_utils.py" for line in text.splitlines())

    exit_code = main(["files", str(run_dir), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _snapshot(run_dir) == before
    assert captured.out.endswith("\n")
    assert "\\u" not in captured.out
    assert "笔记.txt" in captured.out
    payload = json.loads(captured.out)
    assert payload == collect_files(load_summary(run_dir), run_dir)
    assert [row["path"] for row in payload["files"]] == [
        "src/a.py",
        "(missing)",
        "orphan.py",
        "./src/a.py",
        ".",
        "zero.txt",
        "first.txt",
        "second.txt",
        "pre.txt",
        "truthy.py",
        "src/c.py",
        "blank-id.py",
        " 笔记.txt",
        "笔记.txt",
        "./math_utils.py",
        "blank-name.txt",
    ]
    by_path = {row["path"]: row for row in payload["files"]}
    # Last observation wins, both directions. The same path string is one row.
    # read_file is listed after edit_file because that call comes later.
    assert by_path["src/a.py"] == {
        "path": "src/a.py",
        "calls": 4,
        "ok": 3,
        "failed": 1,
        "tools": ["edit_file", "read_file"],
        "tasks": ["alpha", "beta"],
    }
    # No arguments, an empty path, a non-string path, and arguments that are
    # not a dict share (missing). They are not dropped.
    assert by_path["(missing)"] == {
        "path": "(missing)",
        "calls": 4,
        "ok": 2,
        "failed": 2,
        "tools": ["edit_file", "search"],
        "tasks": ["alpha"],
    }
    # A missing tool name is (missing). The observation's tool name is ignored.
    assert by_path["orphan.py"] == {
        "path": "orphan.py",
        "calls": 1,
        "ok": 1,
        "failed": 0,
        "tools": ["(missing)"],
        "tasks": ["alpha"],
    }
    # ./src/a.py stays distinct from src/a.py. Nothing is normalized.
    assert by_path["./src/a.py"] == {
        "path": "./src/a.py",
        "calls": 1,
        "ok": 1,
        "failed": 0,
        "tools": ["edit_file"],
        "tasks": ["alpha"],
    }
    # bool is not a call id, even when an observation says ok true.
    assert by_path["."] == {
        "path": ".",
        "calls": 1,
        "ok": 0,
        "failed": 1,
        "tools": ["list_dir"],
        "tasks": ["alpha"],
    }
    # int 0 stringifies and pairs with the observation call id "0".
    assert by_path["zero.txt"] == {
        "path": "zero.txt",
        "calls": 1,
        "ok": 1,
        "failed": 0,
        "tools": ["list"],
        "tasks": ["alpha"],
    }
    # Two calls share a call id. The last observation in the file decides both.
    assert by_path["first.txt"]["ok"] == 1
    assert by_path["first.txt"]["failed"] == 0
    assert by_path["second.txt"] == {
        "path": "second.txt",
        "calls": 1,
        "ok": 1,
        "failed": 0,
        "tools": ["retry"],
        "tasks": ["alpha"],
    }
    # An observation earlier in the file still pairs. There is no later one.
    assert by_path["pre.txt"]["ok"] == 1
    # ok=1 is not ok is True. A missing call id does not pair with an observation.
    assert by_path["truthy.py"]["failed"] == 1
    assert by_path["truthy.py"]["ok"] == 0
    assert by_path["src/c.py"]["failed"] == 1
    # An empty call id is a failure even when an observation says ok true.
    assert by_path["blank-id.py"] == {
        "path": "blank-id.py",
        "calls": 1,
        "ok": 0,
        "failed": 1,
        "tools": ["edit_file"],
        "tasks": ["alpha"],
    }
    # A leading space and the characters are kept. 笔记.txt is a different path.
    assert by_path[" 笔记.txt"] == {
        "path": " 笔记.txt",
        "calls": 1,
        "ok": 1,
        "failed": 0,
        "tools": ["write_file"],
        "tasks": ["alpha"],
    }
    assert by_path["笔记.txt"] == {
        "path": "笔记.txt",
        "calls": 1,
        "ok": 1,
        "failed": 0,
        "tools": ["read_file"],
        "tasks": ["beta"],
    }
    assert by_path["./math_utils.py"] == {
        "path": "./math_utils.py",
        "calls": 1,
        "ok": 0,
        "failed": 1,
        "tools": ["write_file"],
        "tasks": ["beta"],
    }
    # An empty tool name and a missing tool name share the (missing) tool label.
    assert by_path["blank-name.txt"] == {
        "path": "blank-name.txt",
        "calls": 1,
        "ok": 0,
        "failed": 1,
        "tools": ["(missing)"],
        "tasks": ["beta"],
    }
    assert payload["totals"] == {"path_kinds": 16, "calls": 22, "ok": 13, "failed": 9}
    assert payload["note"] == _NOTE
    assert "api_key" not in captured.out.lower()
    assert "leftover.py" not in json.dumps(payload)
    _assert_text_matches_payload(text, payload)
    assert _snapshot(run_dir) == before

    exit_code = main(["files", str(run_dir), "--task", "alpha"])
    captured = capsys.readouterr()
    assert exit_code == 0
    alpha_text = captured.out
    assert "beta" not in alpha_text
    assert "笔记.txt" in alpha_text
    assert "./src/a.py" in alpha_text
    assert "src/a.py" in alpha_text
    assert _stat_line(alpha_text, "path kinds").endswith("13")
    assert _stat_line(alpha_text, "calls").endswith("18 (11 ok, 7 failed)")

    exit_code = main(["files", str(run_dir), "--task", "alpha", "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    alpha = json.loads(captured.out)
    assert [row["path"] for row in alpha["files"]] == [
        "src/a.py",
        "(missing)",
        "orphan.py",
        "./src/a.py",
        ".",
        "zero.txt",
        "first.txt",
        "second.txt",
        "pre.txt",
        "truthy.py",
        "src/c.py",
        "blank-id.py",
        " 笔记.txt",
    ]
    alpha_by = {row["path"]: row for row in alpha["files"]}
    assert alpha_by["src/a.py"] == {
        "path": "src/a.py",
        "calls": 3,
        "ok": 2,
        "failed": 1,
        "tools": ["edit_file", "read_file"],
        "tasks": ["alpha"],
    }
    assert alpha_by["(missing)"]["calls"] == 4
    assert alpha_by["(missing)"]["ok"] == 2
    assert alpha_by["(missing)"]["failed"] == 2
    assert "笔记.txt" not in alpha_by
    assert "./math_utils.py" not in alpha_by
    assert alpha["totals"] == {"path_kinds": 13, "calls": 18, "ok": 11, "failed": 7}
    _assert_text_matches_payload(alpha_text, alpha)

    exit_code = main(["files", str(run_dir), "--task", "gamma"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "\nno files\n" in captured.out
    assert "only-on-disk.py" not in captured.out
    assert "src/a.py" not in captured.out
    assert _stat_line(captured.out, "calls").endswith("0 (0 ok, 0 failed)")
    assert _NOTE in captured.out

    exit_code = main(["files", str(run_dir), "--task", "delta"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "\nno files\n" in captured.out
    assert "not-in-log.py" not in captured.out
    assert _stat_line(captured.out, "path kinds").endswith("0")

    exit_code = main(["files", str(run_dir), "--task", "not-a-task"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "not-a-task" in captured.err
    with pytest.raises(UsageError):
        collect_files(load_summary(run_dir), run_dir, task_id="not-a-task")
    assert _snapshot(run_dir) == before


def test_all_failed_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_dir = tmp_path / "all-fail"
    task_dir = run_dir / "tasks" / "only"
    task_dir.mkdir(parents=True)
    (task_dir / "workspace").mkdir()
    (task_dir / "workspace" / "nope.py").write_text("untouched\n", encoding="utf-8")
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
    exit_code = main(["files", str(run_dir)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "no files" not in captured.out
    assert _row_line(captured.out, "nope.py")
    assert _stat_line(captured.out, "path kinds").endswith("1")
    assert _stat_line(captured.out, "calls").endswith("1 (0 ok, 1 failed)")
    assert _NOTE in captured.out
    assert _snapshot(run_dir) == before

    exit_code = main(["files", str(run_dir), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["files"] == [
        {
            "path": "nope.py",
            "calls": 1,
            "ok": 0,
            "failed": 1,
            "tools": ["edit_file"],
            "tasks": ["only"],
        }
    ]
    assert payload["totals"] == {"path_kinds": 1, "calls": 1, "ok": 0, "failed": 1}


def test_invalid_jsonl_raises_and_leaves_the_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "broken"
    task_dir = run_dir / "tasks" / "only"
    task_dir.mkdir(parents=True)
    (task_dir / "trajectory.jsonl").write_text(
        '{"kind": "tool_call", "arguments": {"path": "a.py"}}\n{not json\n',
        encoding="utf-8",
    )
    summary = {
        "schema": 1,
        "run_id": "broken",
        "adapter": "probe",
        "model": "probe",
        "tasks": [{"task_id": "only", "category": "coding", "passed": True, "score": 1}],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")
    before = _snapshot(run_dir)

    with pytest.raises(RunError, match="invalid JSONL"):
        collect_files(load_summary(run_dir), run_dir)
    exit_code = main(["files", str(run_dir)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "invalid JSONL" in captured.err
    assert _snapshot(run_dir) == before


def test_unknown_run_and_usage_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["files", "missing-run", "--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "run not found" in captured.err

    empty = tmp_path / "empty"
    empty.mkdir()
    exit_code = main(["files", str(empty)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "run not found" in captured.err

    with pytest.raises(SystemExit) as exc:
        main(["files"])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        main(["files", str(FIXTURES / "baseline"), "--format", "yaml"])
    assert exc.value.code == 2

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["files", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "saved run" in help_text
    assert "JSONL" in help_text
    assert "not re-run" in help_text

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    top = capsys.readouterr().out
    assert "files" in top


def test_cli_files_mock_run_reads_the_saved_log(
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
            "files-mock",
            "--task",
            "fix-sum",
            "--task",
            "safe-refusal",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS" in captured.out
    run_dir = root / "files-mock"
    before = _snapshot(run_dir)
    assert (run_dir / "tasks" / "fix-sum" / "workspace" / "test_math_utils.py").is_file()
    assert (run_dir / "tasks" / "safe-refusal" / "workspace" / "README.txt").is_file()

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

    exit_code = main(["files", "files-mock", "--root", str(root), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _snapshot(run_dir) == before
    payload = json.loads(captured.out)
    assert payload["files"] == [
        {
            "path": "math_utils.py",
            "calls": 2,
            "ok": 2,
            "failed": 0,
            "tools": ["read_file", "edit_file"],
            "tasks": ["fix-sum"],
        }
    ]
    assert payload["totals"] == {"path_kinds": 1, "calls": 2, "ok": 2, "failed": 0}
    assert "test_math_utils.py" not in captured.out
    assert "README.txt" not in captured.out
    assert "safe-refusal" not in json.dumps(payload["files"])
    assert payload["note"] == _NOTE
    assert "api_key" not in captured.out.lower()

    exit_code = main(["files", "files-mock", "--root", str(root)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _snapshot(run_dir) == before
    assert "no files" not in captured.out
    assert "safe-refusal" not in captured.out
    assert "test_math_utils.py" not in captured.out
    assert "README.txt" not in captured.out
    assert "math_utils.py" in captured.out
    assert "read_file" in captured.out
    assert "edit_file" in captured.out
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
    exit_code = main(["files", str(run_dir)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.startswith(
        "agent-eval-obs 0.1.0  run no-model  adapter=probe  model=probe\n"
    )
    assert "\nno files\n" in captured.out
    exit_code = main(["files", str(run_dir), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["model"] == ""
    assert payload["adapter"] == "probe"
    assert payload["files"] == []


def _assert_text_matches_payload(text: str, payload: dict) -> None:
    assert text.startswith(
        f"agent-eval-obs {payload['version']}  run {payload['run_id']}  "
        f"adapter={payload['adapter']}  "
    )
    if payload["model"]:
        assert f"model={payload['model']}" in text.splitlines()[0]
    if payload["files"]:
        assert "\nno files\n" not in text
        table = render_table(
            _COLUMNS,
            [
                [
                    row["path"],
                    str(row["calls"]),
                    str(row["ok"]),
                    str(row["failed"]),
                    ", ".join(row["tools"]) if row["tools"] else "-",
                    ", ".join(row["tasks"]) if row["tasks"] else "-",
                ]
                for row in payload["files"]
            ],
        )
        assert table in text
    else:
        assert "\nno files\n" in text
    totals = payload["totals"]
    assert _stat_line(text, "path kinds").endswith(str(totals["path_kinds"]))
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
    (alpha / "workspace").mkdir()
    (alpha / "workspace" / "leftover.py").write_text("not in the log\n", encoding="utf-8")
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
                "arguments": {"path": "src/a.py"},
            },
            {"kind": "observation", "call_id": "e2", "tool": "edit_file", "ok": True},
            {"kind": "observation", "call_id": "e2", "tool": "edit_file", "ok": False},
            {
                "kind": "tool_call",
                "call_id": "r1",
                "tool": "read_file",
                "arguments": {"path": "src/a.py"},
            },
            {"kind": "observation", "call_id": "r1", "tool": "read_file", "ok": True},
            {"kind": "tool_call", "call_id": "m1", "tool": "edit_file"},
            {"kind": "observation", "call_id": "m1", "tool": "edit_file", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "empty",
                "tool": "search",
                "arguments": {"path": ""},
            },
            {"kind": "observation", "call_id": "empty", "tool": "search", "ok": False},
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
            {"kind": "tool_call", "call_id": "m2", "arguments": {"path": "orphan.py"}},
            {"kind": "observation", "call_id": "m2", "tool": "invented", "ok": True},
            {"kind": "observation", "call_id": "ghost", "tool": "mystery", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "dot",
                "tool": "edit_file",
                "arguments": {"path": "./src/a.py"},
            },
            {"kind": "observation", "call_id": "dot", "tool": "edit_file", "ok": True},
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
            {
                "kind": "tool_call",
                "call_id": "num",
                "tool": "edit_file",
                "arguments": {"path": "truthy.py"},
            },
            {"kind": "observation", "call_id": "num", "tool": "edit_file", "ok": 1},
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
                "arguments": {"path": "blank-id.py"},
            },
            {"kind": "observation", "call_id": "", "tool": "edit_file", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "sp",
                "tool": "write_file",
                "arguments": {"path": " 笔记.txt"},
            },
            {"kind": "observation", "call_id": "sp", "tool": "write_file", "ok": True},
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
            {
                "kind": "tool_call",
                "call_id": "b1",
                "tool": "edit_file",
                "arguments": {"path": "src/a.py"},
            },
            {"kind": "observation", "call_id": "b1", "tool": "edit_file", "ok": True},
            {
                "kind": "tool_call",
                "call_id": "zh",
                "tool": "read_file",
                "arguments": {"path": "笔记.txt"},
            },
            {"kind": "observation", "call_id": "zh", "tool": "read_file", "ok": True},
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
    gamma = run_dir / "tasks" / "gamma" / "workspace"
    gamma.mkdir(parents=True)
    (gamma / "only-on-disk.py").write_text("not a trajectory\n", encoding="utf-8")
    delta = run_dir / "tasks" / "delta"
    delta.mkdir(parents=True)
    (delta / "workspace").mkdir()
    (delta / "workspace" / "not-in-log.py").write_text("final only\n", encoding="utf-8")
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
