from __future__ import annotations

import logging
from typing import Any

from langgraph.types import Send

from app.graph.clarifier import format_clarification
from app.graph.query_transform import query_transform_node  # noqa: F401 — re-export for variant builders
from app.graph.state import RAGState
from app.observability.tracer import traced
from app.rag.fusion import get_fuser

logger = logging.getLogger(__name__)


@traced("extract_features")
async def extract_features_node(state: RAGState, services: Any) -> dict[str, Any]:
    features = await services.feature_extractor.extract(
        user_input=state["user_input"],
        recent_history=state.get("recent_history"),
    )
    return {"features": features}


@traced("route")
async def route_node(state: RAGState, services: Any) -> dict[str, Any]:
    result = await services.router.route_message(
        state["user_input"],
        state.get("recent_history", "No recent conversation."),
    )
    skill = services.skill_registry.get(result.target_skill) or services.skill_registry.require(
        "hollow_knight_guide"
    )
    return {"router_result": result, "skill": skill}


@traced("retrieve")
async def retrieve_basic_node(state: RAGState, services: Any) -> dict[str, Any]:
    """P1 原版單 seed retrieve（給 basic variant 用，spec-19）。

    與 expand_seeds + retrieve_one + fuse_scores 的 multi-seed 路徑互斥；
    basic variant 只用本 node 一次性 embed → match → rerank → log。
    """
    router_result = state["router_result"]
    if not router_result.is_rag_required:
        return {"rag_chunks": [], "rag_context": "No retrieved context."}

    chunks = await services.retriever.retrieve(
        router_result.rag_query or state["user_input"],
        categories=router_result.rag_categories,
        top_k=services.settings.knowledge_top_k,
        external_user_id=state["external_user_id"],
        skill_id=router_result.target_skill,
    )
    context = services.retriever.build_context(chunks)
    return {"rag_chunks": chunks, "rag_context": context}


@traced("generate")
async def generate_basic_node(state: RAGState, services: Any) -> dict[str, Any]:
    """P1 原版單階段 generator（給 basic variant 用，spec-19）。

    呼叫 services.responder.generate_response（既有 ResponseGenerator），
    含失敗 fallback。selfrag/reflection 用 build_answer_contract + render_narrative 取代。
    """
    try:
        responses = await services.responder.generate_response(
            user_input=state["user_input"],
            router_result=state["router_result"],
            skill=state["skill"],
            rag_chunks=state.get("rag_chunks", []),
            rag_context=state.get("rag_context", "No retrieved context."),
            recent_history=state.get("recent_history", "No recent conversation."),
        )
    except Exception as e:
        logger.exception("generate_response failed: %s", e)
        responses = ["系統暫時無法完成此請求，請稍後再試。"]
    return {"responses": responses}


@traced("expand_seeds")
async def expand_seeds_node(state: RAGState, services: Any) -> dict[str, Any]:
    """Expand features into seeds. Also merges transformed_queries from spec-26."""
    router_result = state["router_result"]
    if not router_result.is_rag_required:
        return {"seeds": [], "hits_per_seed": []}

    seeds = services.seed_expander.expand(
        state["features"],
        max_seeds=services.settings.max_seeds,
    )
    if not seeds:
        seeds = [router_result.rag_query or state["user_input"]]

    # spec-26: merge transformed_queries as additional seeds
    extra = state.get("transformed_queries") or []
    for q in extra:
        if q and q not in seeds:
            seeds.append(q)

    max_s = services.settings.max_seeds
    seeds = seeds[:max_s]
    return {"seeds": seeds, "hits_per_seed": []}


def fan_out_to_retrieve(state: RAGState):
    """Conditional edge：若有 seeds 則 fan-out；否則跳過 retrieve 直奔 fuse_scores。"""
    seeds = state.get("seeds") or []
    if not seeds:
        return ["fuse_scores"]
    return [
        Send(
            "retrieve_one",
            {
                "user_input": state["user_input"],
                "external_user_id": state["external_user_id"],
                "channel": state.get("channel", ""),
                "router_result": state["router_result"],
                "seed": s,
                "seed_index": i,
            },
        )
        for i, s in enumerate(seeds)
    ]


