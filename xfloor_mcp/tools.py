"""MCP tool registration for xFloor APIs."""

from __future__ import annotations

import json
import inspect
import logging
import mimetypes
import os
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .active_floor_state import get_active_floor_state, resolve_floor_reference, set_active_floor_state
from .chatgpt_files import AttachmentBridgeError, download_chatgpt_attachment
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


class XFloorChatGPTAttachmentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    download_url: str | None = Field(default=None, description="ChatGPT attachment download URL")
    file_id: str | None = Field(default=None, description="ChatGPT file identifier")


XFloorChatGPTAttachmentParam = XFloorChatGPTAttachmentInput


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


class XFloorQueryCurrentFloorInput(BaseModel):
    query: str = Field(description="Natural-language question to ask about the currently active xFloor")
    topic: str | None = Field(default=None, description="Optional topic hint to improve retrieval focus")
    limit: int | None = Field(default=None, ge=1, le=20, description="Optional maximum number of results to consider")


class XFloorGetCurrentFloorEventsInput(BaseModel):
    limit: int | None = Field(default=10, ge=1, le=100, description="Maximum number of recent events to return")
    event_type: str | None = Field(default=None, description="Optional event type filter")


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
    

class XFloorPostEventWithAttachmentToCurrentFloorInput(BaseModel):
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
    attachment: XFloorChatGPTAttachmentParam = Field(
        description="Single official ChatGPT widget attachment object: {file_id, download_url}.",
    )


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


def _validate_post_event_attachments(files: list[XFloorFileInput] | None) -> list[dict[str, str]] | None:
    if not files:
        return None

    images: list[XFloorFileInput] = []
    videos: list[XFloorFileInput] = []
    pdfs: list[XFloorFileInput] = []

    for file in files:
        if not (file.content_base64 and file.content_base64.strip()) and not (file.file_path and file.file_path.strip()):
            raise ValueError("Each attachment requires either content_base64 or file_path.")
        mime = (file.mime_type or "").strip().lower()
        if not mime or mime == "application/octet-stream":
            candidate_name = (file.filename or "").strip()
            if not candidate_name and file.file_path:
                candidate_name = os.path.basename(file.file_path.strip())
            guessed, _ = mimetypes.guess_type(candidate_name)
            mime = (guessed or "").lower()
        if mime in {"image/png", "image/jpeg", "image/jpg"}:
            images.append(file)
        elif mime.startswith("video/"):
            videos.append(file)
        elif mime == "application/pdf":
            pdfs.append(file)
        else:
            raise ValueError(
                "Unsupported attachment type. Allowed: PNG/JPEG images, one video, or one PDF."
            )

    groups_present = sum(1 for group in (images, videos, pdfs) if group)
    if groups_present > 1:
        raise ValueError("Attachments must be either images OR one video OR one PDF (do not mix types).")

    if images and len(images) > 4:
        raise ValueError("You can attach up to 4 images (PNG/JPEG).")
    if videos and len(videos) != 1:
        raise ValueError("You can attach exactly 1 video.")
    if pdfs and len(pdfs) != 1:
        raise ValueError("You can attach exactly 1 PDF.")

    return [file.model_dump() for file in files]


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


