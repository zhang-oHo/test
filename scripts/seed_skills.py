from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.skills.registry import SkillRegistry
from app.storage.supabase_client import SupabaseRestClient


async def main() -> None:
    settings = get_settings()
    registry = SkillRegistry.from_directory(settings.skills_path)
    client = SupabaseRestClient(settings)
    await client.upsert(
        "ai_skills",
        [skill.to_seed_record() for skill in registry.list()],
        on_conflict="skill_id",
    )
    print(f"Seeded {len(registry.list())} skills into Supabase.")


if __name__ == "__main__":
    asyncio.run(main())
