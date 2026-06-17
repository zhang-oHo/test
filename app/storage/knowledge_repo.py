from __future__ import annotations

from app.rag.schemas import KnowledgeChunk
from app.storage.supabase_client import SupabaseRestClient


class KnowledgeRepository:
    def __init__(self, client: SupabaseRestClient) -> None:
        self._client = client

    async def match_private_knowledge(
        self,
        *,
        query_embedding: list[float],
        query_text: str,
        categories: list[str] | None = None,
        top_k: int = 8,
        vector_weight: float = 0.5,
        keyword_weight: float = 0.5,
    ) -> list[KnowledgeChunk]:
        rows = await self._client.rpc(
            "match_private_knowledge",
            {
                "query_embedding": query_embedding,
                "query_text": query_text,
                "match_count": top_k,
                "category_filter": categories or None,
                "vector_weight": vector_weight,
                "keyword_weight": keyword_weight,
            },
        )
        return [KnowledgeChunk.model_validate(row) for row in rows]
