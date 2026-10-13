from __future__ import annotations

import httpx

from app.config import get_settings

settings = get_settings()

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Shared async HTTP client.

    Reused across all provider calls so connections are pooled — on a 512 MB instance the
    number of live sockets matters as much as the number of live objects.
    """
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.llm_timeout_seconds, connect=10.0),
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=8),
            headers={"User-Agent": "agent-workbench/0.1"},
        )
    return _client


async def close_http_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None
