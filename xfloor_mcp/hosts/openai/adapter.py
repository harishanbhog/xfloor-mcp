"""OpenAI host adapter: widget metadata + template decoration."""

from __future__ import annotations

import logging
import inspect
from dataclasses import dataclass
from typing import Any

from ..base import HostCapabilities
from ...settings import Settings
from .constants import QUERY_CURRENT_FLOOR_WIDGET_URI, SET_ACTIVE_FLOOR_WIDGET_URI, WIDGET_MIME_TYPE
from .widget_templates import build_floor_summary_widget_html, build_query_floor_answer_widget_html

logger = logging.getLogger(__name__)
DEFAULT_WIDGET_RESOURCE_DOMAINS = [
    "https://persistent.oaistatic.com",
    "https://d2e5822u5ecuq8.cloudfront.net",
]


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

    def _build_registration_kwargs(self, mcp: Any, *, name: str, description: str, meta: dict[str, Any]) -> dict[str, Any]:
        """Build best-effort resource registration kwargs for current runtime signature."""

        try:
            supported = set(inspect.signature(mcp.resource).parameters.keys())
        except (TypeError, ValueError):
            supported = set()

        kwargs: dict[str, Any] = {}
        if "name" in supported:
            kwargs["name"] = name
        if "description" in supported:
            kwargs["description"] = description
        if "mime_type" in supported:
            kwargs["mime_type"] = WIDGET_MIME_TYPE
        elif "mimeType" in supported:
            kwargs["mimeType"] = WIDGET_MIME_TYPE
        if "_meta" in supported:
            kwargs["_meta"] = meta
        elif "meta" in supported:
            kwargs["meta"] = meta

        logger.info("openai resource registration kwargs resolved supported=%s kwargs_keys=%s", sorted(supported), sorted(kwargs.keys()))
        return kwargs

    def _build_widget_resource(self) -> dict[str, Any]:
        connect_domains = list(
            dict.fromkeys(
                (self.settings.xfloor_widget_connect_domains if self.settings else [])
                + ([self.settings.xfloor_base_url] if self.settings else [])
            )
        )
        configured = self.settings.xfloor_widget_resource_domains if self.settings else DEFAULT_WIDGET_RESOURCE_DOMAINS
        resource_domains = list(dict.fromkeys(configured + DEFAULT_WIDGET_RESOURCE_DOMAINS))

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
                    "mimeType": WIDGET_MIME_TYPE,
                    "text": build_floor_summary_widget_html(
                        asset_base_url=(self.settings.xfloor_widget_domain if self.settings else None)
                    ),
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
        configured = self.settings.xfloor_widget_resource_domains if self.settings else DEFAULT_WIDGET_RESOURCE_DOMAINS
        resource_domains = list(dict.fromkeys(configured + DEFAULT_WIDGET_RESOURCE_DOMAINS))
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

        payload = {
            "contents": [
                {
                    "uri": QUERY_CURRENT_FLOOR_WIDGET_URI,
                    "mimeType": WIDGET_MIME_TYPE,
                    "text": build_query_floor_answer_widget_html(
                        asset_base_url=(self.settings.xfloor_widget_domain if self.settings else None)
                    ),
                    "_meta": query_widget_meta,
                }
            ]
        }
        logger.info(
            "openai query widget payload built uri=%s mime=%s openai_widget_csp=%s ui_csp=%s ui_domain=%s",
            QUERY_CURRENT_FLOOR_WIDGET_URI,
            payload["contents"][0]["mimeType"],
            payload["contents"][0]["_meta"].get("openai/widgetCSP"),
            payload["contents"][0]["_meta"].get("ui", {}).get("csp"),
            payload["contents"][0]["_meta"].get("ui", {}).get("domain"),
        )
        return payload

    def register_resources(self, mcp: Any) -> None:
        logger.info(
            "Registering openai widget resources set_active_uri=%s query_uri=%s",
            SET_ACTIVE_FLOOR_WIDGET_URI,
            QUERY_CURRENT_FLOOR_WIDGET_URI,
        )
        resource_domains = list(
            dict.fromkeys(
                list(self.settings.xfloor_widget_resource_domains if self.settings else [])
                + DEFAULT_WIDGET_RESOURCE_DOMAINS
            )
        )
        set_active_registration_meta = {
            "ui": {
                "csp": {
                    "connectDomains": self.settings.xfloor_widget_connect_domains if self.settings else [],
                    "resourceDomains": resource_domains,
                },
                "domain": self.settings.xfloor_widget_domain if self.settings else None,
            }
        }
        query_registration_meta = {
            "ui": {
                "csp": {
                    "connectDomains": self.settings.xfloor_widget_connect_domains if self.settings else [],
                    "resourceDomains": resource_domains,
                },
                "domain": self.settings.xfloor_widget_domain if self.settings else None,
            }
        }
        logger.info(
            "openai query widget registration meta uri=%s ui_csp=%s ui_domain=%s",
            QUERY_CURRENT_FLOOR_WIDGET_URI,
            (query_registration_meta.get("ui") or {}).get("csp"),
            (query_registration_meta.get("ui") or {}).get("domain"),
        )
        set_active_kwargs = self._build_registration_kwargs(
            mcp,
            name="xfloor-set-active-floor-v1",
            description="OpenAI widget template for xFloor set-active-floor responses.",
            meta=set_active_registration_meta,
        )
        query_kwargs = self._build_registration_kwargs(
            mcp,
            name="xfloor-query-current-floor-v1",
            description="OpenAI widget template for xFloor query-current-floor responses.",
            meta=query_registration_meta,
        )

        def openai_set_active_floor_widget() -> str:
            resource_payload = self._build_widget_resource()
            csp_meta = resource_payload["contents"][0]["_meta"]["openai/widgetCSP"]
            ui_meta = resource_payload["contents"][0]["_meta"].get("ui", {})
            html = resource_payload["contents"][0].get("text") or ""
            logger.info(
                "openai widget resource served uri=%s csp_connect=%s csp_resource=%s ui_domain=%s",
                SET_ACTIVE_FLOOR_WIDGET_URI,
                csp_meta.get("connectDomains"),
                csp_meta.get("resourceDomains"),
                ui_meta.get("domain"),
            )
            logger.info(
                "openai widget html preview uri=%s html_start=%r",
                SET_ACTIVE_FLOOR_WIDGET_URI,
                html[:500],
            )
            return html

        def openai_query_current_floor_widget() -> str:
            resource_payload = self._build_query_widget_resource()
            csp_meta = resource_payload["contents"][0]["_meta"]["openai/widgetCSP"]
            ui_meta = resource_payload["contents"][0]["_meta"].get("ui", {})
            html = resource_payload["contents"][0].get("text") or ""
            logger.info(
                "openai query widget resource served uri=%s csp_connect=%s csp_resource=%s ui_domain=%s",
                QUERY_CURRENT_FLOOR_WIDGET_URI,
                csp_meta.get("connectDomains") or csp_meta.get("connect_domains"),
                csp_meta.get("resourceDomains") or csp_meta.get("resource_domains"),
                ui_meta.get("domain"),
            )
            logger.info(
                "openai query widget html preview uri=%s html_start=%r",
                QUERY_CURRENT_FLOOR_WIDGET_URI,
                html[:500],
            )
            return html

        try:
            mcp.resource(SET_ACTIVE_FLOOR_WIDGET_URI, **set_active_kwargs)(openai_set_active_floor_widget)
        except TypeError:
            mcp.resource(SET_ACTIVE_FLOOR_WIDGET_URI)(openai_set_active_floor_widget)

        try:
            mcp.resource(QUERY_CURRENT_FLOOR_WIDGET_URI, **query_kwargs)(openai_query_current_floor_widget)
        except TypeError:
            mcp.resource(QUERY_CURRENT_FLOOR_WIDGET_URI)(openai_query_current_floor_widget)

    def build_render_tool_result_meta(self, resource_uri: str) -> dict[str, Any]:
        """Metadata contract for render tools (Apps-first + ChatGPT compatibility)."""

        return {
            "ui": {"resourceUri": resource_uri},
            "openai/outputTemplate": resource_uri,
        }

    def build_render_tool_annotations(self, resource_uri: str) -> dict[str, Any]:
        return {
            "openai/outputTemplate": resource_uri,
            "ui/resourceUri": resource_uri,
        }

    def decorate_set_active_floor_response(self, core_response: dict[str, Any]) -> dict[str, Any]:
        decorated = dict(core_response)
        decorated["_meta"] = self.build_render_tool_result_meta(SET_ACTIVE_FLOOR_WIDGET_URI)
        return decorated

    def decorate_query_current_floor_response(self, response: dict[str, Any]) -> dict[str, Any]:
        decorated = dict(response)
        decorated["_meta"] = self.build_render_tool_result_meta(QUERY_CURRENT_FLOOR_WIDGET_URI)
        return decorated
