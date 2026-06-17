"""Seed Expander — 把 ExtractedFeatures 展開為多條檢索 seed。

對應 spec-14 / task-14。下游 retrieve_one_node 對每條 seed 並行 retrieve。

`DefaultSeedExpander` 的規則通用，學生轉題目時可子類化覆寫 `expand`。
"""

from __future__ import annotations

from typing import Protocol

from app.graph.feature_extractor import ExtractedFeatures


class SeedExpander(Protocol):
    def expand(self, features: ExtractedFeatures, *, max_seeds: int = 5) -> list[str]: ...


class DefaultSeedExpander:
    """通用展開規則：
    1. primary_topic 單獨成一條
    2. primary_topic + 各 qualifier
    3. 第一個 entity 串接 primary_topic
    4. raw_query 保底
    去重 + 截斷至 max_seeds。
    """

    def expand(self, features: ExtractedFeatures, *, max_seeds: int = 5) -> list[str]:
        seeds: list[str] = []

        if features.primary_topic:
            seeds.append(features.primary_topic)

        for q in features.qualifiers[:3]:
            combined = f"{features.primary_topic} {q}".strip()
            if combined:
                seeds.append(combined)

        if features.entities:
            entity_seed = f"{features.entities[0]} {features.primary_topic}".strip()
            if entity_seed:
                seeds.append(entity_seed)

        if features.raw_query:
            seeds.append(features.raw_query)

        seen: set[str] = set()
        unique: list[str] = []
        for s in seeds:
            cleaned = s.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                unique.append(cleaned)

        return unique[:max_seeds]
