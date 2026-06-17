from __future__ import annotations

import base64
import hashlib
import hmac

import httpx

from app.config import Settings


class LineMessagingClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def validate_signature(self, body: bytes, signature: str | None) -> bool:
        if not signature or not self._settings.line_channel_secret:
            return False
        digest = hmac.new(
            self._settings.line_channel_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()
        expected = base64.b64encode(digest).decode("utf-8")
        return hmac.compare_digest(signature, expected)

    async def push_text(self, user_id: str, messages: list[str] | str) -> None:
        if isinstance(messages, str):
            messages = [messages]

        payload = {
            "to": user_id,
            "messages": [{"type": "text", "text": message} for message in messages[:5]],
        }
        headers = {
            "Authorization": f"Bearer {self._settings.line_channel_access_token}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{self._settings.line_api_base.rstrip('/')}/v2/bot/message/push",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
