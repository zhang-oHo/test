from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from app.ai.factory import build_embedder, build_llm, has_llm_configured
from app.channels import HttpChannel, LineChannel, OutputChannel
from app.config import Settings, get_settings
from app.generator.contract import AnswerContractBuilder
from app.generator.narrative import NarrativeRenderer
from app.generator.responder import ResponseGenerator
from app.graph.checkpoint import build_checkpointer
from app.graph.clarifier import Clarifier, LLMClarifier
from app.graph.feature_extractor import FeatureExtractor, LLMFeatureExtractor
from app.graph.rag_graph import build_rag_graph
from app.graph.seed_expander import DefaultSeedExpander, SeedExpander
from app.graph.sufficiency import SufficiencyChecker, SufficiencyConfig
from app.judge.scorer import GroundednessJudge
from app.observability.tracer import TracerRegistry
from app.line.client import LineMessagingClient
from app.rag.retriever import RAGRetriever
from app.router.intent_router import IntentRouter
from app.skills.registry import SkillRegistry
from app.storage.cache_repo import CacheRepository
from app.storage.knowledge_repo import KnowledgeRepository
from app.storage.knowledge_store import KnowledgeStore
from app.storage.logs_repo import LogsRepository
from app.storage.messages_repo import MessagesRepository
from app.storage.stores import build_store
from app.storage.supabase_client import SupabaseRestClient
from app.storage.traces_repo import TracesRepository


@dataclass
class RuntimeServices:
    line_client: LineMessagingClient
    messages_repo: MessagesRepository
    skill_registry: SkillRegistry
    router: IntentRouter
    retriever: RAGRetriever
    responder: ResponseGenerator
    feature_extractor: FeatureExtractor
    seed_expander: SeedExpander
    sufficiency_checker: SufficiencyChecker
    clarifier: Clarifier
    contract_builder: AnswerContractBuilder
    narrative_renderer: NarrativeRenderer
    judge: GroundednessJudge
    settings: Settings
    tracer_registry: TracerRegistry | None = None
    channels: dict[str, OutputChannel] = field(default_factory=dict)
    checkpointer: Any = None
    reranker: Any = None
    rag_graph: Any = None


@lru_cache(maxsize=1)
def get_supabase_client() -> SupabaseRestClient:
    return SupabaseRestClient(get_settings())


@lru_cache(maxsize=1)
def get_skill_registry() -> SkillRegistry:
    """spec-08：file 為預設來源；skill_source=supabase 時 lifespan 會在 startup
    呼叫 `replace_skill_registry` 用 SkillRegistry.from_supabase() 取代。

    這裡同步建構保留 from_directory 為 fallback——若 Supabase 啟動拉失敗
    （網路 / 表空），bot 仍能用 file 版啟動。
    """
    return SkillRegistry.from_directory(get_settings().skills_path)


def replace_skill_registry(new_registry: SkillRegistry) -> None:
    """spec-08：lifespan 啟動時把 file-based registry 換成 supabase 版。

    Graph node 透過 `services.skill_registry` 動態 lookup，所以只需要替換
    RuntimeServices 上的 attribute，不必重建 rag_graph。
    """
    if get_runtime_services.cache_info().currsize > 0:
        services = get_runtime_services()
        services.skill_registry = new_registry


@lru_cache(maxsize=1)
def get_line_client() -> LineMessagingClient:
    return LineMessagingClient(get_settings())


@lru_cache(maxsize=1)
def get_messages_repo() -> MessagesRepository:
    return MessagesRepository(get_supabase_client())


@lru_cache(maxsize=1)
def get_knowledge_repo() -> KnowledgeRepository:
    return KnowledgeRepository(get_supabase_client())


@lru_cache(maxsize=1)
def get_logs_repo() -> LogsRepository:
    return LogsRepository(get_supabase_client())


@lru_cache(maxsize=1)
def get_router() -> IntentRouter:
    settings = get_settings()
    llm = build_llm(settings, "router") if has_llm_configured(settings) else None
    return IntentRouter(llm=llm, confidence_threshold=settings.router_confidence_threshold)


@lru_cache(maxsize=1)
def get_knowledge_store() -> KnowledgeStore:
    return build_store(get_settings())


@lru_cache(maxsize=1)
def get_reranker():
    from app.rag.reranker import make_reranker
    try:
        return make_reranker(get_settings())
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("reranker init failed: %s", exc)
        return None


