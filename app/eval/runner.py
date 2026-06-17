"""Eval runner — 跑 golden case set 對三變體輸出 metric。

對應 spec-20 / task-20 步驟 4。
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel, Field

from app.eval.metrics import (
    chunk_recall_at_k,
    citation_accuracy,
    forbidden_phrase_hit,
    must_cite_satisfied,
)
from app.eval.schema import GoldenCase
from app.graph.variants import VARIANT_BUILDERS


class EvalResult(BaseModel):
    case_id: str
    variant: str
    chunk_recall: float | None = None
    citation_accuracy: float | None = None
    forbidden_phrase_hit: bool = False
    must_cite_satisfied: bool | None = None
    went_to_clarify: bool = False
    judge_passed: bool | None = None
    latency_ms: int = 0
    response_excerpt: str = ""
    failure_reasons: list[str] = Field(default_factory=list)


class EvalRunner:
    def __init__(self, services: Any) -> None:
        self._services = services

    async def run_case(self, case: GoldenCase, variant: str) -> EvalResult:
        builder = VARIANT_BUILDERS[variant]
        # 為了切換 variant 需重 build graph；保留原 services.rag_graph 不動
        graph = builder(self._services)

        t0 = time.time()
        final = await graph.ainvoke(
            {
                "user_input": case.query,
                "external_user_id": f"U_eval_{case.id}",
                "recent_history": "",
                "dry_run": True,
            }
        )
        latency_ms = int((time.time() - t0) * 1000)

        retrieved = final.get("rag_chunks") or []
        responses = final.get("responses") or []
        response_text = "\n".join(responses)
        contract = final.get("answer_contract")
        cited_chunk_ids = (
            [cit.chunk_id for cit in contract.citations] if contract else []
        )
        cited_sources = (
            [cit.source for cit in contract.citations] if contract else []
        )

        went_to_clarify = bool(final.get("clarification_questions"))
        score = final.get("judge_score")
        judge_passed: bool | None
        if score is None:
            judge_passed = None
        else:
            judge_passed = score.passes(
                min_axis=self._services.settings.judge_min_axis,
                min_mean=self._services.settings.judge_min_mean,
            )

        forbidden_hit = forbidden_phrase_hit(case, response_text)
        cite_satisfied = must_cite_satisfied(case, cited_sources)

        failures: list[str] = []
        if case.expect_clarification and not went_to_clarify:
            failures.append("expected clarify but went to generate")
        # spec-20 §「易誘發 hallucination」：expected_chunks=[] 的 hallucination 案例
        # 測的是 forbidden_phrase，不是 clarify 路由。selfrag / reflection 在無 chunks
        # 時 sufficiency=insufficient → 走 clarify 是 _正確行為_，不該標 failure。
        if (
            not case.expect_clarification
            and went_to_clarify
            and case.expected_chunks  # 只有「應該找到 chunks」的 case 才檢查
        ):
            failures.append("unexpected clarify (case has chunks but graph asked to clarify)")
        if forbidden_hit:
            failures.append(f"hit forbidden phrase: {case.forbidden_phrases}")
        # spec-20 §「Metric」：citation_accuracy 不適用 basic variant（basic 不產 contract、
        # 沒 cited_sources），不應把 must_cite 列為 failure。
        if cite_satisfied is False and variant != "basic":
            failures.append(f"missing required citation: {case.must_cite_sources}")

        return EvalResult(
            case_id=case.id,
            variant=variant,
            chunk_recall=chunk_recall_at_k(case, retrieved),
            citation_accuracy=citation_accuracy(retrieved, cited_chunk_ids),
            forbidden_phrase_hit=forbidden_hit,
            must_cite_satisfied=cite_satisfied,
            went_to_clarify=went_to_clarify,
            judge_passed=judge_passed,
            latency_ms=latency_ms,
            response_excerpt=response_text[:300],
            failure_reasons=failures,
        )

    async def run(
        self, *, cases: list[GoldenCase], variants: list[str]
    ) -> list[EvalResult]:
        results: list[EvalResult] = []
        for variant in variants:
            for case in cases:
                results.append(await self.run_case(case, variant))
        return results

    @staticmethod
    def aggregate(results: list[EvalResult]) -> dict:
        by_variant: dict[str, list[EvalResult]] = {}
        for r in results:
            by_variant.setdefault(r.variant, []).append(r)

        def _avg_optional(xs):
            xs = [x for x in xs if x is not None]
            return sum(xs) / len(xs) if xs else None

        out = {}
        for variant, rs in by_variant.items():
            judge_pass_seq = [
                1.0 if r.judge_passed else 0.0
                for r in rs
                if r.judge_passed is not None
            ]
            durations = sorted(r.latency_ms for r in rs)
            out[variant] = {
                "n": len(rs),
                "chunk_recall_avg": _avg_optional(r.chunk_recall for r in rs),
                "citation_accuracy_avg": _avg_optional(r.citation_accuracy for r in rs),
                "forbidden_phrase_rate": sum(r.forbidden_phrase_hit for r in rs) / len(rs),
                "clarification_rate": sum(r.went_to_clarify for r in rs) / len(rs),
                "judge_pass_rate": (
                    sum(judge_pass_seq) / len(judge_pass_seq) if judge_pass_seq else None
                ),
                "latency_ms_median": durations[len(durations) // 2] if durations else 0,
                "failed": [r.case_id for r in rs if r.failure_reasons],
            }
        return out
