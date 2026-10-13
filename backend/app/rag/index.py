from __future__ import annotations

import uuid
from typing import Any, cast

import structlog
from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Chunk, Document
from app.llm.embeddings import get_embedding_client
from app.rag.chunking import chunk_text

logger = structlog.get_logger(__name__)
settings = get_settings()


async def _mark_failed(session: AsyncSession, document_id: uuid.UUID, error: str) -> None:
    await session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(status="failed", error=error, chunk_count=0)
    )
    await session.commit()


async def ingest_document(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    document_id: uuid.UUID,
    text: str,
) -> int:
    """Chunk, embed and index a document. Replaces any previous chunks for that document."""
    chunks = chunk_text(text)
    if not chunks:
        await _mark_failed(session, document_id, "No extractable text found")
        return 0

    limit = settings.max_chunks_per_document
    if len(chunks) > limit:
        await _mark_failed(
            session,
            document_id,
            f"Document produced {len(chunks)} chunks, over the limit of {limit}. "
            "Split it into smaller files and upload them separately.",
        )
        return 0

    await session.execute(delete(Chunk).where(Chunk.document_id == document_id))

    written = 0
    async for vectors in get_embedding_client().embed_batches(chunks, input_type="passage"):
        session.add_all(
            [
                Chunk(
                    tenant_id=tenant_id,
                    document_id=document_id,
                    ordinal=written + offset,
                    content=chunks[written + offset],
                    char_count=len(chunks[written + offset]),
                    embedding=vector,
                )
                for offset, vector in enumerate(vectors)
            ]
        )
        written += len(vectors)
        # Flush each batch inside the one transaction, then drop the ORM's references to it.
        # The inserts stay uncommitted, so a failure never leaves a half-indexed document
        # that retrieval would happily return; but the session holds one batch of vectors at
        # a time instead of the whole document's.
        await session.flush()
        session.expunge_all()

    await session.execute(
        update(Document)
        .where(Document.id == document_id)
        .values(status="ready", chunk_count=len(chunks), error=None)
    )
    await session.commit()

    logger.info(
        "document_ingested",
        document_id=str(document_id),
        chunks=len(chunks),
        chars=sum(len(chunk) for chunk in chunks),
    )
    return len(chunks)


async def load_chunks_by_ids(
    session: AsyncSession, *, tenant_id: uuid.UUID, chunk_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[Chunk, str]]:
    if not chunk_ids:
        return {}
    stmt = (
        select(Chunk, Document.filename)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.tenant_id == tenant_id, Chunk.id.in_(chunk_ids))
    )
    rows = (await session.execute(stmt)).all()
    return {chunk.id: (chunk, filename) for chunk, filename in rows}


async def corpus_version(session: AsyncSession, tenant_id: uuid.UUID) -> tuple[int, str]:
    """Cheap fingerprint of a tenant's corpus, used to invalidate the in-process BM25 index."""
    from sqlalchemy import func

    stmt = select(func.count(Chunk.id), func.max(Chunk.created_at)).where(
        Chunk.tenant_id == tenant_id
    )
    count, latest = (await session.execute(stmt)).one()
    return int(count or 0), str(latest or "")


async def recover_stale_documents(session: AsyncSession | None = None) -> int:
    """Mark documents whose ingestion was cut off by a restart.

    Ingestion runs as an in-process asyncio task, so a deploy or crash leaves rows stuck at
    ``processing`` forever unless they are reconciled on boot.
    """
    if session is None:
        from app.db.session import SessionLocal

        async with SessionLocal() as owned_session:
            return await recover_stale_documents(owned_session)

    result = cast(
        "CursorResult[Any]",
        await session.execute(
            update(Document)
            .where(Document.status.in_(("pending", "processing")))
            .values(status="failed", error="Process restarted while this document was ingesting")
        ),
    )
    await session.commit()
    return result.rowcount or 0
