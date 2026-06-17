"""Channel adapter Protocol + 共用 schema。對應 spec-23 / task-23 步驟 1。

每個 channel 負責：
1. 解析請求（webhook / HTTP body）→ ChannelInput
2. 提供 thread_id 命名（HITL / persistence 用）
3. 載入歷史對話（給 graph 的 recent_history）
4. 把最終 markdown 切段 / 格式化（LINE 5000 char、Slack mrkdwn、Web 完整）
5. 推送（push API / HTTP response / WebSocket）

Graph 不直接呼叫 LINE / HTTP；只透過 services.channels[name] 取對應 adapter。
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field


class ChannelInput(BaseModel):
    channel: str
    external_user_id: str
    external_message_id: str
    raw_text: str
    metadata: dict = Field(default_factory=dict)


class OutputChannel(Protocol):
    name: str

    def build_thread_id(self, inp: ChannelInput) -> str: ...

    async def load_recent_history(
        self, *, external_user_id: str, limit: int = 5
    ) -> str: ...

    def format(self, markdown: str) -> list[str]: ...

    async def push(self, *, recipient_id: str, messages: list[str]) -> None: ...
