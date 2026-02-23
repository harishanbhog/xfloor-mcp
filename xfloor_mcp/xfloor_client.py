"""Typed async client for xFloor HTTP APIs."""

from __future__ import annotations

from typing import Any

import httpx


class XFloorClient:
    """Simple async HTTP wrapper around xFloor APIs."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a request against xFloor and return parsed JSON content."""

        url = f"{self._base_url}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self._timeout_seconds, headers=self._headers()) as client:
            response = await client.request(method=method.upper(), url=url, params=params, json=json)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return payload
            return {"data": payload}

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.request("GET", path=path, params=params)

    async def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.request("POST", path=path, json=body)
