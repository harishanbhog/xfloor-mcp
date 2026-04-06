"""Local stdio entrypoint for MCP clients."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .hosts.factory import build_host_adapter
from .request_context import set_app_id, set_auth_token, set_session_key, set_user_id
from .settings import Settings
from .tools import register_tools
from .xfloor_client import XFloorClient


def create_stdio_server(settings: Settings) -> FastMCP:
    """Build FastMCP instance for stdio transport."""

    mcp = FastMCP(settings.app_name)
    client = XFloorClient(
        base_url=settings.xfloor_base_url,
        timeout_seconds=settings.xfloor_timeout_seconds,
    )
    host_adapter = build_host_adapter(settings)
    register_tools(mcp, client, settings=settings, host_adapter=host_adapter)
    return mcp


async def run_stdio(settings: Settings) -> None:
    """Run MCP server in stdio mode."""

    if settings.xfloor_default_auth_token:
        set_auth_token(settings.xfloor_default_auth_token)
    if settings.xfloor_default_user_id:
        set_user_id(settings.xfloor_default_user_id)
    if settings.xfloor_default_app_id:
        set_app_id(settings.xfloor_default_app_id)

    session_user = settings.xfloor_default_user_id or "stdio-user"
    session_app = settings.xfloor_default_app_id or "stdio-app"
    set_session_key(f"stdio:{session_user}:{session_app}")

    mcp = create_stdio_server(settings)
    await mcp.run_stdio_async()


if __name__ == "__main__":
    import asyncio

    from .settings import get_settings

    asyncio.run(run_stdio(get_settings()))
