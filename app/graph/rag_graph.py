"""Thin wrapper：依 services.settings.graph_variant 選擇 variant builder。

新程式碼應直接 import `app.graph.variants.VARIANT_BUILDERS` 或具體 builder；
本檔保留 `build_rag_graph()` 作向後相容（既有 dependencies / tests / scripts 都用這個 entry）。
"""

from __future__ import annotations

from typing import Any

from app.graph.variants import VARIANT_BUILDERS


def build_rag_graph(services: Any):
    variant = getattr(services.settings, "graph_variant", "reflection")
    builder = VARIANT_BUILDERS.get(variant)
    if builder is None:
        available = ", ".join(sorted(VARIANT_BUILDERS.keys()))
        raise ValueError(
            f"unknown graph_variant: {variant!r}. Available: {available}"
        )
    return builder(services)
