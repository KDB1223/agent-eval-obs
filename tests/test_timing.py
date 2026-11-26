"""Wall-clock timing over a saved run. The agent is not re-run."""

import json
from pathlib import Path

import pytest

from aeo.cli import main
from aeo.errors import RunError, UsageError
from aeo.runner.store import load_summary
from aeo.scoreboard import render_table
from aeo.timing import collect_timing

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
_COLUMNS = ["task", "result", "score", "events", "started", "ended", "duration_ms", "unparsed"]
_ROW_KEYS = {
    "task_id",
    "category",
    "result",
    "passed",
    "score",
    "events",
    "unparsed_ts",
    "started",
    "ended",
    "duration_ms",
    "has_trajectory",
}


def test_baseline_and_candidate_fixtures(capsys: pytest.CaptureFixture[str]) -> None:
    baseline = FIXTURES / "baseline"
    candidate = FIXTURES / "candidate"
    before = {"baseline": _snapshot(baseline), "candidate": _snapshot(candidate)}

    exit_code = main(["timing", str(baseline)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    text = captured.out
    assert text.startswith("agent-eval-obs 0.1.0  run baseline  adapter=fixture  model=fixture\n")
    assert _shown_ids(text, BASELINE_TASKS) == BASELINE_TASKS
    fix = _row_line(text, "fix-sum").split()
    assert fix[1:4] == ["PASS", "1.00", "8"]
    assert fix[4:8] == [
        "2026-11-01T00:00:00.000Z",
        "2026-11-01T00:00:00.007Z",
        "7",
        "0",
    ]
    for task_id in BASELINE_TASKS:
        if task_id == "fix-sum":
            continue
        cells = _row_line(text, task_id).split()
        assert cells[3] == "0"
        assert cells[4:7] == ["-", "-", "-"]
        assert cells[7] == "0"
        assert "2026" not in _row_line(text, task_id)
    assert _stat_line(text, "with timing").endswith("1/8")
    assert _stat_line(text, "events").endswith("8")
    assert _stat_line(text, "unparsed_ts").endswith("0")
    assert _stat_line(text, "started").endswith("2026-11-01T00:00:00.000Z")
    assert _stat_line(text, "ended").endswith("2026-11-01T00:00:00.007Z")
    assert _stat_line(text, "duration_ms").endswith("7")
    assert str(baseline) in text
    assert _NOTE in text

    exit_code = main(["timing", str(baseline), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.endswith("\n")
    assert captured.out.startswith("{\n")
    payload = json.loads(captured.out)
    assert payload == collect_timing(load_summary(baseline), baseline)
    assert payload["version"] == "0.1.0"
    assert payload["run_id"] == "baseline"
    assert payload["adapter"] == "fixture"
    assert payload["model"] == "fixture"
    assert payload["run_dir"] == str(baseline)
    assert payload["note"] == _NOTE
    assert [row["task_id"] for row in payload["tasks"]] == BASELINE_TASKS
    summary_tasks = _summary_tasks(baseline)
    by_id = {row["task_id"]: row for row in payload["tasks"]}
    for task in summary_tasks:
        row = by_id[task["task_id"]]
        assert set(row) == _ROW_KEYS
        assert row["category"] == task["category"]
        assert row["score"] == float(task["score"])
        assert row["passed"] is bool(task["passed"])
        assert row["result"] == ("PASS" if task["passed"] else "FAIL")
        assert "grades" not in row
        if task["task_id"] == "fix-sum":
            assert row["events"] == 8
            assert row["unparsed_ts"] == 0
            assert row["has_trajectory"] is True
            assert row["started"] == "2026-11-01T00:00:00.000Z"
            assert row["ended"] == "2026-11-01T00:00:00.007Z"
            assert row["duration_ms"] == 7
        else:
            assert row["events"] == 0
            assert row["unparsed_ts"] == 0
            assert row["has_trajectory"] is False
            assert row["started"] is None
            assert row["ended"] is None
            assert row["duration_ms"] is None
    assert payload["totals"] == {
        "tasks_shown": 8,
        "events": 8,
        "unparsed_ts": 0,
        "with_timing": 1,
        "started": "2026-11-01T00:00:00.000Z",
        "ended": "2026-11-01T00:00:00.007Z",
        "duration_ms": 7,
    }
    assert "api_key" not in captured.out.lower()
    _assert_text_matches_payload(text, payload)

    exit_code = main(["timing", "baseline", "--root", str(FIXTURES), "--task", "fix-sum"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _shown_ids(captured.out, BASELINE_TASKS) == ["fix-sum"]
    assert "fizzbuzz" not in captured.out
    assert "2026-11-01T00:00:00.007Z" in captured.out
    assert _stat_line(captured.out, "with timing").endswith("1/1")
    assert _stat_line(captured.out, "events").endswith("8")
    assert _stat_line(captured.out, "duration_ms").endswith("7")
    assert _NOTE in captured.out

    exit_code = main(["timing", str(baseline), "--task", "fix-sum", "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    filtered = json.loads(captured.out)
    assert [row["task_id"] for row in filtered["tasks"]] == ["fix-sum"]
    assert filtered["tasks"][0]["duration_ms"] == 7
    assert filtered["totals"]["tasks_shown"] == 1
    assert filtered["totals"]["with_timing"] == 1
    assert filtered["totals"]["duration_ms"] == 7
    assert filtered["totals"]["events"] == 8

    exit_code = main(["timing", str(baseline), "--task", "fizzbuzz"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _shown_ids(captured.out, BASELINE_TASKS) == ["fizzbuzz"]
    assert _row_line(captured.out, "fizzbuzz").split()[4:7] == ["-", "-", "-"]
    assert "2026" not in captured.out
    assert _stat_line(captured.out, "with timing").endswith("0/1")
    assert _stat_line(captured.out, "events").endswith("0")
    assert _stat_line(captured.out, "unparsed_ts").endswith("0")
    assert _stat_line(captured.out, "started").endswith("-")
    assert _stat_line(captured.out, "ended").endswith("-")
    assert _stat_line(captured.out, "duration_ms").endswith("-")
    assert _NOTE in captured.out

    exit_code = main(["timing", str(baseline), "--task", "fizzbuzz", "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    fizz = json.loads(captured.out)
    assert fizz["tasks"][0]["has_trajectory"] is False
    assert fizz["tasks"][0]["events"] == 0
    assert fizz["tasks"][0]["duration_ms"] is None
    assert fizz["totals"]["duration_ms"] is None
    assert fizz["totals"]["with_timing"] == 0

    exit_code = main(["timing", str(baseline), "--task", "not-a-task"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "not-a-task" in captured.err
    with pytest.raises(UsageError):
        collect_timing(load_summary(baseline), baseline, task_id="not-a-task")

    exit_code = main(["timing", str(candidate)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    body = captured.out
    candidate_ids = [task["task_id"] for task in _summary_tasks(candidate)]
    assert body.startswith("agent-eval-obs 0.1.0  run candidate  adapter=fixture  model=fixture\n")
    assert _shown_ids(body, candidate_ids) == candidate_ids
    assert len(candidate_ids) == 8
    assert "2026" not in body
    for task_id in candidate_ids:
        cells = _row_line(body, task_id).split()
        assert cells[3] == "0"
        assert cells[4:7] == ["-", "-", "-"]
    assert "FAIL" in _row_line(body, "edit-json")
    assert "0.00" in _row_line(body, "edit-json")
    assert "PASS" in _row_line(body, "fizzbuzz")
    assert _stat_line(body, "with timing").endswith("0/8")
    assert _stat_line(body, "events").endswith("0")
    assert _stat_line(body, "unparsed_ts").endswith("0")
    assert _stat_line(body, "started").endswith("-")
    assert _stat_line(body, "ended").endswith("-")
    assert _stat_line(body, "duration_ms").endswith("-")
    assert _NOTE in body

    exit_code = main(["timing", str(candidate), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    candidate_payload = json.loads(captured.out)
    assert candidate_payload["run_id"] == "candidate"
    assert [row["task_id"] for row in candidate_payload["tasks"]] == candidate_ids
    assert all(row["events"] == 0 for row in candidate_payload["tasks"])
    assert all(row["has_trajectory"] is False for row in candidate_payload["tasks"])
    assert all(row["started"] is None for row in candidate_payload["tasks"])
    assert all(row["duration_ms"] is None for row in candidate_payload["tasks"])
    assert candidate_payload["totals"] == {
        "tasks_shown": 8,
        "events": 0,
        "unparsed_ts": 0,
        "with_timing": 0,
        "started": None,
        "ended": None,
        "duration_ms": None,
    }
    assert candidate_payload["note"] == _NOTE
    edit = next(row for row in candidate_payload["tasks"] if row["task_id"] == "edit-json")
    assert edit["result"] == "FAIL"
    assert edit["score"] == 0.0
    assert edit["category"] == "tool-use"
    assert "api_key" not in captured.out.lower()
    _assert_text_matches_payload(body, candidate_payload)

    assert {"baseline": _snapshot(baseline), "candidate": _snapshot(candidate)} == before


def test_timestamp_edges_do_not_rewrite_the_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = _write_edge_run(tmp_path / "edges")
    before = _snapshot(run_dir)

    exit_code = main(["timing", str(run_dir)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    text = captured.out
    assert text.startswith("agent-eval-obs 0.1.0  run edges  adapter=probe  model=probe\n")
    order = ["missing", "empty", "blank-ts", "messy", "reversed", "equal", "offset", "one"]
    assert _shown_ids(text, order) == order
    assert _row_line(text, "missing").split()[4:7] == ["-", "-", "-"]
    assert _row_line(text, "empty").split()[4:7] == ["-", "-", "-"]
    assert _row_line(text, "blank-ts").split()[4:7] == ["-", "-", "-"]
    assert _row_line(text, "reversed").split()[-2] == "0"
    assert _row_line(text, "equal").split()[-2] == "0"
    messy_cells = _row_line(text, "messy").split()
    assert messy_cells[4:7] == [
        "2026-11-01T00:00:00.100+08:00",
        "2026-11-01T00:00:00.007Z",
        "28799907",
    ]
    offset_line = _row_line(text, "offset")
    assert "2026-11-01T00:00:00.000+00:00" in offset_line
    assert "2026-11-01 00:00:00.250+00:00" in offset_line
    assert "2026-11-01T05:00:00.000+05:00" in _row_line(text, "equal")
    assert "2026-11-01T00:00:00.000z" in _row_line(text, "equal")
    assert _stat_line(text, "with timing").endswith("5/8")
    assert _stat_line(text, "events").endswith("30")
    assert _stat_line(text, "unparsed_ts").endswith("21")
    assert _stat_line(text, "started").endswith("2026-11-01T00:00:00.100+08:00")
    assert _stat_line(text, "ended").endswith("2026-10-31T00:00:00.000Z")
    assert _stat_line(text, "duration_ms").endswith("0")
    assert _NOTE in text

    exit_code = main(["timing", str(run_dir), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _snapshot(run_dir) == before
    assert captured.out.endswith("\n")
    assert "\\u" not in captured.out
    assert "编码" in captured.out
    payload = json.loads(captured.out)
    assert payload == collect_timing(load_summary(run_dir), run_dir)
    by_id = {row["task_id"]: row for row in payload["tasks"]}

    assert by_id["missing"]["has_trajectory"] is False
    assert by_id["missing"]["events"] == 0
    assert by_id["missing"]["unparsed_ts"] == 0
    assert by_id["missing"]["started"] is None
    assert by_id["missing"]["duration_ms"] is None
    assert by_id["missing"]["result"] == "PASS"

    assert by_id["empty"]["has_trajectory"] is True
    assert by_id["empty"]["events"] == 0
    assert by_id["empty"]["unparsed_ts"] == 0
    assert by_id["empty"]["started"] is None
    assert by_id["empty"]["ended"] is None
    assert by_id["empty"]["duration_ms"] is None
    assert by_id["empty"]["result"] == "FAIL"

    assert by_id["blank-ts"]["has_trajectory"] is True
    assert by_id["blank-ts"]["events"] == 3
    assert by_id["blank-ts"]["unparsed_ts"] == 3
    assert by_id["blank-ts"]["started"] is None
    assert by_id["blank-ts"]["ended"] is None
    assert by_id["blank-ts"]["duration_ms"] is None
    assert by_id["blank-ts"]["score"] == 0.5

    messy = by_id["messy"]
    assert messy["events"] == 15
    assert messy["unparsed_ts"] == 13
    assert messy["started"] == "2026-11-01T00:00:00.100+08:00"
    assert messy["ended"] == "2026-11-01T00:00:00.007Z"
    assert messy["duration_ms"] == 28_799_907
    assert messy["has_trajectory"] is True

    reversed_row = by_id["reversed"]
    assert reversed_row["started"] == "2026-11-01T00:00:02.000Z"
    assert reversed_row["ended"] == "2026-11-01T00:00:00.500Z"
    assert reversed_row["duration_ms"] == 0
    assert reversed_row["events"] == 5
    assert reversed_row["unparsed_ts"] == 3

    equal = by_id["equal"]
    assert equal["started"] == "2026-11-01T05:00:00.000+05:00"
    assert equal["ended"] == "2026-11-01T00:00:00.000z"
    assert equal["duration_ms"] == 0
    assert equal["unparsed_ts"] == 0

    offset = by_id["offset"]
    assert offset["started"] == "2026-11-01T00:00:00.000+00:00"
    assert offset["ended"] == "2026-11-01 00:00:00.250+00:00"
    assert offset["duration_ms"] == 250
    assert offset["unparsed_ts"] == 0

    one = by_id["one"]
    assert one["category"] == "编码"
    assert one["started"] == "2026-10-31T00:00:00.000Z"
    assert one["ended"] == "2026-10-31T00:00:00.000Z"
    assert one["duration_ms"] == 0
    assert one["events"] == 3
    assert one["unparsed_ts"] == 2

    assert payload["totals"] == {
        "tasks_shown": 8,
        "events": 30,
        "unparsed_ts": 21,
        "with_timing": 5,
        "started": "2026-11-01T00:00:00.100+08:00",
        "ended": "2026-10-31T00:00:00.000Z",
        "duration_ms": 0,
    }
    assert payload["note"] == _NOTE
    _assert_text_matches_payload(text, payload)
    assert _snapshot(run_dir) == before

    exit_code = main(["timing", str(run_dir), "--task", "offset", "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    offset_payload = json.loads(captured.out)
    assert [row["task_id"] for row in offset_payload["tasks"]] == ["offset"]
    assert offset_payload["tasks"][0]["started"] == "2026-11-01T00:00:00.000+00:00"
    assert offset_payload["tasks"][0]["ended"] == "2026-11-01 00:00:00.250+00:00"
    assert offset_payload["tasks"][0]["duration_ms"] == 250
    assert offset_payload["totals"] == {
        "tasks_shown": 1,
        "events": 2,
        "unparsed_ts": 0,
        "with_timing": 1,
        "started": "2026-11-01T00:00:00.000+00:00",
        "ended": "2026-11-01 00:00:00.250+00:00",
        "duration_ms": 250,
    }
    assert "messy" not in captured.out
    assert "编码" not in captured.out

    exit_code = main(["timing", str(run_dir), "--task", "blank-ts"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _row_line(captured.out, "blank-ts").split()[4:7] == ["-", "-", "-"]
    assert _stat_line(captured.out, "with timing").endswith("0/1")
    assert _stat_line(captured.out, "events").endswith("3")
    assert _stat_line(captured.out, "unparsed_ts").endswith("3")
    assert _stat_line(captured.out, "duration_ms").endswith("-")
    assert "2026" not in captured.out

    exit_code = main(["timing", str(run_dir), "--task", "one"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert _stat_line(captured.out, "with timing").endswith("1/1")
    assert _stat_line(captured.out, "duration_ms").endswith("0")
    assert _stat_line(captured.out, "started").endswith("2026-10-31T00:00:00.000Z")
    assert _stat_line(captured.out, "ended").endswith("2026-10-31T00:00:00.000Z")
    assert _snapshot(run_dir) == before


def test_invalid_jsonl_raises_and_leaves_the_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_dir = tmp_path / "broken"
    task_dir = run_dir / "tasks" / "only"
    task_dir.mkdir(parents=True)
    (task_dir / "trajectory.jsonl").write_text(
        '{"ts": "2026-11-01T00:00:00.000Z"}\n{not json\n',
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
        collect_timing(load_summary(run_dir), run_dir)
    exit_code = main(["timing", str(run_dir)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "invalid JSONL" in captured.err
    assert _snapshot(run_dir) == before

    array_dir = tmp_path / "array"
    array_task = array_dir / "tasks" / "only"
    array_task.mkdir(parents=True)
    (array_task / "trajectory.jsonl").write_text("[1]\n", encoding="utf-8")
    (array_dir / "summary.json").write_text(
        json.dumps(
            {
                "run_id": "array",
                "adapter": "probe",
                "model": "probe",
                "tasks": [{"task_id": "only", "passed": False, "score": 0}],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_array = _snapshot(array_dir)
    with pytest.raises(RunError, match="expected a JSON object"):
        collect_timing(load_summary(array_dir), array_dir)
    exit_code = main(["timing", str(array_dir), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.out == ""
    assert "expected a JSON object" in captured.err
    assert _snapshot(array_dir) == before_array


def test_unknown_run_and_usage_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["timing", "missing-run", "--root", str(tmp_path)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "run not found" in captured.err

    empty = tmp_path / "empty"
    empty.mkdir()
    exit_code = main(["timing", str(empty)])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "run not found" in captured.err

    with pytest.raises(SystemExit) as exc:
        main(["timing"])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        main(["timing", str(FIXTURES / "baseline"), "--format", "yaml"])
    assert exc.value.code == 2

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["timing", "--help"])
    assert exc.value.code == 0
    help_text = capsys.readouterr().out
    assert "ts" in help_text
    assert "not re-run" in help_text


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
    exit_code = main(["timing", str(run_dir)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.startswith("agent-eval-obs 0.1.0  run no-model  adapter=probe  model=probe\n")
    assert _stat_line(captured.out, "duration_ms").endswith("-")
    exit_code = main(["timing", str(run_dir), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["model"] == ""
    assert payload["adapter"] == "probe"
    assert payload["tasks"][0]["has_trajectory"] is False
    assert payload["totals"]["duration_ms"] is None


def _assert_text_matches_payload(text: str, payload: dict) -> None:
    assert text.startswith(
        f"agent-eval-obs {payload['version']}  run {payload['run_id']}  "
        f"adapter={payload['adapter']}  "
    )
    if payload["model"]:
        assert f"model={payload['model']}" in text.splitlines()[0]
    ids = [row["task_id"] for row in payload["tasks"]]
    assert _shown_ids(text, ids) == ids
    table = render_table(
        _COLUMNS,
        [
            [
                str(row["task_id"]),
                str(row["result"]),
                f"{float(row['score']):.2f}",
                str(row["events"]),
                row["started"] if row["started"] is not None else "-",
                row["ended"] if row["ended"] is not None else "-",
                "-" if row["duration_ms"] is None else str(row["duration_ms"]),
                str(row["unparsed_ts"]),
            ]
            for row in payload["tasks"]
        ],
    )
    assert table in text
    totals = payload["totals"]
    assert _stat_line(text, "with timing").endswith(
        f"{totals['with_timing']}/{totals['tasks_shown']}"
    )
    assert _stat_line(text, "events").endswith(str(totals["events"]))
    assert _stat_line(text, "unparsed_ts").endswith(str(totals["unparsed_ts"]))
    assert _stat_line(text, "started").endswith("-" if totals["started"] is None else totals["started"])
    assert _stat_line(text, "ended").endswith("-" if totals["ended"] is None else totals["ended"])
    duration = "-" if totals["duration_ms"] is None else str(totals["duration_ms"])
    assert _stat_line(text, "duration_ms").endswith(duration)
    assert payload["run_dir"] in _stat_line(text, "run dir")
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


def _write_edge_run(run_dir: Path) -> Path:
    run_dir.mkdir(parents=True)
    summary = {
        "schema": 1,
        "run_id": "edges",
        "adapter": "probe",
        "model": "probe",
        "passed": 5,
        "total": 8,
        "mean_score": 0.5,
        "tasks": [
            {"task_id": "missing", "category": "coding", "passed": True, "score": 1},
            {"task_id": "empty", "category": "coding", "passed": False, "score": 0},
            {"task_id": "blank-ts", "category": "coding", "passed": False, "score": 0.5},
            {"task_id": "messy", "category": "tool-use", "passed": True, "score": 1},
            {"task_id": "reversed", "category": "coding", "passed": False, "score": 0},
            {"task_id": "equal", "category": "coding", "passed": True, "score": 1},
            {"task_id": "offset", "category": "tool-use", "passed": True, "score": 1},
            {"task_id": "one", "category": "编码", "passed": True, "score": 1},
        ],
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    empty = run_dir / "tasks" / "empty"
    empty.mkdir(parents=True)
    (empty / "trajectory.jsonl").write_text("\n\n", encoding="utf-8")
    blank = run_dir / "tasks" / "blank-ts"
    blank.mkdir(parents=True)
    _write_jsonl(
        blank / "trajectory.jsonl",
        [
            {"kind": "thought", "ts": ""},
            {"kind": "thought", "ts": "yesterday"},
            {"kind": "final"},
        ],
    )
    messy = run_dir / "tasks" / "messy"
    messy.mkdir(parents=True)
    _write_jsonl(
        messy / "trajectory.jsonl",
        [
            {"kind": "thought"},
            {"kind": "thought", "ts": ""},
            {"kind": "thought", "ts": None},
            {"kind": "thought", "ts": 0},
            {"kind": "thought", "ts": False},
            {"kind": "thought", "ts": "nope"},
            {"kind": "thought", "ts": "2026-11-01T00:00:00"},
            {"kind": "task_start", "ts": "2026-11-01T00:00:00.100+08:00"},
            {"kind": "thought", "ts": "later-garbage"},
            {"kind": "thought", "ts": []},
            {"kind": "task_end", "ts": "2026-11-01T00:00:00.007Z"},
            {"kind": "thought", "ts": " "},
            {"kind": "thought", "ts": "2026-11-01T00:00:00.999"},
            {"kind": "thought", "ts": {"at": "2026-11-01T00:00:00.000Z"}},
            {"kind": "thought", "ts": 1.5},
        ],
    )
    reversed_dir = run_dir / "tasks" / "reversed"
    reversed_dir.mkdir(parents=True)
    _write_jsonl(
        reversed_dir / "trajectory.jsonl",
        [
            {"kind": "thought", "ts": None},
            {"kind": "task_start", "ts": "2026-11-01T00:00:02.000Z"},
            {"kind": "thought", "ts": "nope"},
            {"kind": "task_end", "ts": "2026-11-01T00:00:00.500Z"},
            {"kind": "thought", "ts": ""},
        ],
    )
    equal = run_dir / "tasks" / "equal"
    equal.mkdir(parents=True)
    _write_jsonl(
        equal / "trajectory.jsonl",
        [
            {"kind": "task_start", "ts": "2026-11-01T05:00:00.000+05:00"},
            {"kind": "task_end", "ts": "2026-11-01T00:00:00.000z"},
        ],
    )
    offset = run_dir / "tasks" / "offset"
    offset.mkdir(parents=True)
    _write_jsonl(
        offset / "trajectory.jsonl",
        [
            {"kind": "task_start", "ts": "2026-11-01T00:00:00.000+00:00"},
            {"kind": "task_end", "ts": "2026-11-01 00:00:00.250+00:00"},
        ],
    )
    one = run_dir / "tasks" / "one"
    one.mkdir(parents=True)
    _write_jsonl(
        one / "trajectory.jsonl",
        [
            {"kind": "thought", "ts": "not a time"},
            {"kind": "task_end", "ts": "2026-10-31T00:00:00.000Z"},
            {"kind": "final"},
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
