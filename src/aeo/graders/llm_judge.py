"""Optional LLM-as-judge grader.

The judge runs only when the caller passes a client. The CLI does that when
``--llm-judge`` is set or ``AEO_LLM_JUDGE`` is ``1``. Offline runs leave the
client empty, the grader is recorded as skipped, and it drops out of the score.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from aeo.errors import UsageError
from aeo.http_client import Transport, post_json
from aeo.models import GradeResult, GraderSpec, Task

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class LLMJudge:
    """Ask an OpenAI-compatible chat model for a 0..1 score."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60.0,
        transport: Transport | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.transport = transport

    @classmethod
    def from_env(
        cls,
        *,
        model: str | None = None,
        base_url: str | None = None,
        transport: Transport | None = None,
    ) -> LLMJudge:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise UsageError("LLM judge requires OPENAI_API_KEY")
        resolved_model = model or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
        resolved_base = base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        timeout = float(os.environ.get("AEO_HTTP_TIMEOUT") or 60)
        return cls(
            api_key=key,
            base_url=resolved_base,
            model=resolved_model,
            timeout=timeout,
            transport=transport,
        )

    def grade(
        self,
        *,
        task: Task,
        answer: str,
        events: list[dict[str, Any]],
        criteria: str,
        threshold: float,
        spec: GraderSpec,
    ) -> GradeResult:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You grade a coding-agent trajectory. "
                        "Reply with one JSON object: "
                        '{"score": <number from 0 to 1>, "reason": "<short reason>"}.'
                    ),
                },
                {"role": "user", "content": _prompt(task, answer, events, criteria)},
            ],
        }
        data = post_json(
            self.base_url + "/chat/completions",
            payload,
            {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            self.timeout,
            self.transport,
        )
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("judge response has no message content") from exc
        score, reason = parse_judge_payload(str(text or ""))
        passed = score + 1e-9 >= threshold
        return GradeResult(
            id=spec.id,
            type=spec.type,
            passed=passed,
            score=score,
            weight=spec.weight,
            detail=reason or f"score {score:.2f}",
            required=spec.required,
        )


def parse_judge_payload(text: str) -> tuple[float, str]:
    """Pull ``score`` and ``reason`` out of a model reply."""
    match = _JSON_OBJECT.search(text)
    if match is None:
        raise ValueError("judge did not return a JSON object")
    data = json.loads(match.group(0))
    if not isinstance(data, dict) or "score" not in data:
        raise ValueError("judge JSON needs a score")
    score = float(data["score"])
    if score < 0 or score > 1:
        score = min(1.0, max(0.0, score))
    reason = str(data.get("reason") or "")
    return score, reason


def judge_enabled_from_env() -> bool:
    """True when ``AEO_LLM_JUDGE`` is 1, true, or yes."""
    raw = os.environ.get("AEO_LLM_JUDGE", "").strip().lower()
    return raw in {"1", "true", "yes"}


def _prompt(task: Task, answer: str, events: list[dict[str, Any]], criteria: str) -> str:
    trace = _compact_trace(events)
    return (
        f"Task: {task.title}\n"
        f"Prompt:\n{task.prompt}\n\n"
        f"Rubric:\n{task.rubric or criteria}\n\n"
        f"Criteria:\n{criteria}\n\n"
        f"Final answer:\n{answer}\n\n"
        f"Trace:\n{trace}\n"
    )


def _compact_trace(events: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for event in events:
        kind = event.get("kind")
        if kind == "tool_call":
            lines.append(f"tool {event.get('tool')} {json.dumps(event.get('arguments') or {}, sort_keys=True)}")
        elif kind == "observation":
            status = "ok" if event.get("ok") else "error"
            lines.append(f"observe {event.get('tool')} {status}")
        elif kind == "final":
            lines.append("final")
    text = "\n".join(lines)
    if len(text) > 6000:
        return text[:6000] + "\n…(truncated)"
    return text
