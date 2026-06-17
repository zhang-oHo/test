"""Variant 1: Basic RAG（線性，無反思）

對應 docs/RAG/LangGraph/ch06 §1 基本 RAG。
最接近 P1（spec-12 / task-12）完成時的形態：route → retrieve → generate → push。

特點：
- 單 seed retrieve（不展開 features、不 multi-seed）
- 單階段 generator（不拆 contract / narrative）
- 無 sufficiency 判定、無 judge 迴圈

教學意義：學生對照 ch06 §1 看「最簡單能跑的 RAG」是什麼樣子。
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    generate_basic_node,
    input_guard_node,
    push_node,
    retrieve_basic_node,
    route_after_input_guard,
    route_node,
)
from app.graph.state import RAGState


def build_basic_graph(services: Any):
    g = StateGraph(RAGState)

    g.add_node("input_guard", partial(input_guard_node, services=services))
    g.add_node("route", partial(route_node, services=services))
    g.add_node("retrieve", partial(retrieve_basic_node, services=services))
    g.add_node("generate", partial(generate_basic_node, services=services))
    g.add_node("push", partial(push_node, services=services))

    g.add_edge(START, "input_guard")
    g.add_conditional_edges("input_guard", route_after_input_guard, ["route", "push"])
    g.add_edge("route", "retrieve")
    g.add_edge("retrieve", "generate")
    g.add_edge("generate", "push")
    g.add_edge("push", END)

    return g.compile()
