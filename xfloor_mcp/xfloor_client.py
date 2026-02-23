"""Typed async client for xFloor HTTP APIs."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx


class XFloorClient:
    """Async HTTP wrapper around xFloor APIs."""

    def __init__(self, base_url: str, timeout_seconds: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def _headers(self, auth_token: str) -> dict[str, str]:
        if not auth_token or not auth_token.strip():
            raise ValueError("Missing auth token. Provide a valid Bearer token.")
        return {"Authorization": f"Bearer {auth_token.strip()}"}

    async def _request_json(
        self,
        method: str,
        path: str,
        auth_token: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/{path.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=self._headers(auth_token),
                params=params,
                json=json_body,
                data=data,
                files=files,
            )
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {"data": payload}

    async def query_memory(
        self,
        auth_token: str,
        *,
        user_id: str,
        query: str,
        floor_ids: list[str],
        filters: dict[str, Any] | None = None,
        k: int | None = None,
        include_metadata: str = "0",
        summary_needed: str = "0",
        app_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "user_id": user_id,
            "query": query,
            "floor_ids": floor_ids,
            "include_metadata": include_metadata,
            "summary_needed": summary_needed,
        }
        if filters is not None:
            body["filters"] = filters
        if k is not None:
            body["k"] = k
        if app_id:
            body["app_id"] = app_id
        return await self._request_json("POST", "/agent/memory/query", auth_token, json_body=body)

    async def create_event(
        self,
        auth_token: str,
        *,
        input_info: str,
        app_id: str | None = None,
        files: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        form_data: dict[str, str] = {"input_info": input_info}
        if app_id:
            form_data["app_id"] = app_id

        request_files: list[tuple[str, tuple[str, bytes, str]]] = []
        for item in files or []:
            filename = item.get("filename")
            content_base64 = item.get("content_base64")
            mime_type = item.get("mime_type")
            if not filename or not content_base64:
                raise ValueError("Each file requires filename and content_base64.")
            decoded = base64.b64decode(content_base64)
            request_files.append(("files", (filename, decoded, mime_type or "application/octet-stream")))

        return await self._request_json(
            "POST",
            "/api/memory/events",
            auth_token,
            data=form_data,
            files=request_files or None,
        )

    async def recent_events(self, auth_token: str, *, params: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json("GET", "/api/memory/recent/events", auth_token, params=params)

    async def get_floor_info(self, auth_token: str, *, floor_id: str) -> dict[str, Any]:
        floor_id = floor_id.strip()
        if not floor_id:
            raise ValueError("floor_id cannot be empty.")
        return await self._request_json("GET", f"/api/memory/floor/info/{floor_id}", auth_token)

    @staticmethod
    def validate_input_info(input_info: str) -> None:
        """Validate required keys inside input_info JSON string."""

        try:
            payload = json.loads(input_info)
        except json.JSONDecodeError as exc:
            raise ValueError("input_info must be a valid JSON string.") from exc

        required = {"floor_id", "block_id", "user_id", "title", "description"}
        missing = sorted(key for key in required if not payload.get(key))
        if missing:
            raise ValueError(f"input_info is missing required field(s): {', '.join(missing)}")