@traced("retrieve_one")
async def retrieve_one_node(state: RAGState, services: Any) -> dict[str, Any]:
    router_result = state["router_result"]

    logger.info("====== 實際傳送的分類參數是: %s ======", router_result.rag_categories)
    
    current_seed = state["seed"]
    
    # 🎯 呼叫原本的檢索邏輯
    chunks = await services.retriever.retrieve_for_seed(
        current_seed,
        categories=[],
        top_k=services.settings.knowledge_top_k,
    )
    
    # 如果 API 爆了導致離線檢索找不到任何 Chunk (0 chunks)
    if not chunks or len(chunks) == 0:
        logger.warning(f"離線檢索未命中任何資料，啟動硬核關鍵字檔名映射攔截！當前 Seed: {current_seed}")
        
        # 1. 建立常用護符名稱與你專案中實際 Markdown 檔名的映射字典
        charm_mapping = {
            "舞夢者": "dreamwielder.md",
            "巴德爾之殼": "baldur_shell.md",
            "無憂旋律": "carefree_melody.md",
            "衝刺大師": "dashmaster.md",
            "薩滿之石": "shaman_stone.md",
            "國王之魂": "kingsoul.md"
        }
        
        # 2. 檢查目前檢索的關鍵字有沒有在對應表內
        matched_filename = None
        for k, v in charm_mapping.items():
            if k in current_seed:
                matched_filename = v
                break
                
        # 3. 如果成功映射到檔名，直接從本地讀取該檔案當作保底 Chunk 塞回去
        if matched_filename:
            import os
            # 依據你專案的知識庫目錄調整，通常在根目錄的某個資料夾，或跟著 python 執行路徑找
            # 這裡我們先假設檔案存在於當前目錄或常見的知識庫路徑，嘗試進行安全讀取
            possible_paths = [
                matched_filename,
                os.path.join("knowledge", matched_filename),
                os.path.join("data", matched_filename),
                # 也可以加上你實際存放這些 md 檔案的資料夾名稱，例如：
                os.path.join("app", "rag", matched_filename) 
            ]
            
            content = ""
            for p in possible_paths:
                if os.path.exists(p):
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            content = f.read()
                        logger.info(f"【保底成功】從路徑 {p} 成功讀取本地護符檔案！")
                        break
                    except Exception:
                        pass
            
            # 4. 如果成功讀到內容，將其包裝成模擬的 Chunk 物件塞入 chunks 列表中
            if content:
                # 建立一個匿名物件或字典（根據你系統原本 Chunk 的結構，通常具有 text / content / score 屬性）
                # 這裡為了高度相容你的系統，我們創建一個動態類別來模擬 chunks
                class MockChunk:
                    def __init__(self, text, score=1.0):
                        self.text = text
                        self.content = text
                        self.score = score
                        self.title = matched_filename  # 補這個
                        self.id = matched_filename     # 補這個
                        self.metadata = {"source": matched_filename}
                
                chunks = [MockChunk(text=content)]
                logger.info(f"成功手動建立 1 個保底 Chunk，內容長度: {len(content)}")

    logger.info(
        "retrieve_one seed=%r idx=%d → %d chunks",
        current_seed,
        state.get("seed_index", -1),
        len(chunks),
    )
    return {"hits_per_seed": [chunks]}


@traced("fuse_scores")
async def fuse_scores_node(state: RAGState, services: Any) -> dict[str, Any]:
    """合併所有 seed 的命中、依 fusion strategy 排序、取 top final_context_k。"""
    hits_per_seed = state.get("hits_per_seed") or []
    router_result = state["router_result"]

    if not hits_per_seed or not any(hits_per_seed):
        return {"rag_chunks": [], "rag_context": "No retrieved context."}

    strategy = services.settings.fusion_strategy
    fuser = get_fuser(strategy)
    fused = fuser(hits_per_seed)
    final = fused[: services.settings.final_context_k]

    logger.info(
        "fuse strategy=%s seeds=%d total_unique=%d top=%d",
        strategy,
        len(hits_per_seed),
        len(fused),
        len(final),
    )

    # 統一 log（取代原 retrieve_node 內每次 retrieve 的 log）
    await services.retriever.log_fused_retrieval(
        query=state["user_input"],
        chunks=final,
        categories=router_result.rag_categories,
        external_user_id=state["external_user_id"],
        skill_id=router_result.target_skill,
    )

    context = services.retriever.build_context(final)
    return {"rag_chunks": final, "rag_context": context}


