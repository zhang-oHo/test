"""KnowledgeStore Protocol — 對應 spec-24 / task-24。

把 vector store 抽成介面，讓 retriever / ingest pipeline 不綁定 Supabase。
三實作（Supabase / sqlite-vec / Pinecone）在 app/storage/stores/。
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, Field

from app.rag.schemas import KnowledgeChunk


class SearchFilters(BaseModel):
    categories: list[str] | None = None
    tags: list[str] | None = None
    after: datetime | None = None
    metadata_match: dict | None = None
    tenant_id: str | None = None
    # spec-27 hybrid retrieval weights（透傳給 store.search → RPC）
    vector_weight: float = 1.0
    keyword_weight: float = 0.0


class KnowledgeChunkInsert(BaseModel):
    """Ingest pipeline 寫入 store 的單位。

    與 retrieval 出口的 KnowledgeChunk 區別：
    - insert 含 embedding（要寫進 vector index）
    - insert 必有 content_hash（去重 / upsert key）
    - retrieval 結果含 vector_score / keyword_score / combined_score（store 算的）
    """

    id: str
    content: str
    category: str
    embedding: list[float]
    title: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    content_hash: str
    source_id: str | None = None
    source_type: str = "markdown"
    # spec-06：同一個 pipeline.run() 的所有 chunk 共用同一個 knowledge_version；
    # None 代表 store 用 schema 預設值（教學版單機 sqlite_vec / pinecone 不一定有此欄位）
    knowledge_version: int | None = None


class KnowledgeStore(Protocol):
    name: str

    async def search(
        self,
        *,
        query_embedding: list[float],
        query_text: str | None = None,
        filters: SearchFilters | None = None,
        top_k: int = 8,
    ) -> list[KnowledgeChunk]: ...

    async def upsert(self, chunks: list[KnowledgeChunkInsert]) -> int: ...

    async def delete_by_source(self, source_id: str) -> int: ...

    async def health_check(self) -> bool: ...

    async def source_hash(self, source_id: str) -> str | None:
        """回傳 source_id 在 store 裡已存的 content_hash；不存在回 None。
        用於 IngestionPipeline 增量跳過：hash 一致就不重新 embed / upsert。
        """
        ...
