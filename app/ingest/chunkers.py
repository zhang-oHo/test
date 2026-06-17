"""Per-source chunkers — 不同來源用不同 chunking 策略。

對應 spec-25 / task-25 步驟 8。

| source | chunker | 邏輯 |
|--------|---------|------|
| markdown / web / notion | MarkdownHeadingChunker | 既有 chunk_markdown（size cap + overlap）|
| pdf | PageBoundaryChunker | 自然以 page 為單位，page 過長再 size cap 切 |
| csv | NoOpChunker | 一列即一 chunk，不切 |
"""

from __future__ import annotations

from typing import Protocol

from app.rag.chunker import chunk_markdown


class Chunker(Protocol):
    def chunk(self, text: str) -> list[str]: ...


class MarkdownHeadingChunker:
    """既有 chunk_markdown 的物件包裝。size cap + overlap。"""

    def __init__(self, *, max_chars: int = 1200, overlap: int = 120) -> None:
        self._max = max_chars
        self._overlap = overlap

    def chunk(self, text: str) -> list[str]:
        return chunk_markdown(text, max_chars=self._max, overlap=self._overlap)


class PageBoundaryChunker:
    """PDF 用：原則上一個 page 一個 chunk，page 過長才二次切。"""

    def __init__(self, *, max_chars: int = 2400, overlap: int = 120) -> None:
        self._max = max_chars
        self._overlap = overlap

    def chunk(self, text: str) -> list[str]:
        if not text or not text.strip():
            return []
        if len(text) <= self._max:
            return [text.strip()]
        return chunk_markdown(text, max_chars=self._max, overlap=self._overlap)


class NoOpChunker:
    """CSV / 行資料：不切，整段就是一 chunk。"""

    def chunk(self, text: str) -> list[str]:
        text = text.strip()
        return [text] if text else []


DEFAULT_CHUNKERS: dict[str, Chunker] = {
    "markdown": MarkdownHeadingChunker(),
    "web": MarkdownHeadingChunker(),
    "notion": MarkdownHeadingChunker(),
    "pdf": PageBoundaryChunker(),
    "csv": NoOpChunker(),
    "docx": MarkdownHeadingChunker(),
    "manual": MarkdownHeadingChunker(),
}


def chunker_for(source_type: str) -> Chunker:
    return DEFAULT_CHUNKERS.get(source_type, MarkdownHeadingChunker())
