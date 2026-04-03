"""MCP tool registration for xFloor APIs."""

from __future__ import annotations

import json
import hashlib
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .active_floor_state import clear_active_floor_state, get_active_floor_state, resolve_floor_reference, set_active_floor_state
from .core.active_floor_response import build_core_set_active_floor_response
from .hosts.openai.constants import QUERY_CURRENT_FLOOR_WIDGET_URI, SET_ACTIVE_FLOOR_WIDGET_URI  # backwards-compatible re-export
from .request_context import (
    get_active_floor_id,
    get_auth_mode,
    get_auth_token,
    get_oauth_issuer,
    get_oauth_subject,
    get_user_id,
    get_xfloor_service_token,
)
from .settings import Settings
from .xfloor_client import XFloorClient

logger = logging.getLogger(__name__)
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
    floor_id: str | None = Field(
        default=None,
        description="Optional explicit floor ID. If omitted, the currently active floor is used.",
    )
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
    floor_id: str = Field(
        description="Floor ID to query, e.g. 'rmm' or 'pesedu'. Required for reliable cross-host operation.",
    )
    query: str = Field(description="Natural-language question to ask about the currently active xFloor")
    topic: str | None = Field(default=None, description="Optional topic hint to improve retrieval focus")
    limit: int | None = Field(default=None, ge=1, le=20, description="Optional maximum number of results to consider")


class XFloorPostEventToCurrentFloorInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    floor_id: str = Field(
        description="Floor ID to post, e.g. 'rmm' or 'pesedu'. Required for reliable cross-host operation.",
    )
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


class WidgetRelatedFloor(BaseModel):
    floor_id: str
    floorName: str | None = None
    label: str | None = None


class WidgetFloorBlock(BaseModel):
    name: str | None = None
    block_id: str | None = None


class SetActiveFloorWidgetStructuredContent(BaseModel):
    floor_ref: str
    floor_id: str
    floor_title: str | None = None
    floor_description: str | None = None
    floor_logo_url: str | None = None
    blocks: list[WidgetFloorBlock] = Field(default_factory=list)


class QueryCurrentFloorWidgetStructuredContent(BaseModel):
    answer: str
    relatedFloors: list[WidgetRelatedFloor] = Field(default_factory=list)


def _looks_like_jwt(token: str) -> bool:
    parts = token.split(".")
    return len(parts) == 3


def _extract_auth_token(ctx: Any, token_override: str | None) -> str:
    auth_mode = get_auth_mode()
    service_token = get_xfloor_service_token()

    if auth_mode == "oauth":
        if service_token and service_token.strip():
            return service_token.strip()
        raise ValueError("Missing xFloor service token for downstream API call in oauth mode.")

    bearer_token = None
    if token_override and token_override.strip():
        bearer_token = token_override.strip()
    else:
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
                bearer_token = header[7:].strip()
                break

    if auth_mode == "auto" and bearer_token and _looks_like_jwt(bearer_token):
        if service_token and service_token.strip():
            return service_token.strip()
        raise ValueError("Missing xFloor service token for downstream API call in auto/oauth mode.")

    if bearer_token:
        return bearer_token

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
    floor = _resolve_stored_floor_context()
    if floor:
        return floor
    raise ValueError("No active floor set. Please set one first (eg: @phari or use @croma).")


def _resolve_stored_floor_context() -> dict[str, str] | None:
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
    return None


def _resolve_floor_for_request(explicit_floor_id: str | None) -> tuple[dict[str, Any], str, str | None]:
    normalized_explicit = (explicit_floor_id or "").strip() or None
    stored_floor = _resolve_stored_floor_context()
    stored_floor_id = (stored_floor or {}).get("floor_id") if stored_floor else None

    if normalized_explicit:
        return (
            {
                "floor_id": normalized_explicit,
                "floor_ref": normalized_explicit,
                "source": "input",
            },
            "input",
            stored_floor_id,
        )
    if stored_floor_id and stored_floor:
        floor = dict(stored_floor)
        floor["source"] = "session"
        return floor, "session", stored_floor_id
    raise ValueError("No floor available for this request. Pass floor_id explicitly or set an active floor first.")


