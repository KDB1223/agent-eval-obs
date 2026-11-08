"""On-disk layout for one run under ``.aeo/runs/<run_id>/``."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aeo.errors import UsageError

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")


def utc_now() -> str:
    """UTC timestamp with millisecond precision."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def new_run_id() -> str:
    """A sortable id that is also a safe directory name."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = uuid_suffix()
    return f"{stamp}-{suffix}"


def uuid_suffix() -> str:
    import uuid

    return uuid.uuid4().hex[:6]


def validate_run_id(run_id: str) -> str:
    """Reject ids that could escape the runs directory."""
    if not _RUN_ID.match(run_id):
        raise UsageError(
            "run id must be 1-81 characters of letters, digits, '.', '_' or '-'"
        )
    return run_id


class Recorder:
    """Append trajectory events as JSONL and keep them in memory for graders."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.events: list[dict[str, Any]] = []
        self._seq = 0
        self._handle = path.open("a", encoding="utf-8")

    def write(self, event: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        row: dict[str, Any] = {"ts": utc_now(), "seq": self._seq, **event}
        self.events.append(row)
        self._handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        self._handle.flush()
        return row

    def close(self) -> None:
        self._handle.close()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve_run(value: str, root: str | Path) -> Path:
    """Find a run directory from an id or a filesystem path."""
    candidate = Path(value)
    if candidate.is_dir() and (candidate / "summary.json").is_file():
        return candidate
    alt = Path(root) / value
    if alt.is_dir() and (alt / "summary.json").is_file():
        return alt
    raise UsageError(f"run not found: {value}")


def load_summary(run_dir: Path) -> dict[str, Any]:
    """Read ``summary.json`` and attach the directory path."""
    path = run_dir / "summary.json"
    if not path.is_file():
        raise UsageError(f"run not found: {run_dir}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise UsageError(f"{path} is not an object")
    data["run_dir"] = str(run_dir)
    return data
