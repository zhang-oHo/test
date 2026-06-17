"""Multi-format ingestion — Document 中介格式 + Ingester Protocol + Pipeline。

對應 spec-25 / task-25。把 retrieval 端 (KnowledgeStore Protocol) 與 ingestion 端
(Ingester Protocol) 分離，學生轉題目時換資料源 / 換 store 兩個關注點獨立。
"""

from app.ingest.base import Ingester
from app.ingest.document import Document, DocumentSection
from app.ingest.pipeline import IngestionPipeline, IngestStats

__all__ = [
    "Document",
    "DocumentSection",
    "Ingester",
    "IngestionPipeline",
    "IngestStats",
]
