"""Notion Export ZIP / directory ingestion — 對應 spec-07。

把 Notion「Export → Markdown & CSV」吐出的目錄（或 .zip）裡的 .md 檔
塞進 IngestionPipeline。

說明：
- 不走 Notion API（spec-07 §「不需 API」的方向）
- ZIP 支援：傳 .zip 路徑 → 解壓到暫存目錄再 ingest
- 內容清理（移除 UUID 後綴、轉內部連結、清 metadata block）是 spec-25
  Notion ingester 真實作的範圍；本腳本目前先單純把 markdown 餵 MarkdownIngester。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ai.factory import build_embedder
from app.config import get_settings
from app.ingest.ingesters import MarkdownIngester
from app.ingest.pipeline import IngestionPipeline
from app.storage.stores import build_store


async def ingest_directory(export_dir: Path, *, category: str) -> None:
    markdown_files = sorted(export_dir.rglob("*.md"))
    if not markdown_files:
        print(f"no markdown files under {export_dir}")
        return

    settings = get_settings()
    pipeline = IngestionPipeline(
        embedder=build_embedder(settings),
        store=build_store(settings),
    )
    ingester = MarkdownIngester(markdown_files, category=category)
    stats = await pipeline.run(ingester)
    print(
        f"Ingested docs={stats.docs} chunks={stats.chunks} "
        f"skipped={stats.skipped} unchanged={stats.unchanged} "
        f"from {len(markdown_files)} markdown files."
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest a Notion export (dir or .zip).")
    parser.add_argument("export_path", help="Notion export 解壓後的目錄，或 .zip 檔")
    parser.add_argument("--category", default="notion")
    args = parser.parse_args()

    src = Path(args.export_path)
    if not src.exists():
        sys.exit(f"path not found: {src}")

    if src.is_file() and src.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory(prefix="notion-export-") as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(src) as zf:
                # zip-slip 防護：拒絕含絕對路徑或 ".." 跳脫的 entry。Notion 官方 export
                # 不會產出這種檔，但本機 CLI 直接吃任意 zip，加保護不費事。
                for info in zf.infolist():
                    name = info.filename
                    if Path(name).is_absolute() or ".." in Path(name).parts:
                        sys.exit(f"refusing to extract suspicious zip entry: {name!r}")
                zf.extractall(tmp_path)
            await ingest_directory(tmp_path, category=args.category)
    elif src.is_dir():
        await ingest_directory(src, category=args.category)
    else:
        sys.exit(f"unsupported path (need dir or .zip): {src}")


if __name__ == "__main__":
    asyncio.run(main())
