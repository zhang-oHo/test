"""SupabaseArticleIngester — 從 crawler.articles 讀取已爬文章，yield Document。

對應 ch09-rag-bridge（project-playwright 收口章）：
  project-playwright 把爬蟲結果存入 Supabase crawler.articles，
  本 Ingester 讀取後交給 IngestionPipeline 進行 chunk → embed → upsert。

與 WebIngester 的差別：
  - WebIngester：即時爬取 → 直接 yield Document
  - SupabaseArticleIngester：讀已爬完的 articles → yield Document
    (content_hash 已由爬蟲計算，IngestionPipeline 的 source_hash()
     可直接跳過未更新的文章，不重複 embed)

兩個專案必須共用同一個 Supabase 實例（SUPABASE_URL 相同）。
本 Ingester 查詢 crawler schema（Accept-Profile: crawler），
不影響 linebot-rag-skills 對 public schema 的其他存取。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, AsyncIterator

import httpx

from app.ingest.document import Document, DocumentSection

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


class SupabaseArticleIngester:
    """從共用 Supabase 的 crawler.articles 產出 Document 串流。

    Args:
        settings:  linebot-rag-skills 的 Settings（取 supabase_url / service_role_key）。
        category:  只處理指定分類；None 表示全部。
        since:     只取 created_at 大於此時間的文章；None 表示全部。
        limit:     每次最多取幾筆（預設 500，防止單次 embed 過多）。
    """

    name = "supabase_articles"

    def __init__(
        self,
        settings: Settings,
        *,
        category: str | None = None,
        since: datetime | None = None,
        limit: int = 500,
    ) -> None:
        base = settings.supabase_url.rstrip("/")
        self._url = f"{base}/rest/v1/articles"
        api_key = settings.supabase_service_role_key
        self._headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Accept-Profile": "crawler",   # 切換到 crawler schema
        }
        self._category = category
        self._since = since
        self._limit = limit

    def required_settings(self) -> list[str]:
        return ["supabase_url", "supabase_service_role_key"]

    async def yield_documents(self) -> AsyncIterator[Document]:
        params: dict[str, str] = {
            "select": (
                "source_url,title,content_text,content_hash,"
                "category,source_type,meta,created_at"
            ),
            "limit": str(self._limit),
            "order": "created_at.desc",
        }
        if self._category:
            params["category"] = f"eq.{self._category}"
        if self._since:
            params["created_at"] = f"gte.{self._since.isoformat()}"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(self._url, headers=self._headers, params=params)
            resp.raise_for_status()
            rows: list[dict] = resp.json()

        logger.info(
            "[%s] fetched %d articles from crawler.articles (category=%s)",
            self.name, len(rows), self._category or "*",
        )

        for row in rows:
            content = (row.get("content_text") or "").strip()
            if not content:
                logger.debug("skip empty content_text: %s", row.get("source_url"))
                continue

            meta: dict = row.get("meta") or {}
            tags: list[str] = meta.get("tags") or []
            source_url: str = row["source_url"]
            created_at_raw: str | None = row.get("created_at")

            yield Document(
                source_id=source_url,
                source_type="web",
                source_url=source_url,
                title=row.get("title") or source_url,
                content_hash=row.get("content_hash") or "",
                sections=[DocumentSection(
                    text=content,
                    metadata={"source_url": source_url},
                )],
                category=row.get("category") or "general",
                tags=tags,
                fetched_at=_parse_dt(created_at_raw),
                metadata={"source_url": source_url},
            )


def _parse_dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)