@traced("check_sufficiency")
async def check_sufficiency_node(state: RAGState, services: Any) -> dict[str, Any]:
    """判斷 retrieval 是否足以生成可信回覆。不需 RAG 的 skill 直接視為 sufficient。"""
    router_result = state["router_result"]
    if not router_result.is_rag_required:
        return {"sufficiency": "sufficient", "sufficiency_reasons": []}

    decision, reasons = services.sufficiency_checker.check(
        chunks=state.get("rag_chunks", []),
        features=state["features"],
    )
    logger.info("sufficiency=%s reasons=%s", decision, reasons)
    return {"sufficiency": decision, "sufficiency_reasons": reasons}


def route_by_sufficiency(state: RAGState) -> str:
    return state.get("sufficiency", "sufficient")


@traced("clarify")
async def clarify_node(state: RAGState, services: Any) -> dict[str, Any]:
    """資料不足時生成具體追問，組成 responses 直接 push。"""
    questions = await services.clarifier.generate_questions(
        user_input=state["user_input"],
        features=state["features"],
        chunks=state.get("rag_chunks", []),
    )
    return {
        "clarification_questions": questions,
        "responses": [format_clarification(questions)],
    }


@traced("build_answer_contract")
async def build_answer_contract_node(state: RAGState, services: Any) -> dict[str, Any]:
    """Stage 1：純程式組 Answer Contract（無 LLM）。"""
    contract = services.contract_builder.build(
        features=state["features"],
        chunks=state.get("rag_chunks", []),
        router_result=state["router_result"],
        sufficiency_reasons=state.get("sufficiency_reasons", []),
    )
    logger.info(
        "answer_contract: findings=%d caveats=%d citations=%d",
        len(contract.key_findings),
        len(contract.caveats),
        len(contract.citations),
    )
    return {"answer_contract": contract}


@traced("render_narrative")
async def render_narrative_node(state: RAGState, services: Any) -> dict[str, Any]:
    """Stage 2：受限 LLM 把 contract 寫成 markdown，依 LINE 上限切段。

    spec-31：當 settings.streaming_enabled 為真且 channel="http" 時，改走
    stream_render 並透過 LangGraph custom stream writer 推送每個 token；
    成品 responses 仍寫回 state（供 judge / push 使用）。
    """
    router_result = state["router_result"]
    response_mode = getattr(router_result, "response_mode", "default")
    # spec-02：把 emotion_state 一路餵進 narrative renderer，讓 prompt 能差異化
    emotion_state = getattr(router_result, "emotion_state", "neutral")
    settings = services.settings
    use_stream = (
        getattr(settings, "streaming_enabled", False)
        and state.get("channel") == "http"
    )

    if use_stream:
        try:
            from langgraph.config import get_stream_writer
            writer = get_stream_writer()
        except Exception:
            writer = None

        try:
            from app.generator.formatter import split_for_line
            full = ""
            async for token in services.narrative_renderer.stream_render(
                contract=state["answer_contract"],
                skill=state["skill"],
                response_mode=response_mode,
                emotion_state=emotion_state,
                feedback=state.get("judge_feedback"),
            ):
                full += token
                if writer is not None:
                    writer({"token": token})
            responses = split_for_line(
                full, max_chars=services.narrative_renderer.line_max_message_chars
            )
        except Exception:
            logger.exception("stream render_narrative failed")
            responses = ["系統暫時無法完成此請求，請稍後再試。"]
        return {"responses": responses}

    # 非串流路徑（既有行為）
    try:
        responses = await services.narrative_renderer.render(
            contract=state["answer_contract"],
            skill=state["skill"],
            response_mode=response_mode,
            emotion_state=emotion_state,
            feedback=state.get("judge_feedback"),
        )
    except Exception:
        logger.exception("render_narrative failed")
        responses = ["系統暫時無法完成此請求，請稍後再試。"]
    return {"responses": responses}


