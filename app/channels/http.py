"""HTTP channel adapter — 給 web UI / API / 學生 demo。

對應 spec-23 / task-23 步驟 4。

設計：
- HTTP 是 request-response，不切段、不外推
- `push` 是 no-op（response 由 endpoint 直接從 final_state 取）
- recent_history 為簡化教學版預設空字串（學生若要 cross-session 對話可改用 messages_repo）
"""

from __future__ import annotations

from typing import Any

from app.channels.base import ChannelInput


class HttpChannel:
    name = "http"

    def __init__(self, messages_repo: Any | None = None) -> None:
        self._messages_repo = messages_repo

    def build_thread_id(self, inp: ChannelInput) -> str:
        return f"http-{inp.external_user_id}-{inp.external_message_id}"

    async def load_recent_history(
        self, *, external_user_id: str, limit: int = 5
    ) -> str:
        # 預設無歷史（無狀態 API）。學生若要保留歷史可改：
        # return await self._messages_repo.build_recent_history(external_user_id, limit)
        return "No recent conversation."

    def format(self, markdown: str) -> list[str]:
        # web 不切段；保留完整 markdown
        return [markdown]

    async def push(self, *, recipient_id: str, messages: list[str]) -> None:
        # HTTP 同步回應 — endpoint 直接從 final_state 取 responses，這裡 no-op
        return
