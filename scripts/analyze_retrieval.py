"""retrieval_logs CLI 分析工具 — 對應 spec-09 §「分析功能」。

用法：

    python scripts/analyze_retrieval.py --empty-hits [--days 7]
    python scripts/analyze_retrieval.py --low-score [--threshold 0.3] [--days 7]
    python scripts/analyze_retrieval.py --category-stats [--days 30]
    python scripts/analyze_retrieval.py --query "LangGraph 是什麼"

各模式都讀 retrieval_logs 後在 Python 端聚合（PostgREST 不直接支援 GROUP BY
與 jsonb path 過濾，把資料拉到 client 再算最簡單，個人使用量量級也夠用）。
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
from app.eval.retrieval_analytics import (
    aggregate_category_stats,
    aggregate_empty_hits,
    aggregate_low_score,
    cutoff_iso,
    filter_query_records,
    render_table,
)
from app.storage.supabase_client import SupabaseRestClient


async def _fetch_logs(client: SupabaseRestClient, *, days: int) -> list[dict]:
    return await client.select(
        "retrieval_logs",
        {
            "select": "query,skill_id,category_filter,retrieved_ids,scores,created_at",
            "created_at": f"gte.{cutoff_iso(days)}",
            "order": "created_at.desc",
            "limit": "5000",
        },
    )


async def _fetch_all_logs(client: SupabaseRestClient) -> list[dict]:
    """`--query` 模式：不限天數，保留 created_at 倒序給聚合函式排序。"""
    return await client.select(
        "retrieval_logs",
        {
            "select": "query,skill_id,category_filter,retrieved_ids,scores,created_at",
            "order": "created_at.desc",
            "limit": "5000",
        },
    )


async def run_empty_hits(client: SupabaseRestClient, *, days: int) -> str:
    rows = await _fetch_logs(client, days=days)
    return render_table(
        aggregate_empty_hits(rows), headers=["query", "count"]
    )


async def run_low_score(
    client: SupabaseRestClient, *, threshold: float, days: int
) -> str:
    rows = await _fetch_logs(client, days=days)
    return render_table(
        aggregate_low_score(rows, threshold=threshold),
        headers=["query", "max_combined", "category_filter", "created_at"],
    )


async def run_category_stats(client: SupabaseRestClient, *, days: int) -> str:
    rows = await _fetch_logs(client, days=days)
    return render_table(
        aggregate_category_stats(rows),
        headers=["category", "count", "avg_max_score"],
    )


async def run_query(client: SupabaseRestClient, *, query_text: str) -> str:
    rows = await _fetch_all_logs(client)
    return render_table(
        filter_query_records(rows, query_text),
        headers=["created_at", "query", "skill_id", "max_combined", "retrieved_ids"],
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--empty-hits", action="store_true")
    g.add_argument("--low-score", action="store_true")
    g.add_argument("--category-stats", action="store_true")
    g.add_argument("--query", metavar="QUERY_TEXT")
    p.add_argument("--days", type=int, default=7, help="time window (default 7)")
    p.add_argument(
        "--threshold", type=float, default=0.3,
        help=(
            "--low-score 閾值（max combined < threshold 視為低分；default 0.3）。"
            "注意：--low-score 只看「有命中但分數低」的 query；"
            "完全 0 命中的 query 請用 --empty-hits 看。"
        ),
    )
    return p


async def _async_main(args: argparse.Namespace) -> int:
    client = SupabaseRestClient(get_settings())
    if args.empty_hits:
        print(await run_empty_hits(client, days=args.days))
    elif args.low_score:
        print(await run_low_score(
            client, threshold=args.threshold, days=args.days
        ))
    elif args.category_stats:
        print(await run_category_stats(client, days=args.days))
    elif args.query:
        print(await run_query(client, query_text=args.query))
    return 0


def main() -> None:
    args = _build_parser().parse_args()
    sys.exit(asyncio.run(_async_main(args)))


if __name__ == "__main__":
    main()