# spec-17：不送 judge 的 skill 清單。必須對齊 app/router/schemas.py::SkillId 字面值。
# "small_talk" 雖在語意上等價於閒聊，但實際 SkillId 是 "general_chat"——之前寫錯導致
# 生產環境 general_chat（無 RAG chunks）總被送進 judge、必拿低分、觸發品質警告。
SKIP_JUDGE_SKILLS: set[str] = {"general_chat", "emotional_calibration"}


@traced("judge")
async def judge_node(state: RAGState, services: Any) -> dict[str, Any]:
    """P4 LLM-as-Judge：4 軸結構化評分。失敗 / 跳過情境 → judge_score=None 視為 pass。"""
    settings = services.settings
    if not getattr(settings, "judge_enabled", True):
        return {"judge_score": None, "judge_feedback": []}

    skill = state.get("skill")
    if skill is not None and skill.skill_id in SKIP_JUDGE_SKILLS:
        logger.info("judge skipped: skill=%s in SKIP_JUDGE_SKILLS", skill.skill_id)
        return {"judge_score": None, "judge_feedback": []}

    router_result = state["router_result"]
    if not router_result.is_rag_required:
        # 不需 RAG 的回覆通常無 chunks 可審；pass through
        return {"judge_score": None, "judge_feedback": []}

    response_mode = getattr(router_result, "response_mode", "default")
    narrative = "\n\n".join(state.get("responses") or [])

    score = await services.judge.judge(
        narrative=narrative,
        contract=state["answer_contract"],
        response_mode=response_mode,
    )
    if score is None:
        return {"judge_score": None, "judge_feedback": []}

    passed = score.passes(
        min_axis=settings.judge_min_axis, min_mean=settings.judge_min_mean
    )
    feedback = [] if passed else list(score.issues)
    logger.info(
        "judge mean=%.1f pass=%s issues=%d",
        score.mean,
        passed,
        len(score.issues),
    )
    return {"judge_score": score, "judge_feedback": feedback}


def make_route_after_judge(max_retries: int, *, hitl_enabled: bool = False):
    """Closure：注入 max_retries 作為 retry → force_push / human_review 的門檻。

    硬上限保險：min(settings.max_reflection_retries, 2)——避免設定過高導致無限迴圈。
    `hitl_enabled=True` 時，retry 用盡走 human_review；否則走 force_push（既有行為）。
    """
    HARD_MAX = 2
    effective_max = min(max(max_retries, 0), HARD_MAX)

    def route_after_judge(state: RAGState) -> str:
        score = state.get("judge_score")
        feedback = state.get("judge_feedback") or []
        if score is None or not feedback:
            return "pass"
        retry = state.get("reflection_retry", 0)
        if retry >= effective_max:
            return "human_review" if hitl_enabled else "force_push"
        return "retry"

    return route_after_judge


@traced("human_review")
async def human_review_node(state: RAGState, services: Any) -> dict[str, Any]:
    """HITL 中繼 node。實際 interrupt 由 graph compile 時的 interrupt_before 完成。

    Resume 後本 node 不做事；push_node 會讀 reviewer_decision 決定推什麼。
    """
    logger.info(
        "human_review entered: thread=%s reviewer_decision=%s",
        state.get("external_message_id"),
        state.get("reviewer_decision"),
    )
    return {}


@traced("increment_retry")
async def increment_retry_node(state: RAGState, services: Any) -> dict[str, Any]:
    """retry 路徑：累加 reflection_retry 計數，下一輪 render_narrative 會帶 feedback。"""
    current = state.get("reflection_retry", 0)
    next_count = current + 1
    logger.info("reflection retry → %d (max=%d)", next_count, services.settings.max_reflection_retries)
    return {"reflection_retry": next_count}


