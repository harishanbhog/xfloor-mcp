"""OpenAI host adapter: widget metadata + template decoration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..base import HostCapabilities
from ...settings import Settings
from .constants import QUERY_CURRENT_FLOOR_WIDGET_URI, SET_ACTIVE_FLOOR_WIDGET_URI
from .widget_templates import build_floor_summary_widget_html, build_query_floor_answer_widget_html

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

        widget_csp = {
            "connectDomains": connect_domains,
            "resourceDomains": resource_domains,
            # Added for compatibility with host inspectors that render snake_case keys.
            "connect_domains": connect_domains,
            "resource_domains": resource_domains,
        }

        widget_meta: dict[str, Any] = {
            "openai/widgetDescription": "Shows active floor details including title, description, logo, and blocks.",
            "openai/widgetPrefersBorder": True,
            "openai/widgetCSP": widget_csp,
            "ui": ui_meta,
        }
        if self.settings and self.settings.xfloor_widget_domain:
            widget_meta["openai/widgetDomain"] = self.settings.xfloor_widget_domain

        payload = {
            "contents": [
                {
                    "uri": SET_ACTIVE_FLOOR_WIDGET_URI,
                    "mimeType": "text/html",
                    "text": build_floor_summary_widget_html(),
                    "_meta": widget_meta,
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

    def _build_query_widget_resource(self) -> dict[str, Any]:
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

        widget_csp = {
            "connectDomains": connect_domains,
            "resourceDomains": resource_domains,
            "connect_domains": connect_domains,
            "resource_domains": resource_domains,
        }

        query_widget_meta: dict[str, Any] = {
            "openai/widgetDescription": "Shows floor query answer with related floor links.",
            "openai/widgetPrefersBorder": True,
            "openai/widgetCSP": widget_csp,
            "ui": ui_meta,
        }
        if self.settings and self.settings.xfloor_widget_domain:
            query_widget_meta["openai/widgetDomain"] = self.settings.xfloor_widget_domain

        return {
            "contents": [
                {
                    "uri": QUERY_CURRENT_FLOOR_WIDGET_URI,
                    "mimeType": "text/html",
                    "text": build_query_floor_answer_widget_html(),
                    "_meta": query_widget_meta,
                }
            ]
        }

    def register_resources(self, mcp: Any) -> None:
        logger.info("Registering openai widget resource uri=%s", SET_ACTIVE_FLOOR_WIDGET_URI)
        set_active_kwargs = (
            {"name": "xFloor Active Floor", "description": "OpenAI widget template for xFloor set-active-floor responses.", "mime_type": "text/html"},
            {"name": "xFloor Active Floor", "description": "OpenAI widget template for xFloor set-active-floor responses.", "mimeType": "text/html"},
            {},
        )
        query_kwargs = (
            {"name": "xFloor Query Result", "description": "OpenAI widget template for xFloor query-current-floor responses.", "mime_type": "text/html"},
            {"name": "xFloor Query Result", "description": "OpenAI widget template for xFloor query-current-floor responses.", "mimeType": "text/html"},
            {},
        )

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

        def openai_query_current_floor_widget() -> dict[str, Any]:
            return self._build_query_widget_resource()

        for candidate in set_active_kwargs:
            try:
                mcp.resource(SET_ACTIVE_FLOOR_WIDGET_URI, **candidate)(openai_set_active_floor_widget)
                break
            except TypeError:
                continue

        for candidate in query_kwargs:
            try:
                mcp.resource(QUERY_CURRENT_FLOOR_WIDGET_URI, **candidate)(openai_query_current_floor_widget)
                break
            except TypeError:
                continue

    def decorate_set_active_floor_response(self, core_response: dict[str, Any]) -> dict[str, Any]:
        decorated = dict(core_response)
        decorated["_meta"] = {
            "openai/outputTemplate": SET_ACTIVE_FLOOR_WIDGET_URI,
        }
        return decorated

    def decorate_query_current_floor_response(self, response: dict[str, Any]) -> dict[str, Any]:
        decorated = dict(response)
        decorated["_meta"] = {
            "openai/outputTemplate": QUERY_CURRENT_FLOOR_WIDGET_URI,
        }
        return decorated
