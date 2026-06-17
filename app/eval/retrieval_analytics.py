"""Pure-function retrieval_logs 分析 — 對應 spec-09 §「分析功能」。

把純資料聚合邏輯與 CLI / Supabase 分開，方便單測。CLI 端
（scripts/analyze_retrieval.py）負責 IO，本模組只接 list[dict] 並回統計結果。

retrieved_ids = [] 視為「找不到資料」；scores 結構為 {chunk_id: {vector, keyword,
combined}} —— 但歷史版本可能只記了 combined，所以取分數時做 best-effort。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any


def cutoff_iso(days: int) -> str:
    """spec-09：用於 PostgREST `created_at=gte.{iso}` 過濾。"""
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _max_combined(scores: dict[str, Any]) -> float | None:
    """從 scores dict 抽 max combined_score；0 視為「沒有實際命中」並排除。

    `scores` 形如 `{chunk_id: {"combined": 0.7, ...}}`（新版）或 `{chunk_id: 0.7}`
    （舊版 flat 格式）。回 None 代表本筆 row 沒有可用分數——下游 aggregate_low_score
    會跳過、aggregate_category_stats 不會把 0 拉低平均分。
    """
    if not scores:
        return None
    out: list[float] = []
    for v in scores.values():
        if isinstance(v, dict):
            c = v.get("combined")
            if isinstance(c, (int, float)) and c > 0:
                out.append(float(c))
        elif isinstance(v, (int, float)) and v > 0:
            out.append(float(v))
    return max(out) if out else None


def aggregate_empty_hits(rows: list[dict]) -> list[dict]:
    """spec-09 §「1. 找出找不到資料的 query」：retrieved_ids=[] → group by query desc。"""
    counter: Counter[str] = Counter()
    for row in rows:
        if not row.get("retrieved_ids"):
            q = (row.get("query") or "").strip()
            if q:
                counter[q] += 1
    return [
        {"query": q, "count": n}
        for q, n in counter.most_common()
    ]


def aggregate_low_score(rows: list[dict], threshold: float) -> list[dict]:
    """spec-09 §「2. 低分檢索」：有命中但 max(combined_score) < threshold，升序。

    完全 0 命中的 query 由 `aggregate_empty_hits` 負責；本函式只看「有 chunk
    被回傳但分數普遍偏低」的情境（典型 retrieval 品質問題：query 與知識庫
    語意相關但匹配不佳）。
    """
    out: list[tuple[float, dict]] = []
    for row in rows:
        if not row.get("retrieved_ids"):
            continue  # 由 aggregate_empty_hits 覆蓋
        max_score = _max_combined(row.get("scores") or {})
        if max_score is None or max_score >= threshold:
            continue
        out.append(
            (
                max_score,
                {
                    "query": row.get("query"),
                    "max_combined": round(max_score, 4),
                    "category_filter": row.get("category_filter") or [],
                    "created_at": row.get("created_at"),
                },
            )
        )
    out.sort(key=lambda x: x[0])  # 升序
    return [entry for _, entry in out]


def aggregate_category_stats(rows: list[dict]) -> list[dict]:
    """spec-09 §「3. 按 category 分布」：unnest(category_filter) → count + avg score。

    avg_score 取每 row 的 max_combined（沒有就跳過），確保有命中才算進平均。
    """
    count: Counter[str] = Counter()
    score_sum: defaultdict[str, float] = defaultdict(float)
    score_n: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        cats = row.get("category_filter") or []
        if not cats:
            count["(no filter)"] += 1
            ms = _max_combined(row.get("scores") or {})
            if ms is not None:
                score_sum["(no filter)"] += ms
                score_n["(no filter)"] += 1
            continue
        ms = _max_combined(row.get("scores") or {})
        for c in cats:
            count[c] += 1
            if ms is not None:
                score_sum[c] += ms
                score_n[c] += 1
    out = []
    for cat, n in count.most_common():
        avg = (
            round(score_sum[cat] / score_n[cat], 4)
            if score_n[cat] > 0
            else None
        )
        out.append({"category": cat, "count": n, "avg_max_score": avg})
    return out


def filter_query_records(rows: list[dict], query_text: str) -> list[dict]:
    """spec-09 §「4. 特定 query 的詳細記錄」：模糊比對 query 欄位。

    保留所有對應 row，依 created_at 倒序，回傳精簡 shape 給 CLI 印 table。
    """
    needle = query_text.strip().lower()
    if not needle:
        return []
    matched = [
        row for row in rows
        if needle in (row.get("query") or "").lower()
    ]
    matched.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return [
        {
            "created_at": r.get("created_at"),
            "query": r.get("query"),
            "skill_id": r.get("skill_id"),
            "retrieved_ids": r.get("retrieved_ids") or [],
            "max_combined": _max_combined(r.get("scores") or {}),
        }
        for r in matched
    ]


def render_table(rows: list[dict], headers: list[str]) -> str:
    """純文字 table — 等寬對齊；避免引入 tabulate 額外依賴。"""
    if not rows:
        return "（無記錄）"
    widths = {h: max(len(h), 1) for h in headers}
    str_rows: list[list[str]] = []
    for r in rows:
        cells = [_cell(r.get(h)) for h in headers]
        for i, h in enumerate(headers):
            widths[h] = max(widths[h], len(cells[i]))
        str_rows.append(cells)
    fmt = "  ".join(f"{{:<{widths[h]}}}" for h in headers)
    out = [fmt.format(*headers), fmt.format(*("-" * widths[h] for h in headers))]
    for cells in str_rows:
        out.append(fmt.format(*cells))
    return "\n".join(out)


def _cell(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, list):
        return ",".join(str(x) for x in v) if v else "-"
    return str(v)
