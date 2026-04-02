"""HTTP process entrypoint."""

from __future__ import annotations

import uvicorn

from .server_http import create_http_app
from .settings import get_settings


def create_app():
    """Return configured FastAPI application for ASGI servers."""

    return create_http_app(get_settings())


def cli() -> None:
    """Run uvicorn HTTP server."""

    settings = get_settings()
    uvicorn.run(
        "xfloor_mcp.main:create_app",
        factory=True,
        host=settings.app_host,
        port=settings.app_port,
        log_level=settings.app_log_level,
    )


if __name__ == "__main__":
    cli()
