"""Streaming SSE endpoint for HTTP channel (spec-31).

Two modes：
1. streaming_enabled=False → 跑完整 graph，單次回傳完整文字（仍走 SSE 格式）
2. streaming_enabled=True  → 用 LangGraph custom stream writer 即時推送每個 token；
   render_narrative_node 偵測到 channel="http" + streaming_enabled 時改走 stream_render

HTTP 層保護（即使是教學專案，也避免 trivially DoS）：
- 拒絕 body > MAX_BODY_BYTES
- 拒絕 query 字串 > settings.security_max_input_chars
- 限制同一進程同時最多 MAX_CONCURRENT_STREAMS 條 SSE 連線
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.dependencies import get_runtime_services

logger = logging.getLogger(__name__)

router = APIRouter()


# ── HTTP-layer rate / size guards ────────────────────────────────────────────

# 32 KB 對 JSON request 已綽綽有餘；超過視為惡意
MAX_BODY_BYTES = 32 * 1024
# 同進程最多 32 條同時 SSE 連線（教學版預設；生產環境建議搭配 reverse proxy 限流）
MAX_CONCURRENT_STREAMS = 32

_stream_slots = asyncio.Semaphore(MAX_CONCURRENT_STREAMS)


@router.post("/api/stream/query")
async def stream_query(request: Request):
    """Server-Sent Events endpoint：依 streaming_enabled 切換真串流 / 單次回覆。

    Body:  {"query": "...", "thread_id": "..."}
    SSE:   data: {"token": "..."}\\n\\n  (per delta)
           data: {"done": true}\\n\\n     (terminator)
    """
    # Body size guard — 在解析 JSON 前先擋
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request body too large")

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="request body too large")

    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    query: str = body.get("query", "")
    thread_id: str = body.get("thread_id", "default")

    services = get_runtime_services()
    settings = services.settings

    # Query length guard — 與 input_guard 相同上限
    max_chars = getattr(settings, "security_max_input_chars", 1000)
    if len(query) > max_chars:
        raise HTTPException(
            status_code=413, detail=f"query exceeds {max_chars} chars"
        )

    # Concurrency guard — 全部 slot 都被占用就直接 503，不讓 SSE response 長時間 hang。
    # 之前的版本訪問 asyncio.Semaphore._value 私有屬性（CPython 內部，未來版本可改）；
    # 改用公開的 `locked()`（slot 全占用時為 True）。
    # 殘留的 TOCTOU window 寬度為微秒級，最壞情況偶爾多放 1 條；
    # 教學版預設可接受，生產環境建議搭配 reverse proxy 限流（見檔頭 docstring）。
    if _stream_slots.locked():
        raise HTTPException(status_code=503, detail="too many concurrent streams")

    # spec-21：每次 invocation 帶 thread_id config（即使 HITL 不開、checkpointer
    # 仍能正常持久化 state）。
    graph_config = {"configurable": {"thread_id": thread_id}}

    # ── Mode 1: streaming disabled ─────────────────────────────────────────
    if not getattr(settings, "streaming_enabled", False):
        async def single_event():
            async with _stream_slots:
                state = {
                    "user_input": query,
                    "external_user_id": thread_id,
                    "channel": "http",
                    "dry_run": True,
                }
                try:
                    result = await services.rag_graph.ainvoke(state, config=graph_config)
                    text = "\n\n".join(result.get("responses") or [""])
                    yield f"data: {json.dumps({'token': text})}\n\n"
                except Exception:
                    logger.exception("stream_query (single) error")
                    yield f"data: {json.dumps({'token': '系統暫時無法完成此請求'})}\n\n"
                yield f"data: {json.dumps({'done': True})}\n\n"
        return StreamingResponse(single_event(), media_type="text/event-stream")

    # ── Mode 2: streaming enabled — custom stream writer ───────────────────
    async def event_stream():
        # SSE 是輸出 channel，dry_run=True 讓 push_node 不再送一次
        async with _stream_slots:
            state = {
                "user_input": query,
                "external_user_id": thread_id,
                "channel": "http",
                "dry_run": True,
            }
            try:
                async for chunk in services.rag_graph.astream(
                    state, config=graph_config, stream_mode="custom"
                ):
                    if isinstance(chunk, dict):
                        token = chunk.get("token", "")
                        if token:
                            yield f"data: {json.dumps({'token': token})}\n\n"
            except Exception:
                logger.exception("stream_query error")
                error_payload = json.dumps({'token': '\n[系統錯誤，請稍後再試]'})
                yield f"data: {error_payload}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
