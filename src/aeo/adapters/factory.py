"""Construct the adapter named on the command line."""

from __future__ import annotations

from aeo.adapters.base import BaseAgentAdapter
from aeo.adapters.command import CommandAgentAdapter
from aeo.adapters.mock import MockAgentAdapter
from aeo.adapters.openai_compatible import OpenAICompatibleAgentAdapter
from aeo.errors import UsageError


def build_adapter(
    name: str,
    *,
    command: list[str] | None = None,
    model: str | None = None,
    base_url: str | None = None,
    ingest_glob: str | None = None,
) -> BaseAgentAdapter:
    """Return the adapter for ``aeo run --adapter``."""
    if name == "mock":
        return MockAgentAdapter()
    if name == "openai":
        return OpenAICompatibleAgentAdapter.from_env(model=model, base_url=base_url)
    if name == "command":
        return CommandAgentAdapter(list(command or []), ingest_glob=ingest_glob)
    known = "mock, openai, command"
    raise UsageError(f"unknown adapter: {name} (expected {known})")
