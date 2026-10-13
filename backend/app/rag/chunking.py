from __future__ import annotations

import re

from app.config import get_settings

settings = get_settings()

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n+")
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;.])\s*")
_WHITESPACE = re.compile(r"[ \t\u3000]+")
_BLANK_LINE_RUN = re.compile(r"\n{2,}")

MIN_CHUNK_CHARS = 80


def normalize(text: str) -> str:
    """Collapse horizontal whitespace and normalise line endings.

    Runs of blank lines are collapsed to exactly one empty line rather than removed: chunking
    splits on paragraph breaks, so erasing them here would merge a whole document into a
    single block and defeat the paragraph-aware packing downstream.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _WHITESPACE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    joined = _BLANK_LINE_RUN.sub("\n\n", "\n".join(lines))
    return joined.strip()


def _split_oversized(block: str, target_chars: int) -> list[str]:
    sentences = [piece for piece in _SENTENCE_SPLIT.split(block) if piece.strip()]
    if len(sentences) <= 1:
        return [block[index : index + target_chars] for index in range(0, len(block), target_chars)]

    pieces: list[str] = []
    buffer = ""
    for sentence in sentences:
        if len(buffer) + len(sentence) <= target_chars:
            buffer += sentence
            continue
        if buffer.strip():
            pieces.append(buffer.strip())
        buffer = ""
        if len(sentence) <= target_chars:
            buffer = sentence
        else:
            # A sentence too large to fit must be hard-split, never truncated — slicing to
            # target_chars would silently drop the remainder from the index.
            pieces.extend(
                sentence[index : index + target_chars]
                for index in range(0, len(sentence), target_chars)
            )
    if buffer.strip():
        pieces.append(buffer.strip())
    return pieces


def overlap_tail(text: str, overlap_chars: int) -> str:
    """Take the trailing slice of a chunk, starting at a sentence boundary when possible."""
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return ""
    tail = text[-overlap_chars:]
    boundary = _SENTENCE_SPLIT.search(tail)
    if boundary and boundary.end() < len(tail) - 1:
        return tail[boundary.end() :].strip()
    return tail.strip()


def chunk_text(
    text: str,
    *,
    target_chars: int | None = None,
    overlap_chars: int | None = None,
) -> list[str]:
    """Paragraph-aware chunking with sentence-boundary overflow and overlap tails.

    Paragraph structure carries most of the meaning in policy documents, so chunks are
    packed on paragraph boundaries first and only fall back to sentence splitting when a
    single paragraph exceeds the target size.
    """
    target = target_chars or settings.chunk_target_chars
    overlap = overlap_chars if overlap_chars is not None else settings.chunk_overlap_chars

    cleaned = normalize(text)
    if not cleaned:
        return []

    blocks: list[str] = []
    for paragraph in _PARAGRAPH_SPLIT.split(cleaned):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= target:
            blocks.append(paragraph)
        else:
            blocks.extend(_split_oversized(paragraph, target))

    chunks: list[str] = []
    buffer = ""
    for block in blocks:
        if not buffer:
            buffer = block
            continue
        if len(buffer) + len(block) + 1 <= target:
            buffer = f"{buffer}\n{block}"
        else:
            chunks.append(buffer.strip())
            tail = overlap_tail(buffer, overlap)
            buffer = f"{tail}\n{block}".strip() if tail else block
    if buffer.strip():
        chunks.append(buffer.strip())

    merged: list[str] = []
    for chunk in chunks:
        if merged and len(chunk) < MIN_CHUNK_CHARS:
            merged[-1] = f"{merged[-1]}\n{chunk}"
        else:
            merged.append(chunk)
    return [chunk for chunk in merged if chunk.strip()]
