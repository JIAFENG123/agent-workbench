from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Chunk
from app.rag.index import corpus_version

_LATIN = re.compile(r"[A-Za-z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")
RRF_K = 60


def tokenize(text: str) -> list[str]:
    """Tokenizer for hybrid search that works without a Chinese dictionary.

    Latin runs become lowercase words; CJK text becomes unigrams plus bigrams. Bigrams are
    what give Chinese retrieval its precision — unigrams alone match almost every document,
    and without a segmenter there is no word boundary to rely on.
    """
    lowered = text.lower()
    latin = _LATIN.findall(lowered)
    characters = _CJK.findall(text)
    bigrams = ["".join(pair) for pair in zip(characters, characters[1:], strict=False)]
    return latin + characters + bigrams


@dataclass
class _CorpusEntry:
    version: tuple[int, str]
    chunk_ids: list[uuid.UUID]
    bm25: BM25Okapi


_corpus_cache: dict[uuid.UUID, _CorpusEntry] = {}


async def _get_corpus(session: AsyncSession, tenant_id: uuid.UUID) -> _CorpusEntry | None:
    version = await corpus_version(session, tenant_id)
    cached = _corpus_cache.get(tenant_id)
    if cached is not None and cached.version == version:
        return cached
    if version[0] == 0:
        _corpus_cache.pop(tenant_id, None)
        return None

    stmt = (
        select(Chunk.id, Chunk.content)
        .where(Chunk.tenant_id == tenant_id)
        .order_by(Chunk.document_id, Chunk.ordinal)
    )
    rows = (await session.execute(stmt)).all()
    chunk_ids = [row.id for row in rows]
    tokenized = [tokenize(row.content) or [""] for row in rows]

    entry = _CorpusEntry(version=version, chunk_ids=chunk_ids, bm25=BM25Okapi(tokenized))
    _corpus_cache[tenant_id] = entry
    return entry


def invalidate_corpus(tenant_id: uuid.UUID | None = None) -> None:
    if tenant_id is None:
        _corpus_cache.clear()
    else:
        _corpus_cache.pop(tenant_id, None)


async def vector_search(
    session: AsyncSession, *, tenant_id: uuid.UUID, vector: list[float], k: int
) -> list[uuid.UUID]:
    distance = Chunk.embedding.cosine_distance(vector)
    stmt = (
        select(Chunk.id)
        .where(Chunk.tenant_id == tenant_id, Chunk.embedding.is_not(None))
        .order_by(distance)
        .limit(k)
    )
    return [row.id for row in (await session.execute(stmt)).all()]


async def bm25_search(
    session: AsyncSession, *, tenant_id: uuid.UUID, query: str, k: int
) -> list[uuid.UUID]:
    entry = await _get_corpus(session, tenant_id)
    if entry is None:
        return []
    tokens = tokenize(query)
    if not tokens:
        return []
    scores = entry.bm25.get_scores(tokens)
    ranked = sorted(range(len(scores)), key=lambda index: scores[index], reverse=True)
    return [entry.chunk_ids[index] for index in ranked[:k] if scores[index] > 0]


def reciprocal_rank_fusion(
    ranked_lists: list[list[uuid.UUID]], *, k: int = RRF_K, limit: int | None = None
) -> list[tuple[uuid.UUID, float]]:
    """Fuse several ranked id lists without needing comparable scores.

    RRF is what lets a cosine distance and a BM25 score be merged at all — they live on
    different scales, so only the ranks are trusted.
    """
    scores: dict[uuid.UUID, float] = {}
    for ranked in ranked_lists:
        for rank, chunk_id in enumerate(ranked, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return ordered[:limit] if limit else ordered
