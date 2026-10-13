from __future__ import annotations

from app.rag.chunking import chunk_text, normalize, overlap_tail


def test_normalize_collapses_whitespace_and_line_endings() -> None:
    raw = "标题\r\n\r\n\r\n正文\u3000内容  多空格\t制表\r结尾"
    # Blank-line runs collapse to a single paragraph break, not to nothing — chunking splits
    # on that break.
    assert normalize(raw) == "标题\n\n正文 内容 多空格 制表\n结尾"


def test_empty_input_produces_no_chunks() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  \t ") == []


def test_short_text_stays_a_single_chunk() -> None:
    text = "这是一个简短的段落，应该原样保留为一个 chunk。"
    chunks = chunk_text(text, target_chars=500, overlap_chars=50)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_long_paragraph_is_split_on_sentence_boundaries() -> None:
    text = "".join(f"第{i}句话用于测试分块逻辑。" for i in range(120))
    chunks = chunk_text(text, target_chars=200, overlap_chars=0)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 200
    # Sentence-boundary splitting means every chunk should still end on a terminator.
    assert all(chunk.endswith("。") for chunk in chunks)


def test_chunks_never_grossly_exceed_target_plus_overlap() -> None:
    text = "\n\n".join(f"段落{i}：" + "内容" * 60 for i in range(30))
    target, overlap = 300, 60
    chunks = chunk_text(text, target_chars=target, overlap_chars=overlap)

    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= target + overlap + 2


def test_overlap_carries_context_between_chunks() -> None:
    text = "。".join(f"第{i}句说明平台规则与合规要求" for i in range(80))
    chunks = chunk_text(text, target_chars=200, overlap_chars=60)

    assert len(chunks) >= 3
    for previous, current in zip(chunks, chunks[1:], strict=False):
        tail = overlap_tail(previous, 60)
        assert tail, "expected a non-empty overlap tail on a multi-chunk document"
        assert tail in current


def test_oversized_sentence_is_split_without_losing_content() -> None:
    """A sentence longer than the target must be cut, not truncated."""
    sentence = "甲" * 1000
    chunks = chunk_text(sentence, target_chars=200, overlap_chars=0)

    assert len(chunks) == 5
    assert "".join(chunks) == sentence


def test_tiny_trailing_chunk_is_merged_into_its_predecessor() -> None:
    text = "甲" * 200 + "\n\n短。"
    chunks = chunk_text(text, target_chars=100, overlap_chars=0)
    assert all(len(chunk) >= 10 for chunk in chunks)


def test_overlap_tail_returns_empty_when_text_is_shorter() -> None:
    assert overlap_tail("短文本", 100) == ""


def test_paragraph_breaks_survive_normalisation() -> None:
    text = "第一段内容足够长以便成为一个独立分块。" * 3 + "\n\n" + "第二段内容同样足够长。" * 3
    chunks = chunk_text(text, target_chars=2000, overlap_chars=0)
    assert len(chunks) == 1
    assert "\n" in chunks[0]


def test_crlf_documents_do_not_produce_empty_chunks() -> None:
    raw = "第一行\r\n\r\n第二段内容\r\n\r\n\r\n第三段内容"
    chunks = chunk_text(raw, target_chars=1000, overlap_chars=0)
    assert len(chunks) == 1
    assert "\r" not in chunks[0]
