"""Small request identity resolver for xFloor MCP.

Important:
- `oauth` mode uses real Auth0 issuer metadata / JWKS validation.
- `auto` preserves the existing dev/noauth behavior and only uses the
  explicit stub verifier path when it is already enabled.
- The intent is to centralize request-resolution flow so future production
  auth changes remain isolated from tools and transport wiring.
"""

from __future__ import annotations

import base64
import importlib
import importlib.util
import json
import logging
import time
from functools import lru_cache
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urljoin
from urllib.request import urlopen

from ..settings import Settings

logger = logging.getLogger(__name__)


class OAuthResolutionError(ValueError):
    """Raised when request identity resolution fails."""

    def __init__(self, message: str, *, status_code: int = 400, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.missing = missing or []


@dataclass(frozen=True)
class VerifiedIdentity:
    """Verified external identity extracted from an access token."""

    issuer: str
    subject: str
    claims: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RequestIdentity:
    """Resolved request identity used by the MCP server middleware."""

    auth_mode: str
    auth_token: str
    service_token: str
    user_id: str
    app_id: str
    active_floor_id: str | None
    session_key: str | None
    verified_identity: VerifiedIdentity | None = None


@dataclass(frozen=True)
class _IdentityCacheEntry:
    user_id: str
    cached_at: float


_IDENTITY_CACHE: dict[tuple[str, str], _IdentityCacheEntry] = {}


def clear_identity_cache() -> None:
    """Reset the in-memory iss+sub -> user_id cache (test helper)."""

    _IDENTITY_CACHE.clear()


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    value = authorization.strip()
    if not value.lower().startswith("bearer "):
        return None
    token = value[7:].strip()
    return token or None


def _decode_unverified_jwt_claims(token: str) -> dict[str, Any]:
    """Decode JWT payload without verification for explicit stub mode only."""

    parts = token.split(".")
    if len(parts) != 3:
        return {}

    payload = parts[1]
    padding = "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{payload}{padding}".encode("utf-8"))
        parsed = json.loads(decoded.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}

    return parsed if isinstance(parsed, dict) else {}


def _import_jwt_dependencies() -> tuple[Any, Any]:
    if importlib.util.find_spec("jwt") is None:
        raise OAuthResolutionError(
            "OAuth mode requires PyJWT with JWK support. Install server dependencies for Auth0 verification.",
            status_code=500,
        )
    jwt_module = importlib.import_module("jwt")
    pyjwk_client_cls = getattr(jwt_module, "PyJWKClient", None)
    if pyjwk_client_cls is None:
        raise OAuthResolutionError(
            "OAuth mode requires PyJWT with JWK support. Install server dependencies for Auth0 verification.",
            status_code=500,
        )
    jwt = jwt_module
    PyJWKClient = pyjwk_client_cls
    return jwt, PyJWKClient


def _normalize_issuer(settings: Settings) -> str:
    issuer = (settings.xfloor_auth0_issuer or "").strip()
    if issuer:
        return issuer if issuer.endswith("/") else f"{issuer}/"

    domain = (settings.xfloor_auth0_domain or "").strip()
    if not domain:
        raise OAuthResolutionError(
            "OAuth mode requires XFLOOR_AUTH0_ISSUER or XFLOOR_AUTH0_DOMAIN to be configured.",
            status_code=500,
        )
    domain = domain.removeprefix("https://").removeprefix("http://").strip("/")
    return f"https://{domain}/"


@lru_cache(maxsize=8)
def _fetch_openid_configuration(issuer: str) -> dict[str, Any]:
    metadata_url = urljoin(issuer, ".well-known/openid-configuration")
    try:
        with urlopen(metadata_url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - normalize network/JSON fetch failures
        raise OAuthResolutionError(f"Failed to fetch OAuth issuer metadata: {exc}", status_code=502) from exc
    if not isinstance(payload, dict):
        raise OAuthResolutionError("Auth0 OIDC metadata response must be a JSON object.", status_code=502)
    return payload


@lru_cache(maxsize=8)
def _build_jwks_client(jwks_uri: str) -> Any:
    _, pyjwk_client_cls = _import_jwt_dependencies()
    return pyjwk_client_cls(jwks_uri)


def _verify_auth0_access_token(token: str, settings: Settings) -> dict[str, Any]:
    jwt, _ = _import_jwt_dependencies()
    issuer = _normalize_issuer(settings)
    audience = (settings.xfloor_auth0_audience or "").strip()
    if not audience:
        raise OAuthResolutionError("OAuth mode requires XFLOOR_AUTH0_AUDIENCE to be configured.", status_code=500)

    metadata = _fetch_openid_configuration(issuer)
    jwks_uri = str(metadata.get("jwks_uri") or "").strip()
    if not jwks_uri:
        raise OAuthResolutionError("OIDC metadata did not contain jwks_uri.", status_code=502)

    try:
        logger.info("Attempting inbound Auth0 bearer token verification.")
        signing_key = _build_jwks_client(jwks_uri).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iss", "sub"]},
        )
    except Exception as exc:  # noqa: BLE001 - normalize third-party JWT errors
        logger.warning("Inbound Auth0 bearer token verification failed: %s", exc)
        raise OAuthResolutionError(f"Invalid bearer token: {exc}", status_code=401) from exc

    if not isinstance(claims, dict):
        raise OAuthResolutionError("Validated bearer token claims were not a JSON object.", status_code=401)
    return claims


