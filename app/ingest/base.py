"""Ingester Protocol — 從某個來源 yield 出 Document 流。

對應 spec-25 / task-25 步驟 2。
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol

from app.ingest.document import Document


class Ingester(Protocol):
    name: str

    def yield_documents(self) -> AsyncIterator[Document]: ...

    def required_settings(self) -> list[str]:
        """聲明需要哪些 env / config（例 ["NOTION_API_KEY"]）。"""
        ...
