from __future__ import annotations

from pydantic import BaseModel, Field


class LineSource(BaseModel):
    type: str
    userId: str | None = None

    @property
    def user_id(self) -> str | None:
        return self.userId


class LineMessage(BaseModel):
    id: str | None = None
    type: str
    text: str | None = None


class LineEvent(BaseModel):
    type: str
    replyToken: str | None = None
    source: LineSource
    timestamp: int | None = None
    mode: str | None = None
    message: LineMessage | None = None

    @property
    def is_text_message(self) -> bool:
        return self.type == "message" and self.message is not None and self.message.type == "text"


class LineWebhookPayload(BaseModel):
    destination: str | None = None
    events: list[LineEvent] = Field(default_factory=list)
