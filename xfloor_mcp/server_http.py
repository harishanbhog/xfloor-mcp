"""FastAPI app exposing Streamable HTTP MCP at /mcp."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, Response
from mcp.server.fastmcp import FastMCP

from .auth import (
    OAuthResolutionError,
    build_www_authenticate_header,
    is_public_discovery_path,
    oauth_authorization_server_metadata,
    protected_resource_metadata,
    resolve_request_identity,
)
from .hosts.factory import build_host_adapter
from .hosts.openai.constants import QUERY_CURRENT_FLOOR_WIDGET_URI, SET_ACTIVE_FLOOR_WIDGET_URI, WIDGET_MIME_TYPE
from .hosts.openai.adapter import resolve_ui_domain
from .hosts.openai.widgets.set_active_floor import build_set_active_floor_preview_html
from .hosts.openai.widgets.query_current_floor import build_query_current_floor_preview_html
from .request_context import (
    set_auth_mode,
    set_active_floor_id,
    set_app_id,
    set_auth_token,
    set_oauth_issuer,
    set_oauth_subject,
    set_session_key,
    set_user_id,
    set_xfloor_service_token,
)
from .settings import Settings, get_settings
from .tools import register_tools
from .xfloor_client import XFloorClient

logger = logging.getLogger(__name__)


def _build_mcp_app(mcp: FastMCP) -> Any:
    """Create an ASGI app for Streamable HTTP transport."""

    if hasattr(mcp, "streamable_http_app"):
        try:
            return mcp.streamable_http_app(path="/mcp")
        except TypeError:
            return mcp.streamable_http_app()
    if hasattr(mcp, "http_app"):
        try:
            return mcp.http_app(path="/mcp")
        except TypeError:
            return mcp.http_app()
    raise RuntimeError("Installed mcp package does not expose Streamable HTTP app builders")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Run MCP session manager for clean startup/shutdown."""

    session_manager = getattr(app.state.mcp, "session_manager", None)
    if session_manager is None:
        yield
        return

    if hasattr(session_manager, "run"):
        async with session_manager.run():
            yield
        return

    if hasattr(session_manager, "__aenter__") and hasattr(session_manager, "__aexit__"):
        async with session_manager:
            yield
        return

    yield


