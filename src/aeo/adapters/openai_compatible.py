"""OpenAI-compatible chat adapter.

Any server that accepts ``POST {base_url}/chat/completions`` with bearer
auth and a tools array can drive the in-loop tools. The API key is read
from the environment and is never written to the trajectory.
"""

from __future__ import annotations

import json
import os
from typing import Any

from aeo.adapters.base import BaseAgentAdapter
from aeo.errors import UsageError
from aeo.http_client import Transport, post_json
from aeo.models import AgentAction, AgentState
from aeo.runner.workspace import BUILTIN_TOOLS

_SYSTEM = (
    "You are a coding agent inside a jailed workspace. "
    "Use the provided tools to complete the task. "
    "When you are finished, reply with a short final answer and do not call a tool. "
    "Paths outside the workspace are refused."
)

_TOOL_DOCS: dict[str, dict[str, Any]] = {
    "read_file": {
        "description": "Read a UTF-8 text file inside the workspace.",
        "properties": {
            "path": {"type": "string", "description": "Relative path."},
            "offset": {"type": "integer", "description": "First line, starting at 1."},
            "limit": {"type": "integer", "description": "Maximum lines to return."},
        },
        "required": ["path"],
    },
    "write_file": {
        "description": "Create or replace a UTF-8 text file inside the workspace.",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    "edit_file": {
        "description": "Replace an exact string in a workspace file.",
        "properties": {
            "path": {"type": "string"},
            "old": {"type": "string"},
            "new": {"type": "string"},
            "replace_all": {"type": "boolean"},
        },
        "required": ["path", "old", "new"],
    },
    "list_dir": {
        "description": "List one directory inside the workspace.",
        "properties": {"path": {"type": "string"}},
        "required": [],
    },
    "search": {
        "description": "Search workspace files for a literal or regular expression.",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "regex": {"type": "boolean"},
        },
        "required": ["pattern"],
    },
}


class OpenAICompatibleAgentAdapter(BaseAgentAdapter):
    """In-loop adapter that turns chat completions into tool calls."""

    name = "openai"

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
        api_key: str | None = None,
        transport: Transport | None = None,
    ) -> OpenAICompatibleAgentAdapter:
        key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        if not key.strip():
            raise UsageError(
                "openai adapter requires OPENAI_API_KEY in the environment"
            )
        resolved_model = model or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini"
        resolved_base = base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1"
        timeout = float(os.environ.get("AEO_HTTP_TIMEOUT") or 60)
        return cls(
            api_key=key.strip(),
            base_url=resolved_base,
            model=resolved_model,
            timeout=timeout,
            transport=transport,
        )

    @property
    def model_label(self) -> str:
        return self.model

    def step(self, state: AgentState) -> AgentAction:
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": self._messages(state),
            "tools": self._tools(state.task.tools),
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
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("chat response has no choices[0].message") from exc
        if not isinstance(message, dict):
            raise RuntimeError("chat message is not an object")
        return self._action_from_message(message)

    def _messages(self, state: AgentState) -> list[dict[str, Any]]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": state.task.prompt},
        ]
        for item in state.history:
            kind = item.get("kind")
            if kind == "tool_call":
                messages.append(
                    {
                        "role": "assistant",
                        "content": item.get("thought") or "",
                        "tool_calls": [
                            {
                                "id": item["call_id"],
                                "type": "function",
                                "function": {
                                    "name": item["tool"],
                                    "arguments": json.dumps(item.get("arguments") or {}, sort_keys=True),
                                },
                            }
                        ],
                    }
                )
            elif kind == "observation":
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": item.get("call_id") or "",
                        "content": item.get("content") or "",
                    }
                )
        return messages

    def _tools(self, allowed: list[str]) -> list[dict[str, Any]]:
        specs = []
        for name in allowed:
            if name not in BUILTIN_TOOLS:
                continue
            doc = _TOOL_DOCS[name]
            specs.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": doc["description"],
                        "parameters": {
                            "type": "object",
                            "properties": doc["properties"],
                            "required": doc["required"],
                        },
                    },
                }
            )
        return specs

    def _action_from_message(self, message: dict[str, Any]) -> AgentAction:
        content = message.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        tool_calls = message.get("tool_calls") or []
        if tool_calls:
            call = tool_calls[0]
            function = call.get("function") or {}
            name = str(function.get("name") or "")
            raw_args = function.get("arguments") or "{}"
            if isinstance(raw_args, str):
                try:
                    arguments = json.loads(raw_args) if raw_args.strip() else {}
                except json.JSONDecodeError:
                    arguments = {}
            elif isinstance(raw_args, dict):
                arguments = raw_args
            else:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            return AgentAction(
                kind="tool",
                thought=content,
                tool=name,
                arguments=arguments,
                call_id=str(call.get("id") or ""),
            )
        return AgentAction(kind="final", content=content)
