from __future__ import annotations

from operator import add
from typing import Annotated, Literal, TypedDict

from app.generator.contract import AnswerContract
from app.graph.feature_extractor import ExtractedFeatures
from app.judge.scorer import JudgeScore
from app.rag.schemas import KnowledgeChunk
from app.router.schemas import RouterResult
from app.skills.loader import SkillDefinition


class RAGState(TypedDict, total=False):
    user_input: str
    channel: str                  # "line" | "http" | "stub" | ...
    external_user_id: str         # 跨 channel 通用的識別（取代 line_user_id）
    external_message_id: str
    recent_history: str

    router_result: RouterResult
    skill: SkillDefinition

    features: ExtractedFeatures

    # —— P2 multi-seed
    seeds: list[str]
    # reducer：fan-out 寫入時用 list append（而非覆寫）
    hits_per_seed: Annotated[list[list[KnowledgeChunk]], add]
    # 每條 seed 並行任務的本地欄位（透過 Send 傳入；總體 state 不直接讀）
    seed: str
    seed_index: int

    rag_chunks: list[KnowledgeChunk]
    rag_context: str

    # —— P3 sufficiency / clarification
    sufficiency: Literal["sufficient", "insufficient"]
    sufficiency_reasons: list[str]
    clarification_questions: list[str]

    # —— P3 two-stage generator
    answer_contract: AnswerContract

    # —— P4 judge + reflection
    judge_score: JudgeScore | None
    judge_feedback: list[str]
    reflection_retry: int
    judge_warning_prefix: bool

    # —— task-21 HITL（reflection variant + hitl_enabled 才會用到）
    reviewer_decision: Literal["approve", "revise", "drop"] | None
    reviewer_revised_text: str | None
    reviewed_at: str | None
    reviewer_id: str | None

    responses: list[str]

    # 非 prod 路徑（demo / eval）：push_node 不真的送出訊息
    dry_run: bool

    # —— spec-26 query transform
    transformed_queries: list[str]    # transform 後展開的查詢列表（含原始 user_input）
    hyde_doc: str | None              # HyDE 假設性解答
    transform_strategy: str | None   # 本次使用的策略

    # —— spec-30 security
    blocked: bool                     # input_guard 攔截時設 True
    blocked_reason: str | None
    output_had_leakage: bool          # output_guard 偵測到 PII 洩漏
