#!/usr/bin/env bash
set -euo pipefail

: "${APP_HOST:=0.0.0.0}"
: "${APP_PORT:=8000}"
: "${APP_LOG_LEVEL:=info}"

exec uvicorn xfloor_mcp.main:create_app \
  --factory \
  --host "$APP_HOST" \
  --port "$APP_PORT" \
  --log-level "$APP_LOG_LEVEL"
