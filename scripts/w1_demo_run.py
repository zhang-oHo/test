"""W1 端到端驗收：crawl → ingest → graph → narrative，全部用真 OpenAI + sqlite-vec。

不需 Supabase / LINE webhook / ngrok。
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path("/Users/aaron/Projects/data-science-2026/project-linebot-rag-skills")
sys.path.insert(0, str(PROJECT_ROOT))

# 強制 OpenAI + sqlite-vec
os.environ["AI_PROVIDER"] = "gemini"
os.environ["EMBEDDING_PROVIDER"] = "gemini"
os.environ["ROUTER_MODEL"] = "gemini-2.5-flash"
os.environ["GENERATOR_MODEL"] = "gemini-2.5-flash"
os.environ["EMBEDDING_MODEL"] = "models/text-embedding-004"
os.environ["KNOWLEDGE_STORE_BACKEND"] = "sqlite_vec"
os.environ["SQLITE_VEC_PATH"] = "/tmp/test_kb.db"
os.environ["JUDGE_ENABLED"] = "false"
os.environ["MAX_REFLECTION_RETRIES"] = "0"
# settings 是 lru_cache，要在 import 前設好

from app.ai.factory import build_embedder, build_llm
from app.channels import StubChannel
from app.config import get_settings
from app.generator.contract import AnswerContractBuilder
from app.generator.narrative import NarrativeRenderer
from app.generator.responder import ResponseGenerator
from app.graph.clarifier import LLMClarifier
from app.graph.feature_extractor import LLMFeatureExtractor
from app.graph.seed_expander import DefaultSeedExpander
from app.graph.sufficiency import SufficiencyChecker, SufficiencyConfig
from app.judge.scorer import GroundednessJudge
from app.observability.tracer import (
    GraphTracer, reset_current_tracer, set_current_tracer,
)
from app.rag.retriever import RAGRetriever
from app.router.intent_router import IntentRouter
from app.skills.registry import SkillRegistry
from app.storage.stores import build_store


async def main(query: str, variant: str = "selfrag"):
    settings = get_settings()
    print(f"=== W1 e2e: variant={variant} provider={settings.ai_provider} store={settings.knowledge_store_backend} ===\n")

    # —— 服務組裝（最小集合）
    store = build_store(settings)

    class _NoLogsRepo:
        async def log_retrieval(self, *a, **k): pass

    retriever = RAGRetriever(
        embedder=build_embedder(settings),
        store=store,
        logs_repo=_NoLogsRepo(),
        final_context_k=settings.final_context_k,
    )
    router = IntentRouter(llm=build_llm(settings, "router"), confidence_threshold=settings.router_confidence_threshold)
    responder = ResponseGenerator(llm=build_llm(settings, "generator"), line_max_message_chars=settings.line_max_message_chars)
    feature_extractor = LLMFeatureExtractor(llm=build_llm(settings, "router"))
    seed_expander = DefaultSeedExpander()
    sufficiency_checker = SufficiencyChecker(SufficiencyConfig(
        min_chunks=settings.sufficiency_min_chunks,
        min_top_score=settings.sufficiency_min_top_score,
        min_feature_overlap=settings.sufficiency_min_feature_overlap,
    ))
    clarifier = LLMClarifier(llm=build_llm(settings, "router"))
    contract_builder = AnswerContractBuilder()
    narrative_renderer = NarrativeRenderer(
        llm=build_llm(settings, "generator"),
        line_max_message_chars=settings.line_max_message_chars,
    )
    judge = GroundednessJudge(llm=None)
    skill_registry = SkillRegistry.from_directory(settings.skills_path)
    stub_channel = StubChannel()

    class _Services:
        pass

    s = _Services()
    s.settings = settings
    s.store = store
    s.retriever = retriever
    s.router = router
    s.responder = responder
    s.feature_extractor = feature_extractor
    s.seed_expander = seed_expander
    s.sufficiency_checker = sufficiency_checker
    s.clarifier = clarifier
    s.contract_builder = contract_builder
    s.narrative_renderer = narrative_renderer
    s.judge = judge
    s.skill_registry = skill_registry
    s.tracer_registry = None
    s.checkpointer = None
    s.channels = {"stub": stub_channel}
    s.line_client = None  # graph 不直接呼叫
    s.messages_repo = None  # 走 stub channel 不需要

    # —— 建 graph
    from app.graph.variants import VARIANT_BUILDERS

    builder = VARIANT_BUILDERS[variant]
    graph = builder(s)

    # —— 帶 tracer 跑一次
    tracer = GraphTracer(thread_id="e2e-w1", variant=variant)
    token = set_current_tracer(tracer)
    try:
        final = await graph.ainvoke({
            "user_input": query,
            "channel": "stub",
            "external_user_id": "U_test_e2e",
            "external_message_id": "msg-1",
            "recent_history": "",
        })
    finally:
        reset_current_tracer(token)

    # —— 報告
    print(f"Query: {query}\n")
    print(f"router_result.target_skill: {final['router_result'].target_skill}")
    print(f"router_result.is_rag_required: {final['router_result'].is_rag_required}")

    if "features" in final:
        f = final["features"]
        print(f"\nfeatures:")
        print(f"  primary_topic: {f.primary_topic!r}")
        print(f"  qualifiers:    {f.qualifiers}")
        print(f"  intent:        {f.intent}")
        print(f"  entities:      {f.entities}")

    if "seeds" in final:
        print(f"\nseeds: {final['seeds']}")
        print(f"hits_per_seed: {[len(h) for h in final.get('hits_per_seed') or []]}")

    chunks = final.get("rag_chunks") or []
    print(f"\nrag_chunks: {len(chunks)}")
    for c in chunks[:3]:
        url = (c.metadata or {}).get("source_url", "<no url>")
        print(f"  - {c.id} score={c.combined_score:.3f} url={url}")

    if "sufficiency" in final:
        print(f"\nsufficiency: {final['sufficiency']}")
        if final.get("sufficiency_reasons"):
            print(f"  reasons: {final['sufficiency_reasons']}")

    contract = final.get("answer_contract")
    if contract:
        print(f"\nanswer_contract:")
        print(f"  summary:     {contract.summary}")
        print(f"  findings:    {len(contract.key_findings)}")
        print(f"  caveats:     {len(contract.caveats)}")
        print(f"  citations:   {len(contract.citations)}")
        for cit in contract.citations[:3]:
            print(f"    - {cit.source}")

    print(f"\nresponses (first 800 chars):")
    full = "\n\n".join(final.get("responses") or [])
    print("  " + full[:800].replace("\n", "\n  "))

    print(f"\n[stub channel] pushed:")
    for msg in stub_channel.pushed:
        print(f"  to={msg[0]} chars={sum(len(s) for s in msg[1])}")

    print(f"\n[tracer] events={len(tracer.events)} input_tokens={tracer.total_input_tokens} "
          f"output_tokens={tracer.total_output_tokens} cost=${tracer.total_cost_usd:.6f}")


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "Server Components 跟 Client Components 差在哪？"
    v = sys.argv[2] if len(sys.argv) > 2 else "selfrag"
    asyncio.run(main(q, v))