def protected_resource_metadata(settings: Settings) -> dict[str, Any]:
    issuer = _normalize_issuer(settings)
    resource = (settings.xfloor_oauth_resource or "").strip()
    if not resource:
        raise OAuthResolutionError("OAuth mode requires XFLOOR_OAUTH_RESOURCE to be configured.", status_code=500)

    return {
        "resource": resource,
        "authorization_servers": [issuer],
        "scopes_supported": ["openid", "profile", "email", "offline_access"],
        "resource_documentation": resource,
    }


def build_www_authenticate_header(settings: Settings, resource_metadata_url: str, error: str | None = None) -> str:
    parts = [f'Bearer realm="xfloor-mcp"', f'resource_metadata="{resource_metadata_url}"']
    if error:
        parts.append(f'error="{error}"')
    return ", ".join(parts)


def is_public_discovery_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    return normalized in {
        "/.well-known/oauth-protected-resource",
        "/.well-known/openid-configuration",
        "/.well-known/oauth-authorization-server",
        "/mcp/.well-known/openid-configuration",
        "/mcp/.well-known/oauth-authorization-server",
        "/mcp/.well-known/oauth-protected-resource",
    }


def oauth_authorization_server_metadata(settings: Settings) -> dict[str, Any]:
    issuer = _normalize_issuer(settings)
    authorization_endpoint = urljoin(issuer, "authorize")
    token_endpoint = urljoin(issuer, "oauth/token")
    registration_endpoint = urljoin(issuer, "oidc/register")
    return {
        "issuer": issuer,
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "jwks_uri": urljoin(issuer, ".well-known/jwks.json"),
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic", "none"],
        "registration_endpoint": registration_endpoint,
    }


def verify_access_token(token: str, settings: Settings, *, use_stub: bool = False) -> VerifiedIdentity:
    """Verify access tokens for either real oauth mode or explicit stub mode."""

    if use_stub:
        if not settings.xfloor_oauth_stub_enabled:
            raise OAuthResolutionError(
                "OAuth stub verification is disabled. Set XFLOOR_OAUTH_STUB_ENABLED=true to use OAuth stub mode.",
                status_code=401,
            )

        claims = _decode_unverified_jwt_claims(token)
        issuer = str(claims.get("iss") or settings.xfloor_oauth_stub_iss or "").strip()
        subject = str(claims.get("sub") or settings.xfloor_oauth_stub_sub or "").strip()

        if not issuer or not subject:
            raise OAuthResolutionError(
                "Unable to resolve OAuth identity from bearer token. Provide JWT iss/sub claims or set "
                "XFLOOR_OAUTH_STUB_ISS and XFLOOR_OAUTH_STUB_SUB.",
                status_code=401,
            )

        logger.info("Using OAuth stub verifier for issuer=%s subject=%s", issuer, subject)
        return VerifiedIdentity(issuer=issuer, subject=subject, claims=claims)

    claims = _verify_auth0_access_token(token, settings)
    issuer = str(claims.get("iss") or "").strip()
    subject = str(claims.get("sub") or "").strip()
    if not issuer or not subject:
        raise OAuthResolutionError("Validated bearer token did not contain both iss and sub claims.", status_code=401)

    logger.info("Validated OAuth access token for issuer=%s subject=%s", issuer, subject)
    return VerifiedIdentity(issuer=issuer, subject=subject, claims=claims)


def verify_oauth_user(issuer: str, subject: str, settings: Settings, claims: Mapping[str, Any] | None = None) -> str:
    """Stub xFloor user resolver for verified OAuth identities.

    This currently returns a predefined user ID and is intentionally isolated so
    a later real backend/user-linking lookup can replace it.
    """

    resolved_user_id = settings.xfloor_oauth_stub_user_id.strip()
    logger.info("Using OAuth user stub for issuer=%s subject=%s -> user_id=%s", issuer, subject, resolved_user_id)
    return resolved_user_id


def _resolve_cached_user_id(verified_identity: VerifiedIdentity, settings: Settings) -> str:
    cache_key = (verified_identity.issuer, verified_identity.subject)
    cached = _IDENTITY_CACHE.get(cache_key)

    if cached:
        logger.info("OAuth identity cache hit for issuer=%s subject=%s", verified_identity.issuer, verified_identity.subject)
        return cached.user_id

    logger.info("OAuth identity cache miss for issuer=%s subject=%s", verified_identity.issuer, verified_identity.subject)
    user_id = verify_oauth_user(
        verified_identity.issuer,
        verified_identity.subject,
        settings,
        claims=verified_identity.claims,
    )
    _IDENTITY_CACHE[cache_key] = _IdentityCacheEntry(user_id=user_id, cached_at=time.time())
    return user_id


