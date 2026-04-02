"""Host adapter abstraction for response/resource decorations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class HostCapabilities:
    supports_tool_result_templates: bool
    supports_widget_resources: bool
    supports_html_widgets: bool
    supports_host_metadata_injection: bool


class HostAdapter(Protocol):
    name: str
    capabilities: HostCapabilities

    def register_resources(self, mcp: Any) -> None: ...

    def decorate_set_active_floor_response(self, core_response: dict[str, Any]) -> dict[str, Any]: ...
