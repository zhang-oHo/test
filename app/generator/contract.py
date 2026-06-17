"""Stage 1 of two-stage generator: build a deterministic Answer Contract.

對應 spec-16 / task-16。

設計刻意是純程式（不呼叫 LLM）：學生看到「結構是程式組的、不是 LLM 編的」，
contract 可單獨 dump 出來作 debug、可單元測試、可被 P4 judge 審查。
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.graph.feature_extractor import ExtractedFeatures
from app.rag.schemas import KnowledgeChunk
from app.router.schemas import RouterResult


class Citation(BaseModel):
    chunk_id: str
    source: str
    snippet: str = Field(..., description="原文片段，給 P4 judge 對照 fidelity 用")


class KeyFinding(BaseModel):
    point: str
    citations: list[str] = Field(default_factory=list, description="chunk_id 列表")


class AnswerContract(BaseModel):
    summary: str
    key_findings: list[KeyFinding]
    caveats: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    citations: list[Citation]


_INTENT_PHRASES: dict[str, str] = {
    "how_to": "怎麼做",
    "debug": "如何排查",
    "concept": "是什麼",
    "compare": "如何比較",
    "decide": "如何決定",
}


_RESPONSE_MODE_NEXT_STEPS: dict[str, list[str]] = {
    "step_by_step": ["執行上述步驟後回報結果"],
    "decision_support": ["確認選擇並告知，我再幫你接下一步"],
    "debugging": ["先驗證最高機率的原因，再回報結果"],
}


def _source_from_chunk(c: KnowledgeChunk) -> str:
    """Citation.source 推導順序：metadata.source_url → title → category，
    PDF / Notion 來源附加 (p.42, 第 3.2 節) 後綴（task-25 metadata 流通）。
    """
    meta = c.metadata if isinstance(c.metadata, dict) else {}
    base: str
    url = meta.get("source_url")
    if url:
        base = str(url)
    elif c.title:
        base = c.title
    else:
        base = c.category or "knowledge_base"

    # Page / section 後綴（PDF / Notion 來源帶）
    suffix_parts: list[str] = []
    page = meta.get("page_number")
    if page is not None:
        suffix_parts.append(f"p.{page}")
    section_path = meta.get("section_path")
    if section_path:
        if isinstance(section_path, list):
            suffix_parts.append(" > ".join(str(s) for s in section_path))
        else:
            suffix_parts.append(str(section_path))
    if suffix_parts:
        return f"{base} ({', '.join(suffix_parts)})"
    return base


def _first_sentence(text: str, max_chars: int = 120) -> str:
    """取首句（以「。」「！」「？」分隔），上限 max_chars。"""
    if not text:
        return ""
    cleaned = text.strip()
    for sep in ("。", "！", "？", "\n"):
        idx = cleaned.find(sep)
        if 0 < idx < max_chars:
            return cleaned[: idx + 1].strip()
    return cleaned[:max_chars].strip()


@dataclass
class AnswerContractBuilder:
    low_score_threshold: float = 0.5

    def build(
        self,
        *,
        features: ExtractedFeatures,
        chunks: list[KnowledgeChunk],
        router_result: RouterResult,
        sufficiency_reasons: list[str] | None = None,
    ) -> AnswerContract:
        sufficiency_reasons = sufficiency_reasons or []
        return AnswerContract(
            summary=self._summary(features),
            key_findings=self._key_findings(chunks),
            caveats=self._caveats(chunks, sufficiency_reasons),
            next_steps=self._next_steps(router_result),
            citations=self._citations(chunks),
        )

    def _summary(self, f: ExtractedFeatures) -> str:
        intent_phrase = _INTENT_PHRASES.get(f.intent, "相關說明")
        topic = f.primary_topic or f.raw_query or "（未知主題）"
        return f"關於「{topic}」的{intent_phrase}。"

    def _key_findings(self, chunks: list[KnowledgeChunk]) -> list[KeyFinding]:
        out: list[KeyFinding] = []
        for c in chunks:
            # 跳過 # 標題行，從實際內容取第一句
            content_lines = [l for l in c.content.split('\n') if l.strip() and not l.strip().startswith('#')]
            content_body = '\n'.join(content_lines)
            point = _first_sentence(content_body)
            if not point:
                continue
            out.append(KeyFinding(point=point, citations=[c.id]))
        return out

    def _caveats(
        self,
        chunks: list[KnowledgeChunk],
        sufficiency_reasons: list[str],
    ) -> list[str]:
        caveats: list[str] = []
        if chunks and chunks[0].combined_score < self.low_score_threshold:
            caveats.append(
                f"Top 相關性僅 {chunks[0].combined_score:.2f}，回覆可能不完全切題"
            )
        if sufficiency_reasons:
            caveats.append("檢索條件未全部達標：" + "; ".join(sufficiency_reasons))
        if not caveats:
            caveats.append("以下內容依當前知識庫整理，未涵蓋的最新更新請另行查證")
        return caveats

    def _next_steps(self, r: RouterResult) -> list[str]:
        mode = getattr(r, "response_mode", None)
        return list(_RESPONSE_MODE_NEXT_STEPS.get(mode, []))

    def _citations(self, chunks: list[KnowledgeChunk]) -> list[Citation]:
        return [
            Citation(
                chunk_id=c.id,
                source=_source_from_chunk(c),
                snippet=c.content[:200],
            )
            for c in chunks
            if c.combined_score >= 0.3  # ✅ 同樣過濾
        ]
