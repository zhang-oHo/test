from __future__ import annotations

from app.rag.schemas import RetrievalLogRecord
from app.storage.supabase_client import SupabaseRestClient


class LogsRepository:
    def __init__(self, client: SupabaseRestClient) -> None:
        self._client = client

    async def log_retrieval(self, record: RetrievalLogRecord) -> None:
        await self._client.insert("retrieval_logs", record.model_dump())
