from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from app.config import get_settings
from app.llm.client import LLMError, RetryableLLMError, build_providers
from app.llm.http import get_http_client

logger = structlog.get_logger(__name__)
settings = get_settings()

# NIM rejects a request whose query+passage pair exceeds the model context window unless
# truncation is requested explicitly.
TRUNCATE = "END"
MAX_PASSAGES = 512


@dataclass
class RerankResult:
    index: int
    score: float


class RerankClient:
    """Cross-encoder reranking.

    Two response shapes are understood because NVIDIA's serving surface has both: the
    NeMo Retriever ranking API returns ``rankings[].logit``, while OpenAI/Cohere-style
    rerankers return ``results[].relevance_score``. The request body follows the NeMo
    Retriever contract, which is what the hosted endpoint documents.
    """

    @property
    def model(self) -> str:
        return settings.rerank_model

    def _endpoint(self) -> tuple[str, dict[str, str]]:
        providers = build_providers()
        if not providers:
            raise LLMError("No rerank provider configured. Set NVIDIA_API_KEY.")

        headers = providers[0].headers()
        if settings.rerank_api_key:
            headers["Authorization"] = f"Bearer {settings.rerank_api_key}"

        if settings.rerank_url:
            return settings.rerank_url, headers

        # Documented hosted path:
        #   https://ai.api.nvidia.com/v1/retrieval/nvidia/llama-nemotron-rerank-vl-1b-v2/reranking
        # The model id uses dots where the URL slug uses underscores.
        slug = self.model.replace(".", "_")
        base = settings.rerank_base_url.rstrip("/")
        return f"{base}/{slug}/reranking", headers

    @staticmethod
    def _parse(body: Any) -> list[RerankResult]:
        rows = body if isinstance(body, list) else None
        if rows is None and isinstance(body, dict):
            rows = body.get("rankings")
            if rows is None:
                rows = body.get("results")
        if rows is None:
            keys = list(body.keys()) if isinstance(body, dict) else type(body).__name__
            raise LLMError(f"Unrecognised rerank response shape: {keys}")

        parsed: list[RerankResult] = []
        for row in rows:
            score = row.get("logit")
            if score is None:
                score = row.get("relevance_score")
            if score is None:
                score = row.get("score")
            if score is None:
                continue
            parsed.append(RerankResult(index=int(row.get("index", 0)), score=float(score)))
        # The API documents a descending sort already; re-sorting is cheap insurance against
        # an endpoint that returns the raw order.
        parsed.sort(key=lambda item: item.score, reverse=True)
        return parsed

    async def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[RerankResult]:
        if not documents:
            return []
        if len(documents) > MAX_PASSAGES:
            raise LLMError(f"Rerank accepts at most {MAX_PASSAGES} passages, got {len(documents)}")

        limit = top_n or min(len(documents), settings.retrieval_final_k)
        url, headers = self._endpoint()
        payload: dict[str, Any] = {
            "model": self.model,
            "query": {"text": query},
            "passages": [{"text": document} for document in documents],
            "truncate": TRUNCATE,
        }

        last_error: Exception | None = None
        for attempt in range(1, settings.llm_max_retries + 1):
            try:
                results = await self._post(url, headers, payload)
                return results[:limit]
            except RetryableLLMError as exc:
                last_error = exc
                logger.warning("rerank_retry", attempt=attempt, error=str(exc)[:200])
                if attempt < settings.llm_max_retries:
                    await asyncio.sleep(min(0.5 * 2 ** (attempt - 1), 8.0))
            except LLMError as exc:
                last_error = exc
                break

        raise LLMError(f"Rerank failed: {last_error}")

    async def _post(
        self, url: str, headers: dict[str, str], payload: dict[str, Any]
    ) -> list[RerankResult]:
        started = time.perf_counter()
        try:
            response = await get_http_client().post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise RetryableLLMError(f"Rerank timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise RetryableLLMError(f"Rerank transport error: {exc}") from exc

        if response.status_code >= 400:
            message = f"Rerank API returned {response.status_code}: {response.text[:300]}"
            if response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
                raise RetryableLLMError(message)
            raise LLMError(message)

        logger.debug("rerank_ok", ms=int((time.perf_counter() - started) * 1000))
        return self._parse(response.json())


_client: RerankClient | None = None


def get_rerank_client() -> RerankClient:
    global _client
    if _client is None:
        _client = RerankClient()
    return _client
