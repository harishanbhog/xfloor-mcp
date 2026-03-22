from __future__ import annotations

import importlib.util
import json
from types import SimpleNamespace
from typing import Any, Callable, get_type_hints

import pytest

HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
HAS_HTTPX = importlib.util.find_spec("httpx") is not None
HAS_FASTAPI = importlib.util.find_spec("fastapi") is not None
HAS_DEPS = HAS_PYDANTIC and HAS_HTTPX

if HAS_DEPS:
    from xfloor_mcp.request_context import (
        set_active_floor_id,
        set_app_id,
        set_auth_token,
        set_user_id,
    )
    from xfloor_mcp.tools import (
        XFloorCreateEventInput,
        XFloorGetCurrentFloorEventsInput,
        XFloorGetFloorInfoInput,
        XFloorPostEventToCurrentFloorInput,
        XFloorQueryCurrentFloorInput,
        XFloorQueryMemoryInput,
        XFloorRecentEventsInput,
        register_tools,
    )
    from xfloor_mcp.xfloor_client import XFloorClient


@pytest.mark.skipif(not HAS_DEPS, reason="requires pydantic/httpx")
class TestToolsSmoke:
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
    async def test_tools_registered_with_expected_inputs(self) -> None:
        mcp = self._FakeMCP()
        register_tools(mcp=mcp, client=SimpleNamespace())

        assert set(mcp.registry.keys()) == {
            "xfloor_query_memory",
            "xfloor_create_event",
            "xfloor_recent_events",
            "xfloor_get_floor_info",
            "xfloor_wait_for_ingestion",
            "xfloor_query_current_floor",
            "xfloor_get_current_floor_events",
            "xfloor_post_event_to_current_floor",
        }

        assert get_type_hints(mcp.registry["xfloor_query_memory"])["input"] is XFloorQueryMemoryInput
        assert get_type_hints(mcp.registry["xfloor_create_event"])["input"] is XFloorCreateEventInput
        assert get_type_hints(mcp.registry["xfloor_recent_events"])["input"] is XFloorRecentEventsInput
        assert get_type_hints(mcp.registry["xfloor_get_floor_info"])["input"] is XFloorGetFloorInfoInput
        assert get_type_hints(mcp.registry["xfloor_query_current_floor"])["input"] is XFloorQueryCurrentFloorInput
        assert get_type_hints(mcp.registry["xfloor_get_current_floor_events"])["input"] is XFloorGetCurrentFloorEventsInput
        assert get_type_hints(mcp.registry["xfloor_post_event_to_current_floor"])["input"] is XFloorPostEventToCurrentFloorInput

    @pytest.mark.asyncio
    async def test_client_calls_httpx_with_auth_and_context_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
                return self_outer._MockResponse({"ok": True, "events": [{"title": "hello"}]})

        self_outer = self
        monkeypatch.setattr("xfloor_mcp.xfloor_client.httpx.AsyncClient", _FakeAsyncClient)

        set_auth_token("token-ctx")
        set_user_id("user-ctx")
        set_app_id("app-ctx")

        client = XFloorClient(base_url="https://appfloor.in")
        await client.query_memory(
            None,
            user_id="u1",
            query="find",
            floor_ids=["f1"],
            include_metadata="1",
            summary_needed="0",
        )
        await client.recent_events(None, params={"floor_id": "f1", "limit": 10})
        await client.get_floor_info(None, floor_id="f1")

        assert captured[0]["url"].endswith("/agent/memory/query")
        assert captured[0]["headers"]["Authorization"] == "Bearer token-ctx"
        assert captured[0]["params"]["user_id"] == "user-ctx"
        assert captured[0]["params"]["app_id"] == "app-ctx"

        assert captured[1]["method"] == "GET"
        assert captured[1]["params"]["floor_id"] == "f1"
        assert captured[1]["params"]["user_id"] == "user-ctx"

        assert captured[2]["url"].endswith("/api/memory/floor/info/f1")

    @pytest.mark.asyncio
    async def test_create_event_multipart_and_validation(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
                return self_outer._MockResponse({"ok": True})

        self_outer = self
        monkeypatch.setattr("xfloor_mcp.xfloor_client.httpx.AsyncClient", _FakeAsyncClient)

        set_auth_token("token")
        set_user_id("user-ctx")
        set_app_id("app-ctx")

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
            None,
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
        multipart_fields = {name: payload for name, payload in captured[0]["files"]}
        assert multipart_fields["input_info"][1] == valid_info
        assert multipart_fields["user_id"][1] == "user-ctx"
        assert multipart_fields["app_id"][1] == "app-ctx"
        assert "user_id" not in captured[0]["params"]
        assert "app_id" not in captured[0]["params"]

        with pytest.raises(ValueError, match="missing required field"):
            client.validate_input_info('{"floor_id":"f1"}')

    @pytest.mark.asyncio
    async def test_create_event_includes_user_and_app_in_form_data(self, monkeypatch: pytest.MonkeyPatch) -> None:
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
                return self_outer._MockResponse({"ok": True})

        self_outer = self
        monkeypatch.setattr("xfloor_mcp.xfloor_client.httpx.AsyncClient", _FakeAsyncClient)

        set_auth_token("token")
        set_user_id("user-ctx")
        set_app_id("app-ctx")

        client = XFloorClient(base_url="https://appfloor.in")
        result = await client.create_event(None, input_info='{"floor_id":"f1","block_id":"b1","user_id":"u1","title":"t","description":"d"}')

        assert result["ok"] is True
        assert captured[0]["method"] == "POST"
        assert captured[0]["url"].endswith("/api/memory/events")
        assert captured[0]["files"] is not None
        form_parts = {(name, payload[0]): payload for name, payload in captured[0]["files"] if name in {"input_info", "user_id", "app_id"}}
        assert form_parts[("input_info", None)][1]
        assert form_parts[("user_id", None)][1] == "user-ctx"
        assert form_parts[("app_id", None)][1] == "app-ctx"
        assert "user_id" not in captured[0]["params"]
        assert "app_id" not in captured[0]["params"]

    @pytest.mark.asyncio
    async def test_tool_uses_auth_header_and_wait_for_ingestion(self) -> None:
        mcp = self._FakeMCP()

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

    @pytest.mark.asyncio
    async def test_current_floor_tools_use_active_floor_context(self) -> None:
        mcp = self._FakeMCP()
        set_auth_token("ctx-token")
        set_user_id("ctx-user")
        set_app_id("ctx-app")
        set_active_floor_id("floor-active")

        class _FakeClient:
            async def query_memory(self, token: str, **kwargs: Any) -> dict[str, Any]:
                assert token == "ctx-token"
                assert kwargs["user_id"] == "ctx-user"
                assert kwargs["floor_ids"] == ["floor-active"]
                return {"answers": ["ok"]}

            async def recent_events(self, token: str, *, params: dict[str, Any]) -> dict[str, Any]:
                assert token == "ctx-token"
                assert params["floor_id"] == "floor-active"
                return {"events": [{"title": "Demo"}]}

            async def create_event(self, token: str, **kwargs: Any) -> dict[str, Any]:
                payload = json.loads(kwargs["input_info"])
                assert token == "ctx-token"
                assert payload["floor_id"] == "floor-active"
                assert payload["user_id"] == "ctx-user"
                assert payload["title"] == "Town Hall"
                return {"ok": True}

        register_tools(mcp=mcp, client=_FakeClient())

        query_result = await mcp.registry["xfloor_query_current_floor"](
            XFloorQueryCurrentFloorInput(query="What is happening?"),
            None,
        )
        events_result = await mcp.registry["xfloor_get_current_floor_events"](
            XFloorGetCurrentFloorEventsInput(limit=5),
            None,
        )
        post_result = await mcp.registry["xfloor_post_event_to_current_floor"](
            XFloorPostEventToCurrentFloorInput(title="Town Hall", description="Bring questions"),
            None,
        )

        assert query_result["floor_id"] == "floor-active"
        assert events_result["count"] == 1
        assert post_result["posted"] is True

    @pytest.mark.asyncio
    async def test_current_floor_tools_fail_clearly_without_active_floor(self) -> None:
        mcp = self._FakeMCP()
        set_auth_token("ctx-token")
        set_user_id("ctx-user")
        set_app_id("ctx-app")
        set_active_floor_id(None)

        class _FakeClient:
            async def query_memory(self, token: str, **kwargs: Any) -> dict[str, Any]:
                return {}

        register_tools(mcp=mcp, client=_FakeClient())

        with pytest.raises(ValueError, match="No active xFloor is set"):
            await mcp.registry["xfloor_query_current_floor"](
                XFloorQueryCurrentFloorInput(query="What is happening?"),
                None,
            )


@pytest.mark.skipif(not (HAS_DEPS and HAS_FASTAPI), reason="requires fastapi + runtime deps")
def test_http_middleware_requires_headers_with_clear_error() -> None:
    from fastapi.testclient import TestClient

    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_DEFAULT_USER_ID=None,
            XFLOOR_DEFAULT_APP_ID=None,
        )
    )

    client = TestClient(app)
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "Missing required xFloor headers"
    assert "X-XFloor-User-Id" in payload["missing"]
    assert "X-XFloor-App-Id" in payload["missing"]


@pytest.mark.skipif(not (HAS_DEPS and HAS_FASTAPI), reason="requires fastapi + runtime deps")
def test_http_middleware_accepts_optional_active_floor_header() -> None:
    from fastapi.testclient import TestClient

    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_DEFAULT_USER_ID="fallback-user",
            XFLOOR_DEFAULT_APP_ID="fallback-app",
        )
    )

    client = TestClient(app)
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={
            "Authorization": "Bearer token",
            "X-XFloor-Active-Floor-Id": "floor-active",
        },
    )
    assert response.status_code != 400
