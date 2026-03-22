"""Context-local request metadata for xFloor calls."""

from __future__ import annotations

from contextvars import ContextVar

_auth_token_var: ContextVar[str | None] = ContextVar("xfloor_auth_token", default=None)
_user_id_var: ContextVar[str | None] = ContextVar("xfloor_user_id", default=None)
_app_id_var: ContextVar[str | None] = ContextVar("xfloor_app_id", default=None)
_active_floor_id_var: ContextVar[str | None] = ContextVar("xfloor_active_floor_id", default=None)
_session_key_var: ContextVar[str | None] = ContextVar("xfloor_session_key", default=None)


def set_auth_token(token: str | None) -> None:
    _auth_token_var.set(token)


def get_auth_token() -> str | None:
    return _auth_token_var.get()


def set_user_id(user_id: str | None) -> None:
    _user_id_var.set(user_id)


def get_user_id() -> str | None:
    return _user_id_var.get()


def set_app_id(app_id: str | None) -> None:
    _app_id_var.set(app_id)


def get_app_id() -> str | None:
    return _app_id_var.get()


def set_active_floor_id(floor_id: str | None) -> None:
    _active_floor_id_var.set(floor_id)


def get_active_floor_id() -> str | None:
    return _active_floor_id_var.get()


def set_session_key(session_key: str | None) -> None:
    _session_key_var.set(session_key)


def get_session_key() -> str | None:
    return _session_key_var.get()
