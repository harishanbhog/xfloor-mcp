"""Host adapter factory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import HostCapabilities
from .openai.adapter import OpenAIHostAdapter
from ..settings import Settings


@dataclass
class NoopHostAdapter:
    """Fallback host adapter for host-agnostic operation."""

    name: str = "none"
    capabilities: HostCapabilities = HostCapabilities(
        supports_tool_result_templates=False,
        supports_widget_resources=False,
        supports_html_widgets=False,
        supports_host_metadata_injection=False,
    )

    def register_resources(self, mcp: Any) -> None:
        return None

    def decorate_set_active_floor_response(self, core_response: dict[str, Any]) -> dict[str, Any]:
        return core_response


def build_host_adapter(settings: Settings) -> Any:
    host = (getattr(settings, "xfloor_host_adapter", "openai") or "openai").lower()
    if host == "openai":
        return OpenAIHostAdapter(settings=settings)
    return NoopHostAdapter()
