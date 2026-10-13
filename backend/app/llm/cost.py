from __future__ import annotations

from app.config import get_settings

settings = get_settings()

# model -> (input USD per 1M tokens, output USD per 1M tokens)
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "nvidia/nemotron-3-super-120b-a12b": (0.0, 0.0),
    "nvidia/nemotron-3.5-lightning-30b-a3b": (0.0, 0.0),
    "nvidia/llama-3.3-nemotron-super-49b-v1.5": (0.0, 0.0),
    "deepseek-ai/deepseek-v4-flash": (0.0, 0.0),
}


def price_for(model: str) -> tuple[float, float]:
    return MODEL_PRICES.get(
        model,
        (settings.input_price_per_1m_tokens, settings.output_price_per_1m_tokens),
    )


def compute_cost(prompt_tokens: int, completion_tokens: int, model: str) -> float:
    input_price, output_price = price_for(model)
    cost = prompt_tokens / 1_000_000 * input_price + completion_tokens / 1_000_000 * output_price
    return round(cost, 6)


def estimate_tokens(text: str) -> int:
    """Rough token estimate used only when a provider omits the usage block.

    CJK characters are roughly one token each; Latin text averages about four characters
    per token. Good enough to keep the cost ledger sane, never used for billing.
    """
    if not text:
        return 0
    cjk = sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
    other = len(text) - cjk
    return int(cjk + other / 4) + 1
