"""FastAPI app exposing Streamable HTTP MCP at /mcp."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

from .auth import (
    OAuthResolutionError,
    build_www_authenticate_header,
    is_public_discovery_path,
    oauth_authorization_server_metadata,
    protected_resource_metadata,
    resolve_request_identity,
)
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
    register_tools(mcp, client, settings=settings)

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
            response = await call_next(request)
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

    app.mount("/", _build_mcp_app(mcp))
    return app


# ASGI app for uvicorn module path loading
app = create_http_app(get_settings())
