"""Knowledge store registry — 對應 spec-24 / task-24。

提供 `build_store(settings)` 工廠函式，依 `knowledge_store_backend` 選實作。
"""

from __future__ import annotations

from app.config import Settings
from app.storage.knowledge_store import KnowledgeStore


def build_store(settings: Settings) -> KnowledgeStore:
    backend = settings.knowledge_store_backend
    if backend == "supabase":
        from app.storage.knowledge_repo import KnowledgeRepository
        from app.storage.stores.supabase_store import SupabaseStore
        from app.storage.supabase_client import SupabaseRestClient

        client = SupabaseRestClient(settings)
        return SupabaseStore(client=client, repo=KnowledgeRepository(client))

    if backend == "sqlite_vec":
        from app.storage.stores.sqlite_vec_store import SqliteVecStore

        return SqliteVecStore(path=settings.sqlite_vec_path, dim=settings.sqlite_vec_dim)

    if backend == "pinecone":
        # 提前驗證：PineconeStore 內部建構也會抓不到 api_key 而爆，
        # 但訊息會混在 pinecone SDK 的 stack trace 裡難 debug；這裡直接擋。
        if not settings.pinecone_api_key:
            raise ValueError(
                "knowledge_store_backend=pinecone requires PINECONE_API_KEY to be set"
            )
        if not settings.pinecone_index:
            raise ValueError(
                "knowledge_store_backend=pinecone requires PINECONE_INDEX to be set"
            )
        from app.storage.stores.pinecone_store import PineconeStore

        return PineconeStore(
            api_key=settings.pinecone_api_key,
            index_name=settings.pinecone_index,
        )

    raise ValueError(
        f"unknown knowledge_store_backend: {backend!r}. "
        "Supported: supabase | sqlite_vec | pinecone"
    )
