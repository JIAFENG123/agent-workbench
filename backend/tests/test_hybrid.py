from __future__ import annotations

import uuid

from app.rag.hybrid import reciprocal_rank_fusion, tokenize


def test_tokenize_emits_cjk_unigrams_and_bigrams() -> None:
    tokens = tokenize("平台规则")
    assert "平" in tokens
    assert "平台" in tokens
    assert "规则" in tokens


def test_tokenize_lowercases_latin_words() -> None:
    assert "amazon" in tokenize("Amazon Listing")


def test_tokenize_mixed_script() -> None:
    tokens = tokenize("Amazon 商品 Listing 规则")
    assert "amazon" in tokens
    assert "listing" in tokens
    assert "商品" in tokens


def test_tokenize_handles_non_text_input() -> None:
    assert tokenize("") == []
    assert tokenize("!!!???") == []


def test_rrf_ranks_documents_appearing_in_multiple_lists_highest() -> None:
    shared = uuid.uuid4()
    only_vector = uuid.uuid4()
    only_bm25 = uuid.uuid4()

    fused = reciprocal_rank_fusion([[shared, only_vector], [shared, only_bm25]])

    assert fused[0][0] == shared
    assert {chunk_id for chunk_id, _ in fused} == {shared, only_vector, only_bm25}


def test_rrf_score_decreases_with_rank() -> None:
    ids = [uuid.uuid4() for _ in range(4)]
    fused = reciprocal_rank_fusion([ids])
    scores = [score for _, score in fused]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > scores[-1]


def test_rrf_rank_one_beats_a_late_rank_from_another_list() -> None:
    """Fusion compares positions, not scores: cosine distance and BM25 scores live on wildly
    different scales, so only the rank each retriever assigned is trusted."""
    favourite = uuid.uuid4()
    late = uuid.uuid4()
    filler = [uuid.uuid4() for _ in range(4)]

    fused = reciprocal_rank_fusion([[favourite], [*filler, late]])
    scores = dict(fused)

    assert fused[0][0] == favourite
    assert scores[favourite] > scores[late]


def test_rrf_rewards_agreement_between_retrievers() -> None:
    """The document both retrievers place highly must beat documents only one of them found —
    this is the whole reason to fuse instead of picking a winner."""
    agreed = uuid.uuid4()
    vector_only = uuid.uuid4()
    bm25_only = uuid.uuid4()

    fused = reciprocal_rank_fusion([[vector_only, agreed], [bm25_only, agreed]])

    assert fused[0][0] == agreed


def test_rrf_respects_limit_and_empty_input() -> None:
    ids = [uuid.uuid4() for _ in range(10)]
    assert len(reciprocal_rank_fusion([ids], limit=3)) == 3
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []
