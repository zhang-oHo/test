"""跑 golden case set，輸出三變體 metric 對比表。

用法：
    python scripts/eval.py
    python scripts/eval.py --cases tests/cases/golden.yaml
    python scripts/eval.py --variants reflection
    python scripts/eval.py --case-id faq-001,gap-001
    python scripts/eval.py --output baseline.json --format json
    python scripts/eval.py --quick                # 只跑前 3 個 case
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.dependencies import get_runtime_services
from app.eval.runner import EvalResult, EvalRunner
from app.eval.schema import GoldenCaseSet


def _fmt(v, fmt="{:.2f}"):
    return "n/a" if v is None else fmt.format(v)


def render_table(agg: dict) -> str:
    variants = list(agg.keys())
    rows: list[tuple[str, ...]] = [
        ("metric", *variants),
        ("---", *(["---"] * len(variants))),
        ("chunk_recall_avg", *(_fmt(agg[v]["chunk_recall_avg"]) for v in variants)),
        ("citation_accuracy_avg", *(_fmt(agg[v]["citation_accuracy_avg"]) for v in variants)),
        ("forbidden_phrase_rate", *(_fmt(agg[v]["forbidden_phrase_rate"]) for v in variants)),
        ("clarification_rate", *(_fmt(agg[v]["clarification_rate"]) for v in variants)),
        ("judge_pass_rate", *(_fmt(agg[v]["judge_pass_rate"]) for v in variants)),
        ("latency_ms_median", *(str(agg[v]["latency_ms_median"]) for v in variants)),
    ]
    out = []
    for row in rows:
        out.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(out)


def render_failures(agg: dict) -> str:
    lines = ["\nFailed cases:"]
    for v, info in agg.items():
        failed = info["failed"] or "(none)"
        lines.append(f"  {v}: {failed}")
    return "\n".join(lines)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="tests/cases/golden.yaml")
    parser.add_argument(
        "--variants", default="basic,selfrag,reflection",
        help="comma-separated variant names",
    )
    parser.add_argument("--case-id", default=None, help="comma-separated case ids subset")
    parser.add_argument("--output", default=None, help="write to file instead of stdout")
    parser.add_argument("--format", choices=["table", "json"], default="table")
    parser.add_argument("--quick", action="store_true", help="only run first 3 cases")
    args = parser.parse_args()

    case_set = GoldenCaseSet.load(Path(args.cases))
    cases = case_set.cases
    if args.case_id:
        ids = set(args.case_id.split(","))
        cases = [c for c in cases if c.id in ids]
    if args.quick:
        cases = cases[:3]

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]

    print(f"Cases: {len(cases)} | Variants: {', '.join(variants)}")
    services = get_runtime_services()
    runner = EvalRunner(services)
    results = await runner.run(cases=cases, variants=variants)
    agg = runner.aggregate(results)

    if args.format == "json":
        payload = {
            "results": [r.model_dump() for r in results],
            "aggregate": agg,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
    else:
        text = render_table(agg) + "\n" + render_failures(agg)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"\nwrote {args.output}")
    else:
        print("\n" + text)


if __name__ == "__main__":
    asyncio.run(main())
