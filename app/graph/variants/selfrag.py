"""Variant 2: Self-RAG（multi-seed + sufficiency 分支 + two-stage generator）

對應 docs/RAG/LangGraph/ch06 §2 Self-RAG。
P3（spec-15 / spec-16）完成時的形態：含 fan-out / fan-in、條件分支、Answer Contract。

跟 basic 比，多了：
- extract_features：結構化抽取
- expand_seeds + retrieve_one × N + fuse_scores：multi-seed 並行 + 分數融合
- check_sufficiency + clarify：資料不夠時誠實追問
- build_answer_contract + render_narrative：兩階段生成（程式組骨架 + 受限 LLM 敘事）

跟 reflection 比，少了：
- judge / increment_retry / mark_warning：無 self-correction 迴圈

教學意義：學生看到「自我修正」分支（sufficiency）與 grounded generation 的雛形。
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    build_answer_contract_node,
    check_sufficiency_node,
    clarify_node,
    expand_seeds_node,
    extract_features_node,
    fan_out_to_retrieve,
    fuse_scores_node,
    input_guard_node,
    push_node,
    query_transform_node,
    rerank_node,
    render_narrative_node,
    retrieve_one_node,
    route_after_input_guard,
    route_by_sufficiency,
    route_node,
)
from app.graph.state import RAGState


def build_selfrag_graph(services: Any):
    g = StateGraph(RAGState)

    g.add_node("input_guard", partial(input_guard_node, services=services))
    g.add_node("route", partial(route_node, services=services))
    g.add_node("query_transform", partial(query_transform_node, services=services))
    g.add_node("extract_features", partial(extract_features_node, services=services))
    g.add_node("expand_seeds", partial(expand_seeds_node, services=services))
    g.add_node("retrieve_one", partial(retrieve_one_node, services=services))
    g.add_node("fuse_scores", partial(fuse_scores_node, services=services))
    g.add_node("rerank", partial(rerank_node, services=services))
    g.add_node("check_sufficiency", partial(check_sufficiency_node, services=services))
    g.add_node("clarify", partial(clarify_node, services=services))
    g.add_node("build_answer_contract", partial(build_answer_contract_node, services=services))
    g.add_node("render_narrative", partial(render_narrative_node, services=services))
    g.add_node("push", partial(push_node, services=services))

    g.add_edge(START, "input_guard")
    g.add_conditional_edges("input_guard", route_after_input_guard, ["route", "push"])
    g.add_edge("route", "query_transform")
    g.add_edge("query_transform", "extract_features")
    g.add_edge("extract_features", "expand_seeds")
    g.add_conditional_edges(
        "expand_seeds",
        fan_out_to_retrieve,
        ["retrieve_one", "fuse_scores"],
    )
    g.add_edge("retrieve_one", "fuse_scores")
    g.add_edge("fuse_scores", "rerank")
    g.add_edge("rerank", "check_sufficiency")
    g.add_conditional_edges(
        "check_sufficiency",
        route_by_sufficiency,
        {"sufficient": "build_answer_contract", "insufficient": "clarify"},
    )
    g.add_edge("build_answer_contract", "render_narrative")
    g.add_edge("render_narrative", "push")
    g.add_edge("clarify", "push")
    g.add_edge("push", END)

    return g.compile()
