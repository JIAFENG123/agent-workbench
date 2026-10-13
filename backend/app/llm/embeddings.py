from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any, Literal

import httpx
import structlog

from app.config import get_settings
from app.llm.client import LLMError, RetryableLLMError, build_providers
from app.llm.http import get_http_client

logger = structlog.get_logger(__name__)
settings = get_settings()

InputType = Literal["query", "passage"]


class EmbeddingClient:
    """NVIDIA NIM embeddings.

    Runs remotely on purpose: on a 512 MB free instance there is no room for a local
    encoder, so the whole embedding stack is an API call.
    """

    def __init__(self) -> None:
        self._dim: int | None = None

    @property
    def model(self) -> str:
        return settings.embedding_model

    @property
    def dimension(self) -> int:
        return settings.embedding_dim

    def _endpoint(self) -> tuple[str, dict[str, str]]:
        providers = build_providers()
        if not providers:
            raise LLMError("No embedding provider configured. Set NVIDIA_API_KEY.")
        provider = providers[0]
        return provider.url("embeddings"), provider.headers()

    async def embed_batches(
        self,
        texts: list[str],
        *,
        input_type: InputType = "passage",
    ) -> AsyncIterator[list[list[float]]]:
        """Yield one batch of vectors at a time.

        Ingestion walks this instead of :meth:`embed` so no caller ever holds a whole
        document's vectors in memory — at 2048 dimensions a single chunk's vector costs
        roughly 64 KB as a Python list of floats.
        """
        if not texts:
            return
        url, headers = self._endpoint()
        batch_size = max(1, settings.embedding_batch_size)
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            yield await self._embed_batch(url, headers, batch, input_type)

    async def embed(
        self,
        texts: list[str],
        *,
        input_type: InputType = "passage",
    ) -> list[list[float]]:
        vectors: list[list[float]] = []
        async for batch in self.embed_batches(texts, input_type=input_type):
            vectors.extend(batch)
        return vectors

    async def _embed_batch(
        self,
        url: str,
        headers: dict[str, str],
        batch: list[str],
        input_type: InputType,
    ) -> list[list[float]]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": batch,
            "input_type": input_type,
            "encoding_format": "float",
            # Without truncation the API rejects any input past the model's token limit with a
            # 422 rather than shortening it.
            "truncate": settings.embedding_truncate,
        }
        last_error: Exception | None = None
        for attempt in range(1, 4):
            try:
                return await self._post(url, headers, payload, len(batch))
            except RetryableLLMError as exc:
                last_error = exc
                logger.warning("embedding_retry", attempt=attempt, error=str(exc)[:200])
                await asyncio.sleep(min(0.5 * 2 ** (attempt - 1), 8.0))
        raise LLMError(f"Embedding request failed after retries: {last_error}")

    async def _post(
        self, url: str, headers: dict[str, str], payload: dict[str, Any], expected: int
    ) -> list[list[float]]:
        started = time.perf_counter()
        try:
            response = await get_http_client().post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise RetryableLLMError(f"Embedding request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise RetryableLLMError(f"Embedding transport error: {exc}") from exc

        if response.status_code >= 400:
            message = f"Embedding API returned {response.status_code}: {response.text[:300]}"
            if response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
                raise RetryableLLMError(message)
            raise LLMError(message)

        body = response.json()
        rows = sorted(body.get("data") or [], key=lambda row: row.get("index", 0))
        vectors = [row.get("embedding") or [] for row in rows]

        if len(vectors) != expected:
            raise LLMError(f"Embedding API returned {len(vectors)} vectors for {expected} inputs")
        if vectors and self._dim is None:
            self._dim = len(vectors[0])
            if self._dim != settings.embedding_dim:
                logger.error(
                    "embedding_dim_mismatch",
                    expected=settings.embedding_dim,
                    actual=self._dim,
                    hint="Set EMBEDDING_DIM and re-run migrations.",
                )
        logger.debug(
            "embedding_ok",
            count=len(vectors),
            dim=self._dim,
            ms=int((time.perf_counter() - started) * 1000),
        )
        return vectors

    async def probe_dimension(self) -> int:
        vectors = await self.embed(["dimension probe"], input_type="query")
        return len(vectors[0]) if vectors else 0


_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client
