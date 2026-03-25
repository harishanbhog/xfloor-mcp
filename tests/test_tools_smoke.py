from __future__ import annotations

import importlib.util
import json
import base64
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
    from xfloor_mcp.auth import clear_identity_cache
    from xfloor_mcp.auth.oauth import VerifiedIdentity, verify_access_token
    from xfloor_mcp.request_context import (
        get_auth_mode,
        get_app_id,
        get_auth_token,
        get_oauth_issuer,
        get_oauth_subject,
        get_session_key,
        get_user_id,
        get_xfloor_service_token,
        set_auth_mode,
        set_active_floor_id,
        set_app_id,
        set_auth_token,
        set_user_id,
        set_xfloor_service_token,
    )
    from xfloor_mcp.settings import Settings
    from xfloor_mcp.tools import (
        XFloorCreateEventInput,
        XFloorFileInput,
        XFloorGetFloorInfoInput,
        XFloorPostEventToCurrentFloorInput,
        XFloorQueryCurrentFloorInput,
        XFloorQueryMemoryInput,
        XFloorRecentEventsInput,
        XFloorSetActiveFloorInput,
        _build_query_results_widget_html,
        normalize_query_response,
        register_tools,
    )
    from xfloor_mcp.xfloor_client import XFloorClient


def test_floor_alias_normalization_works_for_plain_and_at_prefixed_refs() -> None:
    assert normalize_floor_ref("phari") == "phari"
    assert normalize_floor_ref("@phari") == "phari"
    assert resolve_floor_reference(floor_ref="@croma")["floor_id"] == "croma"


def test_set_active_floor_input_accepts_string_and_common_alias_keys() -> None:
    if not HAS_DEPS:
        pytest.skip("requires pydantic/httpx")
    from_string = XFloorSetActiveFloorInput.model_validate("@phari")
    assert from_string.floor_ref == "@phari"
    assert from_string.floor_id is None

    from_aliases = XFloorSetActiveFloorInput.model_validate({"floor": "phari", "id": "phari-id"})
    assert from_aliases.floor_ref == "phari"
    assert from_aliases.floor_id == "phari-id"


def test_normalize_query_response_sorts_and_builds_floor_urls() -> None:
    if not HAS_DEPS:
        pytest.skip("requires pydantic/httpx")
    structured, meta = normalize_query_response(
        {
            "result": {
                "answer": "Summary",
                "items": [
                    {"text": json.dumps({"floor": "B", "from_floor_uid": "floor-b", "score": 0.3})},
                    {"text": json.dumps({"floor": "A", "from_floor_uid": "floor-a", "score": 0.9})},
                ],
            }
        },
        active_floor={"floor_id": "phari", "floor_ref": "phari"},
        original_query="What is new?",
    )
    assert structured["answer"] == "Summary"
    assert structured["resultCount"] == 2
    assert structured["bestMatch"]["floorUid"] == "floor-a"
    assert structured["relevantFloors"][0]["floorUrl"] == "floor-a.xfloor.ai"
    assert meta["malformedItemTextCount"] == 0


def test_normalize_query_response_fails_soft_on_malformed_item_text() -> None:
    if not HAS_DEPS:
        pytest.skip("requires pydantic/httpx")
    structured, meta = normalize_query_response(
        {"result": {"answer": "Summary", "items": [{"text": "{bad json"}]}},
        active_floor=None,
        original_query="q",
    )
    assert structured["answer"] == "Summary"
    assert structured["resultCount"] == 1
    assert meta["malformedItemTextCount"] == 1


def test_query_results_widget_template_has_chip_action() -> None:
    if not HAS_DEPS:
        pytest.skip("requires pydantic/httpx")
    html = _build_query_results_widget_html()
    assert "relevantFloors" in html
    assert "callTool(\"xfloor_set_active_floor\"" in html


