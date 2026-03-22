from __future__ import annotations

import importlib.util
import json
from types import SimpleNamespace
from typing import Any, Callable, get_type_hints

import pytest

from xfloor_mcp.active_floor_state import clear_all_active_floor_state, normalize_floor_ref, resolve_floor_reference
from xfloor_mcp.request_context import set_session_key

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
        XFloorSetActiveFloorInput,
        register_tools,
    )
    from xfloor_mcp.xfloor_client import XFloorClient


def test_floor_alias_normalization_works_for_plain_and_at_prefixed_refs() -> None:
    assert normalize_floor_ref("phari") == "phari"
    assert normalize_floor_ref("@phari") == "phari"
    assert resolve_floor_reference(floor_ref="@croma")["floor_id"] == "croma"


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

    def setup_method(self) -> None:
        clear_all_active_floor_state()
        set_session_key("test-session")
        set_active_floor_id(None)

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
            "xfloor_set_active_floor",
            "xfloor_query_current_floor",
            "xfloor_get_current_floor_events",
            "xfloor_post_event_to_current_floor",
        }

        assert get_type_hints(mcp.registry["xfloor_query_memory"])["input"] is XFloorQueryMemoryInput
        assert get_type_hints(mcp.registry["xfloor_create_event"])["input"] is XFloorCreateEventInput
        assert get_type_hints(mcp.registry["xfloor_recent_events"])["input"] is XFloorRecentEventsInput
        assert get_type_hints(mcp.registry["xfloor_get_floor_info"])["input"] is XFloorGetFloorInfoInput
        assert get_type_hints(mcp.registry["xfloor_set_active_floor"])["input"] is XFloorSetActiveFloorInput
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
        assert captured[1]["params"]["floor_id"] == "f1"
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
    async def test_set_active_floor_stores_state_and_current_floor_tools_use_it(self) -> None:
        mcp = self._FakeMCP()
        set_auth_token("ctx-token")
        set_user_id("ctx-user")
        set_app_id("ctx-app")
        set_active_floor_id(None)

        class _FakeClient:
            async def query_memory(self, token: str, **kwargs: Any) -> dict[str, Any]:
                assert kwargs["floor_ids"] == ["phari"]
                return {"answers": ["ok"]}

            async def recent_events(self, token: str, *, params: dict[str, Any]) -> dict[str, Any]:
                assert params["floor_id"] == "phari"
                return {"events": [{"title": "Demo"}]}

            async def create_event(self, token: str, **kwargs: Any) -> dict[str, Any]:
                payload = json.loads(kwargs["input_info"])
                assert payload["floor_id"] == "phari"
                assert payload["user_id"] == "ctx-user"
                return {"ok": True}

        register_tools(mcp=mcp, client=_FakeClient())

        set_result = await mcp.registry["xfloor_set_active_floor"](
            XFloorSetActiveFloorInput(floor_ref="@phari"),
            None,
        )
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

        assert set_result["message"] == "Active floor set to phari"
        assert query_result["floor_source"] == "session_state"
        assert events_result["count"] == 1
        assert post_result["posted"] is True

    @pytest.mark.asyncio
    async def test_stored_floor_takes_precedence_over_stale_header(self) -> None:
        mcp = self._FakeMCP()
        set_auth_token("ctx-token")
        set_user_id("ctx-user")
        set_app_id("ctx-app")
        set_active_floor_id(None)

        class _FakeClient:
            async def query_memory(self, token: str, **kwargs: Any) -> dict[str, Any]:
                assert kwargs["floor_ids"] == ["stored-floor"]
                return {"answers": ["ok"]}

        register_tools(mcp=mcp, client=_FakeClient())
        await mcp.registry["xfloor_set_active_floor"](XFloorSetActiveFloorInput(floor_ref="@stored-floor"), None)

        set_active_floor_id("header-floor")

        class _HeaderClient:
            async def query_memory(self, token: str, **kwargs: Any) -> dict[str, Any]:
                assert kwargs["floor_ids"] == ["stored-floor"]
                return {"answers": ["stored"]}

        mcp_override = self._FakeMCP()
        register_tools(mcp_override, _HeaderClient())
        result = await mcp_override.registry["xfloor_query_current_floor"](
            XFloorQueryCurrentFloorInput(query="What is happening?"),
            None,
        )
        assert result["floor_source"] == "session_state"


    @pytest.mark.asyncio
    async def test_header_override_is_used_when_no_stored_floor_exists(self) -> None:
        mcp = self._FakeMCP()
        set_auth_token("ctx-token")
        set_user_id("ctx-user")
        set_app_id("ctx-app")
        clear_all_active_floor_state()
        set_active_floor_id("header-floor")

        class _HeaderClient:
            async def query_memory(self, token: str, **kwargs: Any) -> dict[str, Any]:
                assert kwargs["floor_ids"] == ["header-floor"]
                return {"answers": ["override"]}

        register_tools(mcp, _HeaderClient())
        result = await mcp.registry["xfloor_query_current_floor"](
            XFloorQueryCurrentFloorInput(query="What is happening?"),
            None,
        )
        assert result["floor_source"] == "header_override"

    @pytest.mark.asyncio
    async def test_current_floor_tools_fail_clearly_without_active_floor(self) -> None:
        mcp = self._FakeMCP()
        set_auth_token("ctx-token")
        set_user_id("ctx-user")
        set_app_id("ctx-app")
        set_active_floor_id(None)
        clear_all_active_floor_state()

        class _FakeClient:
            async def query_memory(self, token: str, **kwargs: Any) -> dict[str, Any]:
                return {}

        register_tools(mcp=mcp, client=_FakeClient())

        with pytest.raises(ValueError, match="No active floor set"):
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
def test_http_middleware_uses_env_defaults_when_headers_are_missing() -> None:
    from fastapi.testclient import TestClient

    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_DEFAULT_AUTH_TOKEN="default-token",
            XFLOOR_DEFAULT_USER_ID="fallback-user",
            XFLOOR_DEFAULT_APP_ID="fallback-app",
        )
    )

    client = TestClient(app)
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response.status_code != 400
