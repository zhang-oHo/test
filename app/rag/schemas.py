from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class KnowledgeChunk(BaseModel):
    id: str
    title: str | None = None
    content: str
    category: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    vector_score: float = 0.0
    keyword_score: float = 0.0
    combined_score: float = 0.0


class RetrievalRequest(BaseModel):
    query: str
    categories: list[str] = Field(default_factory=list)
    top_k: int = 8


class RetrievalLogRecord(BaseModel):
    line_user_id: str | None = None
    query: str
    skill_id: str | None = None
    category_filter: list[str] = Field(default_factory=list)
    retrieved_ids: list[str] = Field(default_factory=list)
    scores: dict[str, Any] = Field(default_factory=dict)
