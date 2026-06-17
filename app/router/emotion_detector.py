from __future__ import annotations

from app.router.schemas import EmotionState


ANXIOUS_KEYWORDS = ("焦慮", "擔心", "害怕", "可怕", "恐懼", "沒人用", "緊張", "壓力", "panic")
FRUSTRATED_KEYWORDS = ("卡住", "煩", "崩潰", "受不了", "失敗", "挫折", "怒")
CONFUSED_KEYWORDS = ("不懂", "看不懂", "為什麼", "怎麼會", "confused")
URGENT_KEYWORDS = ("立即", "馬上", "緊急", "urgent", "asap")
REFLECTIVE_KEYWORDS = ("意義", "價值", "我在想", "反思", "存在")


def detect_emotion(text: str) -> EmotionState:
    lowered = text.lower()
    if any(keyword in text for keyword in ANXIOUS_KEYWORDS):
        return "anxious"
    if any(keyword in text for keyword in FRUSTRATED_KEYWORDS):
        return "frustrated"
    if any(keyword in text for keyword in CONFUSED_KEYWORDS) or "?" in text:
        return "confused"
    if any(keyword in text for keyword in URGENT_KEYWORDS):
        return "urgent"
    if any(keyword in text for keyword in REFLECTIVE_KEYWORDS):
        return "reflective"
    if any(token in lowered for token in ("想知道", "curious", "curiosity")):
        return "curious"
    return "neutral"
