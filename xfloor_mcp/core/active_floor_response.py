"""Host-agnostic response shaping for active-floor tools."""

from __future__ import annotations

from typing import Any


def build_core_set_active_floor_response(state: dict[str, Any]) -> dict[str, Any]:
    """Build neutral set-active-floor response payload.

    This module must remain host-agnostic: no OpenAI template URIs or host metadata.
    """

    minimal_message = f"Active floor set to @{state['floor_ref']}"
    blocks = state.get("floor_blocks") or []

    return {
        "ok": True,
        "message": minimal_message,
        "content": [{"type": "text", "text": minimal_message}],
        "floor_ref": state["floor_ref"],
        "floor_id": state["floor_id"],
        "floor_title": state.get("floor_title"),
        "floor_description": state.get("floor_description"),
        "floor_logo_url": state.get("floor_logo_url"),
        "blocks": blocks,
        "blocks_count": len(blocks),
        "state_scope": "in_memory_session",
        "structuredContent": {
            "floor_ref": state["floor_ref"],
            "floor_id": state["floor_id"],
            "floor_title": state.get("floor_title"),
            "floor_description": state.get("floor_description"),
            "floor_logo_url": state.get("floor_logo_url"),
            "blocks": blocks,
        },
    }
