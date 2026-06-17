"""Clarifier — 資料不足時生成具體追問，讓使用者補齊資訊。

對應 spec-15 / task-15。LLM 生成「具體、可一句話回答」的問題；失敗時降級到預設追問。
回覆組合（將追問列點 + 收尾語）由程式組——**不交給 LLM**——避免 LLM 自行補充未授權內容。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Protocol

from app.graph.feature_extractor import ExtractedFeatures
from app.rag.schemas import KnowledgeChunk

logger = logging.getLogger(__name__)


_PROMPT = """使用者問了：{user_input}

我們找到的相關資料不足以給出可信回覆。已知 features：{features}

找到的（不足）資料摘要：
{chunks_summary}

請生成 2~3 個「具體、可一句話回答」的追問，幫助補齊資訊。要求：
- 每個追問 ≤ 30 字
- 不問空泛的「能再多說明嗎」
- 針對 features 中未明確的點

只輸出 JSON：{{"questions": ["q1", "q2", ...]}}，不要 markdown fence、不要解釋。"""


_FALLBACK_QUESTIONS = [
    "方便提供更多細節嗎？例如使用的版本或場景。",
    "你期望的結果或下一步是什麼？",
]


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


class Clarifier(Protocol):
    async def generate_questions(
        self,
        *,
        user_input: str,
        features: ExtractedFeatures,
        chunks: list[KnowledgeChunk],
    ) -> list[str]: ...


class LLMClarifier:
    def __init__(self, llm) -> None:
        self._llm = llm

    async def generate_questions(
        self,
        *,
        user_input: str,
        features: ExtractedFeatures,
        chunks: list[KnowledgeChunk],
    ) -> list[str]:
        if self._llm is None:
            return list(_FALLBACK_QUESTIONS)

        chunks_summary = "\n".join(
            f"- {c.content[:80]}..." for c in chunks[:3]
        ) or "（無）"

        prompt = _PROMPT.format(
            user_input=user_input,
            features=features.model_dump_json(),
            chunks_summary=chunks_summary,
        )
        try:
            raw = await self._llm.complete(prompt)
            data = json.loads(_strip_fence(raw))
            questions = data.get("questions", [])
            cleaned = [q.strip() for q in questions if isinstance(q, str) and q.strip()]
            return cleaned[:3] if cleaned else list(_FALLBACK_QUESTIONS)
        except Exception:
            logger.warning("clarifier failed, using fallback questions", exc_info=True)
            return list(_FALLBACK_QUESTIONS)


def format_clarification(questions: list[str]) -> str:
    """程式組（不交給 LLM）。"""
    if not questions:
        questions = list(_FALLBACK_QUESTIONS)
    body = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
    return f"我需要再確認幾件事：\n{body}\n\n回覆後我再幫你分析。"
