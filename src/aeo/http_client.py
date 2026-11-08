"""Small JSON POST helper for OpenAI-compatible chat endpoints.

The default transport is the stdlib. Tests pass a callable with the same
signature and never open a socket.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

Transport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


def post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """POST ``payload`` as JSON and return the decoded object."""
    if transport is not None:
        data = transport(url, payload, headers, timeout)
        if not isinstance(data, dict):
            raise RuntimeError("HTTP transport returned a non-object")
        return data
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code} from chat endpoint: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"chat endpoint unreachable: {exc.reason}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("chat endpoint returned non-JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("chat endpoint returned a non-object")
    return parsed
