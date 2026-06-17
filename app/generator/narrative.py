"""Stage 2 of two-stage generator: render Answer Contract to natural language.

對應 spec-16 / task-16。

「受限敘事」原則：LLM 只能用 Contract 中列出的事實，不得引入外部資訊。
LLM 失敗時，降級為純模板輸出（仍含完整 contract 內容）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.generator.contract import AnswerContract
from app.generator.formatter import split_for_line
from app.generator.prompts import _emotion_instruction, _mode_instruction
from app.skills.loader import SkillDefinition

logger = logging.getLogger(__name__)


_PROMPT = """你是 {skill_name} 的回覆撰寫者。依照以下 Answer Contract 寫成自然語言回覆。

嚴格規則（違反任一條視為品質不合格）：
1. 只能使用 Answer Contract 中列出的事實
2. 不得引入 Contract 外的資訊
3. 每個論點若 Contract 中有 citations，必須在敘述後標註「[來源 N]」（N 從 1 起）
4. caveats 必須完整呈現，不可省略

## Mode Instruction（spec-01，response_mode={response_mode}）

{mode_instruction}

## Emotion Instruction（spec-02，emotion_state={emotion_state}；優先於 Mode 的長度與選項數量）

{emotion_instruction}

Skill system prompt（語氣依據）：
{skill_system_prompt}

Answer Contract（JSON）：
{contract_json}

{feedback_section}輸出純 markdown，不要解釋你的決策。"""


class NarrativeLLM(Protocol):
    async def complete(self, prompt: str) -> str: ...


class StreamingNarrativeLLM(Protocol):
    """spec-31：可選串流介面。providers 不一定全實作。"""

    def stream_complete(self, prompt: str): ...


def _fallback_render(contract: AnswerContract) -> str:
    """LLM 失敗或未配置時的模板降級輸出。

    保留所有 contract 內容，明確標註「（降級輸出）」讓使用者知道。
    """
    parts = [f"**摘要**：{contract.summary}", ""]
    if contract.key_findings:
        parts.append("**重點**：")
        for i, kf in enumerate(contract.key_findings, 1):
            cites = (
                " [" + ", ".join(f"來源 {ci+1}" for ci, _ in enumerate(kf.citations)) + "]"
                if kf.citations
                else ""
            )
            parts.append(f"{i}. {kf.point}{cites}")
        parts.append("")
    if contract.caveats:
        parts.append("**注意事項**：")
        parts.extend(f"- {c}" for c in contract.caveats)
        parts.append("")
    if contract.next_steps:
        parts.append("**建議下一步**：")
        parts.extend(f"- {s}" for s in contract.next_steps)
        parts.append("")
    if contract.citations:
        parts.append("**來源**：")
        for i, cit in enumerate(contract.citations, 1):
            parts.append(f"{i}. {cit.source}")
        parts.append("")
    # parts.append("（降級輸出）")
    return "\n".join(parts).strip()


@dataclass
class NarrativeRenderer:
    llm: NarrativeLLM | None = None
    line_max_message_chars: int = 4500

    async def render(
        self,
        *,
        contract: AnswerContract,
        skill: SkillDefinition,
        response_mode: str,
        emotion_state: str = "neutral",
        feedback: list[str] | None = None,
    ) -> list[str]:
        text = await self._render_text(
            contract=contract,
            skill=skill,
            response_mode=response_mode,
            emotion_state=emotion_state,
            feedback=feedback,
        )
        return split_for_line(text, max_chars=self.line_max_message_chars)

    async def _render_text(
        self,
        *,
        contract: AnswerContract,
        skill: SkillDefinition,
        response_mode: str,
        emotion_state: str,
        feedback: list[str] | None,
    ) -> str:
        if self.llm is None:
            return _fallback_render(contract)

        prompt = self._build_prompt(
            contract=contract,
            skill=skill,
            response_mode=response_mode,
            emotion_state=emotion_state,
            feedback=feedback,
        )
        try:
            return await self.llm.complete(prompt)
        except Exception:
            logger.exception("narrative render failed, falling back to template")
            return _fallback_render(contract)

    def _build_prompt(
        self,
        *,
        contract: AnswerContract,
        skill: SkillDefinition,
        response_mode: str,
        emotion_state: str,
        feedback: list[str] | None,
    ) -> str:
        feedback_section = ""
        if feedback:
            feedback_section = (
                "（前一次的問題，請改善）\n"
                + "\n".join(f"- {f}" for f in feedback)
                + "\n\n"
            )
        return _PROMPT.format(
            skill_name=skill.name,
            skill_system_prompt=skill.system_prompt,
            response_mode=response_mode,
            emotion_state=emotion_state,
            mode_instruction=_mode_instruction(response_mode),
            emotion_instruction=_emotion_instruction(emotion_state),
            contract_json=contract.model_dump_json(indent=2),
            feedback_section=feedback_section,
        )

    async def stream_render(
        self,
        *,
        contract: AnswerContract,
        skill: SkillDefinition,
        response_mode: str,
        emotion_state: str = "neutral",
        feedback: list[str] | None = None,
    ):
        """spec-31：以 async generator 形式 yield 文字 chunk。

        前提：self.llm 必須有 `stream_complete(prompt)` 方法（OpenAILLM /
        OpenAIChatLLM 已實作）。沒有時降級回單次 complete + 一次 yield。
        失敗時 yield 模板 fallback。
        """
        if self.llm is None:
            yield _fallback_render(contract)
            return

        prompt = self._build_prompt(
            contract=contract,
            skill=skill,
            response_mode=response_mode,
            emotion_state=emotion_state,
            feedback=feedback,
        )

        stream_method = getattr(self.llm, "stream_complete", None)
        if stream_method is None:
            # Provider 未實作串流：退化成一次性回覆
            try:
                text = await self.llm.complete(prompt)
            except Exception:
                logger.exception("narrative render failed, falling back to template")
                text = _fallback_render(contract)
            yield text
            return

        try:
            async for delta in stream_method(prompt):
                if delta:
                    yield delta
        except Exception:
            logger.exception("stream_render failed, yielding template fallback")
            yield _fallback_render(contract)
