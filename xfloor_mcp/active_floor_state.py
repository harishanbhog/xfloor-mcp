"""In-memory active-floor state and alias resolution helpers."""

from __future__ import annotations

import json
import os
from typing import Any

from .request_context import get_app_id, get_session_key, get_user_id

_ACTIVE_FLOOR_STATE: dict[str, dict[str, str]] = {}


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
        normalized = normalize_floor_ref(floor_ref or floor_id)
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
    return f"fallback:{user_id}:{app_id}"


def set_active_floor_state(floor_id: str, floor_ref: str) -> dict[str, str]:
    """Persist active-floor state for the current session/context."""

    key = _current_state_key()
    state = {"floor_id": floor_id, "floor_ref": floor_ref}
    _ACTIVE_FLOOR_STATE[key] = state
    return state


def get_active_floor_state() -> dict[str, str] | None:
    """Get persisted active-floor state for the current session/context."""

    return _ACTIVE_FLOOR_STATE.get(_current_state_key())


def clear_active_floor_state() -> None:
    """Clear active-floor state for the current session/context."""

    _ACTIVE_FLOOR_STATE.pop(_current_state_key(), None)


def clear_all_active_floor_state() -> None:
    """Test helper to reset all in-memory active-floor state."""

    _ACTIVE_FLOOR_STATE.clear()