@pytest.mark.skipif(not HAS_DEPS, reason="requires pydantic/httpx")
class TestToolsSmoke:
    class _FakeMCP:
        def __init__(self) -> None:
            self.registry: dict[str, Callable[..., Any]] = {}
            self.resources: dict[str, Callable[..., Any]] = {}

        def tool(self, name: str, description: str, **kwargs: Any):
            def decorator(func):
                self.registry[name] = func
                return func

            return decorator

        def resource(self, uri: str, **kwargs: Any):
            def decorator(func):
                self.resources[uri] = func
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
        clear_identity_cache()
        set_auth_mode(None)
        set_xfloor_service_token(None)

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
            "xfloor_post_event_to_current_floor",
        }
        assert "ui://widget/query-results-v1.html" in mcp.resources

        assert get_type_hints(mcp.registry["xfloor_query_memory"])["input"] is XFloorQueryMemoryInput
        assert get_type_hints(mcp.registry["xfloor_create_event"])["input"] is XFloorCreateEventInput
        assert get_type_hints(mcp.registry["xfloor_recent_events"])["input"] is XFloorRecentEventsInput
        assert get_type_hints(mcp.registry["xfloor_get_floor_info"])["input"] is XFloorGetFloorInfoInput
        assert get_type_hints(mcp.registry["xfloor_set_active_floor"])["input"] is XFloorSetActiveFloorInput
        assert get_type_hints(mcp.registry["xfloor_query_current_floor"])["input"] is XFloorQueryCurrentFloorInput
        assert get_type_hints(mcp.registry["xfloor_post_event_to_current_floor"])["input"] is XFloorPostEventToCurrentFloorInput
        assert "xfloor_post_event_with_attachment_to_current_floor" not in mcp.registry

    @pytest.mark.asyncio
    async def test_posting_surface_is_text_only_without_widget_or_attachment_tool(self) -> None:
        mcp = self._FakeMCP()
        register_tools(mcp=mcp, client=SimpleNamespace())
        assert "xfloor_open_post_widget" not in mcp.registry
        assert "xfloor_post_event_with_attachment_to_current_floor" not in mcp.registry

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
        set_xfloor_service_token("service-token-ctx")
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
        assert captured[0]["headers"]["Authorization"] == "Bearer service-token-ctx"
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
    async def test_create_event_accepts_file_path_handoff(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
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

        image_path = tmp_path / "demo.png"
        image_path.write_bytes(b"fake-png-content")

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
        await client.create_event(
            None,
            input_info=valid_info,
            files=[
                {
                    "file_path": str(image_path),
                    "mime_type": "image/png",
                }
            ],
        )

        multipart_fields = captured[0]["files"]
        file_entries = [entry for entry in multipart_fields if entry[0] == "files"]
        assert len(file_entries) == 1
        assert file_entries[0][1][0] == "demo.png"
        assert file_entries[0][1][2] == "image/png"

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
                return {
                    "result": {
                        "answer": "Looks good.",
                        "items": [
                            {"text": json.dumps({"floor": "Phari", "from_floor_uid": "phari", "score": 0.9})}
                        ],
                    }
                }

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
        post_result = await mcp.registry["xfloor_post_event_to_current_floor"](
            XFloorPostEventToCurrentFloorInput(title="Town Hall", description="Bring questions"),
            None,
        )

        assert set_result["message"] == "Active floor set to phari"
        assert query_result["structuredContent"]["activeFloor"]["id"] == "phari"
        assert query_result["structuredContent"]["bestMatch"]["floorUrl"] == "phari.xfloor.ai"
        assert query_result["content"][0]["type"] == "text"
        assert "Related floors you can switch to" in query_result["content"][0]["text"]
        assert query_result["_meta"]["ui_rendering_mode"] == "widget_with_text_fallback"
        assert query_result["_meta"]["widget_debug"]["query_widget_uri"] == "ui://widget/query-results-v1.html"
        assert query_result["_meta"]["widget_debug"]["relevant_floor_count"] == 1
        assert "ui" in query_result["_meta"]
        assert post_result["posted"] is True

    @pytest.mark.asyncio
    async def test_post_event_to_current_floor_uses_description_as_title_and_omits_blank_block_id(self) -> None:
        mcp = self._FakeMCP()
        set_auth_token("ctx-token")
        set_user_id("ctx-user")
        set_app_id("ctx-app")
        set_active_floor_id(None)

        class _FakeClient:
            async def create_event(self, token: str, **kwargs: Any) -> dict[str, Any]:
                payload = json.loads(kwargs["input_info"])
                assert payload["title"] == "Bring questions"
                assert "block_id" not in payload
                return {"ok": True}

        register_tools(mcp=mcp, client=_FakeClient())
        await mcp.registry["xfloor_set_active_floor"](XFloorSetActiveFloorInput(floor_ref="@phari"), None)

        result = await mcp.registry["xfloor_post_event_to_current_floor"](
            XFloorPostEventToCurrentFloorInput(title="   ", description="Bring questions", block_id=" "),
            None,
        )

        assert result["accepted"] is True
        assert result["event"]["title"] == "Bring questions"
        assert result["event"]["block_id"] is None

    @pytest.mark.asyncio
    async def test_post_event_to_current_floor_marks_queue_submission_as_success(self) -> None:
        mcp = self._FakeMCP()
        set_auth_token("ctx-token")
        set_user_id("ctx-user")
        set_app_id("ctx-app")
        set_active_floor_id(None)

        class _FakeClient:
            async def create_event(self, token: str, **kwargs: Any) -> dict[str, Any]:
                return {"message": "Submitted to queue for processing"}

        register_tools(mcp=mcp, client=_FakeClient())
        await mcp.registry["xfloor_set_active_floor"](XFloorSetActiveFloorInput(floor_ref="@phari"), None)
        result = await mcp.registry["xfloor_post_event_to_current_floor"](
            XFloorPostEventToCurrentFloorInput(title="Town Hall", description="Bring questions", block_id="chatgpt"),
            None,
        )
        assert result["status"] == "queued"
        
    @pytest.mark.asyncio
    async def test_post_event_to_current_floor_uses_service_token_in_oauth_mode(self) -> None:
        mcp = self._FakeMCP()
        set_auth_mode("oauth")
        set_auth_token("inbound-auth0-token")
        set_xfloor_service_token("xfloor-service-token")
        set_user_id("ctx-user")
        set_app_id("ctx-app")
        set_active_floor_id(None)

        class _FakeClient:
            async def create_event(self, token: str, **kwargs: Any) -> dict[str, Any]:
                assert token == "xfloor-service-token"
                return {"ok": True}

        register_tools(mcp=mcp, client=_FakeClient())
        await mcp.registry["xfloor_set_active_floor"](XFloorSetActiveFloorInput(floor_ref="@phari"), None)

        result = await mcp.registry["xfloor_post_event_to_current_floor"](
            XFloorPostEventToCurrentFloorInput(
                title="OAuth",
                description="token boundary",
            ),
            ctx=None,
        )
        assert result["posted"] is True
        assert result["accepted"] is True

    @pytest.mark.asyncio
    async def test_real_oauth_verifier_uses_auth0_metadata_and_claims(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _FakePyJWKClient:
            def __init__(self, jwks_uri: str) -> None:
                assert jwks_uri == "https://issuer.example/.well-known/jwks.json"

            def get_signing_key_from_jwt(self, token: str) -> Any:
                assert token == "auth0-token"
                return SimpleNamespace(key="public-key")

        class _FakeJWTModule:
            def decode(self, token: str, key: str, algorithms: list[str], audience: str, issuer: str, options: dict[str, Any]) -> dict[str, Any]:
                assert token == "auth0-token"
                assert key == "public-key"
                assert algorithms == ["RS256"]
                assert audience == "https://xFloorMCPTest"
                assert issuer == "https://issuer.example/"
                assert options["require"] == ["exp", "iss", "sub"]
                return {
                    "iss": "https://issuer.example/",
                    "sub": "auth0|verified-user",
                    "exp": 9999999999,
                    "scope": "openid profile",
                }

        monkeypatch.setattr(
            "xfloor_mcp.auth.oauth._import_jwt_dependencies",
            lambda: (_FakeJWTModule(), _FakePyJWKClient),
        )
        monkeypatch.setattr(
            "xfloor_mcp.auth.oauth._fetch_openid_configuration",
            lambda issuer: {"jwks_uri": "https://issuer.example/.well-known/jwks.json"},
        )

        identity = verify_access_token(
            "auth0-token",
            Settings(
                XFLOOR_AUTH_MODE="oauth",
                XFLOOR_AUTH0_ISSUER="https://issuer.example/",
                XFLOOR_AUTH0_AUDIENCE="https://xFloorMCPTest",
                XFLOOR_OAUTH_RESOURCE="https://resource.example",
            ),
            use_stub=False,
        )

        assert isinstance(identity, VerifiedIdentity)
        assert identity.issuer == "https://issuer.example/"
        assert identity.subject == "auth0|verified-user"
        assert identity.claims["scope"] == "openid profile"

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


@pytest.mark.skipif(not (HAS_DEPS and HAS_FASTAPI), reason="requires fastapi + runtime deps")
def test_http_middleware_noauth_headers_continue_to_work(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    clear_identity_cache()

    async def debug_context(_: Any) -> JSONResponse:
        return JSONResponse(
            {
                "auth_mode": get_auth_mode(),
                "auth_token": get_auth_token(),
                "user_id": get_user_id(),
                "app_id": get_app_id(),
                "session_key": get_session_key(),
                "oauth_issuer": get_oauth_issuer(),
                "oauth_subject": get_oauth_subject(),
                "service_token": get_xfloor_service_token(),
            }
        )

    debug_app = FastAPI()
    debug_app.add_api_route("/{path:path}", debug_context, methods=["GET", "POST"])
    monkeypatch.setattr("xfloor_mcp.server_http._build_mcp_app", lambda mcp: debug_app)

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_AUTH_MODE="noauth",
        )
    )
    client = TestClient(app)
    response = client.post(
        "/mcp",
        headers={
            "Authorization": "Bearer noauth-token",
            "X-XFloor-User-Id": "header-user",
            "X-XFloor-App-Id": "header-app",
            "Mcp-Session-Id": "session-1",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["auth_mode"] == "noauth"
    assert payload["auth_token"] == "noauth-token"
    assert payload["user_id"] == "header-user"
    assert payload["app_id"] == "header-app"
    assert payload["session_key"] == "session-1"
    assert payload["oauth_issuer"] is None
    assert payload["oauth_subject"] is None
    assert payload["service_token"] == "noauth-token"


def _encode_stub_jwt(claims: dict[str, Any]) -> str:
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"{header}.{payload}.signature"


@pytest.mark.skipif(not (HAS_DEPS and HAS_FASTAPI), reason="requires fastapi + runtime deps")
def test_http_middleware_oauth_mode_resolves_user_and_sets_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    clear_identity_cache()

    async def debug_context(_: Any) -> JSONResponse:
        return JSONResponse(
            {
                "auth_mode": get_auth_mode(),
                "user_id": get_user_id(),
                "app_id": get_app_id(),
                "oauth_issuer": get_oauth_issuer(),
                "oauth_subject": get_oauth_subject(),
                "session_key": get_session_key(),
                "service_token": get_xfloor_service_token(),
            }
        )

    debug_app = FastAPI()
    debug_app.add_api_route("/{path:path}", debug_context, methods=["GET", "POST"])
    monkeypatch.setattr("xfloor_mcp.server_http._build_mcp_app", lambda mcp: debug_app)
    monkeypatch.setattr(
        "xfloor_mcp.auth.oauth._verify_auth0_access_token",
        lambda token, settings: {"iss": "https://example.auth0.com/", "sub": "auth0|demo-user", "scope": "openid profile"},
    )

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_AUTH_MODE="oauth",
            XFLOOR_OAUTH_STUB_USER_ID="oauth-dev-user",
            XFLOOR_DEFAULT_AUTH_TOKEN="xfloor-service-token",
            XFLOOR_DEFAULT_APP_ID="fallback-app",
            XFLOOR_AUTH0_ISSUER="https://example.auth0.com/",
            XFLOOR_AUTH0_AUDIENCE="https://xFloorMCPTest",
            XFLOOR_OAUTH_RESOURCE="https://resource.example",
        )
    )
    client = TestClient(app)
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer auth0-token"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["auth_mode"] == "oauth"
    assert payload["user_id"] == "oauth-dev-user"
    assert payload["app_id"] == "fallback-app"
    assert payload["oauth_issuer"] == "https://example.auth0.com/"
    assert payload["oauth_subject"] == "auth0|demo-user"
    assert payload["session_key"] == "oauth-dev-user:fallback-app"
    assert payload["service_token"] == "xfloor-service-token"


@pytest.mark.skipif(not (HAS_DEPS and HAS_FASTAPI), reason="requires fastapi + runtime deps")
def test_http_middleware_oauth_mode_uses_identity_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    clear_identity_cache()
    calls: list[tuple[str, str]] = []

    async def debug_context(_: Any) -> JSONResponse:
        return JSONResponse({"user_id": get_user_id(), "oauth_subject": get_oauth_subject()})

    def fake_verify_oauth_user(issuer: str, subject: str, settings: Any, claims: Any = None) -> str:
        calls.append((issuer, subject))
        return "cached-oauth-user"

    debug_app = FastAPI()
    debug_app.add_api_route("/{path:path}", debug_context, methods=["GET", "POST"])
    monkeypatch.setattr("xfloor_mcp.server_http._build_mcp_app", lambda mcp: debug_app)
    monkeypatch.setattr("xfloor_mcp.auth.oauth.verify_oauth_user", fake_verify_oauth_user)
    monkeypatch.setattr(
        "xfloor_mcp.auth.oauth._verify_auth0_access_token",
        lambda token, settings: {"iss": "https://issuer.example/", "sub": "auth0|same-user"},
    )

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_AUTH_MODE="oauth",
            XFLOOR_DEFAULT_AUTH_TOKEN="xfloor-service-token",
            XFLOOR_DEFAULT_APP_ID="fallback-app",
            XFLOOR_AUTH0_ISSUER="https://issuer.example/",
            XFLOOR_AUTH0_AUDIENCE="https://xFloorMCPTest",
            XFLOOR_OAUTH_RESOURCE="https://resource.example",
        )
    )
    client = TestClient(app)
    token = "auth0-token"

    first = client.post("/mcp", headers={"Authorization": f"Bearer {token}"}, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    second = client.post("/mcp", headers={"Authorization": f"Bearer {token}"}, json={"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["user_id"] == "cached-oauth-user"
    assert second.json()["user_id"] == "cached-oauth-user"
    assert calls == [("https://issuer.example/", "auth0|same-user")]


@pytest.mark.skipif(not (HAS_DEPS and HAS_FASTAPI), reason="requires fastapi + runtime deps")
def test_http_middleware_auto_mode_prefers_oauth_when_bearer_header_is_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    clear_identity_cache()

    async def debug_context(_: Any) -> JSONResponse:
        return JSONResponse({"auth_mode": get_auth_mode(), "user_id": get_user_id()})

    debug_app = FastAPI()
    debug_app.add_api_route("/{path:path}", debug_context, methods=["GET", "POST"])
    monkeypatch.setattr("xfloor_mcp.server_http._build_mcp_app", lambda mcp: debug_app)

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_AUTH_MODE="auto",
            XFLOOR_OAUTH_STUB_ENABLED=True,
            XFLOOR_OAUTH_STUB_USER_ID="oauth-wins",
            XFLOOR_DEFAULT_APP_ID="fallback-app",
        )
    )
    client = TestClient(app)
    token = _encode_stub_jwt({"iss": "https://issuer.example/", "sub": "auth0|auto-user"})
    response = client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "X-XFloor-User-Id": "header-user-should-not-win",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["auth_mode"] == "oauth"
    assert payload["user_id"] == "oauth-wins"


@pytest.mark.skipif(not (HAS_DEPS and HAS_FASTAPI), reason="requires fastapi + runtime deps")
def test_http_middleware_auto_mode_falls_back_to_noauth_without_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    clear_identity_cache()

    async def debug_context(_: Any) -> JSONResponse:
        return JSONResponse({"auth_mode": get_auth_mode(), "user_id": get_user_id(), "auth_token": get_auth_token()})

    debug_app = FastAPI()
    debug_app.add_api_route("/{path:path}", debug_context, methods=["GET", "POST"])
    monkeypatch.setattr("xfloor_mcp.server_http._build_mcp_app", lambda mcp: debug_app)

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_AUTH_MODE="auto",
            XFLOOR_OAUTH_STUB_ENABLED=True,
            XFLOOR_DEFAULT_AUTH_TOKEN="default-noauth-token",
        )
    )
    client = TestClient(app)
    response = client.post(
        "/mcp",
        headers={
            "X-XFloor-User-Id": "fallback-noauth-user",
            "X-XFloor-App-Id": "fallback-noauth-app",
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["auth_mode"] == "noauth"
    assert payload["user_id"] == "fallback-noauth-user"
    assert payload["auth_token"] == "default-noauth-token"


@pytest.mark.skipif(not (HAS_DEPS and HAS_FASTAPI), reason="requires fastapi + runtime deps")
def test_http_middleware_oauth_mode_rejects_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    clear_identity_cache()

    async def debug_context(_: Any) -> JSONResponse:
        return JSONResponse({"ok": True})

    debug_app = FastAPI()
    debug_app.add_api_route("/{path:path}", debug_context, methods=["GET", "POST"])
    monkeypatch.setattr("xfloor_mcp.server_http._build_mcp_app", lambda mcp: debug_app)

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_AUTH_MODE="oauth",
            XFLOOR_DEFAULT_APP_ID="fallback-app",
            XFLOOR_AUTH0_ISSUER="https://example.auth0.com/",
            XFLOOR_AUTH0_AUDIENCE="https://xFloorMCPTest",
            XFLOOR_OAUTH_RESOURCE="https://resource.example",
        )
    )
    client = TestClient(app)
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response.status_code == 401
    assert "Missing bearer token" in response.json()["error"]
    assert "WWW-Authenticate" in response.headers
    assert 'resource_metadata="' in response.headers["WWW-Authenticate"]


