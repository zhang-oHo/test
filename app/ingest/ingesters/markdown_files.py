"""Markdown ingester — 沿用既有 docs/RAG/*.md 路徑，並支援 task-18 frontmatter。

對應：
- task-25：基礎 markdown ingester
- task-18：解析 frontmatter（source_url / content_hash / category / tags / source_title）
  讓爬蟲產出的 markdown 帶著來源 metadata 流到 chunk → narrative `[來源 N]` 自動帶 URL
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import yaml

from app.ingest.document import Document, DocumentSection


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """切出 frontmatter dict 與 body。沒有 frontmatter 時 dict 為空、body 為原文。"""
    if not text.startswith("---\n"):
        return {}, text
    try:
        _, fm_raw, body = text.split("---\n", 2)
        fm = yaml.safe_load(fm_raw) or {}
        if not isinstance(fm, dict):
            return {}, text
        return fm, body.lstrip("\n")
    except (ValueError, yaml.YAMLError):
        return {}, text


class MarkdownIngester:
    name = "markdown"

    def __init__(self, paths: list[Path], *, category: str) -> None:
        self._paths = paths
        self._default_category = category

    def required_settings(self) -> list[str]:
        return []

    async def yield_documents(self) -> AsyncIterator[Document]:
        for path in self._paths:
            raw = path.read_text(encoding="utf-8")
            if not raw.strip():
                continue

            fm, body = parse_frontmatter(raw)
            if not body.strip():
                continue

            # frontmatter 優先於 CLI category（爬蟲產的檔自帶分類）
            category = fm.get("category") or self._default_category
            tags = fm.get("tags") or [path.stem]
            source_url = fm.get("source_url")
            title = fm.get("source_title") or path.stem

            content_hash = (
                fm.get("content_hash")
                or hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
            )

            metadata = {
                "path": str(path),
                **({"source_url": source_url} if source_url else {}),
                **({"crawled_at": fm["crawled_at"]} if "crawled_at" in fm else {}),
                **({"source_title": fm["source_title"]} if "source_title" in fm else {}),
            }

            yield Document(
                source_id=source_url or str(path),
                source_type="web" if source_url else "markdown",
                source_url=source_url,
                title=title,
                sections=[DocumentSection(text=body)],
                fetched_at=datetime.now(timezone.utc),
                content_hash=content_hash,
                category=category,
                tags=list(tags) if isinstance(tags, list) else [str(tags)],
                metadata=metadata,
            )
