"""Markdown ingester — thin wrapper（向後相容）。

新版統一 CLI：`python scripts/ingest.py markdown --paths <...> --category <...>`
本檔保留原命令行介面，內部走 task-25 的 IngestionPipeline + MarkdownIngester。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.ingest.ingesters import MarkdownIngester
from app.ingest.pipeline import IngestionPipeline
from app.ai.factory import build_embedder
from app.storage.stores import build_store


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--category", default="notes")
    args = parser.parse_args()

    # --- 新增這兩行 ---
    print(f"DEBUG: Found {len(args.paths)} files to ingest.")
    print(f"DEBUG: First file path: {args.paths[0]}")
    # ------------------

    settings = get_settings()
    store = build_store(settings)
    embedder = build_embedder(settings)
    pipeline = IngestionPipeline(embedder=embedder, store=store)

    paths = [Path(p) for p in args.paths]
    ingester = MarkdownIngester(paths, category=args.category)
    stats = await pipeline.run(ingester)
    print(f"Ingested {stats.chunks} chunks across {stats.docs} files.")


if __name__ == "__main__":
    asyncio.run(main())
