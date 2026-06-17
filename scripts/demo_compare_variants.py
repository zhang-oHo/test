"""對同一個 query 跑三個 variant，print 對比結果。

用法：
    python scripts/demo_compare_variants.py "什麼是 RAG？"

說明：
- dry_run=True 讓 push_node 跳過實際 LINE 推送（U_demo_compare 僅作識別用）
- 三 variant 都用同一份 RuntimeServices；只切 graph
- 需要 .env 已設定有效的 LLM provider 與 Supabase；缺項會降級為 stub 行為
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.dependencies import get_runtime_services
from app.graph.variants import VARIANT_BUILDERS


async def run_variant(variant_name: str, query: str) -> dict:
    services = get_runtime_services()
    builder = VARIANT_BUILDERS[variant_name]
    graph = builder(services)
    initial_state = {
        "user_input": query,
        "external_user_id": "U_demo_compare",
        "recent_history": "",
        "dry_run": True,
    }
    t0 = time.time()
    final = await graph.ainvoke(initial_state)
    duration = time.time() - t0
    return {
        "variant": variant_name,
        "duration": duration,
        "chunks": len(final.get("rag_chunks") or []),
        "seeds": final.get("seeds") or [],
        "sufficiency": final.get("sufficiency", "(n/a)"),
        "judge_score": final.get("judge_score"),
        "retry": final.get("reflection_retry", 0),
        "warning": final.get("judge_warning_prefix", False),
        "response": "\n\n".join(final.get("responses") or [])[:300],
    }


def print_result(r: dict) -> None:
    print(f"\n[{r['variant']}]")
    print(f"  duration:    {r['duration']:.2f}s")
    print(f"  chunks:      {r['chunks']}")
    if r["seeds"]:
        print(f"  seeds:       {r['seeds']}")
    print(f"  sufficiency: {r['sufficiency']}")
    score = r["judge_score"]
    if score is not None:
        print(
            f"  judge:       ground={score.groundedness} cite={score.citation_fidelity} "
            f"format={score.format_completeness} uncert={score.uncertainty_honesty} "
            f"mean={score.mean:.1f}"
        )
        print(f"  retry:       {r['retry']}")
        if r["warning"]:
            print("  ⚠️  品質警告已加上前綴")
    print("  response (first 300 chars):")
    print("    " + r["response"].replace("\n", "\n    "))


async def main(query: str) -> None:
    print(f"Query: {query}")
    print("=" * 60)

    for name in ("basic", "selfrag", "reflection"):
        try:
            r = await run_variant(name, query)
            print_result(r)
        except Exception as e:
            print(f"\n[{name}] FAILED: {e}")

    print("\n" + "=" * 60)
    print("變體對應 — 詳見 docs/RAG/LangGraph/ch06：")
    print("  basic      → ch06 §1 基本 RAG")
    print("  selfrag    → ch06 §2 Self-RAG")
    print("  reflection → ch06 §3 Reflection Agent")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python scripts/demo_compare_variants.py "<query>"')
        sys.exit(1)
    asyncio.run(main(" ".join(sys.argv[1:])))
