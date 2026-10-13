from __future__ import annotations

from app.llm.cost import compute_cost, estimate_tokens


def test_estimate_tokens_counts_cjk_as_roughly_one_token_each() -> None:
    # 4 CJK characters, plus one token of per-message overhead.
    assert estimate_tokens("你好世界") == 5


def test_estimate_tokens_treats_latin_as_four_chars_per_token() -> None:
    # 8 / 4 = 2, plus one token of per-message overhead.
    assert estimate_tokens("abcdefgh") == 3


def test_estimate_tokens_of_empty_text_is_zero() -> None:
    assert estimate_tokens("") == 0


def test_estimate_tokens_handles_mixed_script_ordering_independently() -> None:
    """Scripts are counted on their own scales and only the shared overhead is counted once."""
    combined = estimate_tokens("平台规则platform")
    assert combined == estimate_tokens("平台规则") + estimate_tokens("platform") - 1


def test_compute_cost_is_zero_for_unpriced_models() -> None:
    assert compute_cost(1_000_000, 1_000_000, "nvidia/nemotron-3-super-120b-a12b") == 0.0


def test_compute_cost_uses_configured_prices_for_unknown_models(monkeypatch) -> None:
    from app.llm import cost

    monkeypatch.setattr(cost.settings, "input_price_per_1m_tokens", 1.0)
    monkeypatch.setattr(cost.settings, "output_price_per_1m_tokens", 2.0)

    assert cost.compute_cost(1_000_000, 1_000_000, "some/unlisted-model") == 3.0
    assert cost.compute_cost(0, 0, "some/unlisted-model") == 0.0