def _build_post_widget_html() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>xFloor Post Widget</title>
    <style>
      body { font-family: system-ui, sans-serif; margin: 16px; }
      form { display: grid; gap: 8px; }
      input, textarea { width: 100%; box-sizing: border-box; }
      textarea { min-height: 96px; }
      .row { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
      .actions { display: flex; gap: 8px; }
      #status { font-size: 12px; color: #444; }
    </style>
  </head>
  <body>
    <h3>xFloor Post</h3>
    <form id="post-form">
      <input id="title" placeholder="Title (optional)" />
      <textarea id="description" placeholder="Description (required)" required></textarea>
      <div class="row">
        <input id="block_id" placeholder="Block ID (optional)" />
        <input id="block_type" placeholder="Block type (optional)" value="note" />
      </div>
      <input id="location" placeholder="Location (optional)" />
      <div class="row">
        <input id="start_date" placeholder="Start date" />
        <input id="start_time" placeholder="Start time" />
      </div>
      <div class="row">
        <input id="end_date" placeholder="End date" />
        <input id="end_time" placeholder="End time" />
      </div>
      <input id="file" type="file" accept="image/png,image/jpeg,application/pdf" />
      <div class="actions">
        <button type="button" id="pick-library">Choose from library</button>
        <button type="submit">Post</button>
      </div>
      <button type="button" id="cancel">Cancel</button>
    </form>
    <p id="status">Ready.</p>
    <script>
      const api = window.openai || {};
      const statusEl = document.getElementById("status");
      const form = document.getElementById("post-form");
      let selectedFile = null;
      const setStatus = (msg) => { statusEl.textContent = msg; };

      const field = (id) => document.getElementById(id).value?.trim();
      const buildArgs = () => ({
        title: field("title") || undefined,
        description: field("description"),
        block_id: field("block_id") || undefined,
        block_type: field("block_type") || undefined,
        location: field("location") || undefined,
        start_date: field("start_date") || undefined,
        start_time: field("start_time") || undefined,
        end_date: field("end_date") || undefined,
        end_time: field("end_time") || undefined,
      });

      document.getElementById("file").addEventListener("change", async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        if (typeof api.uploadFile !== "function" || typeof api.getFileDownloadUrl !== "function") {
          setStatus("File APIs are unavailable in this runtime.");
          return;
        }
        setStatus("Uploading file...");
        const upload = await api.uploadFile(file, { library: true });
        const fileId = upload?.fileId || upload?.id;
        if (!fileId) throw new Error("uploadFile did not return a fileId");
        setStatus("Resolving download URL...");
        const download = await api.getFileDownloadUrl({ fileId });
        selectedFile = { file_id: fileId, download_url: download?.downloadUrl || download?.url };
        if (!selectedFile.download_url) throw new Error("No download URL returned");
        setStatus("File ready.");
      });

      document.getElementById("pick-library").addEventListener("click", async () => {
        if (typeof api.selectFiles !== "function" || typeof api.getFileDownloadUrl !== "function") {
          setStatus("File library picker is unavailable in this runtime.");
          return;
        }
        const selected = await api.selectFiles();
        const first = Array.isArray(selected) ? selected[0] : selected?.files?.[0];
        const fileId = first?.fileId || first?.id;
        if (!fileId) {
          setStatus("No file selected.");
          return;
        }
        const download = await api.getFileDownloadUrl({ fileId });
        selectedFile = { file_id: fileId, download_url: download?.downloadUrl || download?.url };
        if (!selectedFile.download_url) throw new Error("No download URL returned");
        setStatus("Library file ready.");
      });

      document.getElementById("cancel").addEventListener("click", () => {
        if (typeof api.close === "function") api.close();
      });

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const args = buildArgs();
        if (!args.description) {
          setStatus("Description is required.");
          return;
        }
        if (typeof api.callTool !== "function") {
          setStatus("callTool API unavailable.");
          return;
        }
        if (selectedFile) {
          setStatus("Posting with attachment...");
          await api.callTool("xfloor_post_event_with_attachment_to_current_floor", { ...args, attachment: selectedFile });
        } else {
          setStatus("Posting text-only...");
          await api.callTool("xfloor_post_event_to_current_floor", args);
        }
        setStatus("Post submitted.");
      });
    </script>
  </body>
