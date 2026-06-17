"""Pinecone store — 生產 reference。

對應 spec-24 / task-24 步驟 4。

教學重點：學生不需付費帳號即可看「商業 vector DB 怎麼接 Protocol」。
單元測試用 mock client；要真跑需 `pip install -e ".[pinecone]"` + 設 PINECONE_API_KEY。
"""

from __future__ import annotations

from typing import Any

from app.rag.schemas import KnowledgeChunk
from app.storage.knowledge_store import (
    KnowledgeChunkInsert,
    SearchFilters,
)


class PineconeStore:
    name = "pinecone"

    def __init__(
        self,
        *,
        api_key: str = "",
        index_name: str = "rag-lessons",
        client: Any = None,
        index: Any = None,
    ) -> None:
        """Test 友善：可注入 mock client / index 跳過 pinecone-client import。"""
        if index is not None:
            self._index = index
        elif client is not None:
            self._index = client.Index(index_name)
        else:
            from pinecone import Pinecone
            self._index = Pinecone(api_key=api_key).Index(index_name)

    async def search(
        self,
        *,
        query_embedding: list[float],
        query_text: str | None = None,
        filters: SearchFilters | None = None,
        top_k: int = 8,
    ) -> list[KnowledgeChunk]:
        flt: dict | None = None
        if filters and filters.categories:
            flt = {"category": {"$in": filters.categories}}

        resp = self._index.query(
            vector=query_embedding,
            top_k=top_k,
            include_metadata=True,
            filter=flt,
        )
        out: list[KnowledgeChunk] = []
        for match in getattr(resp, "matches", []) or []:
            meta = getattr(match, "metadata", None) or {}
            score = float(getattr(match, "score", 0.0) or 0.0)
            out.append(
                KnowledgeChunk(
                    id=match.id,
                    title=meta.get("title"),
                    content=meta.get("content", ""),
                    category=meta.get("category", ""),
                    tags=list(meta.get("tags") or []),
                    metadata=meta,
                    vector_score=score,
                    keyword_score=0.0,
                    combined_score=score,
                )
            )
        return out

    async def upsert(self, chunks: list[KnowledgeChunkInsert]) -> int:
        vectors = [
            {
                "id": c.id,
                "values": c.embedding,
                "metadata": {
                    **c.metadata,
                    "title": c.title or "",
                    "content": c.content,
                    "category": c.category,
                    "tags": c.tags,
                    "source_id": c.source_id or "",
                    "content_hash": c.content_hash,
                },
            }
            for c in chunks
        ]
        self._index.upsert(vectors=vectors)
        return len(vectors)

    async def delete_by_source(self, source_id: str) -> int:
        # Pinecone delete 用 metadata filter
        self._index.delete(filter={"source_id": source_id})
        # Pinecone API 不回 affected count
        return 0

    async def source_hash(self, source_id: str) -> str | None:
        # Pinecone 的 metadata filter fetch 需要掃全索引，成本太高；
        # 回 None 表示「不知道」，pipeline 會照常 re-embed（安全降級）。
        return None

    async def health_check(self) -> bool:
        try:
            self._index.describe_index_stats()
            return True
        except Exception:
            return False
