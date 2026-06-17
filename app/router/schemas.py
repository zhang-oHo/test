from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


SkillId = Literal[
    "tech_architect",
    "data_scientist",
    "business_strategist",
    "philosophical_dialectic",
    "emotional_calibration",
    "general_chat",
    "hollow_knight_guide",
]
EmotionState = Literal[
    "neutral",
    "curious",
    "urgent",
    "confused",
    "frustrated",
    "anxious",
    "reflective",
]
ResponseMode = Literal[
    "brief",
    "structured",
    "step_by_step",
    "decision_support",
    "debugging",
    "reflection",
]


class RouterResult(BaseModel):
    target_skill: SkillId
    is_rag_required: bool
    rag_query: str
    rag_categories: list[str] = Field(default_factory=list)
    emotion_state: EmotionState
    response_mode: ResponseMode
    confidence: float = Field(ge=0.0, le=1.0)

    @classmethod
    def fallback(
        cls,
        user_input: str,
        *,
        target_skill: SkillId = "general_chat",
        emotion_state: EmotionState = "neutral",
        response_mode: ResponseMode = "brief",
        is_rag_required: bool = False,
        rag_categories: list[str] | None = None,
        confidence: float = 0.3,
    ) -> "RouterResult":
        return cls(
            target_skill=target_skill,
            is_rag_required=is_rag_required,
            rag_query=user_input.strip(),
            rag_categories=rag_categories or [],
            emotion_state=emotion_state,
            response_mode=response_mode,
            confidence=confidence,
        )
