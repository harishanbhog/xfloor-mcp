"""MCP tool registration for xFloor APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .xfloor_client import XFloorClient


class XFloorGetInput(BaseModel):
    """Input payload for generic xFloor GET requests."""

    path: str = Field(description="xFloor API path, e.g. /v1/floors")
    params: dict[str, Any] | None = Field(default=None, description="Optional query params")


class XFloorPostInput(BaseModel):
    """Input payload for generic xFloor POST requests."""

    path: str = Field(description="xFloor API path, e.g. /v1/actions/run")
    body: dict[str, Any] | None = Field(default=None, description="Optional JSON request body")


def register_tools(mcp: Any, client: XFloorClient) -> None:
    """Register MCP tools on the provided FastMCP instance."""

    @mcp.tool(name="xfloor_get", description="Proxy a GET request to the xFloor API")
    async def xfloor_get(input: XFloorGetInput) -> dict[str, Any]:
        return await client.get(path=input.path, params=input.params)

    @mcp.tool(name="xfloor_post", description="Proxy a POST request to the xFloor API")
    async def xfloor_post(input: XFloorPostInput) -> dict[str, Any]:
        return await client.post(path=input.path, body=input.body)
