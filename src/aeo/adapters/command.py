"""Run an external agent as a subprocess.

The prompt is the process stdin. ``{workspace}``, ``{task_id}``, and
``{prompt}`` in argv items are replaced before the process starts. There is
no shell. This is how a local coding agent is plugged in without importing
its source.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from aeo.adapters.base import BaseAgentAdapter
from aeo.errors import UsageError
from aeo.models import LoopOutcome, Task
from aeo.runner.store import Recorder
from aeo.runner.workspace import Workspace

_MAX_INGEST = 200
_MAX_OUTPUT = 20_000


class CommandAgentAdapter(BaseAgentAdapter):
    """Black-box adapter. The external program edits the prepared workspace."""

    name = "command"
    owns_loop = True

    def __init__(
        self,
        argv: list[str],
        *,
        ingest_glob: str | None = None,
        timeout: float | None = None,
    ) -> None:
        if not argv:
            raise UsageError("command adapter requires at least one --command argument")
        if ingest_glob and Path(ingest_glob).is_absolute():
            raise UsageError("--ingest-glob must be relative to the workspace")
        self.argv_template = list(argv)
        self.ingest_glob = ingest_glob
        self.timeout = timeout

    @property
    def model_label(self) -> str:
        return "command"

    def step(self, state):  # pragma: no cover - owns_loop
        raise RuntimeError("command adapter owns the task loop")

    def run_task(self, task: Task, workspace: Workspace, recorder: Recorder) -> LoopOutcome:
        argv = [self._subst(item, task, workspace) for item in self.argv_template]
        recorder.write({"kind": "external_start", "argv": argv})
        timeout = self.timeout if self.timeout is not None else task.timeout_s
        try:
            completed = subprocess.run(
                argv,
                input=task.prompt,
                text=True,
                cwd=workspace.root,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            recorder.write({"kind": "error", "content": "command timed out"})
            return LoopOutcome(final_answer="", n_steps=1, error="command timed out")
        except OSError as exc:
            recorder.write({"kind": "error", "content": str(exc)})
            return LoopOutcome(final_answer="", n_steps=1, error=str(exc))
        stdout = _trim(completed.stdout)
        stderr = _trim(completed.stderr)
        recorder.write(
            {
                "kind": "observation",
                "step": 1,
                "call_id": "command",
                "tool": "command",
                "ok": completed.returncode == 0,
                "content": stdout,
                "stderr": stderr,
                "returncode": completed.returncode,
            }
        )
        self._ingest(workspace, recorder)
        final = stdout.strip()
        recorder.write({"kind": "final", "step": 1, "content": final})
        error = None if completed.returncode == 0 else f"command exited {completed.returncode}"
        return LoopOutcome(final_answer=final, n_steps=1, error=error)

    def _subst(self, token: str, task: Task, workspace: Workspace) -> str:
        return (
            token.replace("{workspace}", str(workspace.root))
            .replace("{task_id}", task.id)
            .replace("{prompt}", task.prompt)
        )

    def _ingest(self, workspace: Workspace, recorder: Recorder) -> None:
        if not self.ingest_glob:
            return
        kept = 0
        truncated = False
        for path in sorted(workspace.root.glob(self.ingest_glob)):
            if not path.is_file():
                continue
            try:
                path.resolve().relative_to(workspace.root)
            except ValueError:
                continue
            relative = path.relative_to(workspace.root).as_posix()
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                if kept >= _MAX_INGEST:
                    truncated = True
                    break
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    record = {"raw": line[:2000]}
                recorder.write({"kind": "external", "source": relative, "record": record})
                kept += 1
            if truncated:
                break
        if truncated:
            recorder.write(
                {
                    "kind": "error",
                    "content": f"ingest stopped at {_MAX_INGEST} external events",
                }
            )


def _trim(text: str | None) -> str:
    if not text:
        return ""
    if len(text) <= _MAX_OUTPUT:
        return text
    return text[:_MAX_OUTPUT] + "\n…(truncated)"
