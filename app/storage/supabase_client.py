from __future__ import annotations

from typing import Any, Mapping

import httpx

from app.config import Settings


class SupabaseRestClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _headers(self) -> dict[str, str]:
        api_key = self._settings.supabase_service_role_key
        return {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept-Profile": self._settings.supabase_schema,
            "Content-Profile": self._settings.supabase_schema,
        }

    def _url(self, path: str) -> str:
        base = self._settings.supabase_url.rstrip("/")
        return f"{base}/rest/v1/{path.lstrip('/')}"

    async def rpc(self, function_name: str, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self._url(f"rpc/{function_name}"),
                headers=self._headers(),
                json=dict(payload),
            )
            response.raise_for_status()
            return response.json()

    async def insert(self, table: str, row: Mapping[str, Any]) -> None:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self._url(table),
                headers={**self._headers(), "Prefer": "return=minimal"},
                json=dict(row),
            )
            response.raise_for_status()

    async def upsert(
        self,
        table: str,
        rows: list[Mapping[str, Any]],
        *,
        on_conflict: str | None = None,
    ) -> None:
        params: dict[str, str] = {}
        if on_conflict:
            params["on_conflict"] = on_conflict
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                self._url(table),
                headers={
                    **self._headers(),
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                },
                params=params,
                json=[dict(row) for row in rows],
            )
            if response.status_code >= 400:
                # spec-X 偵錯：上傳失敗時把 PostgREST 的具體訊息帶上來，
                # 而不只是給一個沒線索的 HTTPStatusError
                import logging
                logging.getLogger(__name__).error(
                    "upsert %s failed: status=%s body=%s keys=%s",
                    table, response.status_code, response.text[:500],
                    sorted(rows[0].keys()) if rows else [],
                )
            response.raise_for_status()

    async def select(self, table: str, params: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                self._url(table),
                headers=self._headers(),
                params=dict(params or {}),
            )
            response.raise_for_status()
            return response.json()

    async def update(
        self,
        table: str,
        patch: Mapping[str, Any],
        *,
        filters: Mapping[str, str],
    ) -> None:
        """PostgREST PATCH — 只更新 patch 列的欄位，依 filters 篩 row（不會 INSERT）。

        `filters` 的 value 必須含 PostgREST operator prefix，例如 `eq.foo` / `in.(a,b)`。
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.patch(
                self._url(table),
                headers={**self._headers(), "Prefer": "return=minimal"},
                params=dict(filters),
                json=dict(patch),
            )
            response.raise_for_status()