def _build_session_key(headers: Mapping[str, str], user_id: str, app_id: str) -> str:
    return (
        headers.get("Mcp-Session-Id")
        or headers.get("X-Mcp-Session-Id")
        or f"{user_id}:{app_id}"
    )


def _resolve_noauth_identity(headers: Mapping[str, str], settings: Settings) -> RequestIdentity:
    token = _extract_bearer(headers.get("Authorization")) or settings.xfloor_default_auth_token
    user_id = headers.get("X-XFloor-User-Id") or settings.xfloor_default_user_id
    app_id = headers.get("X-XFloor-App-Id") or settings.xfloor_default_app_id
    active_floor_id = headers.get("X-XFloor-Active-Floor-Id")

    missing: list[str] = []
    if not token:
        missing.append("Authorization: Bearer <token>")
    if not user_id:
        missing.append("X-XFloor-User-Id")
    if not app_id:
        missing.append("X-XFloor-App-Id")

    if missing:
        raise OAuthResolutionError(
            "Missing required xFloor headers",
            status_code=400,
            missing=missing,
        )

    return RequestIdentity(
        auth_mode="noauth",
        auth_token=token,
        service_token=token,
        user_id=user_id,
        app_id=app_id,
        active_floor_id=active_floor_id,
        session_key=_build_session_key(headers, user_id, app_id),
    )


def _resolve_oauth_identity(headers: Mapping[str, str], settings: Settings) -> RequestIdentity:
    token = _extract_bearer(headers.get("Authorization")) or settings.xfloor_default_auth_token
    if not token:
        raise OAuthResolutionError(
            "Missing bearer token. Provide Authorization: Bearer <token>.",
            status_code=401,
        )

    app_id = headers.get("X-XFloor-App-Id") or settings.xfloor_default_app_id
    if not app_id:
        raise OAuthResolutionError(
            "Missing xFloor app context. Provide X-XFloor-App-Id or configure XFLOOR_DEFAULT_APP_ID.",
            status_code=400,
        )

    active_floor_id = headers.get("X-XFloor-Active-Floor-Id")
    service_token = (settings.xfloor_default_auth_token or "").strip()
    if not service_token:
        raise OAuthResolutionError(
            "OAuth mode requires XFLOOR_DEFAULT_AUTH_TOKEN or XFLOOR_DEFAULT_BEARER_TOKEN for downstream xFloor API calls.",
            status_code=500,
        )
    verified_identity = verify_access_token(token, settings, use_stub=False)
    logger.info("Validated inbound Auth0 token; using xFloor service token for downstream API calls.")
    user_id = _resolve_cached_user_id(verified_identity, settings)

    logger.info(
        "Resolved OAuth request identity issuer=%s subject=%s auth_mode=%s",
        verified_identity.issuer,
        verified_identity.subject,
        settings.xfloor_auth_mode,
    )
    return RequestIdentity(
        auth_mode="oauth",
        auth_token=token,
        service_token=service_token,
        user_id=user_id,
        app_id=app_id,
        active_floor_id=active_floor_id,
        session_key=_build_session_key(headers, user_id, app_id),
        verified_identity=verified_identity,
    )


def resolve_request_identity(headers: Mapping[str, str], settings: Settings) -> RequestIdentity:
    """Resolve request identity according to configured auth mode.

    Modes:
    - noauth: preserve existing header/env fallback behavior.
    - oauth: require bearer token and resolve user_id from verified iss+sub.
    - auto: if bearer header is present and OAuth stub mode is enabled, try oauth
      first; otherwise fall back to noauth behavior.
    """

    mode = settings.xfloor_auth_mode
    logger.info("Resolving request identity with auth_mode=%s", mode)

    if mode == "noauth":
        return _resolve_noauth_identity(headers, settings)

    if mode == "oauth":
        return _resolve_oauth_identity(headers, settings)

    header_bearer = _extract_bearer(headers.get("Authorization"))
    if header_bearer and settings.xfloor_oauth_stub_enabled:
        token = header_bearer or settings.xfloor_default_auth_token
        if not token:
            raise OAuthResolutionError("Missing bearer token. Provide Authorization: Bearer <token>.", status_code=401)

        app_id = headers.get("X-XFloor-App-Id") or settings.xfloor_default_app_id
        if not app_id:
            raise OAuthResolutionError(
                "Missing xFloor app context. Provide X-XFloor-App-Id or configure XFLOOR_DEFAULT_APP_ID.",
                status_code=400,
            )

        active_floor_id = headers.get("X-XFloor-Active-Floor-Id")
        verified_identity = verify_access_token(token, settings, use_stub=True)
        user_id = _resolve_cached_user_id(verified_identity, settings)
        return RequestIdentity(
            auth_mode="oauth",
            auth_token=token,
            service_token=token,
            user_id=user_id,
            app_id=app_id,
            active_floor_id=active_floor_id,
            session_key=_build_session_key(headers, user_id, app_id),
            verified_identity=verified_identity,
        )

    return _resolve_noauth_identity(headers, settings)
