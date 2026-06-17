"""RAG category 合法清單 — router 啟發式與 prompt 共同來源。

對應 spec-03 §「介面契約」：避免 heuristic 與 prompt 各自硬編碼。
"""
from __future__ import annotations

VALID_RAG_CATEGORIES: frozenset[str] = frozenset(
    {
        "rag",
        "engineering",
        "architecture",
        "code",
        "analytics",
        "experiments",
        "metrics",
        "strategy",
        "market",
        "product",
        "philosophy",
        "notes",
    }
)
