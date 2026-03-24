"""Small OAuth-ready request identity resolver for xFloor MCP.

Important:
- This is a dev/stub verifier only.
- It does NOT perform real signature/JWKS/Auth0 validation yet.
- The intent is to centralize the request-resolution flow so a future
  production verifier can be swapped in with minimal changes elsewhere.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Mapping

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


def verify_access_token(token: str, settings: Settings) -> VerifiedIdentity:
    """Dev/stub OAuth verifier.

    This intentionally does not verify signatures. It only exists to exercise
    the request-resolution plumbing until a real OAuth/JWKS verifier is wired in.
    """

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


def verify_oauth_user(issuer: str, subject: str, settings: Settings, claims: Mapping[str, Any] | None = None) -> str:
    """Stub xFloor user resolver for verified OAuth identities.

    This currently returns a predefined user ID and is intentionally isolated so
    a later real backend/user-linking lookup can replace it.
    """

    resolved_user_id = settings.xfloor_oauth_stub_user_id.strip()
    logger.info("Using OAuth user stub for issuer=%s subject=%s -> user_id=%s", issuer, subject, resolved_user_id)
    return resolved_user_id


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
    verified_identity = verify_access_token(token, settings)
    cache_key = (verified_identity.issuer, verified_identity.subject)
    cached = _IDENTITY_CACHE.get(cache_key)

    if cached:
        logger.info(
            "OAuth identity cache hit for issuer=%s subject=%s",
            verified_identity.issuer,
            verified_identity.subject,
        )
        user_id = cached.user_id
    else:
        logger.info(
            "OAuth identity cache miss for issuer=%s subject=%s",
            verified_identity.issuer,
            verified_identity.subject,
        )
        user_id = verify_oauth_user(
            verified_identity.issuer,
            verified_identity.subject,
            settings,
            claims=verified_identity.claims,
        )
        _IDENTITY_CACHE[cache_key] = _IdentityCacheEntry(user_id=user_id, cached_at=time.time())

    logger.info(
        "Resolved OAuth request identity issuer=%s subject=%s auth_mode=%s",
        verified_identity.issuer,
        verified_identity.subject,
        settings.xfloor_auth_mode,
    )
    return RequestIdentity(
        auth_mode="oauth",
        auth_token=token,
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
        return _resolve_oauth_identity(headers, settings)

    return _resolve_noauth_identity(headers, settings)
