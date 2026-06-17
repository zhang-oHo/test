"""LLM-as-Judge: 4 軸結構化評分器。

對應 spec-17 / task-17。

借鑑 project-destiny `src/destiny/judge.py`（Layer D, ADR-008）。本實作把 4 軸通用化、
加上 LangGraph 迴圈控制（spec 的 route_after_judge 在 nodes.py）。

設計重點：
1. 4 軸而非單一分數 — 學生看到「為什麼」分數低
2. LLM 失敗 → 回 None（視為 pass，graceful degrade，不阻塞輸出）
3. 嚴格 JSON 輸出契約 — 解析失敗也降級為 None
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from app.generator.contract import AnswerContract

logger = logging.getLogger(__name__)


class JudgeScore(BaseModel):
    groundedness: int = Field(..., ge=0, le=10)
    citation_fidelity: int = Field(..., ge=0, le=10)
    format_completeness: int = Field(..., ge=0, le=10)
    uncertainty_honesty: int = Field(..., ge=0, le=10)
    issues: list[str] = Field(default_factory=list)

    @property
    def mean(self) -> float:
        return (
            self.groundedness
            + self.citation_fidelity
            + self.format_completeness
            + self.uncertainty_honesty
        ) / 4

    def passes(self, *, min_axis: int = 6, min_mean: float = 7.0) -> bool:
        worst = min(
            self.groundedness,
            self.citation_fidelity,
            self.format_completeness,
            self.uncertainty_honesty,
        )
        return worst >= min_axis and self.mean >= min_mean


_PROMPT = """你是嚴格的 RAG 輸出審查員。
你會收到 (a) 助理產出的回覆 markdown；(b) 該次的 Answer Contract（含 citations）。

依以下 4 軸打分（0~10）：
- groundedness: 結論是否都有 contract 中的依據
- citation_fidelity: 引用文字是否與 contract.citations[].snippet 逐字相符
- format_completeness: 是否符合 response_mode={response_mode} 的格式要求
- uncertainty_honesty: caveats 是否完整呈現

輸出嚴格 JSON（無 markdown fence、無前後文、不要解釋）：
{{
  "groundedness": 0,
  "citation_fidelity": 0,
  "format_completeness": 0,
  "uncertainty_honesty": 0,
  "issues": ["最多 5 條具體問題"]
}}

回覆 markdown：
{narrative}

Answer Contract：
{contract_json}
"""


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _strip_fence(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


class JudgeLLM(Protocol):
    async def complete(self, prompt: str) -> str: ...


@dataclass
class GroundednessJudge:
    llm: JudgeLLM | None = None

    async def judge(
        self,
        *,
        narrative: str,
        contract: AnswerContract,
        response_mode: str,
    ) -> JudgeScore | None:
        if self.llm is None:
            return None

        prompt = _PROMPT.format(
            response_mode=response_mode,
            narrative=narrative,
            contract_json=contract.model_dump_json(indent=2),
        )
        try:
            raw = await self.llm.complete(prompt)
            data = json.loads(_strip_fence(raw))
            issues = data.get("issues") or []
            if isinstance(issues, list):
                issues = [str(i) for i in issues if i][:5]
            return JudgeScore(
                groundedness=int(data["groundedness"]),
                citation_fidelity=int(data["citation_fidelity"]),
                format_completeness=int(data["format_completeness"]),
                uncertainty_honesty=int(data["uncertainty_honesty"]),
                issues=issues,
            )
        except Exception:
            logger.warning("judge call failed; degrading to pass", exc_info=True)
            return None