@pytest.mark.skipif(not (HAS_DEPS and HAS_FASTAPI), reason="requires fastapi + runtime deps")
def test_oauth_discovery_paths_are_public_and_skip_token_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    calls: list[str] = []

    def _should_not_be_called(token: str, settings: Any) -> dict[str, Any]:
        calls.append(token)
        raise AssertionError("token verifier should not run on discovery paths")

    monkeypatch.setattr("xfloor_mcp.auth.oauth._verify_auth0_access_token", _should_not_be_called)

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_AUTH_MODE="oauth",
            XFLOOR_DEFAULT_AUTH_TOKEN="xfloor-service-token",
            XFLOOR_AUTH0_ISSUER="https://dev-aobq6ntuhxzmcu6j.jp.auth0.com/",
            XFLOOR_AUTH0_AUDIENCE="https://xFloorMCPTest",
            XFLOOR_OAUTH_RESOURCE="https://demo.ngrok-free.app",
        )
    )
    client = TestClient(app)

    discovery_paths = [
        "/.well-known/oauth-protected-resource",
        "/.well-known/openid-configuration",
        "/.well-known/oauth-authorization-server",
        "/mcp/.well-known/openid-configuration",
        "/mcp/.well-known/oauth-authorization-server",
        "/mcp/.well-known/oauth-protected-resource",
    ]
    for path in discovery_paths:
        response = client.get(path)
        assert response.status_code == 200

    assert calls == []


