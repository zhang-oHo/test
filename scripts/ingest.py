"""統一 ingestion CLI — 對應 spec-25 / task-25 步驟 9。

六種子命令：

    python scripts/ingest.py markdown  --paths "docs/RAG/*.md" --category rag
    python scripts/ingest.py pdf       --paths "docs/sources/*.pdf" --category regulations
    python scripts/ingest.py csv       --path data/faq.csv --mode row_per_doc \\
                                        --text-columns question,answer --category faq
    python scripts/ingest.py notion    --database-id <id> --category company-wiki
    python scripts/ingest.py web       --urls urls/nextjs.txt --category nextjs
    python scripts/ingest.py articles  --category nextjs   # ← ch09 RAG bridge

articles 子命令從共用 Supabase 的 crawler.articles 讀取爬蟲結果，
直接進 IngestionPipeline（chunk → embed → upsert）。
需與 project-playwright 共用相同的 SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY。

切換 store backend：

    KNOWLEDGE_STORE_BACKEND=sqlite_vec python scripts/ingest.py markdown ...
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.ingest.ingesters import (
    CsvIngester, CsvIngesterConfig, MarkdownIngester,
    PdfIngester, SupabaseArticleIngester, WebIngester,
)
from app.ingest.pipeline import IngestionPipeline
from app.ai.factory import build_embedder
from app.storage.stores import build_store


def _expand(patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in patterns:
        matches = glob.glob(p)
        if matches:
            out.extend(Path(m) for m in matches)
        else:
            out.append(Path(p))
    return out


async def _run(ingester) -> None:
    settings = get_settings()
    store = build_store(settings)
    embedder = build_embedder(settings)
    pipeline = IngestionPipeline(embedder=embedder, store=store)
    stats = await pipeline.run(ingester)
    print(
        f"[{ingester.name}] docs={stats.docs} chunks={stats.chunks} "
        f"skipped={stats.skipped} unchanged={stats.unchanged}"
    )


async def cmd_markdown(args) -> None:
    paths = _expand(args.paths)
    if not paths:
        print(f"no markdown files matched: {args.paths}")
        return
    await _run(MarkdownIngester(paths, category=args.category))


async def cmd_pdf(args) -> None:
    paths = _expand(args.paths)
    if not paths:
        print(f"no PDF files matched: {args.paths}")
        return
    await _run(PdfIngester(paths, category=args.category, use_ocr=args.use_ocr))


async def cmd_csv(args) -> None:
    cfg = CsvIngesterConfig(
        path=args.path,
        mode=args.mode,
        text_columns=args.text_columns.split(",") if args.text_columns else [],
        metadata_columns=(
            args.metadata_columns.split(",") if args.metadata_columns else []
        ),
        title_column=args.title_column,
    )
    await _run(CsvIngester(cfg, category=args.category))


async def cmd_web(args) -> None:
    from scripts.site_rules import rule_for

    urls = [
        line.strip()
        for line in Path(args.urls).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not urls:
        print(f"no URLs found in: {args.urls}")
        return
    ingester = WebIngester(
        urls,
        category=args.category,
        concurrency=args.concurrency,
        delay=args.delay,
        get_rule=rule_for,
        respect_robots=not args.ignore_robots,
    )
    await _run(ingester)


async def cmd_articles(args) -> None:
    from datetime import datetime, timezone

    since: datetime | None = None
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    settings = get_settings()
    ingester = SupabaseArticleIngester(
        settings,
        category=args.category or None,
        since=since,
        limit=args.limit,
    )
    await _run(ingester)


async def cmd_notion(args) -> None:
    from app.ingest.ingesters.notion import NotionIngester

    ingester = NotionIngester(
        api_key=os.environ.get("NOTION_API_KEY", ""),
        database_id=args.database_id,
        page_id=args.page_id,
        category=args.category,
    )
    await _run(ingester)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("markdown")
    p.add_argument("--paths", nargs="+", required=True)
    p.add_argument("--category", default="notes")

    p = sub.add_parser("pdf")
    p.add_argument("--paths", nargs="+", required=True)
    p.add_argument("--category", required=True)
    p.add_argument("--use-ocr", action="store_true")

    p = sub.add_parser("csv")
    p.add_argument("--path", required=True)
    p.add_argument("--mode", choices=["row_per_doc", "table_as_doc"], default="row_per_doc")
    p.add_argument("--text-columns", default="")
    p.add_argument("--metadata-columns", default="")
    p.add_argument("--title-column", default=None)
    p.add_argument("--category", required=True)

    p = sub.add_parser("notion")
    p.add_argument("--database-id", default=None)
    p.add_argument("--page-id", default=None)
    p.add_argument("--category", required=True)

    p = sub.add_parser("web")
    p.add_argument("--urls", required=True, help="URL list 檔；每行一個 URL")
    p.add_argument("--category", required=True)
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--delay", type=float, default=1.0)
    p.add_argument("--ignore-robots", action="store_true", help="略過 robots.txt（測試用）")

    p = sub.add_parser("articles", help="從 crawler.articles（project-playwright）讀取並 embed")
    p.add_argument("--category", default=None, help="只處理指定分類；省略則全部")
    p.add_argument("--since", default=None, metavar="YYYY-MM-DD", help="只取此日期之後新增的文章")
    p.add_argument("--limit", type=int, default=500, help="最多處理幾篇（預設 500）")

    args = parser.parse_args()
    handlers = {
        "markdown": cmd_markdown,
        "pdf": cmd_pdf,
        "csv": cmd_csv,
        "notion": cmd_notion,
        "web": cmd_web,
        "articles": cmd_articles,
    }
    asyncio.run(handlers[args.cmd](args))


if __name__ == "__main__":
    main()
