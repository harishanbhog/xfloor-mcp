"""MCP tool registration for xFloor APIs."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .active_floor_state import clear_active_floor_state, get_active_floor_state, resolve_floor_reference, set_active_floor_state
from .request_context import get_active_floor_id, get_auth_mode, get_auth_token, get_user_id, get_xfloor_service_token
from .xfloor_client import XFloorClient

logger = logging.getLogger(__name__)
SET_ACTIVE_FLOOR_WIDGET_URI = "ui://widget/set-active-floor-v1.html"
DEFAULT_FLOOR_LOGO_DATA_URI = (
    "data:image/svg+xml;utf8,"
    "<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'>"
    "<rect width='120' height='120' rx='18' fill='%23E5E7EB'/>"
    "<circle cx='60' cy='48' r='18' fill='%239CA3AF'/>"
    "<rect x='28' y='78' width='64' height='12' rx='6' fill='%239CA3AF'/>"
    "</svg>"
)


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
            nested_input = value.get("input")
            if isinstance(nested_input, str):
                normalized_nested = nested_input.strip()
                return {"floor_ref": normalized_nested} if normalized_nested else {}
            if isinstance(nested_input, dict):
                value = nested_input
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


class XFloorClearActiveFloorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    

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
            "floor_handle": state.get("floor_handle"),
            "floor_title": state.get("floor_title"),
            "floor_description": state.get("floor_description"),
            "floor_tags": state.get("floor_tags") or [],
            "floor_logo_url": state.get("floor_logo_url"),
            "floor_blocks": state.get("floor_blocks") or [],
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


def _parse_item_text(item_text: Any) -> tuple[dict[str, Any], bool]:
    if isinstance(item_text, dict):
        return item_text, False
    if not isinstance(item_text, str):
        return {}, False
    raw = item_text.strip()
    if not raw:
        return {}, False
    try:
        parsed = json.loads(raw)
    except Exception:  # noqa: BLE001
        return {}, True
    if isinstance(parsed, dict):
        return parsed, False
    return {}, False


def _to_score(value: Any) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return 0.0


def _extract_floor_metadata(floor_payload: dict[str, Any], fallback_ref: str) -> dict[str, Any]:
    result = floor_payload.get("result") if isinstance(floor_payload.get("result"), dict) else floor_payload
    floor_data = result.get("floor") if isinstance(result.get("floor"), dict) else result
    if not isinstance(floor_data, dict):
        floor_data = {}
    floor_handle = str(
        floor_data.get("handle")
        or floor_data.get("floor_handle")
        or floor_data.get("name")
        or fallback_ref
    ).strip() or fallback_ref
    floor_title = str(
        floor_data.get("title")
        or floor_data.get("floor_title")
        or floor_data.get("display_name")
        or floor_data.get("name")
        or ""
    ).strip() or None
    floor_description = str(
        floor_data.get("details")
        or floor_data.get("floor_description")
        or floor_data.get("about")
        or floor_data.get("description")
        or ""
    ).strip() or None
    raw_tags = floor_data.get("tags") or floor_data.get("categories") or []
    tags = [str(item).strip() for item in raw_tags if str(item).strip()] if isinstance(raw_tags, list) else []
    logo_url = str(
        floor_data.get("avatar")
        or floor_data.get("avatar_url")
        or floor_data.get("avatarUrl")
        or floor_data.get("logo")
        or floor_data.get("logo_url")
        or floor_data.get("logoUrl")
        or floor_data.get("image")
        or floor_data.get("image_url")
        or floor_data.get("imageUrl")
        or ""
    ).strip() or None

    raw_blocks = floor_data.get("blocks") or result.get("blocks") or []
    blocks: list[dict[str, Any]] = []
    if isinstance(raw_blocks, list):
        for block in raw_blocks:
            if not isinstance(block, dict):
                continue
            block_id = str(block.get("block_id") or block.get("id") or "").strip() or None
            block_name = str(block.get("name") or block.get("title") or block.get("label") or "").strip() or None
            block_description = str(block.get("description") or block.get("details") or "").strip() or None
            block_type = str(block.get("type") or block.get("block_type") or "").strip() or None
            if block_id or block_name or block_description or block_type:
                blocks.append(
                    {
                        "block_id": block_id,
                        "name": block_name,
                        "description": block_description,
                        "type": block_type,
                    }
                )
    return {
        "floor_handle": floor_handle,
        "floor_title": floor_title,
        "floor_description": floor_description,
        "floor_tags": tags,
        "floor_logo_url": logo_url,
        "floor_blocks": blocks,
    }


def _format_set_active_floor_message(state: dict[str, Any]) -> str:
    title = state.get("floor_title") or state.get("floor_ref")
    description = state.get("floor_description") or "No description available."
    logo_url = state.get("floor_logo_url")
    blocks = state.get("floor_blocks") or []

    lines = [
        f"Active floor set to @{state['floor_ref']}",
        f"Title: {title}",
        f"Description: {description}",
    ]
    if logo_url:
        lines.append(f"Logo: {logo_url}")
    if blocks:
        lines.append("Blocks:")
        for block in blocks[:8]:
            name = block.get("name") or block.get("block_id") or "Unnamed block"
            block_type = block.get("type")
            block_desc = block.get("description")
            if block_type and block_desc:
                lines.append(f"- {name} ({block_type}): {block_desc}")
            elif block_type:
                lines.append(f"- {name} ({block_type})")
            elif block_desc:
                lines.append(f"- {name}: {block_desc}")
            else:
                lines.append(f"- {name}")
        if len(blocks) > 8:
            lines.append(f"- …and {len(blocks) - 8} more")
    return "\n".join(lines)


def _build_set_active_floor_markdown_card(state: dict[str, Any]) -> str:
    title = state.get("floor_title") or state.get("floor_ref") or "Floor"
    floor_ref = str(state.get("floor_ref") or "").lstrip("@")
    floor_id = state.get("floor_id")
    description = state.get("floor_description") or "No description available."
    logo_url = state.get("floor_logo_url") or DEFAULT_FLOOR_LOGO_DATA_URI
    blocks = state.get("floor_blocks") or []

    lines = [
        "<div style=\"background:#F8FAFC;border:1px solid #E5E7EB;border-radius:12px;padding:12px;\">",
        f"<img src=\"{logo_url}\" alt=\"{title} logo\" width=\"72\" height=\"72\" style=\"border-radius:10px;object-fit:cover;border:1px solid #E5E7EB;\" />",
        "",
        f"### ✅ Active Floor: @{floor_ref}",
        f"**Title:** {title}",
        f"**Description:** {description}",
    ]
    if blocks:
        lines.append("")
        lines.append("**Blocks**")
        for block in blocks[:8]:
            name = block.get("name") or block.get("block_id") or "Unnamed block"
            block_type = block.get("type")
            block_desc = block.get("description")
            suffix = f" ({block_type})" if block_type else ""
            if block_desc:
                lines.append(f"- **{name}{suffix}** — {block_desc}")
            else:
                lines.append(f"- **{name}{suffix}**")
        if len(blocks) > 8:
            lines.append(f"- _…and {len(blocks) - 8} more_")
    if floor_id:
        lines.append("")
        lines.append(f"[Open floor](https://{floor_id}.xfloor.ai)")
    lines.append("</div>")
    return "\n".join(lines)


def _tokenize(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2}


def _is_explicit_floor_scoped_prompt(prompt: str, floor: dict[str, Any] | None) -> bool:
    text = prompt.lower()
    floor_id = (floor or {}).get("floor_id")
    floor_ref = (floor or {}).get("floor_ref")
    explicit_phrases = [
        "current floor",
        "this floor",
        "active floor",
        "from xfloor",
        "in the floor",
        "post to the floor",
        "save to the floor",
        "log to the floor",
    ]
    if any(phrase in text for phrase in explicit_phrases):
        return True
    if "@" in text:
        return True
    return bool((floor_id and str(floor_id).lower() in text) or (floor_ref and str(floor_ref).lower() in text))


def _is_generic_writing_prompt(prompt: str) -> bool:
    text = prompt.lower()
    patterns = [
        "paraphrase",
        "rewrite",
        "summarize this text",
        "translate",
        "draft an email",
        "improve grammar",
    ]
    return any(pattern in text for pattern in patterns)


def _is_context_seeking_prompt(prompt: str) -> bool:
    tokens = _tokenize(prompt)
    context_tokens = {"latest", "recent", "updates", "news", "notes", "events", "announcements"}
    return bool(tokens & context_tokens)


def _is_prompt_related_to_active_floor(prompt: str, floor: dict[str, Any] | None) -> bool:
    if not floor:
        return False
    prompt_tokens = _tokenize(prompt)
    if not prompt_tokens:
        return False
    floor_text_parts = [
        str(floor.get("floor_ref") or ""),
        str(floor.get("floor_handle") or ""),
        str(floor.get("floor_title") or ""),
        str(floor.get("floor_description") or ""),
    ] + [str(tag) for tag in (floor.get("floor_tags") or [])]
    floor_tokens = _tokenize(" ".join(floor_text_parts))
    overlap = prompt_tokens & floor_tokens
    if overlap:
        return True
    return _is_context_seeking_prompt(prompt) and bool(floor_tokens)


def should_use_xfloor(prompt: str, floor: dict[str, Any] | None) -> tuple[bool, str]:
    if not floor:
        return False, "no_active_floor"
    if _is_generic_writing_prompt(prompt):
        return False, "generic_writing_task"

    return True, "related_to_active_floor"


def normalize_query_response(
    raw_result: dict[str, Any],
    *,
    active_floor: dict[str, str] | None = None,
    original_query: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = raw_result.get("result") if isinstance(raw_result.get("result"), dict) else raw_result
    answer = str(payload.get("answer") or raw_result.get("answer") or "").strip()
    items = payload.get("items")
    if not isinstance(items, list):
        items = raw_result.get("items") if isinstance(raw_result.get("items"), list) else []

    normalized_by_floor: dict[str, dict[str, Any]] = {}
    normalized_items_raw: list[dict[str, Any]] = []
    malformed_count = 0

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        parsed_text, malformed = _parse_item_text(item.get("text"))
        if malformed:
            malformed_count += 1
        floor_uid = str(
            parsed_text.get("from_floor_uid")
            or parsed_text.get("floor_uid")
            or parsed_text.get("floorUid")
            or item.get("from_floor_uid")
            or item.get("floor_uid")
            or ""
        ).strip()
        floor_name = str(parsed_text.get("floor") or parsed_text.get("floorName") or parsed_text.get("name") or "").strip()
        floor_description = str(parsed_text.get("floor_details") or parsed_text.get("floorDescription") or "").strip()
        post_title = str(parsed_text.get("post_title") or parsed_text.get("postTitle") or parsed_text.get("title") or "").strip()
        post_description = str(
            parsed_text.get("post_details") or parsed_text.get("postDescription") or item.get("text") or ""
        ).strip()
        score = _to_score(parsed_text.get("score") if parsed_text.get("score") is not None else item.get("score"))
        floor_url = f"{floor_uid}.xfloor.ai" if floor_uid else ""

        normalized = {
            "floorName": floor_name,
            "floorDescription": floor_description,
            "postTitle": post_title,
            "postDescription": post_description,
            "score": score,
            "floorUrl": floor_url,
            "floorUid": floor_uid,
        }
        normalized_items_raw.append({"index": idx, **normalized})
        dedupe_key = floor_uid or floor_name or f"item-{idx}"
        existing = normalized_by_floor.get(dedupe_key)
        if existing is None or score > _to_score(existing.get("score")):
            normalized_by_floor[dedupe_key] = normalized

    relevant_floors = sorted(normalized_by_floor.values(), key=lambda row: _to_score(row.get("score")), reverse=True)
    best_match = relevant_floors[0] if relevant_floors else None

    structured_content = {
        "activeFloor": {
            "id": (active_floor or {}).get("floor_id"),
            "name": (active_floor or {}).get("floor_ref"),
        },
        "query": original_query,
        "answer": answer,
        "bestMatch": best_match,
        "relevantFloors": relevant_floors,
        "resultCount": len(relevant_floors),
    }
    meta = {
        "rawItemCount": len(items),
        "malformedItemTextCount": malformed_count,
        "normalizedItemsRaw": normalized_items_raw,
    }
    return structured_content, meta


def _build_floor_summary_widget_html() -> str:
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <style>
      body { font-family: system-ui, sans-serif; margin: 0; padding: 10px; color: #111; background: #f8fafc; }
      .card { border: 1px solid #e5e7eb; border-radius: 14px; padding: 12px; background: #fff; }
      .top { display: flex; gap: 10px; align-items: center; margin-bottom: 8px; }
      .logo { width: 44px; height: 44px; border-radius: 8px; object-fit: cover; border: 1px solid #e5e7eb; display: none; }
      .title { font-weight: 700; font-size: 14px; line-height: 1.2; }
      .handle { font-size: 12px; color: #6b7280; margin-top: 2px; }
      .desc { font-size: 13px; line-height: 1.4; color: #1f2937; margin: 8px 0 10px 0; white-space: pre-wrap; }
      .subhead { font-size: 12px; color: #374151; font-weight: 600; margin-bottom: 6px; }
      .blocks { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
      .block { border: 1px solid #eef2f7; border-radius: 8px; padding: 8px; }
      .block-name { font-size: 12px; font-weight: 600; color: #111827; }
      .block-meta { font-size: 12px; color: #6b7280; margin-top: 2px; }
      .empty { font-size: 12px; color: #6b7280; }
      .footer { margin-top: 10px; font-size: 12px; }
      a { color: #2563eb; text-decoration: none; }
      a:hover { text-decoration: underline; }
    </style>
  </head>
  <body>
    <div class="card">
      <div class="top">
        <img class="logo" id="logo" alt="Floor logo" />
        <div>
          <div class="title" id="title">xFloor</div>
          <div class="handle" id="handle">@floor</div>
        </div>
      </div>
      <div class="desc" id="desc">No description.</div>
      <div class="subhead">Blocks</div>
      <ul class="blocks" id="blocks"></ul>
      <div class="empty" id="blocks-empty" style="display:none;">No blocks available.</div>
      <div class="footer" id="footer"></div>
    </div>
    <script>
      const api = window.openai || {};
      const sc = (window.structuredContent || window.__structuredContent || api?.toolOutput?.structuredContent || {});
      const floorId = sc.floor_id || "";
      const floorRef = sc.floor_ref || floorId || "floor";
      const floorTitle = sc.floor_title || floorRef;
      const floorDescription = sc.floor_description || "No description available.";
      const logoUrl = sc.floor_logo_url || "";
      const blocks = Array.isArray(sc.blocks) ? sc.blocks : [];

      document.getElementById("title").textContent = floorTitle;
      document.getElementById("handle").textContent = "@" + String(floorRef).replace(/^@/, "");
      document.getElementById("desc").textContent = floorDescription;
      const logoEl = document.getElementById("logo");
      if (logoUrl) {
        logoEl.src = logoUrl;
        logoEl.style.display = "block";
      }

      const listEl = document.getElementById("blocks");
      const emptyEl = document.getElementById("blocks-empty");
      if (!blocks.length) {
        emptyEl.style.display = "block";
      } else {
        blocks.slice(0, 8).forEach((block) => {
          const li = document.createElement("li");
          li.className = "block";
          const name = block.name || block.block_id || "Unnamed block";
          const type = block.type ? " (" + block.type + ")" : "";
          const desc = block.description || "";
          li.innerHTML = '<div class="block-name">' + name + type + '</div>' + (desc ? '<div class="block-meta">' + desc + '</div>' : '');
          listEl.appendChild(li);
        });
      }
      if (floorId) {
        const url = "https://" + floorId + ".xfloor.ai";
        document.getElementById("footer").innerHTML = '<a href="' + url + '" target="_blank" rel="noopener noreferrer">Open active floor</a>';
      } else {
        document.getElementById("footer").textContent = "";
      }
    </script>
  </body>
</html>"""


