"""Task-suite inventory from YAML and JSON. The agent is not run."""

import json
from pathlib import Path

import pytest

from aeo import __version__
from aeo.cli import main
from aeo.inventory import collect_inventory
from aeo.suites.loader import load_suite

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "suites"
TASK_IDS = [
    "fix-sum",
    "fizzbuzz",
    "parse-ints",
    "add-docstring",
    "read-config",
    "search-todo",
    "edit-json",
    "safe-refusal",
]
GRADER_TYPES = [
    ("pytest", 4),
    ("contains", 6),
    ("regex", 5),
    ("tool_used", 6),
    ("llm_judge", 1),
    ("tool_any", 3),
    ("exact", 1),
    ("json_subset", 1),
    ("tool_absent", 2),
    ("no_path_escape", 1),
    ("file_absent", 1),
]


def test_shipped_suite_inventory_lists_every_task_in_filename_order() -> None:
    payload = collect_inventory(load_suite(SUITE), SUITE)
    assert payload["version"] == "0.1.0"
    assert payload["version"] == __version__
    assert [row["id"] for row in payload["tasks"]] == TASK_IDS
    assert payload["task_count"] == 8
    assert payload["categories"] == [
        {"category": "coding", "count": 4},
        {"category": "tool-use", "count": 4},
    ]
    assert [(item["type"], item["count"]) for item in payload["grader_types"]] == GRADER_TYPES
    assert payload["with_mock"] == 8
    assert payload["optional_graders"] == 1
    assert "No agent was run." in payload["note"]

    by_id = {row["id"]: row for row in payload["tasks"]}
    fix = by_id["fix-sum"]
    assert [grader["type"] for grader in fix["graders"]] == [
        "pytest",
        "contains",
        "regex",
        "contains",
        "tool_used",
        "tool_used",
        "llm_judge",
    ]
    assert fix["graders"][-1]["id"] == "judge"
    assert fix["graders"][-1]["required"] is False
    assert all(grader["required"] for grader in fix["graders"][:-1])
    assert fix["tools"] == ["read_file", "edit_file", "list_dir"]
    assert fix["mock"] == 3
    assert fix["files"] == 2

    assert by_id["search-todo"]["tools"] == ["list_dir", "search", "read_file"]
    assert by_id["search-todo"]["mock"] == 2
    assert by_id["search-todo"]["files"] == 3
    assert by_id["safe-refusal"]["mock"] == 1
    assert by_id["safe-refusal"]["files"] == 1
    assert by_id["edit-json"]["files"] == 1
    for row in payload["tasks"]:
        assert row["graders"]
        assert row["mock"] >= 1
        assert row["files"] >= 1


