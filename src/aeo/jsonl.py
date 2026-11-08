"""Append-only JSONL helpers shared by the runner and the replay command."""

from __future__ import annotations

import json
from pathlib import Path

from aeo.errors import RunError


def read_jsonl(path: Path) -> list[dict]:
    """Load every JSON object in ``path``. Blank lines are ignored."""
    events: list[dict] = []
    text = path.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RunError(f"{path}:{lineno}: invalid JSONL ({exc})") from exc
        if not isinstance(item, dict):
            raise RunError(f"{path}:{lineno}: expected a JSON object")
        events.append(item)
    return events
