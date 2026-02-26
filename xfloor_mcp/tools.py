"""MCP tool registration for xFloor APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from .request_context import get_auth_token
from .xfloor_client import XFloorClient


class XFloorQueryMemoryInput(BaseModel):
    user_id: str
    query: str
    floor_ids: list[str]
    filters: dict[str, Any] | None = None
    k: int | None = Field(default=None, ge=1)
    include_metadata: str = Field(default="0", pattern="^[01]$")
    summary_needed: str = Field(default="0", pattern="^[01]$")
    auth_token: str | None = Field(default=None, description="Optional override token; usually resolved from Authorization header")


class XFloorFileInput(BaseModel):
    filename: str
    content_base64: str
    mime_type: str | None = "application/octet-stream"


class XFloorCreateEventInput(BaseModel):
    input_info: str = Field(description="JSON string including floor_id, block_id, user_id, title, description")
    files: list[XFloorFileInput] | None = None
    auth_token: str | None = None


class XFloorRecentEventsInput(BaseModel):
    floor_id: str | None = None
    page: int | None = Field(default=None, ge=1)
    limit: int | None = Field(default=None, ge=1, le=200)
    start_time: str | None = None
    end_time: str | None = None
    event_type: str | None = None
    extra_params: dict[str, Any] | None = Field(default=None, description="Any additional query params from docs")
    auth_token: str | None = None


class XFloorGetFloorInfoInput(BaseModel):
    floor_id: str
    auth_token: str | None = None


class XFloorWaitForIngestionInput(BaseModel):
    floor_id: str
    match_text: str
    timeout_s: int = Field(default=30, ge=1, le=600)
    poll_interval_s: int = Field(default=2, ge=1, le=60)
    auth_token: str | None = None

    @field_validator("match_text")
    @classmethod
    def _validate_match_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("match_text cannot be empty")
        return value


def _extract_auth_token(ctx: Any, token_override: str | None) -> str:
    """Resolve auth token from explicit input, request headers, or context var."""

    if token_override and token_override.strip():
        return token_override.strip()

    candidates = [
        getattr(ctx, "request", None),
        getattr(ctx, "http_request", None),
        getattr(ctx, "raw_request", None),
        getattr(ctx, "fastapi_request", None),
    ]

    for request_obj in candidates:
        headers = getattr(request_obj, "headers", None)
        if not headers:
            continue
        header = headers.get("authorization") or headers.get("Authorization")
        if header and header.lower().startswith("bearer "):
            return header[7:].strip()

    context_token = get_auth_token()
    if context_token:
        return context_token

    raise ValueError("Missing Bearer auth token. Set Authorization header or provide auth_token.")


def _compact(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    return {"data": data}


def register_tools(mcp: Any, client: XFloorClient) -> None:
    """Register MCP tools on the provided FastMCP instance."""

    @mcp.tool(name="xfloor_query_memory", description="Query xFloor memory")
    async def xfloor_query_memory(input: XFloorQueryMemoryInput, ctx: Any = None) -> dict[str, Any]:
        token = _extract_auth_token(ctx, input.auth_token)
        result = await client.query_memory(
            token,
            user_id=input.user_id,
            query=input.query,
            floor_ids=input.floor_ids,
            filters=input.filters,
            k=input.k,
            include_metadata=input.include_metadata,
            summary_needed=input.summary_needed,
        )
        return _compact(result)

    @mcp.tool(name="xfloor_create_event", description="Create xFloor memory event")
    async def xfloor_create_event(input: XFloorCreateEventInput, ctx: Any = None) -> dict[str, Any]:
        token = _extract_auth_token(ctx, input.auth_token)
        client.validate_input_info(input.input_info)
        files = [file.model_dump() for file in input.files] if input.files else None
        result = await client.create_event(token, input_info=input.input_info, files=files)
        return _compact(result)

    @mcp.tool(name="xfloor_recent_events", description="Get recent xFloor memory events")
    async def xfloor_recent_events(input: XFloorRecentEventsInput, ctx: Any = None) -> dict[str, Any]:
        token = _extract_auth_token(ctx, input.auth_token)
        params: dict[str, Any] = {}
        for key in ["floor_id", "page", "limit", "start_time", "end_time", "event_type"]:
            value = getattr(input, key)
            if value is not None:
                params[key] = value
        if input.extra_params:
            params.update(input.extra_params)
        result = await client.recent_events(token, params=params)
        return _compact(result)

    @mcp.tool(name="xfloor_get_floor_info", description="Get floor info by floor_id")
    async def xfloor_get_floor_info(input: XFloorGetFloorInfoInput, ctx: Any = None) -> dict[str, Any]:
        token = _extract_auth_token(ctx, input.auth_token)
        result = await client.get_floor_info(token, floor_id=input.floor_id)
        return _compact(result)

    @mcp.tool(name="xfloor_wait_for_ingestion", description="Poll recent events until text appears in title/description")
    async def xfloor_wait_for_ingestion(input: XFloorWaitForIngestionInput, ctx: Any = None) -> dict[str, Any]:
        import asyncio

        token = _extract_auth_token(ctx, input.auth_token)
        target = input.match_text.lower()
        elapsed = 0

        while elapsed <= input.timeout_s:
            events_payload = await client.recent_events(token, params={"floor_id": input.floor_id, "limit": 50})
            events = events_payload.get("events")
            if not isinstance(events, list):
                for key in ("data", "results", "items"):
                    if isinstance(events_payload.get(key), list):
                        events = events_payload[key]
                        break
            events = events or []

            for event in events:
                if not isinstance(event, dict):
                    continue
                title = str(event.get("title", "")).lower()
                description = str(event.get("description", "")).lower()
                if target in title or target in description:
                    return {"found": True, "event": event, "elapsed_s": elapsed}

            await asyncio.sleep(input.poll_interval_s)
            elapsed += input.poll_interval_s

        return {
            "found": False,
            "elapsed_s": elapsed,
            "message": f"No matching event found for '{input.match_text}' in floor {input.floor_id}.",
        }
