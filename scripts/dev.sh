#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export APP_HOST="${APP_HOST:-0.0.0.0}"
export APP_PORT="${APP_PORT:-8000}"
export APP_LOG_LEVEL="${APP_LOG_LEVEL:-info}"

exec uvicorn xfloor_mcp.server_http:app \
  --host "$APP_HOST" \
  --port "$APP_PORT" \
  --reload \
  --log-level "$APP_LOG_LEVEL"
