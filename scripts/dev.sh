#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export APP_HOST="${APP_HOST:-0.0.0.0}"
export APP_PORT="${APP_PORT:-8000}"
export APP_LOG_LEVEL="${APP_LOG_LEVEL:-info}"
export APP_RELOAD="${APP_RELOAD:-true}"
export APP_RELOAD_DELAY="${APP_RELOAD_DELAY:-1.0}"

cmd=(
  uvicorn xfloor_mcp.server_http:app
  --host "$APP_HOST"
  --port "$APP_PORT"
  --log-level "$APP_LOG_LEVEL"
)

if [[ "$APP_RELOAD" == "true" ]]; then
  cmd+=(--reload --reload-delay "$APP_RELOAD_DELAY")
fi

exec "${cmd[@]}"
