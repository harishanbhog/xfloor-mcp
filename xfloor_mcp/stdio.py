"""Module entrypoint so `python -m xfloor_mcp.stdio` works."""

from __future__ import annotations

import asyncio

from .server_stdio import run_stdio
from .settings import get_settings


def main() -> None:
    asyncio.run(run_stdio(get_settings()))


if __name__ == "__main__":
    main()
