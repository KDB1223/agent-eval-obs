"""Offline suite execution, trajectories, and adapter loops."""

import io
import json
import sys
from pathlib import Path

import pytest

from aeo.adapters.command import CommandAgentAdapter
from aeo.adapters.mock import MockAgentAdapter
from aeo.adapters.openai_compatible import OpenAICompatibleAgentAdapter
from aeo.errors import UsageError
from aeo.graders.llm_judge import LLMJudge
from aeo.runner.execute import run_suite

ROOT = Path(__file__).resolve().parents[1]


def line_is_grade(line: str) -> bool:
    return '"kind": "grade"' in line


def _signature(summary: dict) -> list:
    rows = []
    for task in summary["tasks"]:
        grades = tuple((grade["id"], grade["passed"], grade["score"], grade["skipped"]) for grade in task["grades"])
        rows.append((task["task_id"], task["passed"], task["score"], grades))
    return rows


def test_mock_suite_is_reproducible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")
    stdout = io.StringIO()
    first = run_suite(
        ROOT / "suites",
        MockAgentAdapter(),
        run_root=tmp_path,
        run_id="run-a",
        stdout=stdout,
        stderr=io.StringIO(),
    )
    second = run_suite(
        ROOT / "suites",
        MockAgentAdapter(),
        run_root=tmp_path,
        run_id="run-b",
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert first["passed"] == 8
    assert first["total"] == 8
    assert first["mean_score"] == 1.0
    assert _signature(first) == _signature(second)
    board = stdout.getvalue()
    assert "pass rate     8/8 (100%)" in board
    assert "mean score    1.00" in board
    assert (tmp_path / "run-a" / "scoreboard.txt").read_text(encoding="utf-8") == board

    trajectory = (tmp_path / "run-a" / "tasks" / "fix-sum" / "trajectory.jsonl").read_text(encoding="utf-8")
    kinds = [json.loads(line)["kind"] for line in trajectory.splitlines()]
    assert kinds[0] == "task_start"
    assert "prompt" in kinds
    assert "tool_call" in kinds
    assert "observation" in kinds
    assert "final" in kinds
    assert "grade" in kinds
    assert kinds[-1] == "task_end"
    grades = [json.loads(line) for line in trajectory.splitlines() if line_is_grade(line)]
    judge = [grade for grade in grades if grade["id"] == "judge"]
    assert judge and judge[0]["skipped"] is True
    pytest_grade = next(grade for grade in grades if grade["id"] == "tests")
    assert "2 passed" in pytest_grade["detail"]
    blob = []
    for path in (tmp_path / "run-a").rglob("*"):
        if path.is_file():
            blob.append(path.read_text(encoding="utf-8", errors="replace"))
    assert "sk-test-secret-value" not in "\n".join(blob)

    with pytest.raises(UsageError):
        run_suite(
            ROOT / "suites",
            MockAgentAdapter(),
            run_root=tmp_path,
            run_id="run-a",
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )


def test_openai_adapter_loop_uses_a_fake_transport(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "note.yaml").write_text(
        "id: note\ntitle: Read the note\ncategory: tool-use\n"
        "prompt: What does note.txt say?\ntools: [read_file]\n"
        "files:\n  note.txt: |\n    hello from the file\n"
        "graders:\n  - id: answer\n    type: contains\n    target: answer\n    value: hello\n"
        "mock: []\nmax_steps: 4\n",
        encoding="utf-8",
    )
    calls: list[dict] = []

    def transport(url, payload, headers, timeout):
        calls.append(payload)
        assert url.endswith("/chat/completions")
        assert headers["Authorization"] == "Bearer test-key"
        if len(calls) == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "content": "I will read the note.",
                            "tool_calls": [
                                {
                                    "id": "c1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": '{"path": "note.txt"}',
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        roles = [message["role"] for message in payload["messages"]]
        assert "tool" in roles
        return {"choices": [{"message": {"content": "The note says hello from the file."}}]}

    adapter = OpenAICompatibleAgentAdapter(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="fake-model",
        transport=transport,
    )
    summary = run_suite(
        suite,
        adapter,
        run_root=tmp_path / "runs",
        run_id="openai-fake",
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert summary["passed"] == 1
    assert summary["model"] == "fake-model"
    assert len(calls) == 2


def test_command_adapter_grades_the_workspace_and_ingests_jsonl(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "echo.yaml").write_text(
        "id: echo-ok\ntitle: Write ok\ncategory: tool-use\n"
        "prompt: write ok\ntools: []\nfiles:\n  note.txt: seed\n"
        "graders:\n"
        "  - id: body\n    type: contains\n    target: file\n    path: out.txt\n    value: ok\n"
        "  - id: answer\n    type: contains\n    target: answer\n    value: done\n"
        "mock: []\ntimeout_s: 15\n",
        encoding="utf-8",
    )
    script = (
        "from pathlib import Path\n"
        "Path('out.txt').write_text('ok\\n', encoding='utf-8')\n"
        "Path('trace.jsonl').write_text('{\"event\": \"ping\"}\\n', encoding='utf-8')\n"
        "print('done')\n"
    )
    adapter = CommandAgentAdapter(
        [sys.executable, "-c", script],
        ingest_glob="trace.jsonl",
    )
    summary = run_suite(
        suite,
        adapter,
        run_root=tmp_path / "runs",
        run_id="command-demo",
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    assert summary["tasks"][0]["passed"]
    events = (tmp_path / "runs" / "command-demo" / "tasks" / "echo-ok" / "trajectory.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"kind": "external"' in events
    assert "ping" in events


def test_judge_changes_the_score_when_it_is_enabled(tmp_path: Path) -> None:
    def transport(url, payload, headers, timeout):
        return {"choices": [{"message": {"content": '{"score": 0, "reason": "too vague"}'}}]}

    judge = LLMJudge(
        api_key="test-key",
        base_url="https://example.invalid/v1",
        model="fake-judge",
        transport=transport,
    )
    summary = run_suite(
        ROOT / "suites",
        MockAgentAdapter(),
        run_root=tmp_path,
        run_id="judged",
        task_ids=["fix-sum"],
        judge=judge,
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    )
    task = summary["tasks"][0]
    assert task["passed"] is True
    assert task["score"] == pytest.approx(7 / 8)
    judge_grade = next(grade for grade in task["grades"] if grade["id"] == "judge")
    assert judge_grade["skipped"] is False
    assert judge_grade["score"] == 0
