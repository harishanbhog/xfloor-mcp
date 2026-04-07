"""Tool-result normalization helpers for ChatGPT-style clients."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class NormalizedToolRenderDecision:
    should_render_widget: bool
    reason: str
    resource_uri: str | None
    output_template: str | None
    structured_content: dict[str, Any]
    content: list[dict[str, Any]]
    fallback_text: str | None


def _extract_text_fallback(content: list[dict[str, Any]]) -> str | None:
    for item in content:
        if item.get("type") == "text" and isinstance(item.get("text"), str) and item.get("text").strip():
            return item["text"]
    return None


def decide_tool_result_rendering(
    result: dict[str, Any] | None,
    *,
    widget_support_enabled: bool,
    widget_registry: set[str] | None = None,
) -> NormalizedToolRenderDecision:
    """Normalize a tool result for chat rendering while preserving widget metadata."""

    payload = result or {}
    meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    ui = meta.get("ui") if isinstance(meta.get("ui"), dict) else {}

    resource_uri = ui.get("resourceUri") if isinstance(ui.get("resourceUri"), str) else None
    output_template = meta.get("openai/outputTemplate") if isinstance(meta.get("openai/outputTemplate"), str) else None
    structured_content = payload.get("structuredContent") if isinstance(payload.get("structuredContent"), dict) else {}
    content = payload.get("content") if isinstance(payload.get("content"), list) else []
    fallback_text = _extract_text_fallback(content)

    logger.info(
        "tool result contained UI metadata resource_uri=%s output_template=%s structured_content_keys=%s content_items=%s",
        resource_uri,
        output_template,
        sorted(structured_content.keys()),
        len(content),
    )

    chosen_uri = resource_uri or output_template
    if not chosen_uri:
        logger.info("rendering fallback text because widget metadata missing")
        return NormalizedToolRenderDecision(False, "missing_ui_metadata", None, output_template, structured_content, content, fallback_text)

    if not widget_support_enabled:
        logger.info("rendering fallback text because widget unsupported")
        return NormalizedToolRenderDecision(False, "widget_support_disabled", chosen_uri, output_template, structured_content, content, fallback_text)

    if widget_registry is not None and chosen_uri not in widget_registry:
        logger.info("widget registry lookup failed resource_uri=%s", chosen_uri)
        return NormalizedToolRenderDecision(False, "widget_registry_miss", chosen_uri, output_template, structured_content, content, fallback_text)

    logger.info("tool result eligible for widget rendering resource_uri=%s", chosen_uri)
    return NormalizedToolRenderDecision(True, "widget_render_enabled", chosen_uri, output_template, structured_content, content, fallback_text)
