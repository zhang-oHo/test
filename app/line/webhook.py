from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from app.dependencies import RuntimeServices, get_runtime_services
from app.observability.tracer import reset_current_tracer, set_current_tracer

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/api/line", tags=["line"])


@router.post("/webhook")
async def line_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    services: RuntimeServices = Depends(get_runtime_services),
) -> dict[str, bool]:
    """LINE webhook entry — 解析委派給 LineChannel。"""
    line_channel = services.channels["line"]
    _, inputs = await line_channel.parse_request(request)
    for inp in inputs:
        background_tasks.add_task(process_channel_input, inp, services)
    return {"ok": True}


async def process_channel_input(inp, services: RuntimeServices) -> None:
    """Channel-agnostic 入口：給定 ChannelInput 跑完整 graph。

    本檔在 task-23 前是 LINE-specific；現在 LINE 與 HTTP / 其他 channel 都走這條。
    """
    channel = services.channels.get(inp.channel)
    if channel is None:
        logger.error("process_channel_input: unknown channel %r — dropping message", inp.channel)
        return
    user_id = inp.external_user_id

    # —— inbound 落庫（DB column 仍叫 line_user_id，跨 channel 用同欄位）
    try:
        await services.messages_repo.save_message(
            line_user_id=user_id,
            direction="inbound",
            message_text=inp.raw_text,
        )
    except Exception:
        logger.warning("save_message inbound failed for user=%s", user_id, exc_info=True)

    recent_history = await channel.load_recent_history(external_user_id=user_id)

    initial_state = {
        "user_input": inp.raw_text,
        "channel": inp.channel,
        "external_user_id": user_id,
        "external_message_id": inp.external_message_id,
        "recent_history": recent_history,
        "dry_run": user_id.startswith(("U_demo", "U_eval")),
    }

    tracer = None
    token = None
    if services.tracer_registry is not None:
        tracer = services.tracer_registry.start(
            thread_id=channel.build_thread_id(inp),
            variant=services.settings.graph_variant,
        )
        token = set_current_tracer(tracer)

    settings = services.settings
    if getattr(settings, "streaming_enabled", False):
        placeholder = getattr(settings, "streaming_placeholder", "⏳ 思考中，請稍候...")
        try:
            await services.line_client.push_message(
                user_id, [{"type": "text", "text": placeholder}]
            )
        except Exception:
            logger.warning("Failed to send streaming placeholder")

    # spec-21：每次 invocation 都帶 thread_id config，否則 checkpointer + HITL
    # 都不會運作（LangGraph 沒有 thread_id 不會持久化 / 不會 interrupt）。
    thread_id = channel.build_thread_id(inp)
    graph_config = {"configurable": {"thread_id": thread_id}}

    final_state = None
    try:
        final_state = await services.rag_graph.ainvoke(initial_state, config=graph_config)
    except Exception:
        logger.exception("rag_graph invocation failed")
    finally:
        if token is not None:
            reset_current_tracer(token)
        if tracer is not None and services.tracer_registry is not None:
            try:
                await services.tracer_registry.async_write_trace(tracer)
            except Exception:
                logger.exception("write_trace failed")

    if final_state is None:
        return

    # spec-21：偵測 interrupt — 若 graph 在 push 前中斷（hitl_enabled + judge fail），
    # 只標記 pending review，不執行 outbound 落庫 / 推送，等 review_queue.py 接手。
    if await _is_interrupted(services.rag_graph, graph_config):
        try:
            await services.messages_repo.mark_pending_review(
                thread_id=thread_id, line_user_id=user_id
            )
        except Exception:
            logger.warning("mark_pending_review failed for thread=%s", thread_id, exc_info=True)
        return

    # —— outbound 落庫（讀 final_state）
    router_result = final_state.get("router_result")
    responses = final_state.get("responses", [])
    rag_chunks = final_state.get("rag_chunks", [])

    try:
        await services.messages_repo.save_message(
            line_user_id=user_id,
            direction="outbound",
            message_text="\n\n".join(responses),
            skill_id=router_result.target_skill if router_result else None,
            router_result=router_result.model_dump() if router_result else None,
            rag_used=bool(rag_chunks),
        )
    except Exception:
        logger.warning("save_message outbound failed for user=%s", user_id, exc_info=True)


async def _is_interrupted(graph, config: dict) -> bool:
    """spec-21：判斷 graph 是否在 interrupt_before 節點處中斷。

    LangGraph 中斷時 `aget_state(config).next` 會回傳 pending 節點名稱 tuple；
    無 checkpointer / 無 thread_id 時 aget_state 會拋例外，安全當作未中斷處理。
    """
    try:
        snapshot = await graph.aget_state(config)
    except Exception:
        return False
    return bool(getattr(snapshot, "next", ()))


# 向後相容：既有 test_line_webhook.py 直接測 process_text_event
async def process_text_event(event, services: RuntimeServices) -> None:
    """Backward-compat shim：把 LineEvent 包成 ChannelInput 後走 process_channel_input。"""
    from app.channels.base import ChannelInput

    user_id = event.source.user_id
    message = event.message
    if user_id is None or message is None or message.text is None:
        return
    inp = ChannelInput(
        channel="line",
        external_user_id=user_id,
        external_message_id=message.id or "",
        raw_text=message.text,
    )
    await process_channel_input(inp, services)
