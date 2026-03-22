"""FastAPI app exposing Streamable HTTP MCP at /mcp."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

from .request_context import (
    set_active_floor_id,
    set_app_id,
    set_auth_token,
    set_session_key,
    set_user_id,
)
from .settings import Settings, get_settings
from .tools import register_tools
from .xfloor_client import XFloorClient


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


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    value = authorization.strip()
    if not value.lower().startswith("bearer "):
        return None
    token = value[7:].strip()
    return token or None


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
    register_tools(mcp, client)

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
        is_mcp_path = request.url.path == "/mcp" or request.url.path.startswith("/mcp/")
        if not is_mcp_path:
            return await call_next(request)

        token = _extract_bearer(request.headers.get("Authorization")) or settings.xfloor_default_auth_token
        user_id = request.headers.get("X-XFloor-User-Id") or settings.xfloor_default_user_id
        app_id = request.headers.get("X-XFloor-App-Id") or settings.xfloor_default_app_id
        active_floor_id = request.headers.get("X-XFloor-Active-Floor-Id")
        session_key = (
            request.headers.get("Mcp-Session-Id")
            or request.headers.get("X-Mcp-Session-Id")
            or (f"{user_id}:{app_id}" if user_id and app_id else None)
        )

        missing: list[str] = []
        if not token:
            missing.append("Authorization: Bearer <token>")
        if not user_id:
            missing.append("X-XFloor-User-Id")
        if not app_id:
            missing.append("X-XFloor-App-Id")

        if missing:
            return JSONResponse(
                status_code=400,
                content={
                    "error": "Missing required xFloor headers",
                    "missing": missing,
                    "hint": "Set required headers or configure XFLOOR_DEFAULT_AUTH_TOKEN / XFLOOR_DEFAULT_USER_ID / XFLOOR_DEFAULT_APP_ID for local development.",
                },
            )

        set_auth_token(token)
        set_user_id(user_id)
        set_app_id(app_id)
        set_active_floor_id(active_floor_id)
        set_session_key(session_key)
        try:
            return await call_next(request)
        finally:
            set_auth_token(None)
            set_user_id(None)
            set_app_id(None)
            set_active_floor_id(None)
            set_session_key(None)

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    app.mount("/", _build_mcp_app(mcp))
    return app


# ASGI app for uvicorn module path loading
app = create_http_app(get_settings())