def create_http_app(settings: Settings) -> FastAPI:
    """Create FastAPI app and mount MCP Streamable HTTP transport at `/mcp`."""

    mcp = FastMCP(settings.app_name, stateless_http=True, json_response=True)
    client = XFloorClient(
        base_url=settings.xfloor_base_url,
        timeout_seconds=settings.xfloor_timeout_seconds,
    )
    host_adapter = build_host_adapter(settings)
    register_tools(mcp, client, settings=settings, host_adapter=host_adapter)
    if getattr(host_adapter, "name", "") == "openai":
        logger.info(
            "OpenAI synthetic template discovery enabled resources=%s",
            [SET_ACTIVE_FLOOR_WIDGET_URI, QUERY_CURRENT_FLOOR_WIDGET_URI],
        )

    app = FastAPI(title=settings.app_name, lifespan=_lifespan)
    app.state.mcp = mcp

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allow_methods,
        allow_headers=settings.cors_allow_headers,
        expose_headers=["Mcp-Session-Id"],
    )

    @app.middleware("http")
    async def xfloor_context_middleware(request: Request, call_next):
        request_id = uuid.uuid4().hex[:8]
        started = time.perf_counter()
        path = request.url.path
        method = request.method.upper()
        rpc_method: str | None = None
        rpc_id: Any = None
        logger.info("MCP middleware request start request_id=%s method=%s path=%s", request_id, method, path)
        is_mcp_path = path == "/mcp" or path.startswith("/mcp/")
        if is_mcp_path:
            openai_session = request.headers.get("x-openai-session") or request.headers.get("X-OpenAI-Session")
            tool_name = (
                request.headers.get("x-openai-tool-name")
                or request.headers.get("X-OpenAI-Tool-Name")
                or request.headers.get("x-tool-name")
                or request.headers.get("X-Tool-Name")
            )
            logger.info(
                "MCP session header path=%s tool=%s missing=%s x-openai-session=%s",
                path,
                tool_name or "unknown",
                openai_session is None,
                openai_session,
            )
            if method == "POST":
                try:
                    raw_body = await request.body()
                    payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                except Exception:  # noqa: BLE001
                    payload = {}
                rpc_method = payload.get("method") if isinstance(payload, dict) else None
                rpc_id = payload.get("id") if isinstance(payload, dict) else None
                params = payload.get("params") if isinstance(payload, dict) and isinstance(payload.get("params"), dict) else {}
                if rpc_method:
                    logger.info("MCP jsonrpc method request_id=%s method=%s", request_id, rpc_method)
                if rpc_method in {"resources/read", "resources/templates/read", "resources/get"}:
                    requested_uri = params.get("uri") or params.get("resource")
                    logger.info(
                        "MCP widget resource read request_id=%s rpc_method=%s uri=%s expected_set_active_uri=%s",
                        request_id,
                        rpc_method,
                        requested_uri,
                        "ui://widget/set-active-floor-v1.html",
                    )
        if is_public_discovery_path(path):
            logger.info("Bypassing auth for public OAuth discovery path: %s", path)
            response = await call_next(request)
            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "MCP middleware request end request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
                request_id,
                method,
                path,
                response.status_code,
                duration_ms,
            )
            return response
        if not is_mcp_path:
            response = await call_next(request)
            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "MCP middleware request end request_id=%s method=%s path=%s status=%s duration_ms=%.1f",
                request_id,
                method,
                path,
                response.status_code,
                duration_ms,
            )
            return response

        try:
            identity = await asyncio.to_thread(resolve_request_identity, request.headers, settings)
        except OAuthResolutionError as exc:
            content: dict[str, Any] = {"error": str(exc), "auth_mode": settings.xfloor_auth_mode}
            if exc.missing:
                content["missing"] = exc.missing
                content["hint"] = (
                    "Set required headers or configure XFLOOR_DEFAULT_AUTH_TOKEN / XFLOOR_DEFAULT_BEARER_TOKEN / "
                    "XFLOOR_DEFAULT_USER_ID / XFLOOR_DEFAULT_APP_ID for local development."
                )
            headers: dict[str, str] = {}
            if settings.xfloor_auth_mode == "oauth":
                resource_metadata_url = str(request.url_for("oauth_protected_resource_metadata"))
                if exc.status_code == 401:
                    logger.info("Returning 401 Bearer challenge for protected MCP request without valid auth.")
                headers["WWW-Authenticate"] = build_www_authenticate_header(
                    settings,
                    resource_metadata_url,
                    error="invalid_token" if exc.status_code == 401 else "invalid_request",
                )
            response = JSONResponse(
                status_code=exc.status_code,
                content=content,
                headers=headers,
            )
            duration_ms = (time.perf_counter() - started) * 1000
            logger.warning(
                "MCP middleware auth failure request_id=%s method=%s path=%s status=%s duration_ms=%.1f error=%s",
                request_id,
                method,
                path,
                exc.status_code,
                duration_ms,
                str(exc),
            )
            return response

        set_auth_mode(identity.auth_mode)
        set_auth_token(identity.auth_token)
        set_xfloor_service_token(identity.service_token)
        set_user_id(identity.user_id)
        set_app_id(identity.app_id)
        set_active_floor_id(identity.active_floor_id)
        set_session_key(identity.session_key)
        set_oauth_issuer(identity.verified_identity.issuer if identity.verified_identity else None)
        set_oauth_subject(identity.verified_identity.subject if identity.verified_identity else None)
        try:
            if rpc_method in {"resources/list", "resources/templates/list"} and getattr(host_adapter, "name", "") == "openai":
                resource_domains = list(
                    dict.fromkeys(
                        list(settings.xfloor_widget_resource_domains)
                        + ["https://d2e5822u5ecuq8.cloudfront.net"]
                    )
                )
                common_meta = {
                    "ui": {
                        "csp": {
                            "connectDomains": settings.xfloor_widget_connect_domains,
                            "resourceDomains": resource_domains,
                        },
                    },
                    "openai/widgetPrefersBorder": True,
                }
                ui_domain = resolve_ui_domain(settings.xfloor_widget_domain)
                if ui_domain:
                    common_meta["ui"]["domain"] = ui_domain
                resource_items = [
                    {
                        "uri": SET_ACTIVE_FLOOR_WIDGET_URI,
                        "name": "xFloor Active Floor",
                        "description": "OpenAI widget template for xFloor set-active-floor responses.",
                        "mimeType": WIDGET_MIME_TYPE,
                        "_meta": common_meta,
                    },
                    {
                        "uri": QUERY_CURRENT_FLOOR_WIDGET_URI,
                        "name": "xFloor Query Result",
                        "description": "OpenAI widget template for xFloor query-current-floor responses.",
                        "mimeType": WIDGET_MIME_TYPE,
                        "_meta": common_meta,
                    },
                ]
                result_key = "resourceTemplates" if rpc_method == "resources/templates/list" else "resources"
                response = JSONResponse(
                    status_code=200,
                    content={"jsonrpc": "2.0", "id": rpc_id, "result": {result_key: resource_items}},
                )
                duration_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "MCP middleware synthetic %s response request_id=%s resource_count=%s resources=%s duration_ms=%.1f",
                    rpc_method,
                    request_id,
                    len(resource_items),
                    [
                        {
                            "uri": item["uri"],
                            "name": item.get("name"),
                            "mimeType": item.get("mimeType"),
                            "meta_keys": sorted((item.get("_meta") or {}).keys()),
                            "ui_domain": ((item.get("_meta") or {}).get("ui") or {}).get("domain"),
                            "ui_csp": ((item.get("_meta") or {}).get("ui") or {}).get("csp"),
                        }
                        for item in resource_items
                    ],
                    duration_ms,
                )
                logger.info("resources/list returning count=%s", len(resource_items))
                for item in resource_items:
                    meta = item.get("_meta") or {}
                    ui = meta.get("ui") or {}
                    logger.info(
                        "resources/list item uri=%s name=%s mime=%s has_meta=%s meta_keys=%s has_ui=%s has_ui_domain=%s has_ui_csp=%s ui_domain=%s ui_csp=%s",
                        item.get("uri"),
                        item.get("name"),
                        item.get("mimeType"),
                        bool(meta),
                        sorted(meta.keys()),
                        bool(ui),
                        "domain" in ui and bool(ui.get("domain")),
                        "csp" in ui and bool(ui.get("csp")),
                        ui.get("domain"),
                        ui.get("csp"),
                    )
                return response
            response = await call_next(request)
            if rpc_method == "tools/call":
                logger.info("tools/call passthrough mode active; no response-shape rewriting request_id=%s", request_id)
            if rpc_method == "tools/list":
                try:
                    body = getattr(response, "body", None)
                    if body is None and hasattr(response, "body_iterator"):
                        chunks = [chunk async for chunk in response.body_iterator]
                        body = b"".join(chunks)
                        passthrough_headers = {
                            key: value
                            for key, value in response.headers.items()
                            if key.lower() not in {"content-length", "transfer-encoding"}
                        }
                        response = Response(
                            content=body,
                            status_code=response.status_code,
                            headers=passthrough_headers,
                            media_type=response.media_type,
                        )
                    if body:
                        payload = json.loads(body.decode("utf-8"))
                        tools = (((payload or {}).get("result") or {}).get("tools") or [])
                        output_template_by_tool = {
                            "xfloor_set_active_floor": SET_ACTIVE_FLOOR_WIDGET_URI,
                            "xfloor_query_current_floor": QUERY_CURRENT_FLOOR_WIDGET_URI,
                        }
                        for tool in tools:
                            tool_name = tool.get("name")
                            template_uri = output_template_by_tool.get(tool_name)
                            if not template_uri:
                                continue
                            annotations = tool.get("annotations") if isinstance(tool.get("annotations"), dict) else {}
                            annotations["openai/outputTemplate"] = template_uri
                            annotations["ui/resourceUri"] = template_uri
                            tool["annotations"] = annotations
                            meta = tool.get("_meta") if isinstance(tool.get("_meta"), dict) else {}
                            meta["openai/outputTemplate"] = template_uri
                            ui_meta = meta.get("ui") if isinstance(meta.get("ui"), dict) else {}
                            ui_meta["resourceUri"] = template_uri
                            meta["ui"] = ui_meta
                            tool["_meta"] = meta

                        set_active_descriptor = next(
                            (tool for tool in tools if tool.get("name") == "xfloor_set_active_floor"),
                            None,
                        )
                        logger.info("tools/list descriptor xfloor_set_active_floor=%s", set_active_descriptor)
                        patched_headers = {
                            key: value
                            for key, value in response.headers.items()
                            if key.lower() not in {"content-length", "transfer-encoding"}
                        }
                        response = JSONResponse(
                            status_code=response.status_code,
                            content=payload,
                            headers=patched_headers,
                        )
                    else:
                        logger.warning("tools/list response body unavailable for descriptor logging")
                except Exception:
                    logger.exception("Failed to inspect tools/list response payload")
            duration_ms = (time.perf_counter() - started) * 1000
            logger.info(
                "MCP middleware request end request_id=%s method=%s path=%s status=%s duration_ms=%.1f session_key=%s",
                request_id,
                method,
                path,
                response.status_code,
                duration_ms,
                identity.session_key,
            )
            return response
        finally:
            set_auth_mode(None)
            set_auth_token(None)
            set_xfloor_service_token(None)
            set_user_id(None)
            set_app_id(None)
            set_active_floor_id(None)
            set_session_key(None)
            set_oauth_issuer(None)
            set_oauth_subject(None)

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    if getattr(host_adapter, "name", "") == "openai":
        logger.info("Registering OpenAI widget preview route path=%s", "/preview/openai/set-active-floor")

        @app.get("/preview/openai/set-active-floor", response_class=HTMLResponse)
        async def openai_set_active_floor_preview() -> HTMLResponse:
            return HTMLResponse(build_set_active_floor_preview_html(asset_base_url=settings.xfloor_widget_domain))

        @app.get("/preview/openai/query-current-floor", response_class=HTMLResponse)
        async def openai_query_current_floor_preview() -> HTMLResponse:
            return HTMLResponse(build_query_current_floor_preview_html(asset_base_url=settings.xfloor_widget_domain))

        @app.get("/preview/openai/query_current_floor", response_class=HTMLResponse)
        async def openai_query_current_floor_preview_alias() -> HTMLResponse:
            return HTMLResponse(build_query_current_floor_preview_html(asset_base_url=settings.xfloor_widget_domain))

    @app.get("/.well-known/oauth-protected-resource", name="oauth_protected_resource_metadata")
    async def oauth_protected_resource_metadata() -> dict[str, Any]:
        return protected_resource_metadata(settings)

    @app.get("/mcp/.well-known/oauth-protected-resource")
    async def oauth_protected_resource_metadata_mcp_alias() -> dict[str, Any]:
        return protected_resource_metadata(settings)

    @app.get("/.well-known/openid-configuration")
    async def openid_configuration() -> dict[str, Any]:
        return oauth_authorization_server_metadata(settings)

    @app.get("/.well-known/oauth-authorization-server")
    async def oauth_authorization_server() -> dict[str, Any]:
        return oauth_authorization_server_metadata(settings)

    @app.get("/mcp/.well-known/openid-configuration")
    async def openid_configuration_mcp_alias() -> dict[str, Any]:
        return oauth_authorization_server_metadata(settings)

    @app.get("/mcp/.well-known/oauth-authorization-server")
    async def oauth_authorization_server_mcp_alias() -> dict[str, Any]:
        return oauth_authorization_server_metadata(settings)

    widget_dist_candidates = [
        Path(__file__).resolve().parents[1] / "openai_widget" / "dist",
        Path.cwd() / "openai_widget" / "dist",
        Path("/app/openai_widget/dist"),
    ]
    widget_dist_dir = next((candidate for candidate in widget_dist_candidates if candidate.exists()), widget_dist_candidates[0])
    if widget_dist_dir.exists():
        app.mount("/openai-widget", StaticFiles(directory=str(widget_dist_dir)), name="openai-widget-static")
        logger.info("Mounted OpenAI widget static assets path=/openai-widget directory=%s", widget_dist_dir)
    else:
        logger.warning("OpenAI widget dist directory not found; run frontend build to enable static assets path=%s", widget_dist_dir)

    app.mount("/", _build_mcp_app(mcp))
    mount_summaries: list[dict[str, Any]] = []
    for route in app.routes:
        route_path = getattr(route, "path", None)
        route_name = getattr(route, "name", None)
        route_type = route.__class__.__name__
        route_app = getattr(route, "app", None)
        route_app_type = route_app.__class__.__name__ if route_app is not None else None
        route_directory = getattr(route_app, "directory", None)
        mount_summaries.append(
            {
                "path": route_path,
                "name": route_name,
                "type": route_type,
                "app_type": route_app_type,
                "directory": str(route_directory) if route_directory is not None else None,
            }
        )
    logger.info("FastAPI route/mount summary routes=%s", mount_summaries)
    return app


# ASGI app for uvicorn module path loading
app = create_http_app(get_settings())
