from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "project-linebot-rag-skills"

    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    line_api_base: str = "https://api.line.me"

    # --- AI provider selection ---
    # ai_provider: which backend drives the router + generator LLMs
    #   options: openai | claude | gemini | github_copilot
    ai_provider: str = "openai"
    # embedding_provider: which backend drives RAG embeddings
    #   options: openai | gemini
    embedding_provider: str = "openai"

    # OpenAI
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    router_model: str = "gemini-2.5-flash"
    generator_model: str = "gemini-2.5-flash"
    embedding_model: str = "text-embedding-3-small"

    # Anthropic / Claude
    anthropic_api_key: str = ""

    # Google Gemini
    gemini_api_key: str = ""

    # GitHub Copilot (OpenAI-compatible chat completions)
    github_copilot_token: str = ""
    github_copilot_base_url: str = "https://api.githubcopilot.com"

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_schema: str = "public"

    knowledge_top_k: int = 8
    final_context_k: int = 4
    line_max_message_chars: int = 4500
    router_confidence_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    skills_dir: str = "skills"

    # spec-08 Skill hot reload
    skill_source: str = "file"            # file | supabase
    skill_reload_interval: int = 600      # 秒；skill_source=supabase 時生效，<=0 表停用 reload

    # P2 multi-seed retrieval（spec-14 / task-14）
    fusion_strategy: str = "max"   # max | mean | rrf
    max_seeds: int = 5

    # P3 sufficiency（spec-15 / task-15）
    sufficiency_min_chunks: int = 2
    sufficiency_min_top_score: float = 0.4
    sufficiency_min_feature_overlap: int = 1

    # P4 judge + reflection（spec-17 / task-17）
    judge_enabled: bool = True
    judge_model: str = ""              # 空字串 → 沿用 router_model
    judge_min_axis: int = 6            # 各軸最低分
    judge_min_mean: float = 7.0        # 平均最低分
    max_reflection_retries: int = 1    # 硬上限 2

    # 三變體並陳（spec-19 / task-19）
    graph_variant: str = "reflection"  # basic | selfrag | reflection

    # Observability（spec-22 / task-22）
    observability_enabled: bool = True
    observability_persist: bool = False    # 寫 Supabase graph_traces
    trace_dir: str = ".traces"

    # Knowledge Store backend（spec-24 / task-24）
    knowledge_store_backend: str = "supabase"  # supabase | sqlite_vec | pinecone
    sqlite_vec_path: str = ".kb/local.db"
    sqlite_vec_dim: int = 1536                  # OpenAI text-embedding-3-small
    pinecone_api_key: str = ""
    pinecone_index: str = "rag-lessons"

    # HITL + Persistence（spec-21 / task-21）
    hitl_enabled: bool = False
    hitl_always_review_skills: list[str] = []
    checkpoint_backend: str = "memory"   # memory | sqlite | postgres | none
    checkpoint_sqlite_path: str = ".checkpoints/rag.db"
    # spec-21 §「Checkpointer 選擇」postgres backend：與 Supabase 共用 DB
    supabase_db_url: str = ""

    # spec-26 query transform
    query_transform_strategy: str = "none"   # none | hyde | step_back | decompose
    hyde_model: str = ""                      # empty → falls back to router_model
    hyde_max_tokens: int = 150
    step_back_model: str = ""                 # empty → falls back to router_model
    decompose_max_subqueries: int = 3

    # spec-27 hybrid retrieval（Supabase SQL already implements BM25; this exposes the weights）
    hybrid_enabled: bool = False
    hybrid_vector_weight: float = 0.7
    hybrid_keyword_weight: float = 0.3

    # spec-28 reranker
    reranker_enabled: bool = False
    reranker_provider: str = "cohere"          # cohere | bge
    reranker_model: str = "rerank-multilingual-v3.0"
    reranker_top_n: int = 5
    cohere_api_key: str = ""
    bge_reranker_model: str = "BAAI/bge-reranker-base"

    # spec-29 embedding dimensions（text-embedding-3-* supports dimension reduction）
    embedding_dimensions: int | None = None

    # spec-30 security guards
    security_input_guard: bool = True
    security_output_guard: bool = True
    security_poison_screen: bool = True
    security_max_input_chars: int = 1000
    security_blocked_reply: str = "抱歉，這個問題我無法回覆。"

    # spec-31 streaming
    streaming_enabled: bool = False
    streaming_placeholder: str = "⏳ 思考中，請稍候..."

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parent.parent

    @property
    def skills_path(self) -> Path:
        path = Path(self.skills_dir)
        return path if path.is_absolute() else self.project_root / path

    @model_validator(mode="after")
    def _validate_hybrid_weights(self) -> "Settings":
        if self.hybrid_enabled:
            total = self.hybrid_vector_weight + self.hybrid_keyword_weight
            if not (0.99 < total < 1.01):
                raise ValueError(
                    f"hybrid_vector_weight + hybrid_keyword_weight must equal 1.0 "
                    f"(got {total:.3f})"
                )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
