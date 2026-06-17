"""LINE channel adapter。

對應 spec-23 / task-23 步驟 3。封裝 webhook 解析、推送、歷史對話、訊息切段。
"""
from __future__ import annotations

from starlette.requests import ClientDisconnect, Request
import logging
import asyncio  # 引入 asyncio 用於定時清理
from typing import Any

from fastapi import HTTPException, Request

from app.channels.base import ChannelInput
from app.config import Settings
from app.generator.formatter import split_for_line
from app.line.client import LineMessagingClient
from app.line.schemas import LineWebhookPayload

logger = logging.getLogger(__name__)

class LineChannel:
    name = "line"

    def __init__(self, settings: Settings, messages_repo: Any) -> None:
        self._settings = settings
        self._messages_repo = messages_repo
        self._client = LineMessagingClient(settings)
        # 【新增】用於存放已處理過的 LINE webhookEventId，防止重複請求連擊
        self._processed_event_ids: set[str] = set()

    @property
    def client(self) -> LineMessagingClient:
        """暴露 client 給 webhook 簽章驗證用。"""
        return self._client

    def validate_signature(self, body: bytes, signature: str | None) -> bool:
        return self._client.validate_signature(body, signature)

    async def _gc_event_id(self, event_id: str, delay: float = 60.0) -> None:
        """【新增】非同步背景任務，在指定秒數（預設 60 秒）後自動清除快取的 event_id。"""
        await asyncio.sleep(delay)
        self._processed_event_ids.discard(event_id)
        logger.debug(f"Event ID {event_id} has been cleared from deduplication cache.")

    async def parse_request(self, request: Request) -> tuple[bytes, list[ChannelInput]]:
        try:
            body = await request.body()
        except ClientDisconnect:
            logger.warning("Line client disconnected during request body reading.")
            return b"", []  # 回傳空值，結束此次處理，不拋出錯誤
        
        sig = request.headers.get("x-line-signature")
        if not self._client.validate_signature(body, sig):
            raise HTTPException(status_code=400, detail="Invalid LINE signature")

        payload = LineWebhookPayload.model_validate_json(body)
        out: list[ChannelInput] = []
        
        for ev in payload.events:
            # 【新增防重發邏輯】
            # LINE 的每個 event 都有唯一的 event_id (通常在 ev.id 或 ev.webhook_event_id，請依據你們 schemas 的欄位調整)
            # 這裡假設欄位名稱為 ev.id 或 ev.webhook_event_id。若執行噴錯，請檢查 LineWebhookPayload 內 event 的識別字欄位。
            event_id = getattr(ev, "webhook_event_id", None) or getattr(ev, "id", None)
            
            if event_id:
                if event_id in self._processed_event_ids:
                    logger.warning(f"偵測到重複的 LINE Webhook 事件 (Event ID: {event_id})，已成功攔截。")
                    continue  # 跳過這個事件，不重複加入 out，這樣後續的 Graph 就不會被觸發
                
                # 沒看過這個事件，加入快取並安排 60 秒後自動刪除
                self._processed_event_ids.add(event_id)
                asyncio.create_task(self._gc_event_id(event_id, delay=60.0))

            # 原本的文字訊息過濾邏輯
            if ev.is_text_message and ev.source.user_id and ev.message and ev.message.text:
                out.append(
                    ChannelInput(
                        channel="line",
                        external_user_id=ev.source.user_id,
                        external_message_id=ev.message.id,
                        raw_text=ev.message.text,
                    )
                )
        return body, out

    def build_thread_id(self, inp: ChannelInput) -> str:
        return f"line-{inp.external_user_id}-{inp.external_message_id}"

    async def load_recent_history(
        self, *, external_user_id: str, limit: int = 5
    ) -> str:
        try:
            return await self._messages_repo.build_recent_history(
                external_user_id, limit=limit
            )
        except Exception:
            return "No recent conversation."

    def format(self, markdown: str) -> list[str]:
        return split_for_line(markdown, max_chars=self._settings.line_max_message_chars)

    async def push(self, *, recipient_id: str, messages: list[str]) -> None:
        await self._client.push_text(recipient_id, messages)