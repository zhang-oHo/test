"""Supabase graph_traces 落庫（opt-in）— 對應 spec-22 §「介面契約」。

`OBSERVABILITY_PERSIST=true` 時 TracerRegistry 在寫完本機 .traces/*.json 後
透過本 repo 同步寫一份到 Supabase；schema 在 supabase/observability_schema.sql。

未套用 schema（404）或網路失敗時不打斷主流程，只記 log。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.storage.supabase_client import SupabaseRestClient

logger = logging.getLogger("observability")


def _iso(ts: float | None) -> str:
    return datetime.fromtimestamp(ts or 0, tz=timezone.utc).isoformat()


class TracesRepository:
    def __init__(self, client: SupabaseRestClient) -> None:
        self._client = client

    async def insert(self, trace: dict[str, Any]) -> None:
        """寫一筆 trace（GraphTracer.finalize() 的輸出）。

        失敗（schema 未套用 / 網路斷）由 caller 統一處理；本層不 swallow，
        避免「TracerRegistry log 一次、repo 又 log 一次」的重複噪音。
        """
        row = {
            "thread_id": trace["thread_id"],
            "variant": trace["variant"],
            "started_at": _iso(trace.get("started_at")),
            "finished_at": _iso(trace.get("finished_at")),
            "total_duration_ms": trace.get("total_duration_ms", 0),
            "total_input_tokens": trace.get("total_input_tokens", 0),
            "total_output_tokens": trace.get("total_output_tokens", 0),
            "total_cost_usd": trace.get("total_cost_usd", 0),
            "payload": trace,
        }
        await self._client.insert("graph_traces", row)

    async def recent(
        self, *, variant: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """讀近 N 筆 trace。失敗由 caller 處理（不 swallow）。"""
        params: dict[str, str] = {
            "select": "thread_id,variant,started_at,total_duration_ms,total_cost_usd",
            "order": "started_at.desc",
            "limit": str(limit),
        }
        if variant:
            params["variant"] = f"eq.{variant}"
        return await self._client.select("graph_traces", params)
