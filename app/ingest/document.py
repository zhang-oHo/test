"""Document / DocumentSection 中介格式 — Ingester → Pipeline 的契約。

對應 spec-25 / task-25 步驟 1。

設計：
- Document：一份來源文件（一個 URL / PDF 檔 / Notion page / CSV row 集）
- DocumentSection：Document 的邏輯子單位（章節 / page / row 群）
  Chunker 拿到的單位是 section.text；section_path / page_number 流入 metadata。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SourceType = Literal["web", "pdf", "notion", "csv", "docx", "manual", "markdown"]


class DocumentSection(BaseModel):
    text: str
    section_path: list[str] = Field(default_factory=list, description="['第 3 章', '3.2 節']")
    page_number: int | None = None
    metadata: dict = Field(default_factory=dict)


class Document(BaseModel):
    source_id: str
    source_type: SourceType
    source_url: str | None = None
    title: str
    sections: list[DocumentSection]
    fetched_at: datetime
    content_hash: str
    category: str
    tags: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
