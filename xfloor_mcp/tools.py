"""MCP tool registration for xFloor APIs."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .active_floor_state import get_active_floor_state, resolve_floor_reference, set_active_floor_state
from .request_context import get_active_floor_id, get_auth_mode, get_auth_token, get_user_id, get_xfloor_service_token
from .xfloor_client import XFloorClient

logger = logging.getLogger(__name__)


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
    filename: str | None = Field(default=None, description="Optional filename override")
    content_base64: str | None = Field(default=None, description="Base64 encoded file payload")
    file_path: str | None = Field(default=None, description="Optional local file path for environments that can hand off files by path")
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


class XFloorSetActiveFloorInput(BaseModel):
    floor_ref: str | None = Field(default=None, description="Floor reference like phari, @phari, croma, or @croma")
    floor_id: str | None = Field(default=None, description="Optional direct floor ID override")

    @model_validator(mode="before")
    @classmethod
    def _coerce_short_forms(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip()
            return {"floor_ref": normalized} if normalized else {}
        if isinstance(value, dict):
            candidate_floor_ref = value.get("floor_ref") or value.get("floor") or value.get("name")
            candidate_floor_id = value.get("floor_id") or value.get("id")
            if candidate_floor_ref is not None or candidate_floor_id is not None:
                return {
                    "floor_ref": candidate_floor_ref,
                    "floor_id": candidate_floor_id,
                }
        return value


class XFloorQueryCurrentFloorInput(BaseModel):
    query: str = Field(description="Natural-language question to ask about the currently active xFloor")
    topic: str | None = Field(default=None, description="Optional topic hint to improve retrieval focus")
    limit: int | None = Field(default=None, ge=1, le=20, description="Optional maximum number of results to consider")


class XFloorPostEventToCurrentFloorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, description="Optional short event title. If omitted, description will be used as title.")
    description: str = Field(description="Event details or body text")
    block_id: str | None = Field(default=None, description="Optional logical block identifier for the event")
    block_type: str | None = Field(default="note", description="Optional block type")
    location: str | None = Field(default=None, description="Optional event location")
    start_date: str | None = Field(default=None, description="Optional start date")
    start_time: str | None = Field(default=None, description="Optional start time")
    end_date: str | None = Field(default=None, description="Optional end date")
    end_time: str | None = Field(default=None, description="Optional end time")
    

def _extract_auth_token(ctx: Any, token_override: str | None) -> str:
    """Resolve auth token from explicit input, request headers, or context var."""

    auth_mode = get_auth_mode()
    service_token = get_xfloor_service_token()
    if auth_mode == "oauth":
        if service_token and service_token.strip():
            return service_token.strip()
        raise ValueError("Missing xFloor service token for downstream API call in oauth mode.")

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

    context_token = service_token or get_auth_token()
    if context_token:
        return context_token

    raise ValueError("Missing Bearer auth token. Set Authorization header or provide auth_token.")


def _require_context_user_id() -> str:
    user_id = get_user_id()
    if not user_id:
        raise ValueError("Missing xFloor user context. Provide X-XFloor-User-Id on the MCP request.")
    return user_id


def _resolve_active_floor_id() -> dict[str, str]:
    state = get_active_floor_state()
    if state:
        return {
            "floor_id": state["floor_id"],
            "floor_ref": state["floor_ref"],
            "source": "session_state",
        }

    header_floor_id = get_active_floor_id()
    if header_floor_id:
        return {
            "floor_id": header_floor_id,
            "floor_ref": header_floor_id,
            "source": "header_override",
        }

    raise ValueError("No active floor set. Please set one first (eg: @phari or use @croma).")


def _compact(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    return {"data": data}


def _extract_events_list(events_payload: dict[str, Any]) -> list[dict[str, Any]]:
    events = events_payload.get("events")
    if isinstance(events, list):
        return [event for event in events if isinstance(event, dict)]

    for key in ("data", "results", "items"):
        candidate = events_payload.get(key)
        if isinstance(candidate, list):
            return [event for event in candidate if isinstance(event, dict)]
    return []


def _build_post_event_payload(
    *,
    floor_id: str,
    user_id: str,
    title: str | None,
    description: str,
    block_id: str | None,
    block_type: str | None,
    location: str | None,
    start_date: str | None,
    start_time: str | None,
    end_date: str | None,
    end_time: str | None,
) -> tuple[dict[str, Any], str | None]:
    normalized_title = title.strip() if title and title.strip() else description
    normalized_block_id = block_id.strip() if block_id and block_id.strip() else None

    payload: dict[str, Any] = {
        "floor_id": floor_id,
        "user_id": user_id,
        "title": normalized_title,
        "description": description,
    }
    if normalized_block_id:
        payload["block_id"] = normalized_block_id
    if block_type:
        payload["block_type"] = block_type
    if location:
        payload["location"] = location
    if start_date:
        payload["start_date"] = start_date
    if start_time:
        payload["start_time"] = start_time
    if end_date:
        payload["end_date"] = end_date
    if end_time:
        payload["end_time"] = end_time
    return payload, normalized_block_id


def _queued_status(compact_result: dict[str, Any]) -> tuple[str, str]:
    result_text = json.dumps(compact_result).lower()
    queued = "submitted to queue" in result_text or "submitted to the queue" in result_text or '"queued"' in result_text
    status = "queued" if queued else "accepted"
    message = "Event submission accepted and queued." if queued else "Event submission accepted."
    return status, message


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
            events = _extract_events_list(events_payload)

            for event in events:
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

    @mcp.tool(
        name="xfloor_set_active_floor",
        description="Use this when the user explicitly wants to select or switch the current xFloor, for example with phrases like 'use @phari' or '@croma'. This stores the active floor for subsequent current-floor tools.",
    )
    async def xfloor_set_active_floor(input: XFloorSetActiveFloorInput, ctx: Any = None) -> dict[str, Any]:
        resolved = resolve_floor_reference(floor_ref=input.floor_ref, floor_id=input.floor_id)
        state = set_active_floor_state(floor_id=resolved["floor_id"], floor_ref=resolved["floor_ref"])
        return {
            "ok": True,
            "message": f"Active floor set to {state['floor_ref']}",
            "floor_ref": state["floor_ref"],
            "floor_id": state["floor_id"],
            "state_scope": "in_memory_session",
        }

    @mcp.tool(
        name="xfloor_query_current_floor",
        description="Use this when the user wants to ask a question about the currently active xFloor. This tool uses the active floor selected by xfloor_set_active_floor, with the request header acting only as an optional override/debug path.",
    )
    async def xfloor_query_current_floor(input: XFloorQueryCurrentFloorInput, ctx: Any = None) -> dict[str, Any]:
        token = _extract_auth_token(ctx, None)
        floor = _resolve_active_floor_id()
        user_id = _require_context_user_id()
        query_text = input.query if not input.topic else f"{input.query}\n\nTopic: {input.topic}"
        result = await client.query_memory(
            token,
            user_id=user_id,
            query=query_text,
            floor_ids=[floor["floor_id"]],
            k=input.limit,
            include_metadata="1",
            summary_needed="1",
        )
        return {
            "floor_id": floor["floor_id"],
            "floor_ref": floor["floor_ref"],
            "floor_source": floor["source"],
            "query": input.query,
            "result": _compact(result),
        }

    @mcp.tool(
        name="xfloor_post_event_to_current_floor",
        description="Text-only post tool for the currently active xFloor.",
    )
    async def xfloor_post_event_to_current_floor(input: XFloorPostEventToCurrentFloorInput, ctx: Any = None) -> dict[str, Any]:
        logger.info("xfloor_post_event_to_current_floor invoked (text-only)")
        token = _extract_auth_token(ctx, None)
        floor = _resolve_active_floor_id()
        logger.info("Active floor resolved floor_id=%s source=%s", floor["floor_id"], floor["source"])
        user_id = _require_context_user_id()
        logger.info(
            "Downstream auth path auth_mode=%s using_service_token=%s",
            get_auth_mode() or "unknown",
            bool(get_xfloor_service_token()),
        )

        payload, normalized_block_id = _build_post_event_payload(
            floor_id=floor["floor_id"],
            user_id=user_id,
            title=input.title,
            description=input.description,
            block_id=input.block_id,
            block_type=input.block_type,
            location=input.location,
            start_date=input.start_date,
            start_time=input.start_time,
            end_date=input.end_date,
            end_time=input.end_time,
        )
        normalized_title = payload["title"]

        input_info = json.dumps(payload)
        logger.info("Downstream xFloor create_event invoked")
        result = await client.create_event(token, input_info=input_info, files=None)
        compact_result = _compact(result)
        status, message = _queued_status(compact_result)
        logger.info("Queue acknowledgement handled status=%s", status)

        return {
            "floor_id": floor["floor_id"],
            "floor_ref": floor["floor_ref"],
            "floor_source": floor["source"],
            "accepted": True,
            "status": status,
            "verification_required": False,
            "posted": True,
            "message": message,
            "event": {
                "title": normalized_title,
                "description": input.description,
                "block_id": normalized_block_id,
                "location": input.location,
                "start_date": input.start_date,
                "start_time": input.start_time,
                "end_date": input.end_date,
                "end_time": input.end_time,
            },
            "result": compact_result,
        }
