"""分析本機 .traces/*.json — latency / cost / per-node / per-variant 統計。

對應 docs/Lesson_5_Production/ch09 §Step 10。

跟 scripts/analyze_retrieval.py 互補：那個分析「真實流量的 retrieval_logs」，
本 script 分析「每次 graph invocation 的完整事件流」。

用法：
    python scripts/analyze_traces.py
    python scripts/analyze_traces.py --dir .traces --variant reflection
    python scripts/analyze_traces.py --top-nodes 10
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def _load_traces(trace_dir: Path) -> list[dict]:
    out = []
    for p in sorted(trace_dir.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as e:
            print(f"!! skip {p.name}: {e}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--dir", default=".traces", help="trace 檔目錄")
    p.add_argument("--variant", default=None, help="只看特定 variant（basic/selfrag/reflection）")
    p.add_argument("--top-nodes", type=int, default=15, help="列前 N 個最耗時 node")
    args = p.parse_args()

    trace_dir = Path(args.dir)
    if not trace_dir.exists():
        print(f"trace dir not found: {trace_dir.resolve()}")
        return

    traces = _load_traces(trace_dir)
    if args.variant:
        traces = [t for t in traces if t.get("variant") == args.variant]

    if not traces:
        print("no traces matched")
        return

    # ── 全域統計 ──
    total_cost = sum(t.get("total_cost_usd") or 0 for t in traces)
    total_in = sum(t.get("total_input_tokens") or 0 for t in traces)
    total_out = sum(t.get("total_output_tokens") or 0 for t in traces)
    total_dur = [t.get("total_duration_ms") or 0 for t in traces]
    total_dur.sort()
    n = len(traces)

    print(f"\n=== Aggregate ({n} traces"
          + (f", variant={args.variant}" if args.variant else "")
          + ") ===")
    print(f"  total cost USD     : ${total_cost:.4f}")
    print(f"  total tokens (in)  : {total_in:,}")
    print(f"  total tokens (out) : {total_out:,}")
    print(f"  avg cost / run     : ${total_cost / n:.6f}")
    print(f"  duration median ms : {total_dur[n // 2]}")
    print(f"  duration p95 ms    : {total_dur[min(int(n * 0.95), n - 1)]}")

    # ── 各 node 平均 duration ──
    node_durations: dict[str, list[int]] = defaultdict(list)
    for t in traces:
        for nt in t.get("node_timings") or []:
            node_durations[nt["node"]].append(nt["duration_ms"])

    if node_durations:
        print(f"\n=== Per-node avg duration (top {args.top_nodes}) ===")
        sorted_nodes = sorted(
            node_durations.items(),
            key=lambda x: sum(x[1]) / len(x[1]),
            reverse=True,
        )
        for node, ds in sorted_nodes[: args.top_nodes]:
            avg = sum(ds) / len(ds)
            mx = max(ds)
            print(f"  {node:<28} avg={avg:>7.0f}ms  max={mx:>7}ms  n={len(ds)}")

    # ── 各 variant cost / latency 比較 ──
    if not args.variant:
        v_cost = defaultdict(float)
        v_dur: dict[str, list[int]] = defaultdict(list)
        v_n = defaultdict(int)
        for t in traces:
            v = t.get("variant", "?")
            v_cost[v] += t.get("total_cost_usd") or 0
            v_dur[v].append(t.get("total_duration_ms") or 0)
            v_n[v] += 1

        print(f"\n=== Per-variant cost & duration ===")
        for v in sorted(v_n):
            n_v = v_n[v]
            ds = sorted(v_dur[v])
            med = ds[n_v // 2] if ds else 0
            print(
                f"  {v:<15} n={n_v:>4}  "
                f"cost ${v_cost[v]:.4f} (avg ${v_cost[v] / n_v:.6f}/run)  "
                f"duration_median={med}ms"
            )

    # ── LLM call 統計（model × node）──
    llm_calls: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in traces:
        for ev in t.get("events") or []:
            if ev.get("phase") != "llm_call":
                continue
            model = ev.get("model", "?")
            node = ev.get("node", "?")
            llm_calls[(model, node)].append(ev)

    if llm_calls:
        print(f"\n=== LLM calls breakdown (model × node) ===")
        rows = []
        for (model, node), evs in llm_calls.items():
            total_c = sum(e.get("estimated_cost_usd") or 0 for e in evs)
            avg_dur = sum(e.get("duration_ms") or 0 for e in evs) / len(evs)
            rows.append((total_c, model, node, len(evs), avg_dur))
        rows.sort(reverse=True)
        for total_c, model, node, n_calls, avg_dur in rows[: args.top_nodes]:
            print(f"  {model:<32} {node:<22} n={n_calls:>4} cost=${total_c:.4f} avg_dur={avg_dur:.0f}ms")


if __name__ == "__main__":
    main()