@pytest.mark.skipif(not (HAS_DEPS and HAS_FASTAPI), reason="requires fastapi + runtime deps")
def test_http_middleware_oauth_mode_rejects_invalid_token_with_bearer_challenge(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    from xfloor_mcp.auth.oauth import OAuthResolutionError
    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    clear_identity_cache()

    async def debug_context(_: Any) -> JSONResponse:
        return JSONResponse({"ok": True})

    debug_app = FastAPI()
    debug_app.add_api_route("/{path:path}", debug_context, methods=["GET", "POST"])
    monkeypatch.setattr("xfloor_mcp.server_http._build_mcp_app", lambda mcp: debug_app)
    monkeypatch.setattr(
        "xfloor_mcp.auth.oauth._verify_auth0_access_token",
        lambda token, settings: (_ for _ in ()).throw(OAuthResolutionError("Invalid bearer token: signature verification failed", status_code=401)),
    )

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_AUTH_MODE="oauth",
            XFLOOR_DEFAULT_APP_ID="fallback-app",
            XFLOOR_AUTH0_ISSUER="https://example.auth0.com/",
            XFLOOR_AUTH0_AUDIENCE="https://xFloorMCPTest",
            XFLOOR_OAUTH_RESOURCE="https://resource.example",
        )
    )
    client = TestClient(app)
    response = client.post(
        "/mcp",
        headers={"Authorization": "Bearer invalid-token"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert response.status_code == 401
    assert "Invalid bearer token" in response.json()["error"]
    assert "WWW-Authenticate" in response.headers


@pytest.mark.skipif(not (HAS_DEPS and HAS_FASTAPI), reason="requires fastapi + runtime deps")
def test_oauth_protected_resource_metadata_endpoint_returns_expected_values() -> None:
    from fastapi.testclient import TestClient

    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_AUTH_MODE="oauth",
            XFLOOR_AUTH0_ISSUER="https://dev-aobq6ntuhxzmcu6j.jp.auth0.com/",
            XFLOOR_AUTH0_AUDIENCE="https://xFloorMCPTest",
            XFLOOR_OAUTH_RESOURCE="https://demo.ngrok-free.app",
        )
    )

    client = TestClient(app)
    response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
    payload = response.json()
    assert payload["resource"] == "https://xFloorMCPTest"
    assert payload["authorization_servers"] == ["https://dev-aobq6ntuhxzmcu6j.jp.auth0.com/"]

    openid_response = client.get("/mcp/.well-known/openid-configuration")
    assert openid_response.status_code == 200
    openid_payload = openid_response.json()
    assert openid_payload["issuer"] == "https://dev-aobq6ntuhxzmcu6j.jp.auth0.com/"
    oauth_as_response = client.get("/mcp/.well-known/oauth-authorization-server")
    assert oauth_as_response.status_code == 200


