"""比較三種 fusion 策略（max / mean / rrf）對 multi-seed 檢索結果的影響。

對應 docs/Lesson_5_Production/ch06 §Step 6。

跑同一組 seeds 並行檢索，依序套用三種 fusion，列出 top 排序差異。

用法：
    python scripts/compare_fusion.py
    python scripts/compare_fusion.py --query "HNSW lists 怎麼設"
    python scripts/compare_fusion.py --top-n 10
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.dependencies import get_runtime_services  # noqa: E402
from app.graph.feature_extractor import LLMFeatureExtractor  # noqa: E402
from app.graph.seed_expander import DefaultSeedExpander  # noqa: E402
from app.rag.fusion import get_fuser  # noqa: E402


async def main(args: argparse.Namespace) -> None:
    services = get_runtime_services()

    # 1) 抽 features → 展 seeds（跟 graph 同步驟）
    extractor = LLMFeatureExtractor(llm=None)   # 不用 LLM，純 fallback 也夠 demo
    features = await extractor.extract(user_input=args.query)

    expander = DefaultSeedExpander()
    seeds = expander.expand(features, max_seeds=args.max_seeds)
    if not seeds:
        seeds = [args.query]

    print(f"query: {args.query}")
    print(f"seeds ({len(seeds)}):")
    for i, s in enumerate(seeds, 1):
        print(f"  {i}. {s}")

    # 2) 並行檢索每條 seed
    hits_per_seed = await asyncio.gather(*[
        services.retriever.retrieve_for_seed(s, top_k=args.top_k_per_seed)
        for s in seeds
    ])

    total_unique = len({c.id for hits in hits_per_seed for c in hits})
    print(f"\ntotal unique chunks across all seeds: {total_unique}")

    # 3) 三種 fusion 各跑一次
    for strategy in args.strategies.split(","):
        strategy = strategy.strip()
        try:
            fuser = get_fuser(strategy)
        except ValueError as e:
            print(f"\n!! skip {strategy!r}: {e}")
            continue
        fused = fuser(hits_per_seed)[: args.top_n]
        print(f"\n===== fusion: {strategy} (top {len(fused)}) =====")
        for i, c in enumerate(fused, 1):
            title = (c.title or "<no title>")[:60]
            print(f"  {i:>2}. {title}  combined={c.combined_score:.4f}")


def cli() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--query", default="Supabase HNSW 怎麼調 lists 與 ef？")
    p.add_argument("--max-seeds", type=int, default=5)
    p.add_argument("--top-k-per-seed", type=int, default=8)
    p.add_argument("--top-n", type=int, default=5, help="fusion 後保留前 N 名")
    p.add_argument("--strategies", default="max,mean,rrf")
    args = p.parse_args()
    asyncio.run(main(args))


if __name__ == "__main__":
    cli()
