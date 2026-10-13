from __future__ import annotations

import json
import re

import structlog

from app.llm.client import LLMError, get_chat_client
from app.llm.router import route_model
from app.llm.types import ChatMessage

logger = structlog.get_logger(__name__)

REWRITE_SYSTEM = """You rewrite a user's search query so a retrieval system finds more relevant
policy clauses. Produce {n} alternative phrasings that keep the original intent but vary the
wording, terminology and level of abstraction. Reply with a JSON array of strings and nothing
else."""

_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)


async def expand_query(query: str, *, n: int = 3) -> list[str]:
    """Multi-query expansion. Returns [] on any failure so retrieval still proceeds."""
    query = query.strip()
    if not query:
        return []

    try:
        result = await get_chat_client().chat(
            [
                ChatMessage(role="system", content=REWRITE_SYSTEM.format(n=n)),
                ChatMessage(role="user", content=query),
            ],
            model=route_model("route"),
            temperature=0.4,
            max_tokens=256,
        )
    except LLMError as exc:
        logger.warning("query_expansion_failed", error=str(exc)[:200])
        return []

    match = _JSON_ARRAY.search(result.content)
    if not match:
        return []

    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    variants: list[str] = []
    for item in parsed:
        if isinstance(item, str):
            cleaned = item.strip()
            if cleaned and cleaned != query and cleaned not in variants:
                variants.append(cleaned)
    return variants[:n]
