from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from xfloor_mcp.tools import (
    XFloorCreateEventInput,
    XFloorGetFloorInfoInput,
    XFloorQueryMemoryInput,
    XFloorRecentEventsInput,
    register_tools,
)
from xfloor_mcp.xfloor_client import XFloorClient


class _FakeMCP:
    def __init__(self) -> None:
        self.registry: dict[str, Callable[..., Any]] = {}

    def tool(self, name: str, description: str):
        def decorator(func):
            self.registry[name] = func
            return func

        return decorator


class _MockResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


@pytest.mark.asyncio
async def test_tools_registered_with_expected_inputs() -> None:
    mcp = _FakeMCP()
    register_tools(mcp=mcp, client=SimpleNamespace())

    assert set(mcp.registry.keys()) == {
        "xfloor_query_memory",
        "xfloor_create_event",
        "xfloor_recent_events",
        "xfloor_get_floor_info",
        "xfloor_wait_for_ingestion",
    }

    assert mcp.registry["xfloor_query_memory"].__annotations__["input"] is XFloorQueryMemoryInput
    assert mcp.registry["xfloor_create_event"].__annotations__["input"] is XFloorCreateEventInput
    assert mcp.registry["xfloor_recent_events"].__annotations__["input"] is XFloorRecentEventsInput
    assert mcp.registry["xfloor_get_floor_info"].__annotations__["input"] is XFloorGetFloorInfoInput


@pytest.mark.asyncio
async def test_client_calls_httpx_with_auth_and_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, **kwargs):
            captured.append(kwargs)
            return _MockResponse({"ok": True, "events": [{"title": "hello"}]})

    monkeypatch.setattr("xfloor_mcp.xfloor_client.httpx.AsyncClient", _FakeAsyncClient)

    client = XFloorClient(base_url="https://appfloor.in")
    await client.query_memory(
        "token-1",
        user_id="u1",
        query="find",
        floor_ids=["f1"],
        include_metadata="1",
        summary_needed="0",
    )
    await client.recent_events("token-2", params={"floor_id": "f1", "limit": 10})
    await client.get_floor_info("token-3", floor_id="f1")

    assert captured[0]["url"].endswith("/agent/memory/query")
    assert captured[0]["headers"]["Authorization"] == "Bearer token-1"
    assert captured[0]["json"]["include_metadata"] == "1"

    assert captured[1]["method"] == "GET"
    assert captured[1]["params"]["floor_id"] == "f1"

    assert captured[2]["url"].endswith("/api/memory/floor/info/f1")


@pytest.mark.asyncio
async def test_create_event_multipart_and_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict[str, Any]] = []

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def request(self, **kwargs):
            captured.append(kwargs)
            return _MockResponse({"ok": True})

    monkeypatch.setattr("xfloor_mcp.xfloor_client.httpx.AsyncClient", _FakeAsyncClient)

    client = XFloorClient(base_url="https://appfloor.in")
    valid_info = json.dumps(
        {
            "floor_id": "f1",
            "block_id": "b1",
            "user_id": "u1",
            "title": "Title",
            "description": "Desc",
        }
    )

    client.validate_input_info(valid_info)
    await client.create_event(
        "token",
        input_info=valid_info,
        files=[
            {
                "filename": "a.txt",
                "content_base64": "aGVsbG8=",
                "mime_type": "text/plain",
            }
        ],
    )

    assert captured[0]["url"].endswith("/api/memory/events")
    assert captured[0]["data"]["input_info"] == valid_info
    assert captured[0]["files"][0][0] == "files"

    with pytest.raises(ValueError, match="missing required field"):
        client.validate_input_info('{"floor_id":"f1"}')


@pytest.mark.asyncio
async def test_tool_uses_auth_header_and_wait_for_ingestion() -> None:
    mcp = _FakeMCP()

    class _FakeClient:
        def __init__(self) -> None:
            self.called_token: str | None = None
            self.calls = 0

        async def query_memory(self, token: str, **kwargs: Any) -> dict[str, Any]:
            self.called_token = token
            return {"ok": True}

        def validate_input_info(self, input_info: str) -> None:
            return None

        async def create_event(self, token: str, **kwargs: Any) -> dict[str, Any]:
            self.called_token = token
            return {"ok": True}

        async def recent_events(self, token: str, *, params: dict[str, Any]) -> dict[str, Any]:
            self.called_token = token
            self.calls += 1
            if self.calls > 1:
                return {"events": [{"title": "found me", "description": "body"}]}
            return {"events": []}

        async def get_floor_info(self, token: str, *, floor_id: str) -> dict[str, Any]:
            self.called_token = token
            return {"floor_id": floor_id}

    client = _FakeClient()
    register_tools(mcp=mcp, client=client)

    ctx = SimpleNamespace(request=SimpleNamespace(headers={"Authorization": "Bearer auth-from-header"}))

    res = await mcp.registry["xfloor_query_memory"](
        XFloorQueryMemoryInput(user_id="u1", query="q", floor_ids=["f1"]),
        ctx,
    )
    assert res["ok"] is True
    assert client.called_token == "auth-from-header"

    wait = await mcp.registry["xfloor_wait_for_ingestion"](
        SimpleNamespace(floor_id="f1", match_text="found", timeout_s=2, poll_interval_s=1, auth_token="x"),
        None,
    )
    assert wait["found"] is True