def test_cli_lists_the_shipped_suite_without_writing_a_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    suite_before = _snapshot(SUITE)
    exit_code = main(["list-tasks", "--suite", str(SUITE), "--fail-on-incomplete"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert list(tmp_path.iterdir()) == []
    assert _snapshot(SUITE) == suite_before
    assert not (ROOT / ".aeo").exists()

    text = captured.out
    assert text.startswith(f"agent-eval-obs 0.1.0  suite {SUITE}\n")
    assert text.endswith("Listed from the suite files. No agent was run.\n")
    positions = [text.index(task_id) for task_id in TASK_IDS]
    assert positions == sorted(positions)
    fix = next(line for line in text.splitlines() if line.startswith("fix-sum"))
    assert "pytest, contains×2, regex, tool_used×2, llm_judge?" in fix
    assert "read_file, edit_file, list_dir" in fix
    assert "\n" + _footer("tasks", "8") + "\n" in text
    assert "\n" + _footer("categories", "coding 4, tool-use 4") + "\n" in text
    assert "\n" + _footer("with mock", "8/8") + "\n" in text
    assert "\n" + _footer("optional graders", "1") + "\n" in text
    grader_line = next(line for line in text.splitlines() if line.startswith("graders"))
    for name, count in GRADER_TYPES:
        assert f"{name} {count}" in grader_line


def test_cli_json_matches_the_text_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = main(
        ["list-tasks", "--suite", str(SUITE), "--format", "json", "--fail-on-incomplete"]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert captured.out.endswith("\n")
    assert not captured.out.endswith("\n\n")
    assert list(tmp_path.iterdir()) == []
    payload = json.loads(captured.out)
    assert list(payload) == [
        "version",
        "suite",
        "tasks",
        "task_count",
        "categories",
        "grader_types",
        "with_mock",
        "optional_graders",
        "note",
    ]
    assert payload == collect_inventory(load_suite(SUITE), SUITE)
    assert [row["id"] for row in payload["tasks"]] == TASK_IDS
    assert payload["task_count"] == 8
    assert payload["with_mock"] == 8
    assert payload["optional_graders"] == 1


def test_default_suite_is_suites(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(ROOT)
    exit_code = main(["list-tasks", "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["suite"] == "suites"
    assert [row["id"] for row in payload["tasks"]] == TASK_IDS
    assert not (ROOT / ".aeo").exists()


def test_incomplete_mock_exits_1_and_optional_graders_do_not(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "01-bare.json").write_text(
        json.dumps(
            {
                "id": "bare",
                "title": "Bare",
                "category": "zebra",
                "prompt": "Say hi.",
                "tools": [],
                "files": {},
                "graders": [{"id": "judge", "type": "llm_judge", "required": False}],
                "mock": [{"final": "hi"}],
            }
        ),
        encoding="utf-8",
    )
    (suite / "02-unscripted.yaml").write_text(
        "id: unscripted\n"
        "title: No script\n"
        "category: alpha\n"
        "prompt: Do the thing.\n"
        "tools: [read_file]\n"
        "files:\n"
        "  note.txt: hello\n"
        "graders:\n"
        "  - id: word\n"
        "    type: contains\n"
        "    target: answer\n"
        "    value: hello\n"
        "  - id: again\n"
        "    type: contains\n"
        "    target: answer\n"
        "    value: hello\n"
        "  - id: maybe\n"
        "    type: contains\n"
        "    required: false\n"
        "    target: answer\n"
        "    value: hello\n",
        encoding="utf-8",
    )
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    exit_code = main(["list-tasks", "--suite", str(suite), "--fail-on-incomplete"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == ""
    assert list(work.iterdir()) == []
    text = captured.out
    assert text.startswith(f"agent-eval-obs 0.1.0  suite {suite}\n")
    rows = _table_rows(text)
    assert [row["task"] for row in rows] == ["bare", "unscripted"]
    assert rows[0]["category"] == "zebra"
    assert rows[0]["graders"] == "llm_judge?"
    assert rows[0]["tools"] == "-"
    assert rows[0]["mock"] == "1"
    assert rows[0]["files"] == "0"
    assert rows[1]["category"] == "alpha"
    assert rows[1]["graders"] == "contains×2 (1 optional)"
    assert rows[1]["tools"] == "read_file"
    assert rows[1]["mock"] == "0"
    assert rows[1]["files"] == "1"
    assert "zebra 1, alpha 1" in text
    assert "llm_judge 1, contains 3" in text
    assert "\n" + _footer("with mock", "1/2") + "\n" in text
    assert "\n" + _footer("optional graders", "2") + "\n" in text

    exit_code = main(["list-tasks", "--suite", str(suite), "--format", "json", "--fail-on-incomplete"])
    captured = capsys.readouterr()
    assert exit_code == 1
    payload = json.loads(captured.out)
    assert [row["id"] for row in payload["tasks"]] == ["bare", "unscripted"]
    assert payload["categories"] == [
        {"category": "zebra", "count": 1},
        {"category": "alpha", "count": 1},
    ]
    assert payload["grader_types"] == [
        {"type": "llm_judge", "count": 1},
        {"type": "contains", "count": 3},
    ]
    assert payload["tasks"][0]["tools"] == []
    assert payload["tasks"][0]["mock"] == 1
    assert payload["tasks"][0]["files"] == 0
    assert payload["tasks"][0]["graders"] == [{"id": "judge", "type": "llm_judge", "required": False}]
    assert payload["tasks"][1]["mock"] == 0
    assert payload["tasks"][1]["files"] == 1
    assert payload["with_mock"] == 1
    assert payload["task_count"] == 2
    assert payload["optional_graders"] == 2
    assert list(work.iterdir()) == []

    only = tmp_path / "only"
    only.mkdir()
    (only / "01-bare.json").write_text((suite / "01-bare.json").read_text(encoding="utf-8"), encoding="utf-8")
    exit_code = main(["list-tasks", "--suite", str(only), "--fail-on-incomplete"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "llm_judge?" in captured.out
    assert "1/1" in captured.out


def test_missing_empty_and_invalid_suites_exit_2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    exit_code = main(["list-tasks", "--suite", str(tmp_path / "missing")])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert captured.err.startswith("aeo: ")
    assert "suite directory not found" in captured.err

    empty = tmp_path / "empty"
    empty.mkdir()
    exit_code = main(["list-tasks", "--suite", str(empty), "--fail-on-incomplete"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "no task files" in captured.err

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "01-bad.yaml").write_text("id: Not-Valid\ntitle: T\nprompt: p\n", encoding="utf-8")
    exit_code = main(["list-tasks", "--suite", str(invalid), "--format", "json"])
    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == ""
    assert "aeo: " in captured.err
    assert {path.name for path in tmp_path.iterdir()} == {"empty", "invalid"}
    assert not (tmp_path / ".aeo").exists()


def _footer(label: str, value: str) -> str:
    return f"{label:<18}{value}"


def _table_rows(text: str) -> list[dict[str, str]]:
    lines = text.splitlines()
    header_at = next(index for index, line in enumerate(lines) if line.startswith("task"))
    rule = lines[header_at + 1]
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(rule):
        if rule[index] == "-":
            start = index
            while index < len(rule) and rule[index] == "-":
                index += 1
            spans.append((start, index))
        else:
            index += 1
    headers = [lines[header_at][start:end].strip() for start, end in spans]
    rows: list[dict[str, str]] = []
    for line in lines[header_at + 2 :]:
        if not line.strip():
            break
        cells = []
        for start, end in spans:
            cells.append(line[start:end].strip() if start < len(line) else "")
        rows.append(dict(zip(headers, cells, strict=True)))
    return rows


def _snapshot(path: Path) -> dict[str, str]:
    snap: dict[str, str] = {}
    for item in sorted(path.rglob("*")):
        if item.is_file():
            snap[str(item.relative_to(path))] = item.read_text(encoding="utf-8")
    return snap
