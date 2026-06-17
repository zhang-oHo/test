"""Notion ingester — 對應 spec-25 §「Notion ingester 設計」。

實作要點：
1. `notion-client` AsyncClient（optional dep `[notion]`），auth 用 `NOTION_API_KEY`
2. `database_id` → 列出資料庫所有 page；`page_id` → 單一 page
3. 每個 page → walk blocks，遇到 heading_1/2/3 開啟新 section，
   其餘 block（paragraph / list / quote / code）累積為 section.text
4. content_hash = sha256(page_id + last_edited_time)[:16]，
   只要 page 未編輯就會跟上次 ingest 一致 → IngestionPipeline 在 store
   端比對 `unchanged` 直接跳過 embed
5. 子 page 不遞迴（避免抓爆，超出教學主線範圍）

Constructor 接受 `client` 注入用於測試；正式環境 client=None 時走真 SDK。
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from app.ingest.document import Document, DocumentSection

logger = logging.getLogger(__name__)


# Notion block types 對應的純文字鍵
_TEXT_BLOCK_TYPES = {
    "paragraph",
    "bulleted_list_item",
    "numbered_list_item",
    "to_do",
    "toggle",
    "quote",
    "callout",
    "code",
}


def _extract_rich_text(block: dict[str, Any], block_type: str) -> str:
    """從 Notion block 取出 rich_text 純文字串接。"""
    body = block.get(block_type) or {}
    rich = body.get("rich_text") or []
    return "".join(r.get("plain_text", "") for r in rich)


def _block_to_text(block: dict[str, Any]) -> tuple[str, str]:
    """回 (block_type, plain_text)；不在已知型別中時回空字串。"""
    btype = block.get("type", "")
    if btype.startswith("heading_") or btype in _TEXT_BLOCK_TYPES:
        return btype, _extract_rich_text(block, btype)
    return btype, ""


def _content_hash(page_id: str, last_edited: str) -> str:
    raw = f"{page_id}:{last_edited}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _page_title(page: dict[str, Any]) -> str:
    """從 Notion page 物件 best-effort 取標題。"""
    # database row：properties 內第一個 title type
    props = page.get("properties") or {}
    for prop in props.values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", []))
    # standalone page
    title = page.get("title") or []
    if isinstance(title, list):
        return "".join(t.get("plain_text", "") for t in title)
    return page.get("id", "untitled")


class NotionIngester:
    name = "notion"

    def __init__(
        self,
        *,
        api_key: str,
        database_id: str | None = None,
        page_id: str | None = None,
        category: str,
        client: Any = None,
    ) -> None:
        if not database_id and not page_id:
            raise ValueError("NotionIngester needs either database_id or page_id")
        self._api_key = api_key
        self._database_id = database_id
        self._page_id = page_id
        self._category = category
        self._client = client  # 注入用；正式 None → 跑 _make_client()

    def required_settings(self) -> list[str]:
        return ["NOTION_API_KEY"]

    def _make_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self._api_key:
            raise ValueError("NOTION_API_KEY is empty; pass api_key or inject client")
        try:
            from notion_client import AsyncClient  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "notion-client not installed — `pip install -e \".[notion]\"`"
            ) from exc
        return AsyncClient(auth=self._api_key)

    async def yield_documents(self) -> AsyncIterator[Document]:
        client = self._make_client()
        pages = await self._list_pages(client)
        for page in pages:
            doc = await self._page_to_document(client, page)
            if doc is not None:
                yield doc

    async def _list_pages(self, client: Any) -> list[dict[str, Any]]:
        """database_id → query all pages（自動 paginate）；page_id → 包成單一元素 list。"""
        if self._page_id:
            page = await client.pages.retrieve(page_id=self._page_id)
            return [page]
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        # 防呆：上限 20 batch（Notion 預設一批 100 → 約 2000 page），超過視為設定錯誤
        max_batches = 20
        for _ in range(max_batches):
            kwargs: dict[str, Any] = {"database_id": self._database_id}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = await client.databases.query(**kwargs)
            pages.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        else:
            logger.warning(
                "NotionIngester._list_pages hit batch cap (%d) for database_id=%s; "
                "page list may be truncated. Consider narrowing the database or raising the cap.",
                max_batches, self._database_id,
            )
        return pages

    async def _page_to_document(
        self, client: Any, page: dict[str, Any]
    ) -> Document | None:
        page_id = page.get("id")
        if not page_id:
            return None
        last_edited = page.get("last_edited_time") or page.get("created_time") or ""
        sections = await self._collect_sections(client, page_id)
        if not sections:
            return None
        title = _page_title(page) or page_id
        return Document(
            source_id=page_id,
            source_type="notion",
            source_url=page.get("url"),
            title=title,
            sections=sections,
            fetched_at=datetime.now(timezone.utc),
            content_hash=_content_hash(page_id, last_edited),
            category=self._category,
            tags=[],
            metadata={
                "notion_last_edited_time": last_edited,
                **({"notion_url": page["url"]} if page.get("url") else {}),
            },
        )

    async def _collect_sections(
        self, client: Any, page_id: str
    ) -> list[DocumentSection]:
        blocks = await self._list_all_blocks(client, page_id)
        sections: list[DocumentSection] = []
        section_path: list[str] = []
        buffer: list[str] = []

        def flush() -> None:
            text = "\n".join(b for b in buffer if b).strip()
            if text:
                sections.append(
                    DocumentSection(
                        text=text,
                        section_path=list(section_path),
                    )
                )

        for block in blocks:
            btype, text = _block_to_text(block)
            if btype.startswith("heading_"):
                # heading 觸發 flush，並依等級截斷 path
                flush()
                buffer = []
                level = int(btype.removeprefix("heading_") or "1")
                section_path = section_path[: max(level - 1, 0)]
                if text:
                    section_path.append(text)
            elif text:
                buffer.append(text)
        flush()
        return sections

    async def _list_all_blocks(
        self, client: Any, block_id: str
    ) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        cursor: str | None = None
        max_batches = 50  # 防呆：最多 ~5000 blocks / page
        for _ in range(max_batches):
            kwargs: dict[str, Any] = {"block_id": block_id}
            if cursor:
                kwargs["start_cursor"] = cursor
            resp = await client.blocks.children.list(**kwargs)
            blocks.extend(resp.get("results", []))
            if not resp.get("has_more"):
                break
            cursor = resp.get("next_cursor")
        else:
            logger.warning(
                "NotionIngester._list_all_blocks hit batch cap (%d) for block_id=%s; "
                "blocks may be truncated.", max_batches, block_id,
            )
        return blocks
