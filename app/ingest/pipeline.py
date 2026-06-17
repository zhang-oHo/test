"""Ingestion pipeline：Ingester → Chunker（依 source_type 選）→ Embedder → Store。

對應 spec-25 / task-25 步驟 3。pipeline 對 Ingester 做迭代、對每個 Document 的
section 切 chunks、embed、批量 upsert。
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

from app.ingest.base import Ingester
from app.ingest.chunkers import Chunker, chunker_for
from app.ingest.document import Document, DocumentSection
from app.storage.knowledge_store import KnowledgeChunkInsert, KnowledgeStore

logger = logging.getLogger(__name__)


@dataclass
class IngestStats:
    docs: int = 0
    chunks: int = 0
    skipped: int = 0
    unchanged: int = 0
    sources: list[str] = field(default_factory=list)


class IngestionPipeline:
    def __init__(
        self,
        *,
        embedder: Any,
        store: KnowledgeStore,
        chunker: Chunker | None = None,
        poison_screen: bool = True,
    ) -> None:
        """`chunker` 為 None 時依 Document.source_type 自動挑（DEFAULT_CHUNKERS）。"""
        self._embedder = embedder
        self._store = store
        self._chunker_override = chunker
        self._poison_screen = poison_screen

    def _chunker_for(self, doc: Document) -> Chunker:
        if self._chunker_override is not None:
            return self._chunker_override
        return chunker_for(doc.source_type)

    @staticmethod
    def _build_chunk_insert(
        doc: Document,
        section: DocumentSection,
        chunk_text: str,
        chunk_index: int,
        embedding: list[float],
        knowledge_version: int | None,
    ) -> KnowledgeChunkInsert:
        # id：deterministic 字串便於去重 / 跨 store 對應
        page_part = section.page_number if section.page_number is not None else "x"
        chunk_id = f"{doc.source_id}#p{page_part}#c{chunk_index}"
        content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
        return KnowledgeChunkInsert(
            id=chunk_id,
            content=chunk_text,
            category=doc.category,
            embedding=embedding,
            title=doc.title,
            tags=list(doc.tags),
            metadata={
                **doc.metadata,
                **section.metadata,
                **({"source_url": doc.source_url} if doc.source_url else {}),
                **({"page_number": section.page_number} if section.page_number is not None else {}),
                **({"section_path": section.section_path} if section.section_path else {}),
                "title": doc.title,
            },
            content_hash=content_hash,
            source_id=doc.source_id,
            source_type=doc.source_type,
            knowledge_version=knowledge_version,
        )

    async def _resolve_knowledge_version(self) -> int | None:
        """spec-06：pipeline 開頭跟 store 要本次匯入用的 knowledge_version。

        Store 沒實作 `next_knowledge_version` 時回 None（chunk insert 走 schema
        預設值）；prompt_cache 失效機制在那些 store 上不適用（屬已知 trade-off）。
        """
        getter = getattr(self._store, "next_knowledge_version", None)
        if getter is None:
            return None
        try:
            return await getter()
        except Exception as exc:
            logger.warning(
                "next_knowledge_version failed; chunks will use schema default. exc=%s(%s)",
                type(exc).__name__, exc,
            )
            return None

    async def run(self, ingester: Ingester) -> IngestStats:
        stats = IngestStats()
        # spec-06：整次 pipeline 共用同一個 knowledge_version；首批 ingest（表空）回 1。
        knowledge_version = await self._resolve_knowledge_version()
        if knowledge_version is not None:
            logger.info(
                "ingest pipeline using knowledge_version=%d", knowledge_version
            )
        async for doc in ingester.yield_documents():
            # 增量跳過：store 裡已有相同 content_hash 就不重新 embed
            if doc.content_hash:
                stored = await self._store.source_hash(doc.source_id)
                if stored == doc.content_hash:
                    stats.unchanged += 1
                    continue

            chunker = self._chunker_for(doc)
            inserts: list[KnowledgeChunkInsert] = []
            chunk_idx = 0
            for section in doc.sections:
                for chunk_text in chunker.chunk(section.text):
                    if self._poison_screen:
                        from app.security.guards import detect_rag_poison
                        if detect_rag_poison(chunk_text):
                            logger.warning(
                                "security: poison detected in chunk from %s, skipping",
                                doc.source_id,
                            )
                            stats.skipped += 1
                            continue
                    chunk_idx += 1
                    embedding = await self._embedder.embed_query(chunk_text)
                    inserts.append(
                        self._build_chunk_insert(
                            doc, section, chunk_text, chunk_idx, embedding,
                            knowledge_version,
                        )
                    )
            if inserts:
                await self._store.upsert(inserts)
                stats.docs += 1
                stats.chunks += len(inserts)
                stats.sources.append(doc.source_id)
            else:
                stats.skipped += 1
        return stats
