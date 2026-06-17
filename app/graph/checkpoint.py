"""Checkpointer factory — 對應 spec-21 / task-21 步驟 2。

兩種預設 backend：
- `memory`：教學 / 測試用 InMemorySaver；每次 process restart 重置
- `sqlite`：跨 restart 持久化；需 `pip install -e ".[hitl]"` + 在 FastAPI startup
  hook 內 await async setup（本實作提供 build_sqlite_saver_async 給 startup 用）

`none`：不啟用 checkpointer（HITL / persistence 都關閉）。
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


def build_checkpointer(settings: Settings) -> Any | None:
    """同步建構：memory / none 立即可用。sqlite / postgres 回 None 並提示走 async setup。"""
    backend = settings.checkpoint_backend
    if backend in ("none", ""):
        return None
    if backend == "memory":
        from langgraph.checkpoint.memory import InMemorySaver
        return InMemorySaver()
    if backend == "sqlite":
        logger.warning(
            "checkpoint_backend=sqlite needs async setup; "
            "use build_sqlite_saver_async() in FastAPI startup hook. "
            "Falling back to None for now."
        )
        return None
    if backend == "postgres":
        # spec-21 §「Checkpointer 選擇」：與既有 Supabase 共用 connection。
        # 需 optional dep：`pip install -e ".[hitl-postgres]"`，且在 FastAPI
        # startup hook 內走 build_postgres_saver_async（PostgresSaver 需 setup）。
        logger.warning(
            "checkpoint_backend=postgres needs async setup; "
            "use build_postgres_saver_async() in FastAPI startup hook. "
            "Falling back to None for now."
        )
        return None
    raise ValueError(f"unknown checkpoint_backend: {backend!r}")


async def build_postgres_saver_async(conn_url: str) -> tuple[Any, Any]:
    """在 FastAPI startup（async context）建構 AsyncPostgresSaver。

    對應 spec-21 §「Checkpointer 選擇」postgres backend。
    需 `pip install -e ".[hitl-postgres]"`。

    回傳 `(saver, cm)` tuple — caller 必須在 shutdown 時 `await cm.__aexit__(None, None, None)`
    才不會洩漏 postgres 連線。

    用法（lifespan）：
        saver, cm = await build_postgres_saver_async(settings.supabase_db_url)
        services.checkpointer = saver
        services._checkpoint_cm = cm
        services.rag_graph = build_rag_graph(services)
        try:
            yield
        finally:
            await cm.__aexit__(None, None, None)
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    cm = AsyncPostgresSaver.from_conn_string(conn_url)
    saver = await cm.__aenter__()
    await saver.setup()
    return saver, cm


async def build_sqlite_saver_async(path: str) -> tuple[Any, Any]:
    """在 FastAPI startup（async context）建構 AsyncSqliteSaver。

    回傳 `(saver, conn)` — caller 必須在 shutdown 時 `await conn.close()`。

    用法（lifespan）：
        saver, conn = await build_sqlite_saver_async(settings.checkpoint_sqlite_path)
        services.checkpointer = saver
        services._checkpoint_conn = conn
        services.rag_graph = build_rag_graph(services)
        try:
            yield
        finally:
            await conn.close()
    """
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(path)
    saver = AsyncSqliteSaver(conn)
    await saver.setup()
    return saver, conn
