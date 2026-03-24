"""OAuth-ready request identity helpers for xFloor MCP.

This module intentionally contains only a small, additive dev/stub auth layer.
It is designed so real JWKS/Auth0 verification can replace the stub verifier
later without forcing unrelated request/tool changes.
"""

from .oauth import (
    OAuthResolutionError,
    RequestIdentity,
    VerifiedIdentity,
    clear_identity_cache,
    resolve_request_identity,
    verify_access_token,
    verify_oauth_user,
)

__all__ = [
    "OAuthResolutionError",
    "RequestIdentity",
    "VerifiedIdentity",
    "clear_identity_cache",
    "resolve_request_identity",
    "verify_access_token",
    "verify_oauth_user",
]
