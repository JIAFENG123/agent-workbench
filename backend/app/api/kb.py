from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models import Document
from app.db.session import SessionLocal, get_session
from app.deps import Principal, get_principal
from app.llm.client import LLMError
from app.rag.hybrid import invalidate_corpus
from app.rag.index import ingest_document
from app.rag.loading import ensure_allowed, extract_text
from app.schemas import DocumentOut, KbLimitsOut

logger = structlog.get_logger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/kb", tags=["knowledge-base"])

# Strong references to in-flight ingestion tasks; asyncio only keeps weak ones, so without
# this a document could be garbage-collected mid-upload.
_ingest_tasks: set[asyncio.Task[None]] = set()


async def _ingest(document_id: uuid.UUID, tenant_id: uuid.UUID, text: str) -> None:
    """Runs outside the request so a large document cannot time out the upload call."""
    try:
        async with SessionLocal() as session:
            await ingest_document(session, tenant_id=tenant_id, document_id=document_id, text=text)
    except Exception as exc:  # noqa: BLE001 - recorded on the row, not raised into the void
        logger.exception("ingest_failed", document_id=str(document_id))
        async with SessionLocal() as session:
            from sqlalchemy import update

            await session.execute(
                update(Document)
                .where(Document.id == document_id)
                .values(status="failed", error=f"{type(exc).__name__}: {exc}"[:500])
            )
            await session.commit()
    finally:
        invalidate_corpus(tenant_id)


def _spawn_ingest(document_id: uuid.UUID, tenant_id: uuid.UUID, text: str) -> None:
    task = asyncio.create_task(_ingest(document_id, tenant_id, text), name=f"ingest-{document_id}")
    _ingest_tasks.add(task)
    task.add_done_callback(_ingest_tasks.discard)


@router.get("/limits", response_model=KbLimitsOut)
async def get_limits(_: Principal = Depends(get_principal)) -> KbLimitsOut:
    """Upload constraints, so the client can refuse an oversized file before sending it."""
    return KbLimitsOut(
        max_upload_bytes=settings.max_upload_bytes,
        max_chunks_per_document=settings.max_chunks_per_document,
    )


@router.post("/documents", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    file: UploadFile = File(...),
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> Document:
    filename = file.filename or "untitled.txt"

    try:
        # Reject on the declared size first: reading the body is what costs memory, and a
        # file we are going to refuse should never be materialised. The byte count is still
        # checked authoritatively below, since ``size`` is only advisory.
        if file.size is not None:
            ensure_allowed(filename, file.size)
        raw = await file.read()
        ensure_allowed(filename, len(raw))
        text = extract_text(filename, raw)
    except LLMError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    if not text.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File contains no text")

    document = Document(
        tenant_id=principal.tenant_id,
        filename=filename,
        content_type=file.content_type or "text/plain",
        size_bytes=len(raw),
        status="processing",
    )
    session.add(document)
    await session.commit()
    await session.refresh(document)

    _spawn_ingest(document.id, principal.tenant_id, text)
    logger.info("document_uploaded", document_id=str(document.id), bytes=len(raw))
    return document


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> list[Document]:
    stmt = (
        select(Document)
        .where(Document.tenant_id == principal.tenant_id)
        .order_by(Document.created_at.desc())
        .limit(200)
    )
    return list((await session.execute(stmt)).scalars().all())


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> None:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(Document).where(
                Document.id == document_id, Document.tenant_id == principal.tenant_id
            )
        ),
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    await session.commit()
    invalidate_corpus(principal.tenant_id)
