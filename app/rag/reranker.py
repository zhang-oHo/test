from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod

from app.rag.schemas import KnowledgeChunk

logger = logging.getLogger(__name__)


class BaseReranker(ABC):
    @abstractmethod
    async def rerank(
        self, query: str, chunks: list[KnowledgeChunk], top_n: int
    ) -> list[KnowledgeChunk]:
        """Return chunks reranked by cross-encoder score, capped at top_n."""


class CohereReranker(BaseReranker):
    def __init__(self, api_key: str, model: str = "rerank-multilingual-v3.0") -> None:
        import cohere
        self._client = cohere.AsyncClientV2(api_key=api_key)
        self._model = model

    async def rerank(
        self, query: str, chunks: list[KnowledgeChunk], top_n: int
    ) -> list[KnowledgeChunk]:
        if not chunks:
            return []
        docs = [c.content for c in chunks]
        try:
            resp = await self._client.rerank(
                model=self._model,
                query=query,
                documents=docs,
                top_n=min(top_n, len(docs)),
            )
        except Exception as exc:
            # spec-04 §Fallback：API 失敗（超時 / 限流 / 網路）靜默降回 RRF 排序，
            # 不打斷主流程；只留 log。
            logger.warning(
                "Cohere rerank failed (%s); falling back to RRF score sort", exc
            )
            return sorted(chunks, key=lambda c: c.combined_score, reverse=True)[:top_n]
        reranked: list[KnowledgeChunk] = []
        for result in resp.results:
            chunk = chunks[result.index].model_copy()
            chunk.combined_score = result.relevance_score
            reranked.append(chunk)
        return reranked


class BgeReranker(BaseReranker):
    """Local BGE Reranker using sentence-transformers CrossEncoder."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-base") -> None:
        from sentence_transformers import CrossEncoder
        self._model = CrossEncoder(model_name)

    async def rerank(
        self, query: str, chunks: list[KnowledgeChunk], top_n: int
    ) -> list[KnowledgeChunk]:
        if not chunks:
            return []
        pairs = [(query, c.content) for c in chunks]
        loop = asyncio.get_event_loop()
        scores: list[float] = await loop.run_in_executor(
            None, self._model.predict, pairs
        )
        ranked = sorted(zip(scores, chunks), key=lambda x: x[0], reverse=True)
        result: list[KnowledgeChunk] = []
        for score, chunk in ranked[:top_n]:
            c = chunk.model_copy()
            c.combined_score = float(score)
            result.append(c)
        return result


def make_reranker(settings: object) -> BaseReranker | None:
    """Factory: return a reranker instance or None when disabled."""
    if not getattr(settings, "reranker_enabled", False):
        return None
    provider = getattr(settings, "reranker_provider", "cohere")
    if provider == "cohere":
        api_key = getattr(settings, "cohere_api_key", "")
        if not api_key:
            # spec-04 §Fallback：缺 key 時靜默降回 RRF（回 None → select_top_chunks
            # 走 score-sort 路徑），不拋例外。
            logger.warning(
                "reranker_provider=cohere but COHERE_API_KEY is empty; "
                "falling back to RRF score sort (no rerank)"
            )
            return None
        return CohereReranker(
            api_key=api_key,
            model=getattr(settings, "reranker_model", "rerank-multilingual-v3.0"),
        )
    if provider == "bge":
        return BgeReranker(
            model_name=getattr(settings, "bge_reranker_model", "BAAI/bge-reranker-base")
        )
    raise ValueError(f"Unknown reranker_provider: {provider!r}. Valid: cohere | bge")


def select_top_chunks(chunks: list[KnowledgeChunk], limit: int) -> list[KnowledgeChunk]:
    """Fallback sort-based selection when reranker is disabled."""
    return sorted(chunks, key=lambda chunk: chunk.combined_score, reverse=True)[:limit]
