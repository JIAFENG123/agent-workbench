from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from app.llm import embeddings as embeddings_module
from app.llm.embeddings import EmbeddingClient
from app.rag import index as index_module
from app.rag.chunking import chunk_text

DIMS = 4


class _FakeSession:
    """Records what the ingest pipeline tried to do, without a database."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.executed: list[object] = []
        self.flushes = 0
        self.expunges = 0
        self.commits = 0

    async def execute(self, statement: object) -> None:
        self.executed.append(statement)

    def add_all(self, instances: list[object]) -> None:
        self.added.extend(instances)

    async def flush(self) -> None:
        self.flushes += 1

    def expunge_all(self) -> None:
        self.expunges += 1

    async def commit(self) -> None:
        self.commits += 1


class _FakeEmbeddings:
    def __init__(self, batch_size: int = 2) -> None:
        self.batch_size = batch_size

    async def embed_batches(
        self, texts: list[str], *, input_type: str = "passage"
    ) -> AsyncIterator[list[list[float]]]:
        for start in range(0, len(texts), self.batch_size):
            yield [[0.5] * DIMS for _ in texts[start : start + self.batch_size]]


class _ExplodingEmbeddings:
    """Fails after the first batch, to prove a partial run commits nothing."""

    async def embed_batches(
        self, texts: list[str], *, input_type: str = "passage"
    ) -> AsyncIterator[list[list[float]]]:
        yield [[0.5] * DIMS for _ in texts[:2]]
        raise RuntimeError("embedding API went away")


def _long_text(paragraphs: int = 20) -> str:
    return "\n\n".join(f"第{index}段：" + "内容" * 300 for index in range(paragraphs))


def _stub_client(monkeypatch: pytest.MonkeyPatch, seen: list[list[str]]) -> EmbeddingClient:
    """An EmbeddingClient whose transport is replaced, so no HTTP is attempted."""
    client = EmbeddingClient()
    monkeypatch.setattr(client, "_endpoint", lambda: ("http://test/embeddings", {}))

    async def fake_batch(
        url: str, headers: dict[str, str], batch: list[str], input_type: str
    ) -> list[list[float]]:
        seen.append(list(batch))
        return [[float(len(text))] for text in batch]

    monkeypatch.setattr(client, "_embed_batch", fake_batch)
    return client


async def test_embed_batches_yields_one_request_per_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []
    client = _stub_client(monkeypatch, seen)
    monkeypatch.setattr(embeddings_module.settings, "embedding_batch_size", 2)
    texts = [f"t{index}" for index in range(5)]

    batches = [batch async for batch in client.embed_batches(texts)]

    assert [len(batch) for batch in batches] == [2, 2, 1]
    assert seen == [texts[0:2], texts[2:4], texts[4:5]]


async def test_embed_batches_of_nothing_issues_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    client = _stub_client(monkeypatch, seen)

    assert [batch async for batch in client.embed_batches([])] == []
    assert seen == []


async def test_embed_still_returns_every_vector_flattened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[list[str]] = []
    client = _stub_client(monkeypatch, seen)
    monkeypatch.setattr(embeddings_module.settings, "embedding_batch_size", 2)

    vectors = await client.embed([f"t{index}" for index in range(5)])

    assert len(vectors) == 5
    assert len(seen) == 3


async def test_ingest_writes_every_chunk_and_flushes_per_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    monkeypatch.setattr(index_module, "get_embedding_client", lambda: _FakeEmbeddings(2))
    text = _long_text()
    expected = chunk_text(text)
    assert len(expected) > 2

    written = await index_module.ingest_document(
        session, tenant_id=uuid.uuid4(), document_id=uuid.uuid4(), text=text
    )

    assert written == len(expected)
    assert [chunk.content for chunk in session.added] == expected
    assert [chunk.ordinal for chunk in session.added] == list(range(len(expected)))
    assert all(chunk.char_count == len(chunk.content) for chunk in session.added)
    assert session.flushes == -(-len(expected) // 2)
    # Each flushed batch is detached, which is what keeps peak memory at one batch.
    assert session.expunges == session.flushes
    # One commit for the whole document, so a failure halfway leaves no rows behind.
    assert session.commits == 1


async def test_ingest_rejects_a_document_over_the_chunk_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    monkeypatch.setattr(index_module, "get_embedding_client", lambda: _FakeEmbeddings(2))
    monkeypatch.setattr(index_module.settings, "max_chunks_per_document", 2)

    written = await index_module.ingest_document(
        session, tenant_id=uuid.uuid4(), document_id=uuid.uuid4(), text=_long_text()
    )

    assert written == 0
    assert session.added == []
    assert session.flushes == 0
    # It records the failure, so the document does not sit at "processing" forever.
    assert session.commits == 1


async def test_ingest_of_empty_text_marks_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    monkeypatch.setattr(index_module, "get_embedding_client", lambda: _FakeEmbeddings(2))

    written = await index_module.ingest_document(
        session, tenant_id=uuid.uuid4(), document_id=uuid.uuid4(), text="   \n\n  "
    )

    assert written == 0
    assert session.added == []
    assert session.commits == 1


async def test_a_failed_ingest_commits_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retrieval does not filter on document status, so half an index must never be visible."""
    session = _FakeSession()
    monkeypatch.setattr(index_module, "get_embedding_client", lambda: _ExplodingEmbeddings())

    with pytest.raises(RuntimeError):
        await index_module.ingest_document(
            session, tenant_id=uuid.uuid4(), document_id=uuid.uuid4(), text=_long_text()
        )

    assert session.commits == 0