@pytest.mark.skipif(not (HAS_DEPS and HAS_FASTAPI), reason="requires fastapi + runtime deps")
def test_oauth_protected_resource_falls_back_to_oauth_resource_when_audience_missing() -> None:
    from fastapi.testclient import TestClient

    from xfloor_mcp.server_http import create_http_app
    from xfloor_mcp.settings import Settings

    app = create_http_app(
        Settings(
            XFLOOR_BASE_URL="https://appfloor.in",
            XFLOOR_AUTH_MODE="oauth",
            XFLOOR_AUTH0_ISSUER="https://dev-aobq6ntuhxzmcu6j.jp.auth0.com/",
            XFLOOR_AUTH0_AUDIENCE="",
            XFLOOR_OAUTH_RESOURCE="https://demo.ngrok-free.app/mcp",
        )
    )

    client = TestClient(app)
    response = client.get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
    payload = response.json()
    assert payload["resource"] == "https://demo.ngrok-free.app/mcp"


@pytest.mark.skipif(not HAS_DEPS, reason="requires pydantic/httpx")
@pytest.mark.asyncio
async def test_current_floor_tools_continue_to_work_with_oauth_resolved_user() -> None:
    clear_identity_cache()
    mcp = TestToolsSmoke._FakeMCP()
    set_auth_token("auth0-inbound-token")
    set_xfloor_service_token("xfloor-service-token")
    set_user_id("oauth-dev-user")
    set_app_id("oauth-app")
    set_active_floor_id(None)
    set_session_key("oauth-session")

    class _FakeClient:
        async def create_event(self, token: str, **kwargs: Any) -> dict[str, Any]:
            assert token == "xfloor-service-token"
            payload = json.loads(kwargs["input_info"])
            assert payload["user_id"] == "oauth-dev-user"
            assert payload["floor_id"] == "phari"
            return {"ok": True}

        async def recent_events(self, token: str, *, params: dict[str, Any]) -> dict[str, Any]:
            assert token == "xfloor-service-token"
            assert params["floor_id"] == "phari"
            return {"events": [{"title": "OAuth Demo"}]}

        async def query_memory(self, token: str, **kwargs: Any) -> dict[str, Any]:
            assert token == "xfloor-service-token"
            assert kwargs["user_id"] == "oauth-dev-user"
            assert kwargs["floor_ids"] == ["phari"]
            return {"answers": ["ok"]}

    register_tools(mcp=mcp, client=_FakeClient())

    set_result = await mcp.registry["xfloor_set_active_floor"](XFloorSetActiveFloorInput(floor_ref="@phari"), None)
    query_result = await mcp.registry["xfloor_query_current_floor"](
        XFloorQueryCurrentFloorInput(query="What is happening?"),
        None,
    )
    post_result = await mcp.registry["xfloor_post_event_to_current_floor"](
        XFloorPostEventToCurrentFloorInput(title="OAuth Town Hall", description="Bring questions"),
        None,
    )

    assert set_result["message"] == "Active floor set to phari"
    assert query_result["floor_source"] == "session_state"
    assert post_result["posted"] is True
