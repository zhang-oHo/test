"""Per-million-token pricing (USD)。對應 spec-22 / task-22 步驟 2。

學生轉題目用其他模型時自行擴充本表。未列模型 → cost=0（不報錯）。
"""

from __future__ import annotations

PRICING_USD_PER_1M: dict[str, dict[str, float]] = {
    # OpenAI（公開定價，2025 中）
    "gpt-4.1": {"input": 2.50, "output": 10.00},
    "gpt-4.1-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # Anthropic
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-4-5-20251001": {"input": 0.80, "output": 4.00},
    # Google
    "gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    "gemini-2.5-pro": {"input": 1.25, "output": 5.00},
    # Embedding
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
    "text-embedding-3-large": {"input": 0.13, "output": 0.0},
}


def estimate_cost_usd(*, model: str, input_tokens: int, output_tokens: int) -> float:
    p = PRICING_USD_PER_1M.get(model)
    if p is None:
        return 0.0
    return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000
