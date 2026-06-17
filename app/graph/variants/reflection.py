"""Variant 3: Reflection Agent（selfrag + judge 三向分流 + reflection 迴圈）

對應 docs/RAG/LangGraph/ch06 §3 Reflection Agent。
P4（spec-17 / task-17）完成時的形態：含 4 軸 LLM-as-Judge 與 retry 迴圈。

跟 selfrag 比，多了：
- judge：4 軸結構化評分（groundedness / citation_fidelity / format / uncertainty）
- 三向分流（pass / retry / force_push）+ retry 迴圈
- mark_warning：retry 用盡時加 ⚠️ 品質警告前綴

教學意義：學生看到完整 self-correction loop（render → judge → 重 render）與 retry 上限保險。
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
    human_review_node,
    increment_retry_node,
    input_guard_node,
    judge_node,
    make_route_after_judge,
    mark_warning_node,
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


def build_reflection_graph(services: Any):
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
    g.add_node("judge", partial(judge_node, services=services))
    g.add_node("increment_retry", partial(increment_retry_node, services=services))
    g.add_node("mark_warning", partial(mark_warning_node, services=services))
    g.add_node("human_review", partial(human_review_node, services=services))
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
    g.add_edge("render_narrative", "judge")

    hitl_enabled = bool(getattr(services.settings, "hitl_enabled", False))
    route_after_judge = make_route_after_judge(
        services.settings.max_reflection_retries,
        hitl_enabled=hitl_enabled,
    )
    branches: dict[str, str] = {"pass": "push", "retry": "increment_retry"}
    if hitl_enabled:
        branches["human_review"] = "human_review"
    else:
        branches["force_push"] = "mark_warning"
    g.add_conditional_edges("judge", route_after_judge, branches)

    g.add_edge("increment_retry", "render_narrative")
    g.add_edge("mark_warning", "push")
    g.add_edge("human_review", "push")
    g.add_edge("clarify", "push")
    g.add_edge("push", END)

    compile_kwargs: dict[str, Any] = {}
    checkpointer = getattr(services, "checkpointer", None)
    if checkpointer is not None:
        compile_kwargs["checkpointer"] = checkpointer
    if hitl_enabled:
        if checkpointer is None:
            raise RuntimeError(
                "hitl_enabled=True 但 services.checkpointer 為 None。"
                " HITL 需要 checkpointer 才能 interrupt + resume；"
                " 設 CHECKPOINT_BACKEND=memory（教學）或 sqlite（生產）。"
            )
        compile_kwargs["interrupt_before"] = ["human_review"]
    return g.compile(**compile_kwargs)
