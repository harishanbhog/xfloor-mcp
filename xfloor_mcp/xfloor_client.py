"""Typed async client for xFloor HTTP APIs."""

from __future__ import annotations

import base64
import json
from typing import Any, IO

import httpx

from .request_context import get_app_id, get_auth_token, get_user_id


class XFloorClient:
    """Async HTTP wrapper around xFloor APIs."""

    def __init__(self, base_url: str, timeout_seconds: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def _headers(self, auth_token: str) -> dict[str, str]:
        if not auth_token or not auth_token.strip():
            raise ValueError("Missing auth token. Provide a valid Bearer token.")
        return {"Authorization": f"Bearer {auth_token.strip()}"}

    def _context_params(self) -> dict[str, str]:
        user_id = get_user_id()
        app_id = get_app_id()
        if not user_id or not app_id:
            raise ValueError("Missing xFloor context. user_id/app_id must be set from headers or defaults.")
        return {"user_id": user_id, "app_id": app_id}

    async def _request_json(
        self,
        method: str,
        path: str,
        auth_token: str | None = None,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: list[tuple[str, tuple[str | None, str | bytes | IO[Any]] | tuple[str, bytes, str]]] | None = None,
        include_context_params: bool = True,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/{path.lstrip('/')}"
        resolved_token = auth_token or get_auth_token()
        merged_params = dict(params or {})
        if include_context_params:
            merged_params.update(self._context_params())
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.request(
                method=method.upper(),
                url=url,
                headers=self._headers(resolved_token or ""),
                params=merged_params,
                json=json_body,
                data=data,
                files=files,
            )
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {"data": payload}

    async def query_memory(
        self,
        auth_token: str | None = None,
        *,
        user_id: str,
        query: str,
        floor_ids: list[str],
        filters: dict[str, Any] | None = None,
        k: int | None = None,
        include_metadata: str = "0",
        summary_needed: str = "0",
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
        return await self._request_json("POST", "/agent/memory/query", auth_token, json_body=body)

    async def create_event(
        self,
        auth_token: str | None = None,
        *,
        input_info: str,
        files: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        ctx = self._context_params()
        request_files: list[tuple[str, tuple[str | None, str | bytes | IO[Any]] | tuple[str, bytes, str]]] = [
            ("input_info", (None, input_info)),
            ("user_id", (None, ctx["user_id"])),
            ("app_id", (None, ctx["app_id"])),
        ]

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
            params={},
            files=request_files,
            include_context_params=False,
        )

    async def recent_events(self, auth_token: str | None = None, *, params: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json("GET", "/api/memory/recent/events", auth_token, params=params)

    async def get_floor_info(self, auth_token: str | None = None, *, floor_id: str) -> dict[str, Any]:
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

        required = {"floor_id", "block_id", "title", "description"}
        missing = sorted(key for key in required if not payload.get(key))
        if missing:
            raise ValueError(f"input_info is missing required field(s): {', '.join(missing)}")
