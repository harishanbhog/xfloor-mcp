"""FastAPI app exposing Streamable HTTP MCP at /mcp."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.fastmcp import FastMCP

from .settings import Settings
from .tools import register_tools
from .xfloor_client import XFloorClient


def _build_mcp_app(mcp: FastMCP) -> Any:
    """Create an ASGI app for Streamable HTTP transport.

    We normalize to path='/' so mounting in FastAPI at '/mcp' does not produce '/mcp/mcp'.
    """

    if hasattr(mcp, "streamable_http_app"):
        try:
            return mcp.streamable_http_app(path="/")
        except TypeError:
            return mcp.streamable_http_app()
    if hasattr(mcp, "http_app"):
        try:
            return mcp.http_app(path="/")
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

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    app.mount("/mcp", _build_mcp_app(mcp))
    return app
