from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from app.router.categories import VALID_RAG_CATEGORIES
from app.router.emotion_detector import detect_emotion
from app.router.prompts import render_router_prompt
from app.router.schemas import EmotionState, ResponseMode, RouterResult, SkillId


GAME_KEYWORDS = ("空洞騎士", "小騎士", "護符", "Boss", "敵人", "NPC", "骨釘", "地圖")
TECH_KEYWORDS = ("supabase", "fastapi", "rag", "api", "schema", "webhook", "deploy", "pgvector")
DATA_KEYWORDS = ("ab test", "metric", "實驗", "資料", "模型", "預測", "特徵")
BUSINESS_KEYWORDS = ("商業", "定價", "市場", "產品定位", "營收", "growth", "gtm")
PHILOSOPHY_KEYWORDS = ("價值", "存在", "自由意志", "倫理", "辯證", "意義")
KNOWLEDGE_KEYWORDS = ("筆記", "adr", "spec", "規格", "知識庫", "project", "專案脈絡")


class RouterLLM(Protocol):
    async def complete(self, prompt: str) -> str:
        ...


@dataclass
class IntentRouter:
    llm: RouterLLM | None = None
    confidence_threshold: float = 0.55

    async def route_message(self, user_input: str, recent_history: str) -> RouterResult:
        emotion = detect_emotion(user_input)
        if self.llm is None:
            return self._heuristic_route(user_input, emotion)

        try:
            prompt = render_router_prompt(user_input, recent_history)
            raw_output = await self.llm.complete(prompt)
            parsed = self._parse_router_output(raw_output)
            result = RouterResult.model_validate(parsed)
            return self._normalize_result(result, user_input, emotion)
        except Exception:
            return self._heuristic_route(user_input, emotion)

    def _normalize_result(
        self,
        result: RouterResult,
        user_input: str,
        fallback_emotion: EmotionState,
    ) -> RouterResult:
        normalized = result.model_copy(
            update={
                "rag_query": result.rag_query.strip() or user_input.strip(),
                "emotion_state": result.emotion_state or fallback_emotion,
                "rag_categories": [
                    c for c in result.rag_categories if c in VALID_RAG_CATEGORIES
                ],
            }
        )
        if normalized.confidence < self.confidence_threshold:
            return self._heuristic_route(user_input, fallback_emotion)
        return normalized

    def _parse_router_output(self, raw_output: str) -> dict[str, object]:
        stripped = raw_output.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start == -1 or end == -1:
                raise
            return json.loads(stripped[start : end + 1])

    def _heuristic_route(self, user_input: str, emotion: EmotionState) -> RouterResult:
        lowered = user_input.lower()

        if any(keyword in user_input for keyword in GAME_KEYWORDS):
            return RouterResult.fallback(
                user_input,
                target_skill="hollow_knight_guide",
                emotion_state=emotion,
                response_mode="structured",
                is_rag_required=True,
                onfidence=0.9,
            )

        if any(keyword in lowered for keyword in TECH_KEYWORDS):
            return RouterResult.fallback(
                user_input,
                target_skill="hollow_knight_guide",
                emotion_state=emotion,
                response_mode="structured",
                is_rag_required=True, # 強制開啟 RAG，這樣它才會去查你的 data/knight/ 資料夾
                rag_categories=None,
                confidence=0.9, # 提高信心分數，避免被一般聊天覆蓋
            )
        if any(keyword in lowered for keyword in DATA_KEYWORDS):
            return RouterResult.fallback(
                user_input,
                target_skill="data_scientist",
                emotion_state=emotion,
                response_mode="structured",
                is_rag_required=any(keyword in lowered for keyword in KNOWLEDGE_KEYWORDS),
                rag_categories=["analytics", "experiments", "metrics"],
                confidence=0.65,
            )
        if any(keyword in lowered for keyword in BUSINESS_KEYWORDS):
            return RouterResult.fallback(
                user_input,
                target_skill="business_strategist",
                emotion_state=emotion,
                response_mode="decision_support",
                is_rag_required=any(keyword in lowered for keyword in KNOWLEDGE_KEYWORDS),
                rag_categories=["strategy", "market", "product"],
                confidence=0.65,
            )
        if emotion in {"anxious", "frustrated"}:
            return RouterResult.fallback(
                user_input,
                target_skill="emotional_calibration",
                emotion_state=emotion,
                response_mode="reflection",
                is_rag_required=False,
                confidence=0.7,
            )
        if any(keyword in user_input for keyword in PHILOSOPHY_KEYWORDS):
            return RouterResult.fallback(
                user_input,
                target_skill="philosophical_dialectic",
                emotion_state=emotion,
                response_mode="reflection",
                is_rag_required=any(keyword in lowered for keyword in KNOWLEDGE_KEYWORDS),
                rag_categories=["philosophy", "notes"],
                confidence=0.6,
            )
        return RouterResult.fallback(
            user_input,
            target_skill="general_chat",
            emotion_state=emotion,
            response_mode="brief",
            confidence=0.5,
        )
