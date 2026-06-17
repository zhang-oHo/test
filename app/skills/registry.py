"""SkillRegistry — 對應 spec-08 §「兩種載入來源」+「Reload 機制」。

兩種來源：
- file：從 `skills/*/SKILL.md` 載入（預設、向後相容）
- supabase：從 `ai_skills` 資料表載入；可定時 reload

Reload 用單次 attribute rebind（Python GIL 下原子）；reader 看到的要嘛是
舊 dict、要嘛是新 dict，無半新半舊狀態。Supabase 拉取失敗時保留舊 skills，
記 warning，不中斷服務。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.skills.loader import SkillDefinition, load_skills

logger = logging.getLogger(__name__)


def _row_to_skill(row: dict[str, Any]) -> SkillDefinition | None:
    """ai_skills 表的 row → SkillDefinition；驗證失敗回 None 並 log。"""
    try:
        return SkillDefinition.model_validate(
            {
                "skill_id": row["skill_id"],
                "name": row["name"],
                "description": row["description"],
                "category": row["category"],
                "version": row.get("version") or "0.1.0",
                "use_when": row.get("use_when") or [],
                "avoid_when": row.get("avoid_when") or [],
                "default_temperature": row.get("default_temperature") or 0.4,
                "rag_categories": row.get("rag_categories") or [],
                "output_style": row.get("output_style") or {},
                "system_prompt": row["system_prompt"],
                "source_path": None,
            }
        )
    except Exception as exc:
        logger.warning(
            "skipping malformed ai_skills row skill_id=%s: %s",
            row.get("skill_id"), exc,
        )
        return None


class SkillRegistry:
    def __init__(self, skills: list[SkillDefinition]) -> None:
        # Python attribute rebind 在 GIL 下是原子的——reader（get/require/list）
        # 看到的要嘛是舊 dict、要嘛是新 dict，不會看到半新半舊狀態。因此 reload
        # 不需要 lock；之前的 asyncio.Lock 沒在保護任何東西（reader 也未取 lock），
        # 移除避免誤導未來改 code 的人覺得「有 lock 就有保護」。
        self._skills: dict[str, SkillDefinition] = {s.skill_id: s for s in skills}

    @classmethod
    def from_directory(cls, skills_root: Path) -> "SkillRegistry":
        return cls(load_skills(skills_root))

    @classmethod
    async def from_supabase(cls, supabase_client: Any) -> "SkillRegistry":
        """spec-08：從 `ai_skills` WHERE enabled=true 載入 SkillRegistry。

        失敗時 raise——首次啟動就讀不到應該明顯失敗、不要靜默退化成空 registry。
        Lifespan 內如果用 from_supabase 啟動失敗，會在 dependencies fallback 到
        from_directory。
        """
        skills = await _fetch_skills_from_supabase(supabase_client)
        if not skills:
            raise RuntimeError(
                "ai_skills returned 0 enabled rows; run scripts/seed_skills.py first"
            )
        return cls(skills)

    async def reload_from_supabase(self, supabase_client: Any) -> bool:
        """重抓 ai_skills，成功才原子替換 in-memory dict。回傳是否真的更新。

        spec-08 §Fallback：Supabase 失敗時保留舊 skills，log warning，不拋。
        """
        try:
            skills = await _fetch_skills_from_supabase(supabase_client)
        except Exception as exc:
            logger.warning("skill reload failed (keeping previous): %s", exc)
            return False
        if not skills:
            logger.warning("skill reload returned 0 rows; keeping previous")
            return False

        # 單次 attribute rebind；無需 lock（見 __init__ 註解）。
        self._skills = {s.skill_id: s for s in skills}
        logger.info("skills reloaded from supabase: count=%d", len(skills))
        return True

    def get(self, skill_id: str) -> SkillDefinition | None:
        return self._skills.get(skill_id)

    def require(self, skill_id: str) -> SkillDefinition:
        skill = self.get(skill_id)
        if skill is None:
            raise KeyError(f"Unknown skill: {skill_id}")
        return skill

    def list(self) -> list[SkillDefinition]:
        return list(self._skills.values())


async def _fetch_skills_from_supabase(client: Any) -> list[SkillDefinition]:
    rows = await client.select(
        "ai_skills",
        {"select": "*", "enabled": "eq.true"},
    )
    skills: list[SkillDefinition] = []
    for row in rows:
        skill = _row_to_skill(row)
        if skill is not None:
            skills.append(skill)
    return skills


async def skill_reload_loop(
    registry: SkillRegistry,
    supabase_client: Any,
    interval_seconds: int,
) -> None:
    """背景無限迴圈：每 interval 秒重抓一次 ai_skills。

    Lifespan 啟動時 `asyncio.create_task(skill_reload_loop(...))`，
    shutdown 時 task.cancel() 結束。CancelledError 視為正常結束。
    """
    if interval_seconds <= 0:
        logger.info("skill reload disabled (interval<=0)")
        return
    while True:
        try:
            await asyncio.sleep(interval_seconds)
            await registry.reload_from_supabase(supabase_client)
        except asyncio.CancelledError:
            logger.info("skill reload loop cancelled")
            raise
        except Exception:
            # reload_from_supabase 內部已 swallow，但保險：迴圈不該被任何 exc 殺掉
            logger.exception("skill reload loop hit unexpected error; continuing")
