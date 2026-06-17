from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    async def embed_query(self, text: str) -> list[float]:
        ...
