"""Adapter interface.

An in-loop adapter implements ``step`` and lets the runner execute tools.
A black-box adapter sets ``owns_loop`` and implements ``run_task`` when an
external program already owns the workspace.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from aeo.models import AgentAction, AgentState, LoopOutcome, Task
from aeo.runner.store import Recorder
from aeo.runner.workspace import Workspace


class BaseAgentAdapter(ABC):
    """Common surface for mock, HTTP, and subprocess agents."""

    name = "base"
    owns_loop = False

    def begin(self, task: Task) -> None:
        """Reset per-task state. The runner calls this before the first step."""
        return None

    @abstractmethod
    def step(self, state: AgentState) -> AgentAction:
        """Return the next tool call or the final answer."""

    def run_task(self, task: Task, workspace: Workspace, recorder: Recorder) -> LoopOutcome:
        """Used only when ``owns_loop`` is true."""
        raise NotImplementedError(f"{self.name} does not own the task loop")

    @property
    def model_label(self) -> str:
        """Short model name recorded in the run manifest."""
        return self.name
