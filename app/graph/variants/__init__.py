"""Three LangGraph variants — 對應 docs/RAG/LangGraph/ch06 三模式。

| variant | 對應 ch06 | 對應 phase | builder |
|---------|-----------|-----------|---------|
| basic | §1 基本 RAG | P1 | build_basic_graph |
| selfrag | §2 Self-RAG | P3 | build_selfrag_graph |
| reflection | §3 Reflection Agent | P4 | build_reflection_graph |

學生用 GRAPH_VARIANT=basic|selfrag|reflection 切換；
demo_compare_variants.py 在同一輸入上跑三變體比對。
"""

from __future__ import annotations

from app.graph.variants.basic import build_basic_graph
from app.graph.variants.reflection import build_reflection_graph
from app.graph.variants.selfrag import build_selfrag_graph

VARIANT_BUILDERS = {
    "basic": build_basic_graph,
    "selfrag": build_selfrag_graph,
    "reflection": build_reflection_graph,
}

__all__ = [
    "VARIANT_BUILDERS",
    "build_basic_graph",
    "build_selfrag_graph",
    "build_reflection_graph",
]
