from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Chunk
from app.llm.client import LLMError
from app.llm.embeddings import get_embedding_client
from app.llm.rerank import get_rerank_client
from app.obs.tracing import async_span
from app.rag.hybrid import bm25_search, reciprocal_rank_fusion, vector_search
from app.rag.index import load_chunks_by_ids
from app.rag.rewrite import expand_query

logger = structlog.get_logger(__name__)
settings = get_settings()


@dataclass
class Citation:
    index: int
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    ordinal: int
    score: float
    snippet: str


@dataclass
class RetrievalResult:
    query: str
    queries_used: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    stage_ms: dict[str, int] = field(default_factory=dict)
    reranked: bool = False

    @property
    def empty(self) -> bool:
        return not self.citations


def format_context(result: RetrievalResult) -> str:
    """Render citations as a numbered context block the model can point at."""
    if result.empty:
        return "（知识库中没有检索到相关内容）"
    blocks = [
        f"[{citation.index}] 来源：{citation.filename}（第 {citation.ordinal + 1} 段）\n"
        f"{citation.snippet}"
        for citation in result.citations
    ]
    return "\n\n".join(blocks)


def _snippet(text: str, limit: int = 400) -> str:
    text = text.strip()
    return text if len(text) <= limit else f"{text[:limit]}…"


async def retrieve(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    query: str,
    expand: bool = True,
    rerank: bool | None = None,
    final_k: int | None = None,
) -> RetrievalResult:
    """Hybrid retrieval: expansion → vector + BM25 → RRF → cross-encoder rerank."""
    started = time.perf_counter()
    limit = final_k or settings.retrieval_final_k
    stage_ms: dict[str, int] = {}

    async with async_span("rag.retrieve", kind="rag", attributes={"query": query, "limit": limit}):
        queries = [query]
        if expand:
            step = time.perf_counter()
            queries.extend(await expand_query(query))
            stage_ms["expand"] = int((time.perf_counter() - step) * 1000)

        step = time.perf_counter()
        vectors = await get_embedding_client().embed(queries, input_type="query")
        stage_ms["embed"] = int((time.perf_counter() - step) * 1000)

        step = time.perf_counter()
        ranked_lists: list[list[uuid.UUID]] = []
        for text, vector in zip(queries, vectors, strict=True):
            ranked_lists.append(
                await vector_search(
                    session, tenant_id=tenant_id, vector=vector, k=settings.retrieval_vector_k
                )
            )
            ranked_lists.append(
                await bm25_search(
                    session, tenant_id=tenant_id, query=text, k=settings.retrieval_bm25_k
                )
            )
        stage_ms["search"] = int((time.perf_counter() - step) * 1000)

        fused = reciprocal_rank_fusion(ranked_lists, limit=max(limit * 4, limit))
        if not fused:
            stage_ms["total"] = int((time.perf_counter() - started) * 1000)
            logger.info(
                "retrieval_empty",
                tenant_id=str(tenant_id),
                queries=len(queries),
                **{"ms": stage_ms},
            )
            return RetrievalResult(query=query, queries_used=queries, stage_ms=stage_ms)

        fused_scores = dict(fused)
        candidate_ids = [chunk_id for chunk_id, _ in fused]
        loaded = await load_chunks_by_ids(session, tenant_id=tenant_id, chunk_ids=candidate_ids)
        max_fused = max(fused_scores.values()) if fused_scores else 1.0
        candidates: list[tuple[Chunk, str, float]] = [
            (
                loaded[chunk_id][0],
                loaded[chunk_id][1],
                (fused_scores.get(chunk_id, 0.0) / max_fused) if max_fused > 0 else 0.0,
            )
            for chunk_id, _ in fused
            if chunk_id in loaded
        ]

        use_rerank = settings.rerank_enabled if rerank is None else rerank
        reranked = False
        if use_rerank and len(candidates) > 1:
            step = time.perf_counter()
            try:
                results = await get_rerank_client().rerank(
                    query, [chunk.content for chunk, _, _ in candidates], top_n=limit
                )
                reordered = [
                    (candidates[item.index][0], candidates[item.index][1], item.score)
                    for item in results
                    if 0 <= item.index < len(candidates)
                ]
                if reordered:
                    candidates = reordered
                    reranked = True
            except LLMError as exc:
                logger.warning("rerank_failed_falling_back_to_rrf", error=str(exc)[:200])
            stage_ms["rerank"] = int((time.perf_counter() - step) * 1000)

        citations = [
            Citation(
                index=position,
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                filename=filename,
                ordinal=chunk.ordinal,
                score=round(score, 6),
                snippet=_snippet(chunk.content),
            )
            for position, (chunk, filename, score) in enumerate(candidates[:limit], start=1)
        ]

        stage_ms["total"] = int((time.perf_counter() - started) * 1000)
        logger.info(
            "retrieval_done",
            tenant_id=str(tenant_id),
            queries=len(queries),
            candidates=len(fused),
            returned=len(citations),
            reranked=reranked,
            **{"ms": stage_ms},
        )
        return RetrievalResult(
            query=query,
            queries_used=queries,
            citations=citations,
            stage_ms=stage_ms,
            reranked=reranked,
        )