@lru_cache(maxsize=1)
def get_retriever() -> RAGRetriever:
    settings = get_settings()
    return RAGRetriever(
        embedder=build_embedder(settings),
        store=get_knowledge_store(),
        logs_repo=get_logs_repo(),
        final_context_k=settings.final_context_k,
        settings=settings,
    )


@lru_cache(maxsize=1)
def get_cache_repo() -> CacheRepository:
    return CacheRepository(get_supabase_client())


@lru_cache(maxsize=1)
def get_responder() -> ResponseGenerator:
    settings = get_settings()
    llm = build_llm(settings, "generator") if has_llm_configured(settings) else None
    return ResponseGenerator(
        llm=llm,
        line_max_message_chars=settings.line_max_message_chars,
        cache_repo=get_cache_repo(),
    )


@lru_cache(maxsize=1)
def get_feature_extractor() -> FeatureExtractor:
    settings = get_settings()
    # 用 router 模型即可——feature 抽取是輕量任務
    llm = build_llm(settings, "router") if has_llm_configured(settings) else None
    return LLMFeatureExtractor(llm=llm)


@lru_cache(maxsize=1)
def get_seed_expander() -> SeedExpander:
    return DefaultSeedExpander()


@lru_cache(maxsize=1)
def get_sufficiency_checker() -> SufficiencyChecker:
    s = get_settings()
    return SufficiencyChecker(
        SufficiencyConfig(
            min_chunks=s.sufficiency_min_chunks,
            min_top_score=s.sufficiency_min_top_score,
            min_feature_overlap=s.sufficiency_min_feature_overlap,
        )
    )


@lru_cache(maxsize=1)
def get_clarifier() -> Clarifier:
    settings = get_settings()
    llm = build_llm(settings, "router") if has_llm_configured(settings) else None
    return LLMClarifier(llm=llm)


@lru_cache(maxsize=1)
def get_contract_builder() -> AnswerContractBuilder:
    return AnswerContractBuilder()


@lru_cache(maxsize=1)
def get_narrative_renderer() -> NarrativeRenderer:
    settings = get_settings()
    llm = build_llm(settings, "generator") if has_llm_configured(settings) else None
    return NarrativeRenderer(
        llm=llm, line_max_message_chars=settings.line_max_message_chars
    )


@lru_cache(maxsize=1)
def get_traces_repo() -> TracesRepository:
    return TracesRepository(get_supabase_client())


@lru_cache(maxsize=1)
def get_tracer_registry() -> TracerRegistry | None:
    s = get_settings()
    if not s.observability_enabled:
        return None
    # 只在 persist=True 時注入 traces_repo（避免不必要的 Supabase client 建構）
    traces_repo = get_traces_repo() if s.observability_persist else None
    return TracerRegistry(
        trace_dir=s.trace_dir,
        persist=s.observability_persist,
        traces_repo=traces_repo,
    )


@lru_cache(maxsize=1)
def get_judge() -> GroundednessJudge:
    settings = get_settings()
    if not settings.judge_enabled:
        return GroundednessJudge(llm=None)
    # "judge" role 用 settings.judge_model；空字串時自動 fallback router_model。
    llm = build_llm(settings, "judge") if has_llm_configured(settings) else None
    return GroundednessJudge(llm=llm)


@lru_cache(maxsize=1)
def get_checkpointer():
    return build_checkpointer(get_settings())


@lru_cache(maxsize=1)
def get_channels() -> dict[str, OutputChannel]:
    settings = get_settings()
    messages_repo = get_messages_repo()
    return {
        "line": LineChannel(settings, messages_repo),
        "http": HttpChannel(messages_repo),
    }


@lru_cache(maxsize=1)
def get_runtime_services() -> RuntimeServices:
    settings = get_settings()
    services = RuntimeServices(
        line_client=get_line_client(),
        messages_repo=get_messages_repo(),
        skill_registry=get_skill_registry(),
        router=get_router(),
        retriever=get_retriever(),
        responder=get_responder(),
        feature_extractor=get_feature_extractor(),
        seed_expander=get_seed_expander(),
        sufficiency_checker=get_sufficiency_checker(),
        clarifier=get_clarifier(),
        contract_builder=get_contract_builder(),
        narrative_renderer=get_narrative_renderer(),
        judge=get_judge(),
        settings=settings,
        tracer_registry=get_tracer_registry(),
        channels=get_channels(),
        checkpointer=get_checkpointer(),
        reranker=get_reranker(),
    )
    services.rag_graph = build_rag_graph(services)
    return services
