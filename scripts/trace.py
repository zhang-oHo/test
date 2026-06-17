"""Trace CLI — 檢視 / 聚合 .traces/ 目錄內的 graph trace JSON。

用法：
    python scripts/trace.py show <thread_id>
    python scripts/trace.py summary --last 50
    python scripts/trace.py top --by duration --limit 5
    python scripts/trace.py top --by cost --limit 5
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def _load_traces(trace_dir: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in trace_dir.glob("*.json")]


def cmd_show(thread_id: str, trace_dir: Path):
    # 與 TracerRegistry.write_trace 的 sanitize 規則一致
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in thread_id)
    p = trace_dir / f"{safe}.json"
    if not p.exists():
        print(f"no trace for {thread_id} (looked for {p})")
        return
    data = json.loads(p.read_text(encoding="utf-8"))
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_summary(last: int, trace_dir: Path):
    traces = sorted(
        _load_traces(trace_dir), key=lambda t: t["started_at"], reverse=True
    )[:last]
    if not traces:
        print("no traces found")
        return

    by_variant: dict[str, list[dict]] = {}
    for t in traces:
        by_variant.setdefault(t["variant"], []).append(t)

    print(f"{'variant':12} | {'n':>3} | {'p50_ms':>7} | {'p95_ms':>7} | {'avg_cost':>10}")
    print("-" * 56)
    for variant, ts in by_variant.items():
        durations = sorted(t["total_duration_ms"] for t in ts)
        n = len(durations)
        p50 = durations[n // 2]
        p95 = durations[min(int(n * 0.95), n - 1)]
        avg_cost = sum(t["total_cost_usd"] for t in ts) / n
        print(
            f"{variant:12} | {n:>3} | {p50:>7} | {p95:>7} | ${avg_cost:>8.4f}"
        )


def cmd_top(by: str, limit: int, trace_dir: Path):
    traces = _load_traces(trace_dir)
    if not traces:
        print("no traces found")
        return
    key = "total_duration_ms" if by == "duration" else "total_cost_usd"
    top = sorted(traces, key=lambda t: t[key], reverse=True)[:limit]
    print(f"{'thread_id':50} | {'variant':12} | {key}")
    print("-" * 80)
    for t in top:
        print(f"{t['thread_id']:50} | {t['variant']:12} | {t[key]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-dir", default=".traces")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("show")
    p.add_argument("thread_id")

    p = sub.add_parser("summary")
    p.add_argument("--last", type=int, default=50)

    p = sub.add_parser("top")
    p.add_argument("--by", choices=["duration", "cost"], default="duration")
    p.add_argument("--limit", type=int, default=5)

    args = parser.parse_args()
    trace_dir = Path(args.trace_dir)

    if args.cmd == "show":
        cmd_show(args.thread_id, trace_dir)
    elif args.cmd == "summary":
        cmd_summary(args.last, trace_dir)
    elif args.cmd == "top":
        cmd_top(args.by, args.limit, trace_dir)


if __name__ == "__main__":
    main()
