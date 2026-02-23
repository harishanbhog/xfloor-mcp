from __future__ import annotations

from typing import Any, Callable

import pytest

from xfloor_mcp.tools import XFloorGetInput, XFloorPostInput, register_tools


class _FakeMCP:
    def __init__(self) -> None:
        self.registry: dict[str, Callable[..., Any]] = {}

    def tool(self, name: str, description: str):
        def decorator(func):
            self.registry[name] = func
            return func

        return decorator


class _FakeClient:
    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"method": "GET", "path": path, "params": params}

    async def post(self, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"method": "POST", "path": path, "body": body}


@pytest.mark.asyncio
async def test_tools_are_registered_and_callable() -> None:
    mcp = _FakeMCP()
    register_tools(mcp=mcp, client=_FakeClient())

    assert "xfloor_get" in mcp.registry
    assert "xfloor_post" in mcp.registry

    get_result = await mcp.registry["xfloor_get"](XFloorGetInput(path="/v1/floors", params={"limit": 10}))
    post_result = await mcp.registry["xfloor_post"](XFloorPostInput(path="/v1/run", body={"foo": "bar"}))

    assert get_result["method"] == "GET"
    assert post_result["method"] == "POST"
