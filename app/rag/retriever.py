from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.rag.embedder import EmbeddingProvider
from app.rag.reranker import select_top_chunks
from app.rag.schemas import KnowledgeChunk, RetrievalLogRecord
from app.storage.knowledge_store import KnowledgeStore, SearchFilters
from app.storage.logs_repo import LogsRepository


@dataclass
class RAGRetriever:
    embedder: EmbeddingProvider
    store: KnowledgeStore
    logs_repo: LogsRepository
    final_context_k: int = 4
    settings: Any = None   # Settings | None — used for hybrid weights (spec-27)

    async def retrieve_for_seed(
        self,
        seed: str,
        *,
        categories: list[str] | None = None,
        top_k: int = 8,
    ) -> list[KnowledgeChunk]:
        """Single-seed retrieval（不 rerank、不 log）。

        給 multi-seed graph 用：每條 seed 拿到 top_k 候選，由 fuse_scores_node
        合併後做最終排序。獨立 log 由 fuse_scores_node 統一處理。
        """
        try:
            embedding = await self.embedder.embed_query(seed)
            # spec-27: thread hybrid weights from settings into SearchFilters
            s = self.settings
            if s is not None and getattr(s, "hybrid_enabled", False):
                vector_weight = s.hybrid_vector_weight
                keyword_weight = s.hybrid_keyword_weight
            else:
                vector_weight = 1.0
                keyword_weight = 0.0
            return await self.store.search(
                query_embedding=embedding,
                query_text=seed,
                filters=SearchFilters(
                    categories=categories,
                    vector_weight=vector_weight,
                    keyword_weight=keyword_weight,
                ),
                top_k=top_k,
            )
        except Exception:
            return []

    async def retrieve(
        self,
        query: str,
        *,
        categories: list[str] | None = None,
        top_k: int = 8,
        external_user_id: str | None = None,
        skill_id: str | None = None,
    ) -> list[KnowledgeChunk]:
        """Single-seed full pipeline（embed → match → rerank → log）。

        保留作為非 graph 路徑的對外 API（例：CLI 直查、測試 fixture）。
        Multi-seed 路徑改走 `retrieve_for_seed` + fuse_scores_node。

        `external_user_id` 是 channel-agnostic 識別（task-23 引入），
        DB log 表 column 名稱仍為 `line_user_id`（避免 schema migration）。
        """
        try:
            chunks = await self.retrieve_for_seed(
                query, categories=categories, top_k=top_k
            )
            selected = select_top_chunks(chunks, self.final_context_k)
            await self.logs_repo.log_retrieval(
                RetrievalLogRecord(
                    line_user_id=external_user_id,
                    query=query,
                    skill_id=skill_id,
                    category_filter=categories or [],
                    retrieved_ids=[chunk.id for chunk in selected],
                    scores={
                        chunk.id: {
                            "vector_score": chunk.vector_score,
                            "keyword_score": chunk.keyword_score,
                            "combined_score": chunk.combined_score,
                        }
                        for chunk in selected
                    },
                )
            )
            return selected
        except Exception:
            return []

    async def log_fused_retrieval(
        self,
        *,
        query: str,
        chunks: list[KnowledgeChunk],
        categories: list[str] | None = None,
        external_user_id: str | None = None,
        skill_id: str | None = None,
    ) -> None:
        """Multi-seed 路徑專用：fusion 完成後的最終結果統一 log。"""
        try:
            await self.logs_repo.log_retrieval(
                RetrievalLogRecord(
                    line_user_id=external_user_id,
                    query=query,
                    skill_id=skill_id,
                    category_filter=categories or [],
                    retrieved_ids=[chunk.id for chunk in chunks],
                    scores={
                        chunk.id: {
                            "vector_score": chunk.vector_score,
                            "keyword_score": chunk.keyword_score,
                            "combined_score": chunk.combined_score,
                        }
                        for chunk in chunks
                    },
                )
            )
        except Exception:
            pass

    def build_context(self, chunks: list[KnowledgeChunk]) -> str:
        if not chunks:
            return "No retrieved context."
        blocks: list[str] = []
        for index, chunk in enumerate(chunks[: self.final_context_k], start=1):
            title = chunk.title or f"Chunk {index}"
            blocks.append(f"[{index}] {title}\nCategory: {chunk.category}\n{chunk.content}")
        return "\n\n".join(blocks)
