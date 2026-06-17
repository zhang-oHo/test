"""Score fusion across multi-seed retrievals.

對應 spec-14 / task-14。三種策略：
- max: 每 chunk 取所有 seed 中最高 combined_score
- mean: 對未命中的 seed 計 0，偏好多路共識
- rrf: Reciprocal Rank Fusion，鈍化極端分數

借鑑 project-destiny ADR-009 §D1。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable

from app.rag.schemas import KnowledgeChunk


def _by_id(chunk: KnowledgeChunk) -> str:
    return chunk.id


def fuse_max(hits_per_seed: list[list[KnowledgeChunk]]) -> list[KnowledgeChunk]:
    best: dict[str, KnowledgeChunk] = {}
    for hits in hits_per_seed:
        for c in hits:
            cid = _by_id(c)
            if cid not in best or c.combined_score > best[cid].combined_score:
                best[cid] = c
    return sorted(best.values(), key=lambda c: c.combined_score, reverse=True)


def fuse_mean(hits_per_seed: list[list[KnowledgeChunk]]) -> list[KnowledgeChunk]:
    """Mean of combined_score across all seeds (missing → 0)."""
    if not hits_per_seed:
        return []

    n_seeds = len(hits_per_seed)
    by_id: dict[str, list[float]] = defaultdict(list)
    rep: dict[str, KnowledgeChunk] = {}

    for hits in hits_per_seed:
        seen_in_this_seed: set[str] = set()
        for c in hits:
            cid = _by_id(c)
            by_id[cid].append(c.combined_score)
            seen_in_this_seed.add(cid)
            if cid not in rep or c.combined_score > rep[cid].combined_score:
                rep[cid] = c
        # 不在這個 seed 命中的 chunk 不在這裡補 0；最後算 mean 時用 sum/n_seeds

    out: list[KnowledgeChunk] = []
    for cid, scores in by_id.items():
        avg = sum(scores) / n_seeds  # 缺席的 seed 視為 0
        out.append(rep[cid].model_copy(update={"combined_score": avg}))
    return sorted(out, key=lambda c: c.combined_score, reverse=True)


def fuse_rrf(
    hits_per_seed: list[list[KnowledgeChunk]], *, k: int = 60
) -> list[KnowledgeChunk]:
    """Reciprocal Rank Fusion: Σ 1/(k + rank)。

    分數本身被替換為 RRF 值，無法直接與 combined_score 比較——這是 fusion 的特徵。
    """
    rrf_score: dict[str, float] = defaultdict(float)
    rep: dict[str, KnowledgeChunk] = {}

    for hits in hits_per_seed:
        for rank, c in enumerate(hits):
            cid = _by_id(c)
            rrf_score[cid] += 1.0 / (k + rank + 1)
            if cid not in rep or c.combined_score > rep[cid].combined_score:
                rep[cid] = c

    out = [
        rep[cid].model_copy(update={"combined_score": score})
        for cid, score in rrf_score.items()
    ]
    return sorted(out, key=lambda c: c.combined_score, reverse=True)


FUSION_STRATEGIES: dict[str, Callable[[list[list[KnowledgeChunk]]], list[KnowledgeChunk]]] = {
    "max": fuse_max,
    "mean": fuse_mean,
    "rrf": fuse_rrf,
}


def get_fuser(strategy: str):
    fuser = FUSION_STRATEGIES.get(strategy)
    if fuser is None:
        raise ValueError(
            f"unknown fusion strategy: {strategy!r}. "
            f"Available: {sorted(FUSION_STRATEGIES.keys())}"
        )
    return fuser