def _compact(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    return {"data": data}


def _text_debug_signature(value: Any, *, preview_len: int = 200) -> dict[str, Any]:
    text = "" if value is None else str(value)
    encoded = text.encode("utf-8", errors="replace")
    return {
        "len": len(text),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "has_backslash": "\\" in text,
        "preview_unicode_escape": text[:preview_len].encode("unicode_escape", errors="replace").decode("ascii", errors="replace"),
    }


def _sanitize_for_js_embedding(value: Any) -> Any:
    """Defensively escape strings for hosts that interpolate payload text into JS string literals."""

    if isinstance(value, str):
        sanitized = re.sub(r'\\(?![\\/"bfnrtu])', r"\\\\", value)
        return sanitized.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    if isinstance(value, list):
        return [_sanitize_for_js_embedding(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_for_js_embedding(item) for key, item in value.items()}
    return value


def _collect_suspicious_escape_sequences(value: Any, path: str = "$") -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if isinstance(value, str):
        matches = re.findall(r"\\[A-Za-z]", value)
        if matches:
            findings.append(
                {
                    "path": path,
                    "matches": sorted(set(matches)),
                    "preview_unicode_escape": value[:200].encode("unicode_escape", errors="replace").decode("ascii", errors="replace"),
                }
            )
        return findings
    if isinstance(value, list):
        for index, item in enumerate(value):
            findings.extend(_collect_suspicious_escape_sequences(item, f"{path}[{index}]"))
        return findings
    if isinstance(value, dict):
        for key, item in value.items():
            findings.extend(_collect_suspicious_escape_sequences(item, f"{path}.{key}"))
        return findings
    return findings


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
    logo_url = _normalize_logo_url(
        floor_data.get("avatar")
        or floor_data.get("avatar_url")
        or floor_data.get("avatarUrl")
        or floor_data.get("logo")
        or floor_data.get("logo_url")
        or floor_data.get("logoUrl")
        or floor_data.get("image")
        or floor_data.get("image_url")
        or floor_data.get("imageUrl")
    )

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


def _normalize_logo_url(candidate: Any) -> str | None:
    if candidate is None:
        return None
    if isinstance(candidate, str):
        normalized = candidate.strip()
        return normalized or None
    if isinstance(candidate, dict):
        for key in ("url", "avatar", "logo", "src", "href"):
            value = candidate.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
    if isinstance(candidate, list):
        for item in candidate:
            normalized = _normalize_logo_url(item)
            if normalized:
                return normalized
        return None
    return None


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
    floor_ref = str(state.get("floor_ref") or "").strip()
    if floor_ref and not floor_ref.startswith("@"):
        floor_ref = f"@{floor_ref}"

    title = state.get("floor_title")
    description = state.get("floor_description")
    logo_url = state.get("floor_logo_url")
    floor_id = str(state.get("floor_id") or "").strip()
    blocks = state.get("floor_blocks") or []

    sections: list[str] = []

    if floor_ref:
        sections.append(f"**Active Floor**\n{floor_ref}")
    if title:
        sections.append(f"**Title**\n{title}")
    if description:
        sections.append(f"**Description**\n{description}")
    if logo_url:
        sections.append(f"**Logo**\n{logo_url}")
    if blocks:
        block_lines = ["**Blocks**"]
        for block in blocks[:6]:
            name = (block.get("name") or block.get("block_id") or "Unnamed block").strip()
            block_lines.append(f"- {name}")
        if len(blocks) > 6:
            block_lines.append(f"- …and {len(blocks) - 6} more")
        sections.append("\n".join(block_lines))
    if floor_id:
        sections.append(f"**Open Floor**\n[Open floor](https://{floor_id}.xfloor.ai)")

    return "\n\n".join(sections).strip()


def _build_query_floor_markdown_answer(answer: str, relevant_floors: list[dict[str, Any]]) -> str:
    lines = [answer.strip() or "Here’s what I found."]
    links: list[str] = []
    for floor in relevant_floors[:4]:
        floor_id = str(floor.get("floorUid") or "").strip()
        label = str(floor.get("floorName") or floor_id).strip()
        if not floor_id:
            continue
        label_value = f"@{label.lstrip('@')}" if label else f"@{floor_id}"
        links.append(f"- [{label_value}](https://{floor_id}.xfloor.ai)")
    if links:
        lines.append("")
        lines.append("**Related floors**")
        lines.extend(links)
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


def register_tools(mcp: Any, client: XFloorClient, settings: Settings | None = None, host_adapter: Any | None = None) -> None:
    """Register MCP tools on the provided FastMCP instance."""
    enable_v1_expanded_tool_surface = False
    if host_adapter and hasattr(host_adapter, "register_resources"):
        logger.info(
            "Registering host resources host=%s supports_widget_resources=%s",
            getattr(host_adapter, "name", "unknown"),
            bool(getattr(getattr(host_adapter, "capabilities", None), "supports_widget_resources", False)),
        )
        host_adapter.register_resources(mcp)

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
        tool_name = "xfloor_get_floor_info"
        raw_input = input.model_dump() if hasattr(input, "model_dump") else input
        try:
            resolved_floor, resolution_source, stored_floor_id = _resolve_floor_for_request(input.floor_id)
        except ValueError as exc:
            logger.info(
                "%s input received raw_input=%s explicit_floor_id=%s stored_floor_id=%s",
                tool_name,
                raw_input,
                input.floor_id,
                None,
            )
            return {"ok": False, "message": str(exc)}
        logger.info(
            "%s input received raw_input=%s explicit_floor_id=%s stored_floor_id=%s",
            tool_name,
            raw_input,
            input.floor_id,
            stored_floor_id,
        )
        logger.info(
            "%s floor resolved resolved_floor_id=%s source=%s",
            tool_name,
            resolved_floor["floor_id"],
            resolution_source,
        )
        logger.info("%s downstream call floor_id=%s", tool_name, resolved_floor["floor_id"])
        result = await client.get_floor_info(token, floor_id=resolved_floor["floor_id"])
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

    set_active_annotations = {"readOnlyHint": False, "openWorldHint": False, "destructiveHint": False}
    query_annotations = {"readOnlyHint": True, "openWorldHint": False, "destructiveHint": False}
    if host_adapter and hasattr(host_adapter, "build_render_tool_annotations"):
        set_active_annotations.update(host_adapter.build_render_tool_annotations(SET_ACTIVE_FLOOR_WIDGET_URI))
        query_annotations.update(host_adapter.build_render_tool_annotations(QUERY_CURRENT_FLOOR_WIDGET_URI))

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
        annotations=set_active_annotations,
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
        using_default_logo = not bool(state.get("floor_logo_url"))
        core_response = build_core_set_active_floor_response(state)
        response = host_adapter.decorate_set_active_floor_response(core_response) if host_adapter else core_response
        markdown_summary = _build_set_active_floor_markdown_card(state)
        if markdown_summary:
            response["message"] = markdown_summary
            response["content"] = [{"type": "text", "text": markdown_summary}]
        logger.info(
            "xfloor_set_active_floor response text diagnostics message=%s content_text=%s floor_title=%s floor_description=%s",
            _text_debug_signature(response.get("message")),
            _text_debug_signature(((response.get("content") or [{}])[0] or {}).get("text")),
            _text_debug_signature((response.get("structuredContent") or {}).get("floor_title")),
            _text_debug_signature((response.get("structuredContent") or {}).get("floor_description")),
        )
        try:
            response_json = json.dumps(response, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            response_json = ""
        logger.info(
            "xfloor_set_active_floor response payload diagnostics payload=%s",
            _text_debug_signature(response_json, preview_len=300),
        )
        escape_findings = _collect_suspicious_escape_sequences(response)
        if escape_findings:
            logger.warning("xfloor_set_active_floor suspicious escape sequences findings=%s", escape_findings)
        response = _sanitize_for_js_embedding(response)
        logger.info(
            "xfloor_set_active_floor response prepared floor_id=%s blocks=%s widget_uri=%s default_logo=%s logo_normalized=%s",
            state["floor_id"],
            len(state.get("floor_blocks") or []),
            SET_ACTIVE_FLOOR_WIDGET_URI,
            using_default_logo,
            bool(state.get("floor_logo_url")),
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
            "Provide floor_id explicitly on each call. "
            "If the model can answer the request well without consulting Floor content, do NOT call this tool. "
            "Do NOT use this tool for any self-contained request such as general knowledge, definitions, meanings, translation, paraphrasing, "
            "rewriting, summarization, weather, web search, or other queries answerable without Floor content. "
            "Do NOT call this tool because a Floor is active, because the conversation previously used a Floor, because the topic seems related, "
            "or because Floor content might be helpful. Those are not valid reasons. "
            "Only call when the requested answer must be grounded in the active Floor’s published content. "
            "If no active Floor is set, do not call this tool. "
            "When in doubt, do not call it."
        ),
        annotations=query_annotations,
    )
    async def xfloor_query_current_floor(input: XFloorQueryCurrentFloorInput, ctx: Any = None) -> dict[str, Any]:
        tool_name = "xfloor_query_current_floor"
        raw_input = input.model_dump() if hasattr(input, "model_dump") else input
        token = _extract_auth_token(ctx, None)
        try:
            floor, resolution_source, stored_floor_id = _resolve_floor_for_request(input.floor_id)
        except ValueError as exc:
            logger.info(
                "%s input received raw_input=%s explicit_floor_id=%s stored_floor_id=%s",
                tool_name,
                raw_input,
                input.floor_id,
                None,
            )
            return {
                "ok": False,
                "message": str(exc),
            }
        logger.info(
            "%s input received raw_input=%s explicit_floor_id=%s stored_floor_id=%s",
            tool_name,
            raw_input,
            input.floor_id,
            stored_floor_id,
        )
        logger.info(
            "%s floor resolved resolved_floor_id=%s source=%s",
            tool_name,
            floor["floor_id"],
            resolution_source,
        )
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
        logger.info("%s downstream query_memory floor_id=%s", tool_name, floor["floor_id"])
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
        base_answer_text = structured_content.get("answer") or "Here’s what I found."
        logger.info(
            "%s answer diagnostics base_answer=%s",
            tool_name,
            _text_debug_signature(base_answer_text),
        )
        related_floor_handles: list[str] = []
        for floor_item in structured_content["relevantFloors"][:5]:
            floor_name = (floor_item.get("floorName") or "").strip()
            floor_uid = (floor_item.get("floorUid") or "").strip()
            chosen = floor_name or floor_uid
            if chosen:
                related_floor_handles.append(f"@{chosen.lstrip('@')}")
        markdown_answer = _build_query_floor_markdown_answer(base_answer_text, structured_content["relevantFloors"])
        logger.info(
            "%s markdown diagnostics markdown_answer=%s",
            tool_name,
            _text_debug_signature(markdown_answer),
        )
        response = {
            "floor_id": floor["floor_id"],
            "floor_ref": floor["floor_ref"],
            "floor_source": floor["source"],
            "query": input.query,
            "answer": markdown_answer,
            "best_match": structured_content["bestMatch"],
            "relevant_floors": structured_content["relevantFloors"],
            "result_count": structured_content["resultCount"],
            "related_floors_text": related_floor_handles,
            "normalization_meta": normalization_meta,
            "content": [{"type": "text", "text": markdown_answer}],
            "structuredContent": {
                "answer": base_answer_text,
                "relatedFloors": [
                    {
                        "floor_id": str(item.get("floorUid") or "").strip(),
                        "floorName": str(item.get("floorName") or "").strip(),
                        "label": str(item.get("floorName") or item.get("floorUid") or "").strip(),
                    }
                    for item in structured_content["relevantFloors"]
                ],
            },
        }
        try:
            structured_json = json.dumps(response.get("structuredContent") or {}, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            structured_json = ""
        logger.info(
            "%s structured_content diagnostics payload=%s",
            tool_name,
            _text_debug_signature(structured_json, preview_len=300),
        )
        escape_findings = _collect_suspicious_escape_sequences(response)
        if escape_findings:
            logger.warning("%s suspicious escape sequences findings=%s", tool_name, escape_findings)
        response = _sanitize_for_js_embedding(response)
        if host_adapter and hasattr(host_adapter, "decorate_query_current_floor_response"):
            response = host_adapter.decorate_query_current_floor_response(response)
        return response

    @mcp.tool(
        name="xfloor_post_event_to_current_floor",
        description=(
            "Create a text-only event in the currently active xFloor Floor. Use this when the user explicitly wants to post, log, or save text to the active Floor. "
            "Provide floor_id explicitly on each call. "
            "Do not use it for general knowledge, paraphrasing, summarization, translation, meanings, rewriting, weather, web search, or any request answerable without floor context. "
            "Do not use if there is no active floor set. When in doubt, do not call the tool."
        ),
        annotations={"readOnlyHint": False, "openWorldHint": False, "destructiveHint": False},
    )
    async def xfloor_post_event_to_current_floor(input: XFloorPostEventToCurrentFloorInput, ctx: Any = None) -> dict[str, Any]:
        tool_name = "xfloor_post_event_to_current_floor"
        raw_input = input.model_dump() if hasattr(input, "model_dump") else input
        verified_identity_present = bool(get_oauth_issuer() and get_oauth_subject())
        if not verified_identity_present:
            return {
                "accepted": False,
                "posted": False,
                "message": "xfloor_post_event_to_current_floor requires a verified OAuth identity.",
            }
        token = _extract_auth_token(ctx, None)
        try:
            floor, resolution_source, stored_floor_id = _resolve_floor_for_request(input.floor_id)
        except ValueError as exc:
            logger.info(
                "%s input received raw_input=%s explicit_floor_id=%s stored_floor_id=%s",
                tool_name,
                raw_input,
                input.floor_id,
                None,
            )
            return {"accepted": False, "posted": False, "message": str(exc)}
        logger.info(
            "%s input received raw_input=%s explicit_floor_id=%s stored_floor_id=%s",
            tool_name,
            raw_input,
            input.floor_id,
            stored_floor_id,
        )
        logger.info(
            "%s floor resolved resolved_floor_id=%s source=%s",
            tool_name,
            floor["floor_id"],
            resolution_source,
        )
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
        logger.info("%s downstream create_event floor_id=%s", tool_name, floor["floor_id"])
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
