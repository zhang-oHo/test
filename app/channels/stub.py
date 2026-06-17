"""Stub channel — 給測試 / eval / demo 用。對應 spec-23 / task-23 步驟 5。

push 寫進 list；其他方法回安全預設值。
"""

from __future__ import annotations

from app.channels.base import ChannelInput


class StubChannel:
    name = "stub"

    def __init__(self) -> None:
        self.pushed: list[tuple[str, list[str]]] = []

    def build_thread_id(self, inp: ChannelInput) -> str:
        return f"stub-{inp.external_user_id}-{inp.external_message_id}"

    async def load_recent_history(
        self, *, external_user_id: str, limit: int = 5
    ) -> str:
        return ""

    def format(self, markdown: str) -> list[str]:
        return [markdown]

    async def push(self, *, recipient_id: str, messages: list[str]) -> None:
        self.pushed.append((recipient_id, list(messages)))
