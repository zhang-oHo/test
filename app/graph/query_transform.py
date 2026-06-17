from __future__ import annotations

import json
import logging
from typing import Any

from app.graph.state import RAGState

logger = logging.getLogger(__name__)


async def _hyde_transform(user_input: str, settings: Any) -> tuple[str, str]:
    """Return (hypothetical_doc, embed_text). embed_text == hypothetical_doc."""
    from openai import AsyncOpenAI

    model = settings.hyde_model or settings.router_model
    client = AsyncOpenAI(
        api_key=settings.openai_api_key or None,
        base_url=settings.openai_base_url,
    )
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "你是一位專家。請以完整解答的形式回覆（不要重述問題本身）。",
            },
            {"role": "user", "content": user_input},
        ],
        max_tokens=settings.hyde_max_tokens,
        temperature=0.3,
    )
    hyde_doc = resp.choices[0].message.content.strip()
    return hyde_doc, hyde_doc


async def _step_back_transform(user_input: str, settings: Any) -> list[str]:
    """Return [abstract_question, original_input]."""
    from openai import AsyncOpenAI

    model = settings.step_back_model or settings.router_model
    client = AsyncOpenAI(
        api_key=settings.openai_api_key or None,
        base_url=settings.openai_base_url,
    )
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "將以下具體問題轉換成更廣泛的背景問題（一句話，不超過 30 字）。"
                    "只輸出問題，不加說明。"
                ),
            },
            {"role": "user", "content": user_input},
        ],
        max_tokens=60,
        temperature=0.2,
    )
    abstract_q = resp.choices[0].message.content.strip()
    return [abstract_q, user_input]


async def _decompose_transform(user_input: str, settings: Any) -> list[str]:
    """Return a list of sub-questions (max DECOMPOSE_MAX_SUBQUERIES)."""
    from openai import AsyncOpenAI

    max_q = settings.decompose_max_subqueries
    client = AsyncOpenAI(
        api_key=settings.openai_api_key or None,
        base_url=settings.openai_base_url,
    )
    resp = await client.chat.completions.create(
        model=settings.router_model,
        messages=[
            {
                "role": "system",
                "content": (
                    f"將問題分解成最多 {max_q} 個獨立的子問題。"
                    "輸出純 JSON 物件，格式：{{\"questions\": [\"...\", \"...\"]}}。"
                    "若問題本身簡單不需分解，回傳只含原問題的陣列。"
                ),
            },
            {"role": "user", "content": user_input},
        ],
        response_format={"type": "json_object"},
        max_tokens=200,
        temperature=0.2,
    )
    try:
        data = json.loads(resp.choices[0].message.content)
        subqueries = data.get("questions") or data.get("subqueries") or [user_input]
    except (json.JSONDecodeError, KeyError):
        subqueries = [user_input]
    return subqueries[:max_q]


async def query_transform_node(state: RAGState, services: Any) -> dict:
    """Transform user_input into transformed_queries based on strategy config.

    Inserts before extract_features; expand_seeds_node merges results into seeds.
    If strategy=none or LLM unavailable, falls back gracefully to [user_input].
    """
    settings = services.settings
    strategy: str = getattr(settings, "query_transform_strategy", "none")
    user_input: str = state["user_input"]

    if strategy == "none":
        return {
            "transformed_queries": [user_input],
            "hyde_doc": None,
            "transform_strategy": "none",
        }

    try:
        if strategy == "hyde":
            hyde_doc, embed_text = await _hyde_transform(user_input, settings)
            logger.info("query_transform: hyde generated %d chars", len(hyde_doc))
            return {
                "transformed_queries": [embed_text, user_input],
                "hyde_doc": hyde_doc,
                "transform_strategy": "hyde",
            }

        if strategy == "step_back":
            queries = await _step_back_transform(user_input, settings)
            logger.info("query_transform: step_back → %d queries", len(queries))
            return {
                "transformed_queries": queries,
                "hyde_doc": None,
                "transform_strategy": "step_back",
            }

        if strategy == "decompose":
            subqueries = await _decompose_transform(user_input, settings)
            logger.info("query_transform: decompose → %d subqueries", len(subqueries))
            return {
                "transformed_queries": subqueries,
                "hyde_doc": None,
                "transform_strategy": "decompose",
            }

    except Exception:
        logger.exception("query_transform failed (strategy=%s), falling back to none", strategy)

    return {
        "transformed_queries": [user_input],
        "hyde_doc": None,
        "transform_strategy": "none",
    }