</html>"""


async def _resolve_attachment_input(
    attachment: XFloorChatGPTAttachmentParam,
) -> tuple[list[dict[str, str]], list[str], list[str]]:
    payload = attachment.model_dump()
    file_payload, file_id, filename = await download_chatgpt_attachment(payload)
    return [file_payload], [file_id], [filename]


def register_tools(mcp: Any, client: XFloorClient) -> None:
    """Register MCP tools on the provided FastMCP instance."""
    widget_resource_uri = "ui://xfloor/post-widget"
    widget_tool_meta = {
        "openai/outputTemplate": widget_resource_uri,
        "openai/toolInvocation/invoking": "Opening xFloor post widget",
        "openai/toolInvocation/invoked": "xFloor post widget opened",
    }

    tool_signature = inspect.signature(mcp.tool)
    supports_meta = "_meta" in tool_signature.parameters or any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in tool_signature.parameters.values()
    )

    def _register_post_widget_resource() -> None:
        if not hasattr(mcp, "resource"):
            logger.info("Widget resource registration skipped; MCP runtime has no resource API")
            return

        widget_html = _build_post_widget_html()
        logger.info("Widget resource registered uri=%s", widget_resource_uri)
        try:
            @mcp.resource(widget_resource_uri, name="xfloor-post-widget", mime_type="text/html")
            async def _xfloor_post_widget() -> str:
                return widget_html
            return
        except TypeError:
            pass

        try:
            @mcp.resource(uri=widget_resource_uri, name="xfloor-post-widget", mime_type="text/html")
            async def _xfloor_post_widget_kwargs() -> str:
                return widget_html
        except TypeError:
            logger.info("Widget resource registration failed due to incompatible runtime signature")

    _register_post_widget_resource()

    @mcp.tool(
        name="xfloor_open_post_widget",
        description="Default entry point for post/share/create intents. Opens the unified xFloor post widget for text-only or single-attachment posting.",
        **({"_meta": widget_tool_meta} if supports_meta else {}),
    )
    async def xfloor_open_post_widget() -> dict[str, Any]:
        logger.info("Widget opened for posting intent")
        return {
            "ok": True,
            "message": "xFloor post widget opened. Submit text-only or one attachment from the widget.",
            "widget": {"resource_uri": widget_resource_uri},
        }

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
        name="xfloor_get_current_floor_events",
        description="Use this when the user wants recent or upcoming events from the currently active xFloor. This tool uses the active floor selected by xfloor_set_active_floor, with the request header acting only as an optional override/debug path.",
    )
    async def xfloor_get_current_floor_events(input: XFloorGetCurrentFloorEventsInput, ctx: Any = None) -> dict[str, Any]:
        token = _extract_auth_token(ctx, None)
        floor = _resolve_active_floor_id()
        params: dict[str, Any] = {"floor_id": floor["floor_id"]}
        if input.limit is not None:
            params["limit"] = input.limit
        if input.event_type:
            params["event_type"] = input.event_type
        result = await client.recent_events(token, params=params)
        events = _extract_events_list(result)
        return {
            "floor_id": floor["floor_id"],
            "floor_ref": floor["floor_ref"],
            "floor_source": floor["source"],
            "count": len(events),
            "events": events,
        }

    @mcp.tool(
        name="xfloor_post_event_to_current_floor",
        description="Text-only post tool for the currently active xFloor. The unified post widget is the preferred UX for all posting intents; it routes file uploads to the attachment tool automatically.",
        **({"_meta": widget_tool_meta} if supports_meta else {}),
    )
    async def xfloor_post_event_to_current_floor(input: XFloorPostEventToCurrentFloorInput, ctx: Any = None) -> dict[str, Any]:
        logger.info("xfloor_post_event_to_current_floor invoked (text-only)")
        token = _extract_auth_token(ctx, None)
        floor = _resolve_active_floor_id()
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
        result = await client.create_event(token, input_info=input_info, files=None)
        compact_result = _compact(result)
        status, message = _queued_status(compact_result)

        return {
            "floor_id": floor["floor_id"],
            "floor_ref": floor["floor_ref"],
            "floor_source": floor["source"],
            "accepted": True,
            "status": status,
            "verification_required": False,
            "posted": True,
            "message": message,
            "attachments_received": 0,
            "attachment_file_ids": [],
            "attachment_filenames": [],
            "event": {
                "title": normalized_title,
                "description": input.description,
                "block_id": normalized_block_id,
                "location": input.location,
                "start_date": input.start_date,
                "start_time": input.start_time,
                "end_date": input.end_date,
                "end_time": input.end_time,
                "attachments_count": 0,
            },
            "result": compact_result,
        }

    _post_event_attachment_tool_kwargs: dict[str, Any] = {
        "name": "xfloor_post_event_with_attachment_to_current_floor",
        "description": "Post an event with exactly one uploaded image or PDF in the currently active xFloor. The widget must pass top-level attachment={file_id, download_url}. Do not use local paths, base64, image_url, image_path, or nested wrappers.",
    }
    if supports_meta:
        _post_event_attachment_tool_kwargs["_meta"] = {
            "openai/fileParams": ["attachment"],
            **widget_tool_meta,
        }

    @mcp.tool(**_post_event_attachment_tool_kwargs)
    async def xfloor_post_event_with_attachment_to_current_floor(
        description: str,
        attachment: XFloorChatGPTAttachmentParam,
        title: str | None = None,
        block_id: str | None = None,
        block_type: str | None = "note",
        location: str | None = None,
        start_date: str | None = None,
        start_time: str | None = None,
        end_date: str | None = None,
        end_time: str | None = None,
        ctx: Any = None,
    ) -> dict[str, Any]:
        logger.info("xfloor_post_event_with_attachment_to_current_floor invoked")
        logger.info("Widget attachment submit path used")
        token = _extract_auth_token(ctx, None)
        floor = _resolve_active_floor_id()
        user_id = _require_context_user_id()
        logger.info(
            "Downstream auth path auth_mode=%s using_service_token=%s",
            get_auth_mode() or "unknown",
            bool(get_xfloor_service_token()),
        )

        payload, normalized_block_id = _build_post_event_payload(
            floor_id=floor["floor_id"],
            user_id=user_id,
            title=title,
            description=description,
            block_id=block_id,
            block_type=block_type,
            location=location,
            start_date=start_date,
            start_time=start_time,
            end_date=end_date,
            end_time=end_time,
        )
        normalized_title = payload["title"]

        try:
            chatgpt_files_payload, attachment_file_ids, attachment_filenames = await _resolve_attachment_input(
                attachment
            )
        except AttachmentBridgeError as exc:
            logger.info("Attachment bridge failure type=%s", exc.__class__.__name__)
            return {
                "floor_id": floor["floor_id"],
                "floor_ref": floor["floor_ref"],
                "floor_source": floor["source"],
                "accepted": False,
                "posted": False,
                "status": "failed",
                "verification_required": False,
                "attachment_bridge_failed": True,
                "attachments_received": 0,
                "message": "Attachment upload failed. The widget must provide attachment.file_id and attachment.download_url.",
                "error": str(exc),
            }

        files = [XFloorFileInput(**item) for item in (chatgpt_files_payload or [])]
        files_payload = _validate_post_event_attachments(files)
        if not files_payload or len(files_payload) != 1:
            return {
                "floor_id": floor["floor_id"],
                "floor_ref": floor["floor_ref"],
                "floor_source": floor["source"],
                "accepted": False,
                "posted": False,
                "status": "failed",
                "verification_required": False,
                "attachment_bridge_failed": True,
                "attachments_received": len(files_payload or []),
                "message": "Attachment tool requires exactly one official ChatGPT attachment (PNG/JPEG image or PDF).",
            }

        mime = (files_payload[0].get("mime_type") or "").lower()
        if mime not in {"image/png", "image/jpeg", "image/jpg", "application/pdf"}:
            return {
                "floor_id": floor["floor_id"],
                "floor_ref": floor["floor_ref"],
                "floor_source": floor["source"],
                "accepted": False,
                "posted": False,
                "status": "failed",
                "verification_required": False,
                "attachment_bridge_failed": True,
                "attachments_received": 0,
                "message": "Attachment tool supports exactly one PNG/JPEG image or one PDF from official ChatGPT file params.",
            }

        input_info = json.dumps(payload)
        result = await client.create_event(token, input_info=input_info, files=files_payload)
        logger.info("Downstream xFloor upload invoked for attachment tool")
        compact_result = _compact(result)
        status, message = _queued_status(compact_result)

        return {
            "floor_id": floor["floor_id"],
            "floor_ref": floor["floor_ref"],
            "floor_source": floor["source"],
            "accepted": True,
            "status": status,
            "verification_required": False,
            "posted": True,
            "message": message,
            "attachments_received": 1,
            "attachment_file_ids": attachment_file_ids,
            "attachment_filenames": attachment_filenames,
            "event": {
                "title": normalized_title,
                "description": description,
                "block_id": normalized_block_id,
                "location": location,
                "start_date": start_date,
                "start_time": start_time,
                "end_date": end_date,
                "end_time": end_time,
                "attachments_count": 1,
            },
            "result": compact_result,
        }
