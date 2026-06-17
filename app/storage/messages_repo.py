from __future__ import annotations

import logging
from typing import Any

from app.storage.supabase_client import SupabaseRestClient

logger = logging.getLogger(__name__)


class MessagesRepository:
    def __init__(self, client: SupabaseRestClient) -> None:
        self._client = client

    async def save_message(
        self,
        *,
        line_user_id: str,
        direction: str,
        message_text: str,
        skill_id: str | None = None,
        router_result: dict[str, Any] | None = None,
        rag_used: bool = False,
    ) -> None:
        await self._client.insert(
            "line_messages",
            {
                "line_user_id": line_user_id,
                "direction": direction,
                "message_text": message_text,
                "skill_id": skill_id,
                "router_result": router_result or {},
                "rag_used": rag_used,
            },
        )

    async def list_recent_messages(self, line_user_id: str, limit: int = 5) -> list[dict[str, Any]]:
        return await self._client.select(
            "line_messages",
            {
                "select": "direction,message_text,created_at",
                "line_user_id": f"eq.{line_user_id}",
                "order": "created_at.desc",
                "limit": str(limit),
            },
        )

    async def mark_pending_review(
        self,
        *,
        thread_id: str,
        line_user_id: str,
        status: str = "pending",
    ) -> None:
        """spec-21 §「`mark_pending_review`」：HITL interrupt 觸發時記錄一筆。

        寫入 `hitl_pending_reviews`（schema.sql 內 opt-in 表，沒套 schema 時
        Supabase 會回 404，這裡靜默忽略——讓 graph 主流程不受 schema 缺失影響）。
        """
        try:
            await self._client.upsert(
                "hitl_pending_reviews",
                [
                    {
                        "thread_id": thread_id,
                        "line_user_id": line_user_id,
                        "status": status,
                    }
                ],
                on_conflict="thread_id",
            )
        except Exception as exc:
            # opt-in 表不存在時不打斷主流程，但 production debug 需要看得到
            # 真正錯誤類型（schema 缺 vs 認證錯 vs 網路斷）
            logger.warning(
                "mark_pending_review failed thread=%s: %s(%s)",
                thread_id, type(exc).__name__, exc,
            )

    async def list_pending_reviews(self, limit: int = 50) -> list[dict[str, Any]]:
        try:
            return await self._client.select(
                "hitl_pending_reviews",
                {
                    "select": "thread_id,line_user_id,status,created_at",
                    "status": "eq.pending",
                    "order": "created_at.desc",
                    "limit": str(limit),
                },
            )
        except Exception as exc:
            logger.warning(
                "list_pending_reviews failed: %s(%s)", type(exc).__name__, exc
            )
            return []

    async def resolve_pending_review(
        self, *, thread_id: str, status: str
    ) -> None:
        """approve / revise / drop 之後更新狀態（spec-21 §HITL）。

        必須走 PATCH（update by filter）而非 upsert：upsert 預設行為是缺欄位
        就 INSERT，但 hitl_pending_reviews.line_user_id 是 NOT NULL，沒帶上會
        被 DB 拒絕。本方法假設 row 已由 mark_pending_review 建立。
        """
        try:
            await self._client.update(
                "hitl_pending_reviews",
                {"status": status},
                filters={"thread_id": f"eq.{thread_id}"},
            )
        except Exception as exc:
            logger.warning(
                "resolve_pending_review failed thread=%s status=%s: %s",
                thread_id, status, exc,
            )

    async def build_recent_history(self, line_user_id: str, limit: int = 5) -> str:
        rows = await self.list_recent_messages(line_user_id, limit=limit)
        if not rows:
            return "No recent conversation."

        lines: list[str] = []
        for row in reversed(rows):
            speaker = "user" if row["direction"] == "inbound" else "assistant"
            lines.append(f"{speaker}: {row['message_text']}")
        return "\n".join(lines)
