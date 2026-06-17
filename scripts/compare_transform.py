"""比較四種 query transform 策略對檢索結果的影響（docs/Lesson_5_Production/ch05）。

跑同一個 query，依序套用 none / hyde / step_back / decompose，列出
每種策略產生的 transformed_queries 與 top retrieved chunks。

用法：
    python scripts/compare_transform.py
    python scripts/compare_transform.py --query "Supabase HNSW 怎麼設？" --top-k 5
    python scripts/compare_transform.py --strategies none,hyde
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings  # noqa: E402
from app.dependencies import get_runtime_services  # noqa: E402
from app.graph.query_transform import query_transform_node  # noqa: E402


async def _run_one(strategy: str, query: str, top_k: int) -> None:
    # 透過 env 切策略；get_settings() 用 LRU cache，所以本 script 跑一次只能用一個值
    # ——這裡用 monkey-patch 直接改 settings 物件。
    os.environ["QUERY_TRANSFORM_STRATEGY"] = strategy
    settings = get_settings()
    settings.query_transform_strategy = strategy  # 強制覆寫已 cache 的值

    services = get_runtime_services()
    services.settings.query_transform_strategy = strategy

    state = {"user_input": query}
    result = await query_transform_node(state, services)

    print(f"\n===== strategy: {strategy} =====")
    print(f"transformed_queries ({len(result['transformed_queries'])}):")
    for i, q in enumerate(result["transformed_queries"], 1):
        print(f"  {i}. {q[:120]}")

    # 試著拿第一條去檢索看效果
    first = result["transformed_queries"][0]
    chunks = await services.retriever.retrieve_for_seed(first, top_k=top_k)
    print(f"top {top_k} chunks for first transformed query:")
    if not chunks:
        print("  (no results)")
    for i, c in enumerate(chunks, 1):
        title = (c.title or "<no title>")[:60]
        print(f"  {i}. {title}  score={c.combined_score:.4f}")


async def main(args: argparse.Namespace) -> None:
    for strategy in args.strategies.split(","):
        strategy = strategy.strip()
        await _run_one(strategy, args.query, args.top_k)


def cli() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument(
        "--query",
        default="為什麼 Supabase 的 HNSW 比 IVFFlat 更適合小型 KB？",
        help="要測試的 user query",
    )
    p.add_argument("--top-k", type=int, default=5, help="每條 seed 撈幾筆 chunk")
    p.add_argument(
        "--strategies",
        default="none,hyde,step_back,decompose",
        help="逗號分隔的策略名單（none/hyde/step_back/decompose）",
    )
    args = p.parse_args()
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
