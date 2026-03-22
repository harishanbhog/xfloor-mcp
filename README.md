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
XFLOOR_DEFAULT_USER_ID=local-dev-user
XFLOOR_DEFAULT_APP_ID=local-dev-app
```

Auth + identity behavior:
- MCP requests must include `Authorization: Bearer <token>`.
- In HTTP mode, `X-XFloor-User-Id` and `X-XFloor-App-Id` are required.
- If headers are absent, local-dev fallbacks can be set via `XFLOOR_DEFAULT_USER_ID` and `XFLOOR_DEFAULT_APP_ID`.
- Token is forwarded as Bearer auth and `user_id` / `app_id` are attached to every xFloor request as query params.

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
   - `X-XFloor-User-Id: <your-user-id>`
   - `X-XFloor-App-Id: <your-app-id>`
2. Call `xfloor_set_active_floor` once, for example with `@phari`.
3. Then use the current-floor tools without passing a floor ID or the active-floor header.

### New preferred ChatGPT-facing tools

1. `xfloor_set_active_floor`
   - Use this when the user explicitly wants to select or switch the current xFloor, for example with phrases like `use @phari` or `@croma`.
   - Input: `floor_ref` (accepts `phari`, `@phari`, `croma`, `@croma`) and optional `floor_id`.

2. `xfloor_query_current_floor`
   - Use this when the user wants to ask a question about the currently active xFloor.
   - Inputs: `query`, optional `topic`, optional `limit`.

3. `xfloor_get_current_floor_events`
   - Use this when the user wants recent or upcoming events from the currently active xFloor.
   - Inputs: optional `limit`, optional `event_type`.

4. `xfloor_post_event_to_current_floor`
   - Use this when the user explicitly wants to create/post an event in the currently active xFloor.
   - Inputs: `title`, `description`, plus optional event fields like `location`, `start_date`, `start_time`, `end_date`, and `end_time`.

### Active-floor precedence rules

Current-floor tools resolve the floor in this order:

1. `X-XFloor-Active-Floor-Id` header, if present (debug/override path)
2. In-memory server-side active-floor state previously set by `xfloor_set_active_floor`
3. Otherwise the tool fails clearly and asks the caller to set a floor first, for example `@phari` or `use @croma`

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
- `X-XFloor-User-Id: <your-user-id>`
- `X-XFloor-App-Id: <your-app-id>`

Do **not** send `X-XFloor-Active-Floor-Id` for the normal ChatGPT/Inspector flow.

Then run tools in this order:

1. `xfloor_set_active_floor` with: 
   ```json
   {"floor_ref": "@phari"}
   ```
2. `xfloor_query_current_floor`
3. `xfloor_get_current_floor_events`
4. `xfloor_post_event_to_current_floor`

The `X-XFloor-Active-Floor-Id` header is still supported as an optional override/debug mechanism.

## Verify MCP with Inspector (post-deploy)

Start Inspector locally on your machine:

```bash
npx @modelcontextprotocol/inspector
```

In Inspector:

- Transport: **Streamable HTTP**
- URL: `https://your-real-domain.com/mcp`
- Header: `Authorization: Bearer <your-token>`
- Header: `X-XFloor-User-Id: <your-user-id>`
- Header: `X-XFloor-App-Id: <your-app-id>`
- Optional debug override header: `X-XFloor-Active-Floor-Id: <active-floor-id>`

Then run tools:

- First set a floor with: `xfloor_set_active_floor`
- Then use the preferred v1 tools: `xfloor_query_current_floor`, `xfloor_get_current_floor_events`, `xfloor_post_event_to_current_floor`
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