def _build_set_active_floor_widget_resource() -> dict[str, Any]:
    return {
        "contents": [
            {
                "uri": SET_ACTIVE_FLOOR_WIDGET_URI,
                "mimeType": "text/html",
                "text": _build_floor_summary_widget_html(),
                "_meta": {
                    "openai/widgetDescription": "Shows active floor details including title, description, logo, and blocks.",
                    "openai/widgetPrefersBorder": True,
                    "openai/widgetCSP": {
                        "connect_domains": [],
                        "resource_domains": [],
                    },
                },
            }
        ]
    }


def register_tools(mcp: Any, client: XFloorClient) -> None:
    """Register MCP tools on the provided FastMCP instance."""
    enable_v1_expanded_tool_surface = False

    @mcp.resource(SET_ACTIVE_FLOOR_WIDGET_URI)
    def set_active_floor_widget() -> dict[str, Any]:
        resource_payload = _build_set_active_floor_widget_resource()
        logger.info("set_active_floor widget resource served uri=%s", SET_ACTIVE_FLOOR_WIDGET_URI)
        return resource_payload

    if enable_v1_expanded_tool_surface:
        @mcp.tool(
            name="xfloor_query_memory",
            description="Search or retrieve memory and events from the active xFloor, or from a specified floor if one is provided.",
            annotations={"readOnlyHint": True, "openWorldHint": False, "destructiveHint": False},
        )
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

        @mcp.tool(
            name="xfloor_create_event",
            description="Create a new memory/event in the active xFloor. Use when the user wants to post, log, or save information to a floor.",
            annotations={"readOnlyHint": False, "openWorldHint": False, "destructiveHint": False},
        )
        async def xfloor_create_event(input: XFloorCreateEventInput, ctx: Any = None) -> dict[str, Any]:
            token = _extract_auth_token(ctx, input.auth_token)
            client.validate_input_info(input.input_info)
            files = [file.model_dump() for file in input.files] if input.files else None
            result = await client.create_event(token, input_info=input.input_info, files=files)
            return _compact(result)

        @mcp.tool(
            name="xfloor_recent_events",
            description="Get recent xFloor memory events",
            annotations={"readOnlyHint": True, "openWorldHint": False, "destructiveHint": False},
        )
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

    @mcp.tool(
        name="xfloor_get_floor_info",
        description=(
            "Retrieve details for the currently relevant Floor, such as its name, identifier, and metadata. "
            "Call this ONLY when the user’s current message explicitly asks for Floor details or metadata, for example: "
            "'get the floor info', 'show floor details', 'what is the floor id', or 'what blocks are in this floor'. "
            "Do NOT call this tool for general knowledge, paraphrasing, summarization, translation, meanings, rewriting, "
            "weather, web search, or any request answerable without Floor metadata. "
            "Do NOT call this tool just because a Floor is active, the conversation previously used a Floor, "
            "Floor context might be helpful, or the assistant wants to verify context before answering. "
            "Prior floor history, inferred topic, active floor state, or assistant convenience are never sufficient. "
            "If the user’s current message does not explicitly ask for Floor details or metadata, do not call this tool. "
            "If no active Floor is set, do not call this tool. "
            "When in doubt, do not call it."
        ),
        annotations={"readOnlyHint": True, "openWorldHint": False, "destructiveHint": False},
    )
    async def xfloor_get_floor_info(input: XFloorGetFloorInfoInput, ctx: Any = None) -> dict[str, Any]:
        token = _extract_auth_token(ctx, input.auth_token)
        result = await client.get_floor_info(token, floor_id=input.floor_id)
        return _compact(result)

    if enable_v1_expanded_tool_surface:
        @mcp.tool(
            name="xfloor_wait_for_ingestion",
            description="Poll recent events until text appears in title/description",
            annotations={"readOnlyHint": True, "openWorldHint": False, "destructiveHint": False},
        )
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
    else:
        # Temporarily disabled for V1 public MCP surface to reduce over-triggering and keep the tool surface narrow.
        logger.info(
            "V1 narrow tool surface active: xfloor_query_memory, xfloor_create_event, xfloor_recent_events, and xfloor_wait_for_ingestion are not registered."
        )

    @mcp.tool(
        name="xfloor_set_active_floor",
        description=(
            "Call this ONLY when the user’s current message explicitly identifies a floor to use, either:"
            "by directly asking to use/set/switch/select a floor, such as use @phari or switch to @croma, or"
            "by including an inline @floor reference that clearly scopes the request to that floor, such as what’s happening @pesedu."
            "Never call this tool based on prior floor history, inferred topic, ambiguous references, or assistant convenience. "
            "If the current message does not explicitly name a floor with @..., do not call this tool. When in doubt, do not call it. "
            "After a successful call, present a visible floor summary to the user using the returned fields, including "
            "floor title, floor description, logo URL (if present), and top blocks. Do not reduce the response to only "
            "'active floor set' when richer details are available."
        ),
        annotations={"readOnlyHint": False, "openWorldHint": False, "destructiveHint": False},
    )
    async def xfloor_set_active_floor(input: XFloorSetActiveFloorInput, ctx: Any = None) -> dict[str, Any]:
        resolved = resolve_floor_reference(floor_ref=input.floor_ref, floor_id=input.floor_id)
        metadata: dict[str, Any] = {
            "floor_handle": resolved["floor_ref"],
            "floor_title": None,
            "floor_description": None,
            "floor_tags": [],
            "floor_logo_url": None,
            "floor_blocks": [],
        }
        try:
            token = _extract_auth_token(ctx, None)
            floor_info_result = await client.get_floor_info(token, floor_id=resolved["floor_id"])
            metadata = _extract_floor_metadata(_compact(floor_info_result), resolved["floor_ref"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("Active floor metadata fetch skipped due to error: %s", exc, exc_info=True)
        state = set_active_floor_state(
            floor_id=resolved["floor_id"],
            floor_ref=resolved["floor_ref"],
            floor_handle=metadata["floor_handle"],
            floor_title=metadata["floor_title"],
            floor_description=metadata["floor_description"],
            floor_tags=metadata["floor_tags"],
            floor_logo_url=metadata["floor_logo_url"],
            floor_blocks=metadata["floor_blocks"],
        )
        detailed_message = _format_set_active_floor_message(state)
        markdown_card = _build_set_active_floor_markdown_card(state)
        using_default_logo = not bool(state.get("floor_logo_url"))
        response = {
            "ok": True,
            "message": detailed_message,
            "markdown_card": markdown_card,
            "assistant_reply": markdown_card,
            "content": [
                {
                    "type": "text",
                    "text": markdown_card,
                }
            ],
            "floor_ref": state["floor_ref"],
            "floor_id": state["floor_id"],
            "floor_title": state.get("floor_title"),
            "floor_description": state.get("floor_description"),
            "floor_logo_url": state.get("floor_logo_url"),
            "blocks": state.get("floor_blocks") or [],
            "blocks_count": len(state.get("floor_blocks") or []),
            "state_scope": "in_memory_session",
            "structuredContent": {
                "floor_ref": state["floor_ref"],
                "floor_id": state["floor_id"],
                "floor_title": state.get("floor_title"),
                "floor_description": state.get("floor_description"),
                "floor_logo_url": state.get("floor_logo_url"),
                "blocks": state.get("floor_blocks") or [],
            },
            "_meta": {
                "openai/outputTemplate": SET_ACTIVE_FLOOR_WIDGET_URI,
            },
        }
        logger.info(
            "xfloor_set_active_floor response prepared floor_id=%s blocks=%s widget_uri=%s markdown_len=%s default_logo=%s",
            state["floor_id"],
            len(state.get("floor_blocks") or []),
            SET_ACTIVE_FLOOR_WIDGET_URI,
            len(markdown_card),
            using_default_logo,
        )
        return response

    @mcp.tool(
        name="xfloor_clear_active_floor",
        description=(
            "Call this ONLY when the user's current message EXPLICITLY wants to clear or remove the current Floor context, such as 'clear floor' or 'remove floor'. "
            "Never call this tool based on prior floor history, inferred topic, ambiguous references, or assistant convenience. "
            "Do not use it for general knowledge, paraphrasing, summarization, translation, meanings, rewriting, weather, web search, or any request answerable without floor context. When in doubt, do not call the tool."
        ),
        annotations={"readOnlyHint": False, "openWorldHint": False, "destructiveHint": False},
    )
    async def xfloor_clear_active_floor(input: XFloorClearActiveFloorInput | None = None, ctx: Any = None) -> dict[str, Any]:
        existing_state = get_active_floor_state()
        if not existing_state:
            return {
                "ok": True,
                "cleared": False,
                "message": "No active Floor was set for this conversation.",
            }
        clear_active_floor_state()
        return {
            "ok": True,
            "cleared": True,
            "message": f"Active Floor cleared (was {existing_state['floor_ref']}).",
        }

    @mcp.tool(
        name="xfloor_query_current_floor",
        description=(
            "Use this tool ONLY if the answer to the user’s current message depends on information contained in the currently active xFloor Floor. "
            "If the model can answer the request well without consulting Floor content, do NOT call this tool. "
            "Do NOT use this tool for any self-contained request such as general knowledge, definitions, meanings, translation, paraphrasing, "
            "rewriting, summarization, weather, web search, or other queries answerable without Floor content. "
            "Do NOT call this tool because a Floor is active, because the conversation previously used a Floor, because the topic seems related, "
            "or because Floor content might be helpful. Those are not valid reasons. "
            "Only call when the requested answer must be grounded in the active Floor’s published content. "
            "If no active Floor is set, do not call this tool. "
            "When in doubt, do not call it."
        ),
        annotations={"readOnlyHint": True, "openWorldHint": False, "destructiveHint": False},
    )
    async def xfloor_query_current_floor(input: XFloorQueryCurrentFloorInput, ctx: Any = None) -> dict[str, Any]:
        token = _extract_auth_token(ctx, None)
        try:
            floor = _resolve_active_floor_id()
        except ValueError:
            return {
                "ok": False,
                "message": "No active Floor is set. Continue without xFloor, or call xfloor_set_active_floor if Floor-specific context is needed.",
            }
        use_xfloor, reason = should_use_xfloor(input.query, floor)
        if not use_xfloor:
            if reason == "generic_writing_task":
                return {
                    "ok": False,
                    "message": "No xFloor action taken. This request does not appear to need Floor-specific context.",
                }
            return {
                "ok": False,
                "message": "No xFloor action taken. This request is not clearly related to the active Floor’s published context.",
            }
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
        compact_result = _compact(result)
        logger.info("Query raw response received for normalization")
        structured_content, normalization_meta = normalize_query_response(
            compact_result,
            active_floor=floor,
            original_query=input.query,
        )
        logger.info(
            "Query normalization complete normalized_floors=%s malformed_items=%s",
            structured_content["resultCount"],
            normalization_meta["malformedItemTextCount"],
        )
        logger.info(
            "Query response summary floor_id=%s relevant_floors=%s",
            floor["floor_id"],
            structured_content["resultCount"],
        )
        answer_text = structured_content.get("answer") or "Here’s what I found."
        related_floor_handles: list[str] = []
        for floor_item in structured_content["relevantFloors"][:5]:
            floor_name = (floor_item.get("floorName") or "").strip()
            floor_uid = (floor_item.get("floorUid") or "").strip()
            chosen = floor_name or floor_uid
            if chosen:
                related_floor_handles.append(f"@{chosen.lstrip('@')}")
        if related_floor_handles:
            answer_text = (
                f"{answer_text}\n\nRelated floors: {', '.join(related_floor_handles)}\n"
                f"Try: use {related_floor_handles[0]}"
            )
        return {
            "floor_id": floor["floor_id"],
            "floor_ref": floor["floor_ref"],
            "floor_source": floor["source"],
            "query": input.query,
            "answer": answer_text,
            "best_match": structured_content["bestMatch"],
            "relevant_floors": structured_content["relevantFloors"],
            "result_count": structured_content["resultCount"],
            "related_floors_text": related_floor_handles,
            "normalization_meta": normalization_meta,
        }

    @mcp.tool(
        name="xfloor_post_event_to_current_floor",
        description=(
            "Create a text-only event in the currently active xFloor Floor. Use this when the user explicitly wants to post, log, or save text to the active Floor. "
            "Do not use it for general knowledge, paraphrasing, summarization, translation, meanings, rewriting, weather, web search, or any request answerable without floor context. "
            "Do not use if there is no active floor set. When in doubt, do not call the tool."
        ),
        annotations={"readOnlyHint": False, "openWorldHint": False, "destructiveHint": False},
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
