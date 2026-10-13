from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

from app.config import get_settings
from app.llm.client import LLMError

settings = get_settings()

# Most Chinese business documents exported from Office still arrive as GBK/GB18030.
ENCODING_CHAIN = ("utf-8-sig", "utf-8", "gb18030", "utf-16", "latin-1")

# Binary containers that hold text, but only a dedicated extractor can reach it.
BINARY_EXTENSIONS = {
    ".doc",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
}


def ensure_allowed(filename: str, size_bytes: int) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        raise LLMError(
            f"{suffix} files are not supported yet. Convert to .txt, .md, .pdf or .docx first."
        )
    if suffix not in settings.allowed_upload_extensions:
        allowed = ", ".join(settings.allowed_upload_extensions)
        raise LLMError(f"Unsupported file type {suffix!r}. Allowed: {allowed}.")
    if size_bytes > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes / 1024 / 1024
        raise LLMError(f"File is larger than the {limit_mb:.1f} MB limit.")


def decode_bytes(raw: bytes) -> str:
    for encoding in ENCODING_CHAIN:
        try:
            return raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def extract_text(filename: str, raw: bytes) -> str:
    """Pull plain text out of an uploaded file, dispatching on its extension."""
    extractor = EXTRACTORS.get(Path(filename).suffix.lower())
    if extractor is None:
        return decode_bytes(raw)
    return extractor(raw)


def _extract_pdf(raw: bytes) -> str:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(raw))
    except Exception as exc:
        raise LLMError(f"Could not open the PDF: {exc}") from exc

    if reader.is_encrypted:
        raise LLMError("This PDF is password protected. Remove the password and upload it again.")

    try:
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise LLMError(f"Could not extract text from the PDF: {exc}") from exc

    text = "\n\n".join(pages)
    if not text.strip():
        raise LLMError(
            "This PDF has no text layer — it looks like a scan. OCR is not supported; "
            "run OCR over it and upload the resulting text instead."
        )
    return text


def _extract_docx(raw: bytes) -> str:
    from docx import Document as DocxDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = DocxDocument(io.BytesIO(raw))
    except Exception as exc:
        raise LLMError(f"Could not open the .docx file: {exc}") from exc

    lines: list[str] = []
    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            # Blank paragraphs are kept on purpose: chunking splits paragraphs on blank lines.
            lines.append(block.text)
        elif isinstance(block, Table):
            for row in block.rows:
                lines.append("\t".join(cell.text for cell in row.cells))

    text = "\n".join(lines)
    if not text.strip():
        raise LLMError("No text found in this .docx file.")
    return text


EXTRACTORS: dict[str, Callable[[bytes], str]] = {
    ".pdf": _extract_pdf,
    ".docx": _extract_docx,
}
