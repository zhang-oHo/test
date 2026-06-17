"""Playwright crawler — URL list → markdown 檔（帶 frontmatter）。

對應 spec-18 / task-18 兩階段模式：
  crawl → 中介 markdown 檔（帶 frontmatter）→ ingest 多次

內容抽取邏輯（html_to_markdown / content_hash_of / is_allowed_by_robots /
url_to_filename）已移至 app.ingest.ingesters.web 統一維護；
本檔 import 之，不再重複定義。

一步到位（無中介檔）請改用 WebIngester + IngestionPipeline：
    from app.ingest.ingesters.web import WebIngester
    python scripts/ingest.py web --urls urls/nextjs.txt --category nextjs

用法：
    python -m playwright install chromium      # 一次性
    python scripts/crawl_to_markdown.py \\
      --urls urls/nextjs.txt \\
      --out docs/RAG/crawled/nextjs \\
      --category nextjs --concurrency 3
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.site_rules import rule_for
from app.ingest.ingesters.web import (  # noqa: E402
    content_hash_of,
    fetch_html,
    html_to_markdown,
    is_allowed_by_robots,
    url_to_filename,
    USER_AGENT,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger("crawler")

DEFAULT_REQUEST_DELAY = 1.0


# ---- 本檔獨有（中介檔模式專用）--------------------------------------------


def make_frontmatter(
    *, url: str, title: str, category: str, content_hash: str
) -> str:
    fm = {
        "source_url": url,
        "source_title": title,
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": content_hash,
        "category": category,
        "tags": [urlparse(url).netloc.replace("www.", "")],
    }
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False) + "---\n\n"


def existing_hash(path: Path) -> str | None:
    """從現有檔案讀 frontmatter content_hash；不存在 / 解析失敗回 None。"""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            return None
        _, fm_raw, _ = text.split("---\n", 2)
        data = yaml.safe_load(fm_raw) or {}
        return data.get("content_hash")
    except (ValueError, yaml.YAMLError):
        return None


# ---- Playwright 部分（網路依賴，測試時 mock 之）---------------------------


async def crawl_one(
    browser,
    url: str,
    *,
    out_dir: Path,
    category: str,
    rp_cache: dict,
    request_delay: float,
) -> str:
    """回傳 status：wrote / unchanged / skipped_robots / failed。"""
    if not is_allowed_by_robots(url, rp_cache=rp_cache):
        logger.info("skipped by robots.txt: %s", url)
        return "skipped_robots"

    rule = rule_for(url)
    try:
        html, title = await fetch_html(browser, url, wait_selector=rule.get("wait_selector"))
    except Exception as exc:
        logger.error("fetch failed %s: %s", url, exc)
        return "failed"

    chash = content_hash_of(html)
    out_path = out_dir / url_to_filename(url)
    if existing_hash(out_path) == chash:
        logger.info("unchanged, skipped: %s", url)
        return "unchanged"

    md = html_to_markdown(html, rule=rule)
    if not md:
        logger.warning("empty markdown after extraction: %s", url)
        return "failed"

    fm = make_frontmatter(
        url=url, title=title, category=category, content_hash=chash
    )
    out_path.write_text(fm + md, encoding="utf-8")
    logger.info("wrote %s (%d chars)", out_path.name, len(md))
    await asyncio.sleep(request_delay)
    return "wrote"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--urls", required=True, help="URL list 檔；每行一個 URL")
    parser.add_argument("--out", required=True, help="輸出 markdown 目錄")
    parser.add_argument("--category", required=True)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--delay", type=float, default=DEFAULT_REQUEST_DELAY)
    args = parser.parse_args()

    urls = [
        line.strip()
        for line in Path(args.urls).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    sem = asyncio.Semaphore(args.concurrency)
    rp_cache: dict = {}

    from playwright.async_api import async_playwright

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            async def bounded(u: str) -> str:
                async with sem:
                    return await crawl_one(
                        browser, u,
                        out_dir=out_dir, category=args.category,
                        rp_cache=rp_cache, request_delay=args.delay,
                    )

            results = await asyncio.gather(*[bounded(u) for u in urls])
        finally:
            await browser.close()

    summary = {k: results.count(k) for k in set(results)}
    logger.info("done: %s", summary)


if __name__ == "__main__":
    asyncio.run(main())
