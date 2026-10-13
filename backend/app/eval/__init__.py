"""Agent & RAG evaluation suite and benchmark harness."""

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
from app.eval.runner import CaseEvalResult, EvalReport, evaluate_single_case, run_benchmark

__all__ = [
    "CaseEvalResult",
    "EvalCase",
    "EvalReport",
    "evaluate_single_case",
    "faithfulness_score",
    "forbidden_claims_score",
    "hit_rate_at_k",
    "keyword_coverage",
    "load_benchmark",
    "mrr_at_k",
    "precision_at_k",
    "run_benchmark",
    "tool_calling_accuracy",
]