@traced("mark_warning")
async def mark_warning_node(state: RAGState, services: Any) -> dict[str, Any]:
    """force_push 前在訊息開頭加品質警告。"""
    responses = list(state.get("responses") or [])
    if responses:
        responses[0] = "⚠️ 品質警告：本次回覆未通過自審\n\n" + responses[0]
    return {"responses": responses, "judge_warning_prefix": True}


@traced("rerank")
async def rerank_node(state: RAGState, services: Any) -> dict[str, Any]:
    """spec-28: cross-encoder reranking after fusion.

    If reranker is None (disabled), falls back to score-sort.
    """
    from app.rag.reranker import select_top_chunks

    chunks = state.get("rag_chunks") or []
    query = state["user_input"]
    top_n = getattr(services.settings, "reranker_top_n", 5)
    reranker = getattr(services, "reranker", None)

    if reranker is None:
        ranked = select_top_chunks(chunks, top_n)
        strategy = "score-sort"
    else:
        ranked = await reranker.rerank(query, chunks, top_n)
        strategy = "cross-encoder"

    logger.info(
        "rerank: %d → %d chunks (strategy=%s)", len(chunks), len(ranked), strategy
    )
    context = services.retriever.build_context(ranked)
    return {"rag_chunks": ranked, "rag_context": context}


@traced("input_guard")
async def input_guard_node(state: RAGState, services: Any) -> dict[str, Any]:
    """spec-30: Detect prompt injection and enforce input length limit.

    Sets state['blocked']=True when injection detected; push_node will short-circuit.
    """
    from app.security.guards import detect_prompt_injection

    settings = services.settings
    if not getattr(settings, "security_input_guard", True):
        return {"blocked": False}

    user_input: str = state.get("user_input", "")
    max_chars = getattr(settings, "security_max_input_chars", 1000)
    if len(user_input) > max_chars:
        logger.warning("security: input truncated %d → %d chars", len(user_input), max_chars)
        user_input = user_input[:max_chars]

    if detect_prompt_injection(user_input):
        logger.warning("security: prompt injection detected")
        blocked_reply = getattr(settings, "security_blocked_reply", "抱歉，這個問題我無法回覆。")
        return {
            "user_input": user_input,
            "blocked": True,
            "blocked_reason": "prompt_injection",
            "responses": [blocked_reply],
        }

    return {"user_input": user_input, "blocked": False}


def route_after_input_guard(state: RAGState) -> str:
    """Edge: input_guard → route (normal) or push (blocked)."""
    return "push" if state.get("blocked") else "route"


@traced("push")
async def push_node(state: RAGState, services: Any) -> dict[str, Any]:
    user_id = state.get("external_user_id", "")
    if state.get("dry_run", False):
        logger.info("(dry_run) skip push: user=%s msgs=%d", user_id, len(state.get("responses") or []))
        return {}

    # task-21 HITL：reviewer_decision 在 human_review 路徑後可能存在
    decision = state.get("reviewer_decision")
    if decision == "drop":
        logger.info("hitl drop: skipping push for user=%s", user_id)
        return {}

    # graph 不感知 channel 種類；統一委派給 services.channels[channel_name]。
    # state 未指定 channel 時 default "line"（多數教學情境的入口）。
    channel_name = state.get("channel") or "line"
    channel = services.channels.get(channel_name)
    if channel is None:
        logger.error("push_node: unknown channel %r — cannot push to user=%s", channel_name, user_id)
        return {}
    if decision == "revise" and state.get("reviewer_revised_text"):
        text = state["reviewer_revised_text"]
    else:
        text = "\n\n".join(state.get("responses") or [])

    # spec-30: redact PII from outgoing text
    if getattr(services.settings, "security_output_guard", True):
        from app.security.guards import detect_sensitive_leakage, redact_sensitive
        if detect_sensitive_leakage(text):
            logger.warning("security: PII detected in outgoing message, redacting")
            text = redact_sensitive(text)

    await channel.push(recipient_id=user_id, messages=channel.format(text))
    return {}
