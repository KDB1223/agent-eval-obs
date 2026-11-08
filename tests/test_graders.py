"""Rule graders against a workspace and a fake trajectory."""

from pathlib import Path

from aeo.graders.engine import aggregate, grade_task
from aeo.graders.llm_judge import parse_judge_payload
from aeo.models import GraderSpec, Task
from aeo.runner.workspace import Workspace


def _task(*graders: GraderSpec) -> Task:
    return Task(
        id="sample",
        title="Sample",
        category="coding",
        prompt="Do the thing.",
        files={},
        tools=["read_file", "write_file"],
        graders=list(graders),
        mock_steps=[],
        rubric="Be precise.",
    )


def _spec(grader_type: str, **options) -> GraderSpec:
    weight = float(options.pop("weight", 1))
    required = bool(options.pop("required", True))
    return GraderSpec(id=grader_type, type=grader_type, weight=weight, required=required, options=options)


def test_contains_regex_exact_and_json(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "ws")
    workspace.seed(
        {
            "settings.json": '{"name": "demo", "debug": false, "retries": 3}\n',
            "note.txt": "hello lab\n",
        }
    )
    grades = grade_task(
        _task(
            _spec("contains", target="file", path="note.txt", value="lab"),
            _spec("regex", target="answer", pattern=r"done"),
            _spec("exact", target="answer", value="done"),
            _spec("json_subset", path="settings.json", expect={"debug": False, "retries": 3}),
            _spec("file_absent", path="missing.txt"),
        ),
        workspace,
        "done",
        [],
    )
    assert all(grade.passed for grade in grades)


def test_tool_graders_and_path_escape(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "ws")
    workspace.seed({"README.txt": "stay\n"})
    events = [
        {"kind": "tool_call", "tool": "write_file", "arguments": {"path": "../escape.txt", "content": "x"}},
        {"kind": "tool_call", "tool": "search", "arguments": {"pattern": "TODO"}},
    ]
    grades = grade_task(
        _task(
            _spec("tool_used", tool="search"),
            _spec("tool_any", tools=["read_file", "search"]),
            _spec("tool_absent", tool="edit_file"),
            _spec("no_path_escape"),
        ),
        workspace,
        "",
        events,
    )
    by_id = {grade.id: grade for grade in grades}
    assert by_id["tool_used"].passed
    assert by_id["tool_any"].passed
    assert by_id["tool_absent"].passed
    assert not by_id["no_path_escape"].passed


def test_unknown_grader_fails_closed(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "ws")
    grades = grade_task(_task(_spec("not-a-grader")), workspace, "", [])
    assert not grades[0].passed
    assert "unknown grader" in grades[0].detail


def test_skipped_judge_is_excluded_from_the_score(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "ws")
    grades = grade_task(
        _task(
            _spec("contains", target="answer", value="ok"),
            _spec("llm_judge", criteria="say ok", required=False),
        ),
        workspace,
        "ok",
        [],
        judge=None,
    )
    assert grades[1].skipped
    passed, score, _earned, _possible = aggregate(grades)
    assert passed
    assert score == 1.0


def test_parse_judge_payload_clamps_and_reads_a_fence() -> None:
    score, reason = parse_judge_payload('```json\n{"score": 1.4, "reason": "clear"}\n```')
    assert score == 1.0
    assert reason == "clear"
