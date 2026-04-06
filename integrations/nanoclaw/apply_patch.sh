#!/usr/bin/env bash
set -euo pipefail

# Example helper to print a ready-to-apply TypeScript patch block.
# Usage:
#   ./integrations/nanoclaw/apply_patch.sh

cat <<'PATCH'
// --- xfloor MCP patch start ---
config.mcpServers = {
  ...(config.mcpServers ?? {}),
  xfloor: {
    command: "python",
    args: ["-m", "xfloor_mcp.server_stdio"],
    // Alternative:
    // command: "uvx",
    // args: ["xfloor-mcp"],
    env: {
      ...(config.mcpServers?.xfloor?.env ?? {}),
      XFLOOR_BASE_URL: process.env.XFLOOR_BASE_URL ?? "https://appfloor.in",
      XFLOOR_TIMEOUT_SECONDS: process.env.XFLOOR_TIMEOUT_SECONDS ?? "30",
      XFLOOR_DEFAULT_USER_ID: process.env.XFLOOR_DEFAULT_USER_ID ?? "nanoclaw-user",
      XFLOOR_DEFAULT_APP_ID: process.env.XFLOOR_DEFAULT_APP_ID ?? "nanoclaw-app",
    },
  },
};

config.allowedTools = [
  ...(config.allowedTools ?? []),
  "mcp__xfloor__*",
];
// --- xfloor MCP patch end ---
PATCH
