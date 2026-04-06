/**
 * Minimal NanoClaw patch snippet for xFloor MCP tools.
 * Merge this into your existing NanoClaw config object.
 */

export const xfloorPatch = {
  mcpServers: {
    xfloor: {
      // Option A1: local Python module
      command: "python",
      args: ["-m", "xfloor_mcp.server_stdio"],

      // Option A2 (alternative): use uvx package launcher
      // command: "uvx",
      // args: ["xfloor-mcp"],

      env: {
        XFLOOR_BASE_URL: "https://appfloor.in",
        XFLOOR_TIMEOUT_SECONDS: "30",
        XFLOOR_DEFAULT_USER_ID: "nanoclaw-user",
        XFLOOR_DEFAULT_APP_ID: "nanoclaw-app",
      },
    },

    // Option B (alternative): remote MCP URL (if supported by your NanoClaw runtime)
    // xfloor: {
    //   transport: "streamable-http",
    //   url: "https://your-domain.com/mcp",
    //   headers: {
//     Authorization: "Bearer <your-token>",
//     "X-XFloor-User-Id": "<your-user-id>",
//     "X-XFloor-App-Id": "<your-app-id>",
//   },
    // },
  },

  allowedTools: ["mcp__xfloor__*"],
};
