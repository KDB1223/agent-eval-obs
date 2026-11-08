"""Jailed workspace and the small tool set the runner executes.

Adapters propose tool calls. This module is the only code that touches the
task directory, and every path is resolved back under the workspace root.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

BUILTIN_TOOLS = ("read_file", "write_file", "edit_file", "list_dir", "search")

_MAX_WRITE = 200_000
_MAX_READ_BYTES = 200_000
_MAX_SEARCH_HITS = 40


class WorkspaceError(Exception):
    """A path or file operation violated the workspace policy."""


@dataclass
class Observation:
    """Tool result handed back to the adapter and the trajectory log."""

    ok: bool
    content: str


class Workspace:
    """A directory that tool calls are not allowed to leave."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def seed(self, files: dict[str, str]) -> None:
        """Write the task's starter files."""
        for relative, content in files.items():
            path = self.resolve(relative)
            if path.exists() and path.is_symlink():
                raise WorkspaceError(f"refusing to seed through a symlink: {relative}")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    def resolve(self, raw: str) -> Path:
        """Resolve ``raw`` and reject anything outside ``root``."""
        if raw is None:
            raise WorkspaceError("path is required")
        text = str(raw).strip()
        if text in {"", "."}:
            return self.root
        if text.startswith("~"):
            raise WorkspaceError("home paths are outside the workspace")
        if text.startswith("file:"):
            raise WorkspaceError("file URLs are outside the workspace")
        candidate = Path(text)
        if candidate.is_absolute():
            target = candidate.resolve()
        else:
            target = (self.root / candidate).resolve()
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise WorkspaceError(f"path escapes the workspace: {raw}") from exc
        return target


class ToolRuntime:
    """Execute the built-in tools against one workspace."""

    def __init__(self, workspace: Workspace, allowed: list[str]) -> None:
        self.workspace = workspace
        self.allowed = set(allowed)

    def execute(self, name: str, arguments: dict) -> Observation:
        """Run one tool call. Failures become observations, not exceptions."""
        if name not in self.allowed:
            return Observation(False, f"tool not allowed for this task: {name}")
        if name not in BUILTIN_TOOLS:
            return Observation(False, f"unknown tool: {name}")
        if not isinstance(arguments, dict):
            return Observation(False, "arguments must be an object")
        handler = getattr(self, f"_tool_{name}")
        try:
            return handler(arguments)
        except WorkspaceError as exc:
            return Observation(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - tool errors stay in the trajectory
            return Observation(False, f"{type(exc).__name__}: {exc}")

    def _tool_read_file(self, args: dict) -> Observation:
        path = self.workspace.resolve(str(args.get("path", "")))
        if not path.is_file():
            return Observation(False, "not a file")
        size = path.stat().st_size
        if size > _MAX_READ_BYTES:
            return Observation(False, "file is too large to read")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return Observation(False, "file is not utf-8")
        lines = text.splitlines()
        offset = int(args.get("offset") or 1)
        limit = int(args.get("limit") or 200)
        if offset < 1:
            return Observation(False, "offset must be >= 1")
        if limit < 1:
            return Observation(False, "limit must be >= 1")
        selected = lines[offset - 1 : offset - 1 + limit]
        relative = path.relative_to(self.workspace.root).as_posix()
        if selected:
            end = offset + len(selected) - 1
            header = f"{relative}  lines {offset}-{end} of {len(lines)}"
            body = "\n".join(f"{number:>4}| {line}" for number, line in enumerate(selected, offset))
            return Observation(True, header + "\n" + body)
        header = f"{relative}  lines 0-0 of {len(lines)}"
        return Observation(True, header + "\n(empty)")

    def _tool_write_file(self, args: dict) -> Observation:
        path = self.workspace.resolve(str(args.get("path", "")))
        content = args.get("content")
        if not isinstance(content, str):
            return Observation(False, "content must be a string")
        if len(content) > _MAX_WRITE:
            return Observation(False, f"content exceeds {_MAX_WRITE} characters")
        if path.exists() and path.is_symlink():
            return Observation(False, "refusing to follow a symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        relative = path.relative_to(self.workspace.root).as_posix()
        return Observation(True, f"wrote {relative} ({len(content)} chars)")

    def _tool_edit_file(self, args: dict) -> Observation:
        path = self.workspace.resolve(str(args.get("path", "")))
        old = args.get("old")
        new = args.get("new")
        if not isinstance(old, str) or not isinstance(new, str):
            return Observation(False, "old and new must be strings")
        if old == "":
            return Observation(False, "old must be non-empty")
        if not path.is_file():
            return Observation(False, "not a file")
        if path.is_symlink():
            return Observation(False, "refusing to follow a symlink")
        text = path.read_text(encoding="utf-8")
        count = text.count(old)
        replace_all = bool(args.get("replace_all"))
        if count == 0:
            return Observation(False, "old string not found")
        if count > 1 and not replace_all:
            return Observation(
                False,
                f"old string matched {count} times; pass replace_all to replace every match",
            )
        updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
        path.write_text(updated, encoding="utf-8")
        replaced = count if replace_all else 1
        relative = path.relative_to(self.workspace.root).as_posix()
        return Observation(True, f"updated {relative} ({replaced} replacement)")

    def _tool_list_dir(self, args: dict) -> Observation:
        path = self.workspace.resolve(str(args.get("path") or "."))
        if not path.is_dir():
            return Observation(False, "not a directory")
        entries = []
        for child in sorted(path.iterdir(), key=lambda item: item.name):
            kind = "dir" if child.is_dir() and not child.is_symlink() else "file"
            if child.is_symlink():
                kind = "symlink"
            entries.append(f"{kind}  {child.name}")
        relative = path.relative_to(self.workspace.root).as_posix() or "."
        if not entries:
            return Observation(True, f"{relative}  (empty)")
        return Observation(True, f"{relative}\n" + "\n".join(entries))

    def _tool_search(self, args: dict) -> Observation:
        pattern = args.get("pattern")
        if not isinstance(pattern, str) or pattern == "":
            return Observation(False, "pattern is required")
        root = self.workspace.resolve(str(args.get("path") or "."))
        use_regex = bool(args.get("regex"))
        try:
            compiled = re.compile(pattern) if use_regex else None
        except re.error as exc:
            return Observation(False, f"invalid regex: {exc}")
        if root.is_file():
            files = [root]
        elif root.is_dir():
            files = sorted(item for item in root.rglob("*") if item.is_file())
        else:
            return Observation(False, "search path does not exist")
        hits: list[str] = []
        for file_path in files:
            try:
                file_path.resolve().relative_to(self.workspace.root)
            except ValueError:
                continue
            relative = file_path.relative_to(self.workspace.root)
            if any(part in {".git", "__pycache__", ".aeo"} for part in relative.parts):
                continue
            try:
                if file_path.stat().st_size > _MAX_READ_BYTES:
                    continue
                text = file_path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                matched = compiled.search(line) if compiled is not None else pattern in line
                if matched:
                    hits.append(f"{relative.as_posix()}:{lineno}: {line.strip()}")
                    if len(hits) >= _MAX_SEARCH_HITS:
                        break
            if len(hits) >= _MAX_SEARCH_HITS:
                break
        if not hits:
            return Observation(True, "no matches")
        return Observation(True, "\n".join(hits))
