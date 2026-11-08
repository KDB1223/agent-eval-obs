"""Deterministic adapter that replays the ``mock:`` script in a task file.

The script is data, so the same suite produces the same tool sequence on
every machine. The runner still executes the tools, so observations and
file changes in the trajectory are real.
"""

from __future__ import annotations

from aeo.adapters.base import BaseAgentAdapter
from aeo.models import AgentAction, AgentState, Task


class MockAgentAdapter(BaseAgentAdapter):
    """Offline stand-in for a coding agent. Used by CI and the demo."""

    name = "mock"

    def __init__(self) -> None:
        self._task_id = ""
        self._steps: list = []
        self._index = 0

    def begin(self, task: Task) -> None:
        self._task_id = task.id
        self._steps = list(task.mock_steps)
        self._index = 0

    @property
    def model_label(self) -> str:
        return "mock-script"

    def step(self, state: AgentState) -> AgentAction:
        if self._index >= len(self._steps):
            return AgentAction(
                kind="final",
                content=f"No mock script for task {self._task_id or state.task.id}.",
            )
        current = self._steps[self._index]
        self._index += 1
        if current.kind == "final":
            return AgentAction(kind="final", thought=current.thought, content=current.content)
        return AgentAction(
            kind="tool",
            thought=current.thought,
            tool=current.tool,
            arguments=dict(current.arguments),
        )
