"""Evaluation metrics. 對應 spec-20 / task-20 步驟 3。

純程式（不呼叫 LLM）；可獨立單元測試。
"""

from __future__ import annotations

from app.eval.schema import GoldenCase
from app.rag.schemas import KnowledgeChunk


def chunk_recall_at_k(
    case: GoldenCase, retrieved: list[KnowledgeChunk]
) -> float | None:
    """命中 expected_chunks 的比例；case 沒指定時回 None（不納入聚合）。"""
    if not case.expected_chunks:
        return None
    retrieved_ids = {c.id for c in retrieved}
    hit = sum(1 for eid in case.expected_chunks if eid in retrieved_ids)
    return hit / len(case.expected_chunks)


def citation_accuracy(
    retrieved: list[KnowledgeChunk], cited_chunk_ids: list[str]
) -> float | None:
    """回覆中引用的 chunk_id 是否都在 retrieved 集合內（無杜撰）。

    沒引用任何 chunk 時回 None（沒得評）。
    """
    if not cited_chunk_ids:
        return None
    retrieved_ids = {c.id for c in retrieved}
    valid = sum(1 for cid in cited_chunk_ids if cid in retrieved_ids)
    return valid / len(cited_chunk_ids)


def forbidden_phrase_hit(case: GoldenCase, response_text: str) -> bool:
    return any(p in response_text for p in case.forbidden_phrases)


def must_cite_satisfied(
    case: GoldenCase, cited_sources: list[str]
) -> bool | None:
    """回覆是否引用了 must_cite_sources 中至少一個（子字串比對）。

    case 沒指定時回 None。
    """
    if not case.must_cite_sources:
        return None
    return any(
        any(req in src for src in cited_sources)
        for req in case.must_cite_sources
    )
