"""Task loading and the jailed workspace tools."""

from pathlib import Path

import pytest

from aeo.errors import SuiteError
from aeo.runner.workspace import ToolRuntime, Workspace, WorkspaceError
from aeo.suites.loader import load_suite, load_task

ROOT = Path(__file__).resolve().parents[1]


def test_shipped_suite_has_eight_tasks() -> None:
    tasks = load_suite(ROOT / "suites")
    assert [task.id for task in tasks] == [
        "fix-sum",
        "fizzbuzz",
        "parse-ints",
        "add-docstring",
        "read-config",
        "search-todo",
        "edit-json",
        "safe-refusal",
    ]
    categories = {task.category for task in tasks}
    assert categories == {"coding", "tool-use"}
    for task in tasks:
        assert task.prompt
        assert task.graders
        assert task.mock_steps
        assert task.files


def test_loader_rejects_a_bad_task(tmp_path: Path) -> None:
    broken = tmp_path / "bad.yaml"
    broken.write_text("id: Fix\ntitle: x\n", encoding="utf-8")
    with pytest.raises(SuiteError):
        load_task(broken)


def test_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    body = (
        "id: same\ntitle: One\ncategory: coding\nprompt: do it\n"
        "tools: []\nfiles: {}\ngraders:\n  - id: a\n    type: contains\n"
        "    target: answer\n    value: ok\n"
    )
    (tmp_path / "a.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(body, encoding="utf-8")
    with pytest.raises(SuiteError, match="duplicate"):
        load_suite(tmp_path)


def test_tools_stay_inside_the_workspace(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "ws")
    workspace.seed({"math_utils.py": "def add(a, b):\n    return a - b\n"})
    runtime = ToolRuntime(workspace, ["read_file", "write_file", "edit_file", "list_dir", "search"])

    listed = runtime.execute("list_dir", {"path": "."})
    assert listed.ok
    assert "math_utils.py" in listed.content

    found = runtime.execute("search", {"pattern": "return a - b"})
    assert found.ok
    assert "math_utils.py:2:" in found.content

    edited = runtime.execute(
        "edit_file",
        {"path": "math_utils.py", "old": "return a - b", "new": "return a + b"},
    )
    assert edited.ok
    assert "return a + b" in (workspace.root / "math_utils.py").read_text(encoding="utf-8")

    ambiguous = runtime.execute(
        "edit_file",
        {"path": "math_utils.py", "old": "a", "new": "b"},
    )
    assert not ambiguous.ok
    assert "matched" in ambiguous.content

    denied = runtime.execute("write_file", {"path": "../outside.txt", "content": "nope"})
    assert not denied.ok
    assert not (tmp_path / "outside.txt").exists()

    absolute = runtime.execute("read_file", {"path": "/etc/hostname"})
    assert not absolute.ok

    with pytest.raises(WorkspaceError):
        workspace.resolve("~/secret")


def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "secret.txt"
    outside.write_text("secret", encoding="utf-8")
    workspace = Workspace(tmp_path / "ws")
    workspace.seed({"note.txt": "inside\n"})
    (workspace.root / "link").symlink_to(outside)
    runtime = ToolRuntime(workspace, ["read_file"])
    observed = runtime.execute("read_file", {"path": "link"})
    assert not observed.ok
    assert "secret" not in observed.content
