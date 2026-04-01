"""OpenAI host adapter: widget metadata + template decoration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..base import HostCapabilities
from ...settings import Settings
from .constants import SET_ACTIVE_FLOOR_WIDGET_URI
from .widget_templates import build_floor_summary_widget_html

logger = logging.getLogger(__name__)


@dataclass
class OpenAIHostAdapter:
    """OpenAI-specific decoration and resource registration.

    Keeps OpenAI-only concerns out of host-agnostic core logic.
    """

    settings: Settings | None = None
    name: str = "openai"
    capabilities: HostCapabilities = HostCapabilities(
        supports_tool_result_templates=True,
        supports_widget_resources=True,
        supports_html_widgets=True,
        supports_host_metadata_injection=True,
    )

    def _build_widget_resource(self) -> dict[str, Any]:
        connect_domains = list(
            dict.fromkeys(
                (self.settings.xfloor_widget_connect_domains if self.settings else [])
                + ([self.settings.xfloor_base_url] if self.settings else [])
            )
        )
        resource_domains = self.settings.xfloor_widget_resource_domains if self.settings else ["https://persistent.oaistatic.com"]

        ui_meta: dict[str, Any] = {
            "csp": {
                "connectDomains": connect_domains,
                "resourceDomains": resource_domains,
            }
        }
        if self.settings and self.settings.xfloor_widget_domain:
            ui_meta["domain"] = self.settings.xfloor_widget_domain

        payload = {
            "contents": [
                {
                    "uri": SET_ACTIVE_FLOOR_WIDGET_URI,
                    "mimeType": "text/html",
                    "text": build_floor_summary_widget_html(),
                    "_meta": {
                        "openai/widgetDescription": "Shows active floor details including title, description, logo, and blocks.",
                        "openai/widgetPrefersBorder": True,
                        "openai/widgetCSP": {
                            "connectDomains": connect_domains,
                            "resourceDomains": resource_domains,
                        },
                        "ui": ui_meta,
                    },
                }
            ]
        }
        logger.info(
            "openai widget payload built uri=%s mime=%s openai_widget_csp=%s ui_csp=%s ui_domain=%s",
            SET_ACTIVE_FLOOR_WIDGET_URI,
            payload["contents"][0]["mimeType"],
            payload["contents"][0]["_meta"].get("openai/widgetCSP"),
            payload["contents"][0]["_meta"].get("ui", {}).get("csp"),
            payload["contents"][0]["_meta"].get("ui", {}).get("domain"),
        )
        return payload

    def register_resources(self, mcp: Any) -> None:
        logger.info("Registering openai widget resource uri=%s", SET_ACTIVE_FLOOR_WIDGET_URI)

        @mcp.resource(SET_ACTIVE_FLOOR_WIDGET_URI)
        def openai_set_active_floor_widget() -> dict[str, Any]:
            resource_payload = self._build_widget_resource()
            csp_meta = resource_payload["contents"][0]["_meta"]["openai/widgetCSP"]
            ui_meta = resource_payload["contents"][0]["_meta"].get("ui", {})
            logger.info(
                "openai widget resource served uri=%s csp_connect=%s csp_resource=%s ui_domain=%s",
                SET_ACTIVE_FLOOR_WIDGET_URI,
                csp_meta.get("connectDomains"),
                csp_meta.get("resourceDomains"),
                ui_meta.get("domain"),
            )
            return resource_payload

    def decorate_set_active_floor_response(self, core_response: dict[str, Any]) -> dict[str, Any]:
        decorated = dict(core_response)
        decorated["_meta"] = {
            "openai/outputTemplate": SET_ACTIVE_FLOOR_WIDGET_URI,
        }
        return decorated
