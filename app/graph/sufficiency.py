"""Sufficiency Checker — 純 rule-based 判定 retrieval 是否夠生成可信回覆。

對應 spec-15 / task-15。三項規則任一不過即視為 insufficient：
1. chunks 數量 ≥ min_chunks
2. top chunk 的 vector_score ≥ min_top_score（cosine similarity, 0–1）
3. feature 詞彙在 chunks 文字中至少 N 次 lexical overlap

註：早期版本比的是 combined_score，但 spec-27 改為 RRF 後 combined_score 上限 ≈ 0.033，
原 0.4 門檻永遠到不了 → 改比 vector_score（與門檻 0.4 同尺度）。

故意全用程式規則：學生看得懂、改得動。後續可換成 LLM-based 判定，但教學版優先用 rule-based。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.graph.feature_extractor import ExtractedFeatures
from app.rag.schemas import KnowledgeChunk

SufficiencyDecision = Literal["sufficient", "insufficient"]
SufficiencyResult = tuple[SufficiencyDecision, list[str]]


@dataclass
class SufficiencyConfig:
    min_chunks: int = 1
    min_top_score: float = 0.25
    min_feature_overlap: int = 0


class SufficiencyChecker:
    def __init__(self, config: SufficiencyConfig) -> None:
        self._cfg = config

    def check(
        self,
        *,
        chunks: list[KnowledgeChunk],
        features: ExtractedFeatures,
    ) -> SufficiencyResult:
        reasons: list[str] = []

        if len(chunks) < self._cfg.min_chunks:
            reasons.append(
                f"chunks={len(chunks)} < min_chunks={self._cfg.min_chunks}"
            )

        top_score = chunks[0].vector_score if chunks else 0.0
        if top_score < self._cfg.min_top_score:
            reasons.append(
                f"top_score={top_score:.2f} < min_top_score={self._cfg.min_top_score}"
            )

        # lexical overlap：feature 詞是否在任一 chunk 的內容中出現
        terms: set[str] = set()
        if features.primary_topic:
            terms.add(features.primary_topic.lower())
        for q in features.qualifiers:
            if q:
                terms.add(q.lower())

        chunk_text = " ".join(c.content.lower() for c in chunks)
        hit = sum(1 for t in terms if t and t in chunk_text)
        if hit < self._cfg.min_feature_overlap:
            reasons.append(
                f"feature_overlap={hit} < min={self._cfg.min_feature_overlap}"
            )

        return ("insufficient" if reasons else "sufficient", reasons)
