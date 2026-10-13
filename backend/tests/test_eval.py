import pytest

from app.eval.benchmark import EvalCase, load_benchmark
from app.eval.metrics import (
    faithfulness_score,
    forbidden_claims_score,
    hit_rate_at_k,
    keyword_coverage,
    mrr_at_k,
    precision_at_k,
    tool_calling_accuracy,
)
from app.eval.runner import evaluate_single_case, run_benchmark


def test_load_benchmark():
    cases = load_benchmark()
    assert len(cases) >= 10
    first = cases[0]
    assert first.id == "tc_01"
    assert first.query
    assert "kb_search" in first.expected_tools


def test_retrieval_metrics():
    retrieved = [
        "Product must be compliant with regulations.",
        "Amazon listing title cannot contain best seller.",
        "CPC certificate is mandatory for children toys.",
    ]
    gt = ["best seller", "主观评价词"]

    # Hit Rate
    assert hit_rate_at_k(retrieved, gt, k=2) == 1.0
    assert hit_rate_at_k(retrieved, ["unrelated snippet"], k=2) == 0.0

    # MRR (hit is at rank 2 -> 1/2 = 0.5)
    assert mrr_at_k(retrieved, gt, k=3) == 0.5
    assert mrr_at_k(retrieved, ["unrelated"], k=3) == 0.0

    # Precision@K
    assert precision_at_k(retrieved, gt, k=2) == 0.5


def test_tool_accuracy_and_keywords():
    assert tool_calling_accuracy(["kb_search", "calculator"], ["kb_search"]) == 1.0
    assert tool_calling_accuracy(["calculator"], ["kb_search"]) == 0.0
    assert tool_calling_accuracy([], []) == 1.0

    answer = "不能使用该词，因为属于主观促销词，会导致 Listing 下架处罚。"
    assert keyword_coverage(answer, ["不能", "促销", "下架"]) == 1.0
    assert keyword_coverage(answer, ["允许"]) == 0.0


def test_faithfulness_and_forbidden_claims():
    answer_good = "根据规则 [1]，标题禁止包含促销词；且根据 [2] 会被警告。"
    citations = [{"index": 1, "snippet": "rule 1"}, {"index": 2, "snippet": "rule 2"}]
    score_good = faithfulness_score(answer_good, citations)
    assert score_good >= 0.8

    answer_uncited = "标题完全没有限制，随便写。"
    score_uncited = faithfulness_score(answer_uncited, citations)
    assert score_uncited < 0.5

    assert forbidden_claims_score(answer_good, ["允许使用", "合规"]) == 1.0
    assert forbidden_claims_score("此写法完全合规", ["允许使用", "合规"]) == 0.0


@pytest.mark.asyncio
async def test_evaluate_single_case_and_benchmark():
    case = EvalCase(
        id="tc_01",
        category="compliance",
        query="Amazon 标题能不能出现 best seller？",
        expected_tools=["kb_search"],
        expected_keywords=["不能", "下架"],
        forbidden_claims=["允许"],
        ground_truth_snippets=["best seller"],
    )

    res = await evaluate_single_case(
        case,
        agent_answer="根据规则 [1]，标题禁止出现 best seller，违规会导致下架。",
        invoked_tools=["kb_search"],
        citations=[{"index": 1, "snippet": "best seller 禁止出现"}],
    )
    assert res.passed is True
    assert res.overall_score >= 0.8
    assert res.hit_rate == 1.0

    report = await run_benchmark([case])
    assert report.total_cases == 1
    assert report.passed_cases == 1
    assert report.pass_rate == 1.0
