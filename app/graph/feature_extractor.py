"""Feature Extractor — 把使用者輸入結構化抽取為 features。

對應 spec-13 / task-13。Spec-14（multi-seed）會把 features 展開為多條 retrieval seed。

預設提供 LLM-based 實作；介面留 Protocol，學生轉題目時可換 rule-based。
LLM 失敗 / 未配置時，回傳保守 fallback（用原句作為 primary_topic）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal, Protocol

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ExtractedFeatures(BaseModel):
    primary_topic: str = Field(..., description="問題核心主題")
    qualifiers: list[str] = Field(default_factory=list, description="限定條件，最多 5")
    intent: Literal["how_to", "debug", "concept", "compare", "decide", "other"] = "other"
    entities: list[str] = Field(default_factory=list, description="命名實體，最多 8")
    raw_query: str


class FeatureExtractor(Protocol):
    async def extract(
        self,
        *,
        user_input: str,
        recent_history: str | None = None,
    ) -> ExtractedFeatures: ...


_PROMPT = """你是查詢結構化抽取器。讀取使用者問題，輸出 JSON。

欄位定義：
- primary_topic: 問題的核心主題（一個短語）
- qualifiers: 限定條件（版本、場景、限制等），最多 5 條
- intent: 從 [how_to, debug, concept, compare, decide, other] 擇一
- entities: 明確命名的實體（套件、產品、人名...），最多 8 條

使用者輸入：{user_input}
最近對話（可選）：{recent_history}

只輸出 JSON，不要 markdown fence、不要解釋。"""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def _fallback(user_input: str) -> ExtractedFeatures:
    # 預設核心主題為原句
    primary = user_input[:120]
    entities = []

    # 【畢業專題硬核保底】定義知識庫中常見的空洞騎士護符關鍵字
    common_charms = ["舞夢者", "巴德爾之殼", "無憂旋律", "衝刺大師", "薩滿之石", "國王之魂"]
    
    # 如果使用者的輸入內含有這些關鍵字，直接精準提取
    for charm in common_charms:
        if charm in user_input:
            primary = charm       # 讓 RAG 檢索節點拿「舞夢者」去精準搜尋檔案
            entities.append(charm)
            break                 # 抓到第一個主要護符就跳出

    return ExtractedFeatures(
        primary_topic=primary,
        qualifiers=[],
        intent="other",
        entities=entities,
        raw_query=user_input,
    )


class LLMFeatureExtractor:
    def __init__(self, llm, *, name: str = "llm-feature-extractor") -> None:
        self._llm = llm
        self._name = name

    async def extract(
        self,
        *,
        user_input: str,
        recent_history: str | None = None,
    ) -> ExtractedFeatures:
        if self._llm is None:
            return _fallback(user_input)

        prompt = _PROMPT.format(
            user_input=user_input,
            recent_history=recent_history or "（無）",
        )
        try:
            raw = await self._llm.complete(prompt)
            
            # 【關鍵防禦 1】：如果 API 爆了丟回空字串，或回傳的不是 JSON，直接主動走 fallback
            if not raw or not raw.strip() or "Too Many Requests" in raw:
                return _fallback(user_input)
                
            data = json.loads(_strip_fence(raw))
            data.setdefault("raw_query", user_input)
            # 限制長度避免 prompt 注入
            if isinstance(data.get("qualifiers"), list):
                data["qualifiers"] = data["qualifiers"][:5]
            if isinstance(data.get("entities"), list):
                data["entities"] = data["entities"][:8]
            return ExtractedFeatures(**data)
        except Exception:
            logger.warning("feature extraction failed, falling back to raw query", exc_info=True)
            return _fallback(user_input)
