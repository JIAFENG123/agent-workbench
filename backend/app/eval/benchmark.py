from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

BENCHMARK_FILE = Path(__file__).parent / "benchmark_data.json"


class EvalCase(BaseModel):
    id: str
    category: Literal["compliance", "calculation", "general"] = "compliance"
    query: str
    expected_tools: list[str] = Field(default_factory=list)
    expected_keywords: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    ground_truth_snippets: list[str] = Field(default_factory=list)


def load_benchmark(file_path: Path | str | None = None) -> list[EvalCase]:
    """Load benchmark test cases from JSON file."""
    path = Path(file_path) if file_path else BENCHMARK_FILE
    if not path.exists():
        raise FileNotFoundError(f"Benchmark file not found at: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return [EvalCase.model_validate(item) for item in data]
