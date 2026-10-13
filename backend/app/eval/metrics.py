from __future__ import annotations

import re


def _contains_any_truth(snippet: str, ground_truth: list[str]) -> bool:
    """Checks whether a retrieved snippet contains any of the ground-truth key fragments."""
    snippet_lower = snippet.lower()
    return any(gt.lower() in snippet_lower for gt in ground_truth)


def hit_rate_at_k(retrieved_snippets: list[str], ground_truth: list[str], k: int = 5) -> float:
    """Returns 1.0 if at least one ground-truth snippet is hit in top-K, else 0.0."""
    if not ground_truth:
        return 1.0
    for snippet in retrieved_snippets[:k]:
        if _contains_any_truth(snippet, ground_truth):
            return 1.0
    return 0.0


def mrr_at_k(retrieved_snippets: list[str], ground_truth: list[str], k: int = 5) -> float:
    """Mean Reciprocal Rank: reciprocal of the rank of the first relevant snippet."""
    if not ground_truth:
        return 1.0
    for rank, snippet in enumerate(retrieved_snippets[:k], start=1):
        if _contains_any_truth(snippet, ground_truth):
            return 1.0 / rank
    return 0.0


def precision_at_k(retrieved_snippets: list[str], ground_truth: list[str], k: int = 5) -> float:
    """Fraction of retrieved top-K snippets that are relevant."""
    if not ground_truth:
        return 1.0
    top = retrieved_snippets[:k]
    if not top:
        return 0.0
    relevant = sum(1 for s in top if _contains_any_truth(s, ground_truth))
    return relevant / len(top)


def tool_calling_accuracy(invoked_tools: list[str], expected_tools: list[str]) -> float:
    """Accuracy score based on whether all expected tools were invoked."""
    if not expected_tools:
        return 1.0 if not invoked_tools else 0.8
    if not invoked_tools:
        return 0.0
    invoked_set = set(invoked_tools)
    matched = sum(1 for t in expected_tools if t in invoked_set)
    return matched / len(expected_tools)


def keyword_coverage(answer: str, expected_keywords: list[str]) -> float:
    """Fraction of expected keywords matched in the answer."""
    if not expected_keywords:
        return 1.0
    answer_lower = answer.lower()
    matched = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)
    return matched / len(expected_keywords)


def forbidden_claims_score(answer: str, forbidden_claims: list[str]) -> float:
    """Returns 1.0 if zero forbidden claims appeared, or penalizes if violated."""
    if not forbidden_claims:
        return 1.0
    answer_lower = answer.lower()
    violations = sum(1 for claim in forbidden_claims if claim.lower() in answer_lower)
    return 0.0 if violations > 0 else 1.0


def faithfulness_score(answer: str, citations: list[dict]) -> float:
    """Evaluates answer grounding and citation validity.

    Checks:
    1. If citations are returned, are citation markers (e.g. [1], [2]) present in the answer?
    2. Are there invalid citation numbers referenced that do not exist?
    """
    if not citations:
        # If no citations were needed/provided, check if answer claims citations
        has_bracket = bool(re.search(r"\[\d+\]", answer))
        return 0.5 if has_bracket else 1.0

    valid_indices = {c.get("index") for c in citations if "index" in c}
    cited_numbers = [int(n) for n in re.findall(r"\[(\d+)\]", answer)]

    if not cited_numbers:
        # Citations were returned by retriever, but the model did not cite them
        return 0.2

    # Check validity of referenced numbers
    valid_citations_count = sum(1 for num in cited_numbers if num in valid_indices)
    citation_precision = valid_citations_count / len(cited_numbers)

    # Check coverage of available citations
    citation_coverage = min(1.0, len(set(cited_numbers)) / len(valid_indices))

    return round(0.7 * citation_precision + 0.3 * citation_coverage, 2)
