"""Web ingester — Playwright-based crawler，直接 yield Document。

對應 spec-18 / spec-25：把 scripts/crawl_to_markdown.py 的內容抽取邏輯封裝成
符合 Ingester Protocol 的類別，供 IngestionPipeline 使用。

純函式（html_to_markdown, content_hash_of, is_allowed_by_robots, url_to_filename）
同時匯出，讓 scripts/crawl_to_markdown.py 直接 import 而不重複定義。

與 scripts/crawl_to_markdown.py 的分工：
- crawl_to_markdown.py：兩階段模式（crawl → 中介 markdown 檔 → ingest），保留教學用
- WebIngester：一步到位，crawl 完直接進 IngestionPipeline
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import AsyncIterator, Callable
from urllib import robotparser
from urllib.parse import urlparse

from app.ingest.document import Document, DocumentSection

logger = logging.getLogger(__name__)

USER_AGENT = "linebot-rag-skills-edu-crawler/0.1 (+contact: edu@example.com)"
DEFAULT_RULE: dict = {
    "main_selector": None,
    "remove_selectors": [],
    "wait_selector": None,
}

_FILENAME_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


# ── 純函式（可獨立 unit test，不需 Playwright / 網路）─────────────────────────


def content_hash_of(html: str) -> str:
    return hashlib.sha256(html.encode("utf-8")).hexdigest()[:16]


def url_to_filename(url: str) -> str:
    """URL → 安全檔名（保留 path 結構可讀性，截斷至 200 字元）。"""
    parsed = urlparse(url)
    safe_path = _FILENAME_UNSAFE.sub("_", parsed.path.strip("/")) or "index"
    host = parsed.netloc.replace("www.", "").replace(".", "_")
    return f"{host}__{safe_path}.md"[:200]


def is_allowed_by_robots(
    url: str, *, rp_cache: dict, user_agent: str = USER_AGENT
) -> bool:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if base not in rp_cache:
        rp = robotparser.RobotFileParser()
        rp.set_url(f"{base}/robots.txt")
        try:
            rp.read()
            rp_cache[base] = rp
        except Exception:
            logger.warning("robots.txt unreachable for %s, allowing by default", base)
            rp_cache[base] = None
    rp = rp_cache[base]
    return rp.can_fetch(user_agent, url) if rp else True


def html_to_markdown(html: str, *, rule: dict) -> str:
    """先嘗試 site rule CSS selector，失敗 fallback readability。

    依賴 markdownify（必要）、lxml + readability-lxml（selector/fallback 路徑）。
    """
    from markdownify import markdownify

    if rule.get("main_selector"):
        try:
            from lxml import html as lxml_html

            tree = lxml_html.fromstring(html)
            for sel in rule.get("remove_selectors", []) or []:
                for el in tree.cssselect(sel):
                    parent = el.getparent()
                    if parent is not None:
                        parent.remove(el)
            nodes = tree.cssselect(rule["main_selector"])
            if nodes:
                main_html = "".join(
                    lxml_html.tostring(n, encoding="unicode") for n in nodes
                )
                return markdownify(main_html, heading_style="ATX").strip()
        except Exception:
            logger.warning("site selector failed, falling back to readability", exc_info=True)

    from readability import Document as ReadabilityDocument

    doc = ReadabilityDocument(html)
    return markdownify(doc.summary(), heading_style="ATX").strip()


# ── Playwright I/O（測試時可 mock）────────────────────────────────────────────


async def fetch_html(
    browser, url: str, *, wait_selector: str | None
) -> tuple[str, str]:
    """回傳 (html, page_title)。"""
    context = await browser.new_context(user_agent=USER_AGENT)
    page = await context.new_page()
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        if wait_selector:
            try:
                await page.wait_for_selector(wait_selector, timeout=15_000)
            except Exception:
                logger.warning("wait_selector %r missed for %s", wait_selector, url)
        html = await page.content()
        title = await page.title()
        return html, title
    finally:
        await context.close()


# ── Ingester ────────────────────────────────────────────────────────────────


class WebIngester:
    """Playwright-based web ingester — 符合 Ingester Protocol，供 IngestionPipeline 使用。

    Args:
        urls: 要爬取的 URL 列表。
        category: 知識分類標籤。
        concurrency: 同時開啟的 browser context 數（預設 3）。
        delay: 每個 URL 抓完後的等待秒數（預設 1.0，遵守禮貌爬蟲原則）。
        get_rule: URL → site rule dict 的函式；傳入 site_rules.rule_for 即可套用
                  SITE_RULES 設定。預設使用 readability fallback。
        respect_robots: 預設 True，遵守 robots.txt；教學離線測試可設 False。
    """

    name = "web"

    def __init__(
        self,
        urls: list[str],
        *,
        category: str,
        concurrency: int = 3,
        delay: float = 1.0,
        get_rule: Callable[[str], dict] | None = None,
        respect_robots: bool = True,
    ) -> None:
        self._urls = urls
        self._category = category
        self._concurrency = concurrency
        self._delay = delay
        self._get_rule = get_rule or (lambda _: DEFAULT_RULE)
        self._respect_robots = respect_robots

    def required_settings(self) -> list[str]:
        return []

    async def yield_documents(self) -> AsyncIterator[Document]:
        from playwright.async_api import async_playwright

        sem = asyncio.Semaphore(self._concurrency)
        rp_cache: dict = {}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                for url in self._urls:
                    doc = await self._crawl_one(browser, url, sem=sem, rp_cache=rp_cache)
                    if doc is not None:
                        yield doc
            finally:
                await browser.close()

    async def _crawl_one(
        self, browser, url: str, *, sem: asyncio.Semaphore, rp_cache: dict
    ) -> Document | None:
        if self._respect_robots and not is_allowed_by_robots(url, rp_cache=rp_cache):
            logger.info("skipped by robots.txt: %s", url)
            return None

        rule = self._get_rule(url)
        try:
            async with sem:
                html, title = await fetch_html(
                    browser, url, wait_selector=rule.get("wait_selector")
                )
                await asyncio.sleep(self._delay)
        except Exception as exc:
            logger.error("fetch failed %s: %s", url, exc)
            return None

        md = html_to_markdown(html, rule=rule)
        if not md:
            logger.warning("empty markdown after extraction: %s", url)
            return None

        chash = content_hash_of(html)
        host = urlparse(url).netloc.replace("www.", "")

        return Document(
            source_id=url,
            source_type="web",
            source_url=url,
            title=title or url,
            sections=[
                DocumentSection(
                    text=md,
                    metadata={"source_url": url, "content_hash": chash},
                )
            ],
            fetched_at=datetime.now(timezone.utc),
            content_hash=chash,
            category=self._category,
            tags=[host],
            metadata={"source_url": url, "content_hash": chash},
        )
