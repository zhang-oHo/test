from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

from app.generator.formatter import split_for_line
from app.generator.prompts import render_synthesis_prompt
from app.rag.schemas import KnowledgeChunk
from app.router.schemas import RouterResult
from app.skills.loader import SkillDefinition
from app.storage.cache_repo import CacheRepository, build_cache_key

logger = logging.getLogger(__name__)


class GeneratorLLM(Protocol):
    async def complete(self, prompt: str) -> str:
        ...


@dataclass
class ResponseGenerator:
    llm: GeneratorLLM | None = None
    line_max_message_chars: int = 4500
    cache_repo: CacheRepository | None = None

    async def generate_response(
        self,
        *,
        user_input: str,
        router_result: RouterResult,
        skill: SkillDefinition,
        rag_chunks: list[KnowledgeChunk],
        rag_context: str,
        recent_history: str,
    ) -> list[str]:
        # --- 偵錯區塊開始 ---
        print(f"--- [DEBUG] 檢索到的 Chunks 數量: {len(rag_chunks)} ---")
        for i, chunk in enumerate(rag_chunks):
            print(f"--- [DEBUG] 第 {i+1} 筆: {chunk.title} (ID: {chunk.id}) ---")
        # --- 偵錯區塊結束 ---

        if self.llm is None:
            return self._fallback_response(router_result, rag_chunks)

        # spec-05 §「快取條件」：is_rag_required=True 且 rag_chunks 非空才走快取，
        # 避免快取「知識庫不足」的回覆。
        cacheable = bool(
            self.cache_repo is not None
            and router_result.is_rag_required
            and rag_chunks
        )
        cache_key: str | None = None
        knowledge_version = 0
        if cacheable:
            knowledge_version = await self.cache_repo.get_knowledge_version()
            cache_key = build_cache_key(
                skill_id=skill.skill_id,
                knowledge_version=knowledge_version,
                user_input=user_input,
            )
            cached = await self.cache_repo.get(cache_key)
            if cached is not None:
                logger.info(
                    "prompt cache hit skill=%s version=%s key=%s",
                    skill.skill_id, knowledge_version, cache_key[:12],
                )
                return split_for_line(cached, max_chars=self.line_max_message_chars)

        prompt = render_synthesis_prompt(
            skill_name=skill.name,
            skill_system_prompt=skill.system_prompt,
            user_input=user_input,
            recent_history=recent_history,
            emotion_state=router_result.emotion_state,
            response_mode=router_result.response_mode,
            rag_context=rag_context,
        )
        response_text = await self.llm.complete(prompt)

        if router_result.is_rag_required and not rag_chunks:
            response_text = f"目前知識庫沒有足夠資料。\n\n{response_text}".strip()

        if cacheable and cache_key is not None:
            await self.cache_repo.set(
                cache_key=cache_key,
                user_input=user_input,
                skill_id=skill.skill_id,
                knowledge_version=knowledge_version,
                response_text=response_text,
            )

        return split_for_line(response_text, max_chars=self.line_max_message_chars)

    def _fallback_response(
        self,
        router_result: RouterResult,
        rag_chunks: list[KnowledgeChunk],
    ) -> list[str]:
        if router_result.is_rag_required and not rag_chunks:
            text = "目前知識庫沒有足夠資料。先提供保守回應，若需要可補充更多背景。"
        else:
            text = "已收到訊息，系統會依目前 skill 與上下文回覆。"
        return split_for_line(text, max_chars=self.line_max_message_chars)
