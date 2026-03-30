"""In-memory active-floor state and alias resolution helpers."""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from .request_context import get_app_id, get_session_key, get_user_id

logger = logging.getLogger(__name__)

_STATE_TTL_SECONDS = 12 * 60 * 60
_ACTIVE_FLOOR_STATE: dict[str, dict[str, Any]] = {}


def normalize_floor_ref(floor_ref: str) -> str:
    """Normalize a user-facing floor reference like `@phari` or `phari`."""

    normalized = floor_ref.strip()
    if normalized.startswith("@"):
        normalized = normalized[1:]
    return normalized.strip().lower()


def _load_alias_map() -> dict[str, str]:
    raw = os.getenv("XFLOOR_FLOOR_ALIAS_MAP_JSON", "").strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("XFLOOR_FLOOR_ALIAS_MAP_JSON must be valid JSON.") from exc

    if not isinstance(parsed, dict):
        raise ValueError("XFLOOR_FLOOR_ALIAS_MAP_JSON must be a JSON object mapping aliases to floor IDs.")

    alias_map: dict[str, str] = {}
    for key, value in parsed.items():
        if isinstance(key, str) and isinstance(value, str):
            alias_map[normalize_floor_ref(key)] = value
    return alias_map


def resolve_floor_reference(floor_ref: str | None = None, floor_id: str | None = None) -> dict[str, str]:
    """Resolve a floor ref/alias into a concrete floor identifier."""

    if floor_id and floor_id.strip():
        normalized = normalize_floor_ref(floor_ref) if floor_ref and floor_ref.strip() else normalize_floor_ref(floor_id)
        return {
            "floor_ref": normalized or floor_id.strip(),
            "floor_id": floor_id.strip(),
        }

    if not floor_ref or not floor_ref.strip():
        raise ValueError("Please provide a floor to use, for example @phari or use @croma.")

    normalized = normalize_floor_ref(floor_ref)
    if not normalized:
        raise ValueError("Please provide a floor to use, for example @phari or use @croma.")

    alias_map = _load_alias_map()
    return {
        "floor_ref": normalized,
        "floor_id": alias_map.get(normalized, normalized),
    }


def _current_state_key() -> str:
    session_key = get_session_key()
    if session_key:
        return session_key

    user_id = get_user_id() or "unknown-user"
    app_id = get_app_id() or "unknown-app"
    nonce = time.time_ns()
    return f"fallback:{user_id}:{app_id}:{nonce}"


def _cleanup_expired_state(now: float | None = None) -> None:
    current_time = now if now is not None else time.time()
    expired_keys = [
        key
        for key, state in _ACTIVE_FLOOR_STATE.items()
        if current_time - float(state.get("updated_at") or 0.0) > _STATE_TTL_SECONDS
    ]
    for key in expired_keys:
        _ACTIVE_FLOOR_STATE.pop(key, None)


def set_active_floor_state(
    floor_id: str,
    floor_ref: str,
    *,
    floor_handle: str | None = None,
    floor_title: str | None = None,
    floor_description: str | None = None,
    floor_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Persist active-floor state for the current session/context."""

    _cleanup_expired_state()
    key = _current_state_key()
    state = {
        "floor_id": floor_id,
        "floor_ref": floor_ref,
        "floor_handle": floor_handle,
        "floor_title": floor_title,
        "floor_description": floor_description,
        "floor_tags": floor_tags or [],
        "updated_at": time.time(),
    }
    _ACTIVE_FLOOR_STATE[key] = state
    logger.info("Active floor state set state_key=%s", key)
    return {
        "floor_id": floor_id,
        "floor_ref": floor_ref,
        "floor_handle": floor_handle,
        "floor_title": floor_title,
        "floor_description": floor_description,
        "floor_tags": floor_tags or [],
    }


def get_active_floor_state() -> dict[str, Any] | None:
    """Get persisted active-floor state for the current session/context."""

    _cleanup_expired_state()
    key = _current_state_key()
    logger.info("Active floor state get state_key=%s", key)
    state = _ACTIVE_FLOOR_STATE.get(key)
    if not state:
        return None
    return {
        "floor_id": str(state["floor_id"]),
        "floor_ref": str(state["floor_ref"]),
        "floor_handle": state.get("floor_handle"),
        "floor_title": state.get("floor_title"),
        "floor_description": state.get("floor_description"),
        "floor_tags": list(state.get("floor_tags") or []),
    }


def clear_active_floor_state() -> None:
    """Clear active-floor state for the current session/context."""

    _cleanup_expired_state()
    _ACTIVE_FLOOR_STATE.pop(_current_state_key(), None)


def clear_all_active_floor_state() -> None:
    """Test helper to reset all in-memory active-floor state."""

    _ACTIVE_FLOOR_STATE.clear()
