from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.chat import router as chat_router
from app.api.stream import router as stream_router
from app.config import get_settings
from app.dependencies import (
    get_runtime_services,
    get_supabase_client,
    replace_skill_registry,
)
from app.line.webhook import router as line_router
from app.observability.logger import configure_observability
from app.skills.registry import SkillRegistry, skill_reload_loop

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """spec-08 §Reload + spec-22 §observability：startup hook 集中處理。"""
    settings = get_settings()
    configure_observability(settings)

    reload_task: asyncio.Task | None = None
    if settings.skill_source == "supabase":
        supabase = get_supabase_client()
        try:
            registry = await SkillRegistry.from_supabase(supabase)
            replace_skill_registry(registry)
            logger.info(
                "skills loaded from supabase: count=%d", len(registry.list())
            )
        except Exception as exc:
            # Fallback to file-based registry (already loaded by dependencies)
            logger.warning(
                "SKILL_SOURCE=supabase but initial load failed (%s); "
                "falling back to file-based registry", exc,
            )
            registry = get_runtime_services().skill_registry

        if settings.skill_reload_interval > 0:
            reload_task = asyncio.create_task(
                skill_reload_loop(
                    registry, supabase, settings.skill_reload_interval
                ),
                name="skill_reload_loop",
            )

    try:
        yield
    finally:
        if reload_task is not None:
            reload_task.cancel()
            try:
                await reload_task
            except asyncio.CancelledError:
                pass  # 正常 shutdown 路徑
            except Exception as exc:
                logger.warning("skill_reload_loop shutdown raised: %r", exc)


def create_app() -> FastAPI:
    app = FastAPI(title="project-linebot-rag-skills", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(line_router)
    app.include_router(chat_router)
    app.include_router(stream_router)
    return app


app = create_app()
