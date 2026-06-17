"""Prompt cache repository — 對應 spec-05 §「介面契約」。

cache_key = sha256(f"{skill_id}:{knowledge_version}:{normalized_user_input}").
依 knowledge_version 失效：每次 ingest 後版本 +1，舊 cache_key 自然失配 → 重生。

未套用 schema（404）/ 暫時連不上 Supabase 時，所有方法都靜默回 None / no-op，
不打斷主流程（避免 cache 介面變成 production 的單點故障）。
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

from app.storage.supabase_client import SupabaseRestClient

logger = logging.getLogger(__name__)


def _describe(exc: Exception) -> str:
    """讓 silent fallback 的 log 能區分 schema 缺、網路、認證錯誤等情境。"""
    out = type(exc).__name__
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is not None:
        out += f"(status={status})"
    msg = str(exc)
    if msg:
        out += f" {msg[:120]}"
    return out

# spec-05 cache 命中前每次都查一次 knowledge_version，會把 cache 延遲收益吃掉一半。
# 用 in-process TTL cache：60 秒內共用同一個 version；ingest 後最多 60 秒延遲生效。
_KNOWLEDGE_VERSION_TTL_SECONDS = 60


def _normalize(user_input: str) -> str:
    return user_input.strip().lower()


def build_cache_key(
    *, skill_id: str, knowledge_version: int, user_input: str
) -> str:
    payload = f"{skill_id}:{knowledge_version}:{_normalize(user_input)}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class CacheRepository:
    def __init__(
        self,
        client: SupabaseRestClient,
        *,
        version_ttl_seconds: int = _KNOWLEDGE_VERSION_TTL_SECONDS,
    ) -> None:
        self._client = client
        self._version_ttl = version_ttl_seconds
        # (cached_version, cached_at_monotonic)；None 代表未 cache。
        self._version_cache: tuple[int, float] | None = None

    async def get(self, cache_key: str) -> str | None:
        try:
            rows = await self._client.select(
                "prompt_cache",
                {
                    "select": "response_text",
                    "cache_key": f"eq.{cache_key}",
                    "limit": "1",
                },
            )
        except Exception as exc:
            logger.warning("CacheRepository.get failed: %s", _describe(exc))
            return None
        if not rows:
            return None
        return rows[0].get("response_text")

    async def set(
        self,
        *,
        cache_key: str,
        user_input: str,
        skill_id: str,
        knowledge_version: int,
        response_text: str,
    ) -> None:
        try:
            await self._client.upsert(
                "prompt_cache",
                [
                    {
                        "cache_key": cache_key,
                        "user_input": user_input,
                        "skill_id": skill_id,
                        "knowledge_version": knowledge_version,
                        "response_text": response_text,
                    }
                ],
                on_conflict="cache_key",
            )
        except Exception as exc:
            logger.warning("CacheRepository.set failed: %s", _describe(exc))

    async def get_knowledge_version(self) -> int:
        """spec-05 §「Knowledge Version 來源」：取 private_knowledge 的 max version。

        - 命中 TTL cache：直接回快取值，省一次 Supabase 來回（cache 命中時延遲收益的關鍵）
        - 失敗 / 表空時回 0；不寫入 cache（下一次仍會嘗試），避免「Supabase 短暫不可用 →
          整段時間共用 version=0 cache 鍵」的滯後問題
        """
        if self._version_cache is not None:
            version, cached_at = self._version_cache
            if time.monotonic() - cached_at < self._version_ttl:
                return version

        try:
            rows = await self._client.select(
                "private_knowledge",
                {
                    "select": "knowledge_version",
                    "order": "knowledge_version.desc",
                    "limit": "1",
                },
            )
        except Exception as exc:
            logger.warning("get_knowledge_version failed: %s", _describe(exc))
            return 0
        if not rows:
            return 0
        version = int(rows[0].get("knowledge_version") or 0)
        self._version_cache = (version, time.monotonic())
        return version
