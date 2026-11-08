"""Shared records for tasks, adapter actions, and graded results."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GraderSpec:
    """One check declared in a task file."""

    id: str
    type: str
    weight: float = 1.0
    required: bool = True
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class MockStep:
    """One scripted turn for ``MockAgentAdapter``."""

    kind: str
    thought: str = ""
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    content: str = ""


@dataclass
class Task:
    """A single graded task loaded from YAML or JSON."""

    id: str
    title: str
    category: str
    prompt: str
    files: dict[str, str]
    tools: list[str]
    graders: list[GraderSpec]
    mock_steps: list[MockStep]
    rubric: str = ""
    max_steps: int = 8
    timeout_s: float = 30.0
    source: str = ""


@dataclass
class AgentState:
    """What an in-loop adapter can see on each turn."""

    task: Task
    workspace: Path
    history: list[dict[str, Any]] = field(default_factory=list)
    step: int = 0


@dataclass
class AgentAction:
    """A tool call or a final answer returned by an adapter."""

    kind: str
    thought: str = ""
    tool: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    content: str = ""
    call_id: str = ""


@dataclass
class LoopOutcome:
    """Result of an adapter that owns the whole task loop."""

    final_answer: str
    n_steps: int
    error: str | None = None


@dataclass
class GradeResult:
    """One grader's outcome. Skipped graders stay out of the score."""

    id: str
    type: str
    passed: bool
    score: float
    weight: float
    detail: str
    skipped: bool = False
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "passed": self.passed,
            "score": self.score,
            "weight": self.weight,
            "detail": self.detail,
            "skipped": self.skipped,
            "required": self.required,
        }


@dataclass
class TaskResult:
    """Graded outcome for one task inside a run."""

    task_id: str
    title: str
    category: str
    passed: bool
    score: float
    earned: float
    possible: float
    final_answer: str
    n_steps: int
    error: str | None
    grades: list[GradeResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "title": self.title,
            "category": self.category,
            "passed": self.passed,
            "score": self.score,
            "earned": self.earned,
            "possible": self.possible,
            "final_answer": self.final_answer,
            "n_steps": self.n_steps,
            "error": self.error,
            "grades": [grade.to_dict() for grade in self.grades],
        }
