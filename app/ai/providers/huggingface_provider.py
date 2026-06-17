from __future__ import annotations

import asyncio


class HuggingFaceEmbedder:
    """Local HuggingFace sentence-transformers embedder (spec-29)."""

    def __init__(self, settings: object) -> None:
        from sentence_transformers import SentenceTransformer

        model_name = getattr(settings, "embedding_model", "BAAI/bge-small-zh-v1.5")
        self._model = SentenceTransformer(model_name)

    async def embed_query(self, text: str) -> list[float]:
        loop = asyncio.get_event_loop()
        vec = await loop.run_in_executor(None, self._model.encode, text)
        return vec.tolist()
