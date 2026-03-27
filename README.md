# xfloor-mcp

Production-ready Python 3.12 MCP server for xFloor APIs with:

- Streamable HTTP MCP endpoint at `/mcp`
- Local stdio mode: `python -m xfloor_mcp.stdio`

## Quick architecture (EC2)

- `docker compose` runs app on **localhost only**: `127.0.0.1:8000`
- `nginx` handles public HTTPS and reverse-proxies:
  - `/mcp` -> `http://127.0.0.1:8000/mcp`
  - `/healthz` -> `http://127.0.0.1:8000/healthz`

---

## Local development

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
./scripts/dev.sh
```

Health check:

```bash
curl -s http://127.0.0.1:8000/healthz
```

---

## Example `.env` file

Create `.env` in repo root:

```env
APP_NAME=xfloor-mcp
APP_HOST=0.0.0.0
APP_PORT=8000
APP_LOG_LEVEL=info

CORS_ALLOW_ORIGINS=*
CORS_ALLOW_CREDENTIALS=true
CORS_ALLOW_METHODS=*
CORS_ALLOW_HEADERS=*

XFLOOR_BASE_URL=https://appfloor.in
XFLOOR_TIMEOUT_SECONDS=30
XFLOOR_DEFAULT_AUTH_TOKEN=local-dev-bearer-token
# compatibility alias also supported:
# XFLOOR_DEFAULT_BEARER_TOKEN=local-dev-bearer-token
XFLOOR_DEFAULT_USER_ID=local-dev-user
XFLOOR_DEFAULT_APP_ID=local-dev-app
XFLOOR_AUTH_MODE=auto
XFLOOR_OAUTH_STUB_ENABLED=false
XFLOOR_AUTH0_DOMAIN=dev-aobq6ntuhxzmcu6j.jp.auth0.com
XFLOOR_AUTH0_ISSUER=https://dev-aobq6ntuhxzmcu6j.jp.auth0.com/
XFLOOR_AUTH0_AUDIENCE=https://xFloorMCPTest
# Optional override; when omitted, oauth protected-resource metadata uses XFLOOR_AUTH0_AUDIENCE.
XFLOOR_OAUTH_RESOURCE=https://xFloorMCPTest
XFLOOR_OAUTH_STUB_ISS=https://example.auth0.com/
XFLOOR_OAUTH_STUB_SUB=auth0|demo-user
XFLOOR_OAUTH_STUB_USER_ID=oauth-dev-user
```

Auth + identity behavior:
- MCP requests normally include `Authorization: Bearer <token>`.
- In HTTP mode, `X-XFloor-User-Id` and `X-XFloor-App-Id` are normally required.
- `XFLOOR_AUTH_MODE` supports `noauth`, `oauth`, and `auto`. The default is `auto`, which is the least disruptive option here because it preserves the current noauth/dev flow unless an explicit bearer header is present and OAuth stub mode is enabled.
- For local/ngrok development, you can set `XFLOOR_DEFAULT_AUTH_TOKEN` (or compatibility alias `XFLOOR_DEFAULT_BEARER_TOKEN`), `XFLOOR_DEFAULT_USER_ID`, and `XFLOOR_DEFAULT_APP_ID` in `.env` to use defaults when headers are absent.
- Inbound OAuth and outbound xFloor auth are intentionally separate: Auth0 bearer tokens authenticate ChatGPT -> MCP, while MCP -> xFloor uses the configured xFloor service token (`XFLOOR_DEFAULT_AUTH_TOKEN` / `XFLOOR_DEFAULT_BEARER_TOKEN`).
- In `oauth` mode, the MCP server validates the bearer token against Auth0 issuer metadata / JWKS, extracts `iss + sub`, resolves an xFloor `user_id`, and caches that mapping in memory for reuse.

### Real Auth0-backed OAuth test mode

This repo now includes a **real Auth0-backed OAuth test flow** for `XFLOOR_AUTH_MODE=oauth`. This is intended for current ngrok-based testing with the current Auth0 tenant and API. Production tenant/app/API values can be swapped later via environment variables.

What it does today:

1. Accepts `Authorization: Bearer <token>` on each MCP request
2. In `oauth` mode, validates the token against Auth0 OIDC metadata and JWKS
3. Extracts verified `iss + sub`
4. Resolves `iss + sub -> xfloor user_id` using a **stub `verify_oauth_user(...)`**
5. Caches that identity mapping **in memory only** for the life of the server process
6. Populates the existing request context so the current tools continue working unchanged
7. Exposes protected resource metadata at `/.well-known/oauth-protected-resource`
8. Exposes public discovery endpoints on the MCP host (`/.well-known/*` and `/mcp/.well-known/*`) so ChatGPT OAuth inspection can complete without a bearer token
9. Returns `401 Unauthorized` plus `WWW-Authenticate: Bearer ... resource_metadata=...` on unauthenticated or invalid **protected MCP tool requests** in `oauth` mode

What is still stubbed:

- `verify_oauth_user(...)` still returns `XFLOOR_OAUTH_STUB_USER_ID`
- The xFloor-side user-linking/backend lookup is not implemented yet
- The identity cache is still in-memory only and resets on restart

What would be replaced later:

- The Auth0 test tenant/app/API configuration values
- The stub `verify_oauth_user(...)` lookup in `xfloor_mcp/auth/`

Mode behavior:

- `XFLOOR_AUTH_MODE=noauth`
  - Preserves the current working header/env fallback behavior exactly
  - Uses `Authorization` or `XFLOOR_DEFAULT_AUTH_TOKEN` / `XFLOOR_DEFAULT_BEARER_TOKEN`
  - Uses `X-XFloor-User-Id` or `XFLOOR_DEFAULT_USER_ID`
  - Uses `X-XFloor-App-Id` or `XFLOOR_DEFAULT_APP_ID`

- `XFLOOR_AUTH_MODE=oauth`
  - Requires a bearer token
  - Verifies it via Auth0 issuer metadata and JWKS
  - Extracts `iss + sub`
  - Resolves and caches `user_id`
  - Does **not** require `X-XFloor-User-Id`
  - Still uses `X-XFloor-App-Id` or `XFLOOR_DEFAULT_APP_ID` for app context
  - Exposes protected resource metadata and Bearer challenges for ChatGPT/oauth-aware clients

- `XFLOOR_AUTH_MODE=auto`
  - Preserves the current local/ngrok dev behavior exactly
  - If an `Authorization` bearer header is present **and** `XFLOOR_OAUTH_STUB_ENABLED=true`, the server uses the existing stub OAuth path first
  - Otherwise it falls back to the current noauth/dev flow

Example Auth0-backed test env:

```env
XFLOOR_AUTH_MODE=oauth
XFLOOR_AUTH0_DOMAIN=dev-aobq6ntuhxzmcu6j.jp.auth0.com
XFLOOR_AUTH0_ISSUER=https://dev-aobq6ntuhxzmcu6j.jp.auth0.com/
XFLOOR_AUTH0_AUDIENCE=https://xFloorMCPTest
# Optional override; default protected resource = XFLOOR_AUTH0_AUDIENCE
XFLOOR_OAUTH_RESOURCE=https://xFloorMCPTest
XFLOOR_OAUTH_STUB_USER_ID=oauth-dev-user
XFLOOR_DEFAULT_APP_ID=local-dev-app
```

Notes:

- Active-floor session behavior is unchanged.
- The identity cache is in-memory only and resets on process restart.
- Dynamic client registration is expected on the Auth0 side via `https://dev-aobq6ntuhxzmcu6j.jp.auth0.com/oidc/register`.
- `resource_metadata` in Bearer challenges is automatically built from your MCP host URL; the protected-resource `resource` value defaults to `XFLOOR_AUTH0_AUDIENCE` so Auth0 issues tokens for your API identifier.
- Production Auth0 tenant/app/API values can later be swapped by changing env only.

Testing with ChatGPT developer mode + ngrok:

1. Start the server with `XFLOOR_AUTH_MODE=oauth` and the Auth0 env above.
2. Expose the server through ngrok and set `XFLOOR_OAUTH_RESOURCE` to that public base URL.
3. Ensure the Auth0 application/client is configured for the MCP test API audience and dynamic registration flow.
4. Point ChatGPT developer mode at the ngrok MCP URL.
5. ChatGPT should discover the protected-resource metadata, follow the Bearer challenge, obtain an Auth0 token for the configured audience, and then call the MCP tools with `Authorization: Bearer <token>`.

---

## EC2 deployment (Ubuntu 22.04/24.04)

### 1) Provision EC2 + Security Group

Use a security group with:

- **22/tcp** from your admin IP
- **80/tcp** from `0.0.0.0/0`
- **443/tcp** from `0.0.0.0/0`

> Do **not** expose 8000 publicly; app binds to localhost via compose.

### 2) Install Docker + Compose plugin + Nginx + Certbot

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release

sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin nginx certbot python3-certbot-nginx

sudo usermod -aG docker $USER
newgrp docker
```

### 3) Clone repo and configure env

```bash
git clone <your-repo-url> xfloor-mcp
cd xfloor-mcp
cp .env.example .env 2>/dev/null || true
# or create .env manually using the example in this README
```

### 4) Start app container

```bash
./scripts/prod.sh
```

Verify app is listening locally only:

```bash
ss -ltnp | rg ':8000|:80|:443'
curl -s http://127.0.0.1:8000/healthz
```

### 5) Configure nginx

Copy nginx config and set your domain:

```bash
sudo cp nginx/xfloor-mcp.conf /etc/nginx/sites-available/xfloor-mcp.conf
sudo sed -i 's/your-domain.example.com/your-real-domain.com/g' /etc/nginx/sites-available/xfloor-mcp.conf
sudo ln -sf /etc/nginx/sites-available/xfloor-mcp.conf /etc/nginx/sites-enabled/xfloor-mcp.conf
sudo nginx -t
sudo systemctl reload nginx
```

### 6) Issue TLS certificate via Certbot

```bash
sudo certbot --nginx -d your-real-domain.com
sudo systemctl status certbot.timer --no-pager
```

Re-test nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

### 7) Validate externally

```bash
curl -s https://your-real-domain.com/healthz
```

---


## ChatGPT-facing v1 tool surface

This repo now exposes an additive **v1 ChatGPT-facing MCP surface** on top of the existing tools. The preferred floor-selection flow is now **tool-driven** instead of header-driven.

### Preferred ChatGPT-facing flow

1. Connect with the normal required headers:
   - `Authorization: Bearer <your-token>`
   - `X-XFloor-App-Id: <your-app-id>`
   - If using `XFLOOR_AUTH_MODE=noauth`, also send `X-XFloor-User-Id: <your-user-id>`
2. Call `xfloor_set_active_floor` once, for example with `@phari`.
3. Then use the current-floor tools without passing a floor ID or the active-floor header.

### New preferred ChatGPT-facing tools

1. `xfloor_set_active_floor`
   - Use this when the user explicitly wants to select or switch the current xFloor, for example with phrases like `use @phari` or `@croma`.
   - Input: `floor_ref` (accepts `phari`, `@phari`, `croma`, `@croma`) and optional `floor_id`.

2. `xfloor_query_current_floor`
   - Use this when the user wants to ask a question about the currently active xFloor.
   - Inputs: `query`, optional `topic`, optional `limit`.
   - Returns MCP `content` plus normalized `structuredContent`:
     - `activeFloor`
     - `query`
     - `answer`
     - `bestMatch`
     - `relevantFloors[]`
     - `resultCount`
   - In widget-capable app surfaces, `ui://widget/query-results-v1.html` renders tiny floor chips under the answer.
   - In generic remote-MCP tool-calling surfaces, this still returns a text fallback list of related floors.

3. `xfloor_post_event_to_current_floor`
   - **Text-only** post tool for the currently active xFloor.
   - Inputs: optional `title` (falls back to `description`), `description`, optional `block_id`, plus optional `block_type`, `location`, `start_date`, `start_time`, `end_date`, `end_time`.

### Posting status (temporary rollback)

- Posting is currently **text-only**.
- Media/file upload posting is **disabled for now**.
- Widget-based posting flow is **disabled for now**.
- Query/read flows and active-floor tools remain supported.
- A future version may reintroduce robust media posting with a stable contract.

### Query normalization + remote-MCP fallback

- Normalization is done inside the MCP tool (`xfloor_query_current_floor`), not in xFloor backend.
- Raw xFloor `items[].text` are parsed when possible and mapped into normalized floor rows.
- Malformed `item.text` fails soft: answer is still returned, malformed items are counted in `_meta`.
- Relevant floors are sorted by score and exposed in `structuredContent.relevantFloors`.
- Widget-capable app surfaces can render tiny chips from `structuredContent.relevantFloors` and call `xfloor_set_active_floor`.
- Remote MCP tool callers still get a compact text fallback listing related floors with switch-floor guidance.

### Query widget troubleshooting logs

When debugging why chips/widget are not visible, check server logs for:
- `Query widget setup: tool_supports_meta=...`
- `Query widget registration attempt ...` and success/fallback signature messages
- `Query tool descriptor linked to widget ...` (or `_meta unsupported`)
- `Query widget payload generated ...`

The query tool result `_meta.widget_debug` also includes:
- `query_widget_uri`
- `tool_supports_meta`
- `tool_widget_linked`
- `relevant_floor_count`

### Widget CSP (Apps SDK / ChatGPT UI)

- If the ChatGPT Apps panel shows widget CSP as "off", the component can still render, but host-side security restrictions are not explicitly declared.
- This repo now attaches widget CSP metadata on the registered resource (`openai/widgetCSP`) and marks the query tool as widget-callable (`openai/widgetAccessible=true`).
- Current policy is intentionally strict for this widget:
  - `connect_domains: []` (the component itself performs no network fetches)
  - `resource_domains: [<origin from XFLOOR_BASE_URL>]` when that URL is valid
- If your widget later fetches external APIs/CDNs, add only those exact origins to CSP allowlists.

### Active-floor precedence rules

Current-floor tools resolve the floor in this order:

1. In-memory server-side active-floor state previously set by `xfloor_set_active_floor`
2. `X-XFloor-Active-Floor-Id` header, if present, as a fallback/debug path
3. Otherwise the tool fails clearly and asks the caller to set a floor first, for example `@phari` or `use @croma`

This means a floor explicitly selected with `xfloor_set_active_floor` wins over a stale Inspector header value.

### State lifetime / v1 limitation

- Active-floor state is stored in **in-memory server-side session state**.
- For HTTP, it is keyed by MCP session ID when available, otherwise it falls back to a stable user/app-based key.
- For stdio, it is process-local in-memory state.
- State resets on server restart.

### Backward compatibility

The original tools are still preserved and continue to work unchanged:

- `xfloor_query_memory`
- `xfloor_create_event`
- `xfloor_recent_events`
- `xfloor_get_floor_info`
- `xfloor_wait_for_ingestion`

Use the **old tools** when you need low-level control such as explicit `floor_ids`, raw `input_info`, or floor-specific plumbing. Use the **new tools** when you want a cleaner ChatGPT-facing experience for a single active floor.

### Inspector example without active-floor header

Connect with headers:

- `Authorization: Bearer <your-token>`
- `X-XFloor-App-Id: <your-app-id>`

If you are using `XFLOOR_AUTH_MODE=noauth`, also send:

- `X-XFloor-User-Id: <your-user-id>`

If you are using `XFLOOR_AUTH_MODE=oauth` (or `auto` + OAuth stub path), MCP resolves `user_id` from verified `iss + sub`, so `X-XFloor-User-Id` is not required.

Do **not** send `X-XFloor-Active-Floor-Id` for the normal ChatGPT/Inspector flow.

Then run tools in this order:

1. `xfloor_set_active_floor` with: 
   ```json
   {"floor_ref": "@phari"}
   ```
2. `xfloor_query_current_floor`
3. `xfloor_post_event_to_current_floor`

The `X-XFloor-Active-Floor-Id` header is still supported as an optional fallback/debug mechanism, but a floor chosen with `xfloor_set_active_floor` now takes precedence.

## Verify MCP with Inspector (post-deploy)

Start Inspector locally on your machine:

```bash
npx @modelcontextprotocol/inspector
```

In Inspector:

- Transport: **Streamable HTTP**
- URL: `https://your-real-domain.com/mcp`
- Header: `Authorization: Bearer <your-token>`
- Header: `X-XFloor-App-Id: <your-app-id>`
- Optional debug override header: `X-XFloor-Active-Floor-Id: <active-floor-id>`

If you are in `noauth` mode, also include:

- Header: `X-XFloor-User-Id: <your-user-id>`

Then run tools:

- First set a floor with: `xfloor_set_active_floor`
- Then use the preferred v1 tools: `xfloor_query_current_floor`, `xfloor_post_event_to_current_floor`
- Backward-compatible tools remain available: `xfloor_query_memory`, `xfloor_create_event`, `xfloor_recent_events`, `xfloor_get_floor_info`, `xfloor_wait_for_ingestion`

---

## Stdio mode (local clients)

```bash
python -m xfloor_mcp.stdio
```

Or with Inspector stdio mode:

```bash
npx @modelcontextprotocol/inspector \
  --transport stdio \
  --command python \
  --args "-m,xfloor_mcp.stdio"
```
