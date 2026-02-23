"""Local stdio entrypoint for MCP clients."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .settings import Settings
from .tools import register_tools
from .xfloor_client import XFloorClient


def create_stdio_server(settings: Settings) -> FastMCP:
    """Build FastMCP instance for stdio transport."""

    mcp = FastMCP(settings.app_name)
    client = XFloorClient(
        base_url=settings.xfloor_base_url,
        api_key=settings.xfloor_api_key,
        timeout_seconds=settings.xfloor_timeout_seconds,
    )
    register_tools(mcp, client)
    return mcp


async def run_stdio(settings: Settings) -> None:
    """Run MCP server in stdio mode."""

    mcp = create_stdio_server(settings)
    await mcp.run_stdio_async()
