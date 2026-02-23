# NanoClaw integration for xfloor-mcp

This guide helps NanoClaw users wire `xfloor-mcp` in the same style as NanoClaw's add-gmail skill pattern.

## What you will add

1. A new MCP server entry: `mcpServers.xfloor`
2. Tool allowlist rule: `mcp__xfloor__*`

---

## Option A (recommended): run xfloor-mcp as a local command-based MCP server

Add an MCP server named `xfloor` in NanoClaw config.

### Variant 1: Python module

```ts
mcpServers: {
  xfloor: {
    command: "python",
    args: ["-m", "xfloor_mcp.server_stdio"],
    env: {
      XFLOOR_BASE_URL: "https://appfloor.in",
      XFLOOR_TIMEOUT_SECONDS: "30",
    },
  },
}
```

### Variant 2: uvx package command

```ts
mcpServers: {
  xfloor: {
    command: "uvx",
    args: ["xfloor-mcp"],
    env: {
      XFLOOR_BASE_URL: "https://appfloor.in",
      XFLOOR_TIMEOUT_SECONDS: "30",
    },
  },
}
```

---

## Option B: remote MCP URL (if NanoClaw supports remote MCP servers)

If your NanoClaw build can connect to remote MCP over HTTP, point it to your deployed endpoint:

```ts
mcpServers: {
  xfloor: {
    transport: "streamable-http",
    url: "https://your-domain.com/mcp",
    headers: {
      Authorization: "Bearer <your-token>",
    },
  },
}
```

---

## allowedTools update

Make sure `allowedTools` includes xfloor tools:

```ts
allowedTools: [
  // existing tools...
  "mcp__xfloor__*",
]
```

This lets NanoClaw invoke:

- `mcp__xfloor__xfloor_query_memory`
- `mcp__xfloor__xfloor_create_event`
- `mcp__xfloor__xfloor_recent_events`
- `mcp__xfloor__xfloor_get_floor_info`
- `mcp__xfloor__xfloor_wait_for_ingestion`

---

## Minimal patch snippet

See `integrations/nanoclaw/patch-snippet.ts` for a copy/paste snippet, and `integrations/nanoclaw/apply_patch.sh` for an example patch helper script.

---

## WhatsApp prompt examples that should trigger xFloor tools

- `@Andy search my campus floor for scholarship info`
- `@Andy post this note to my floor: Scholarship deadline moved to Friday. Please update your forms.`

These prompts typically map to:

- search -> `xfloor_query_memory`
- post note -> `xfloor_create_event`
