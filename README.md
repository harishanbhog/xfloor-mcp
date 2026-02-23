# xfloor-mcp

Production-ready Python 3.12 MCP server that exposes xFloor APIs as MCP tools over:

1. **Streamable HTTP** mounted at **`/mcp`** in FastAPI
2. **stdio mode** for local MCP clients (`python -m xfloor_mcp.stdio`)

## Features

- FastAPI host app with health endpoint (`/healthz`)
- MCP server built with `FastMCP`
- Streamable HTTP configured with:
  - `stateless_http=True`
  - `json_response=True`
- CORS support with `Mcp-Session-Id` exposed header
- Environment-driven configuration via `pydantic-settings`
- xFloor API wrappers for memory query, event creation, recent events, floor info
- Docker + nginx deployment scaffolding

## Requirements

- Python 3.12+
- Node.js (optional, for MCP Inspector)

## Installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .[dev]
```

## Configuration

Set environment variables (or create a `.env` file):

```bash
export APP_NAME=xfloor-mcp
export APP_HOST=0.0.0.0
export APP_PORT=8000
export APP_LOG_LEVEL=info

export CORS_ALLOW_ORIGINS='*'
export CORS_ALLOW_CREDENTIALS=true
export CORS_ALLOW_METHODS='*'
export CORS_ALLOW_HEADERS='*'

export XFLOOR_BASE_URL='https://appfloor.in'
export XFLOOR_TIMEOUT_SECONDS=15
```

> The MCP request must include `Authorization: Bearer <token>`. The token is forwarded to xFloor APIs.

## Run locally (HTTP)

```bash
python -m xfloor_mcp.main
```

Then:

- Health: `http://localhost:8000/healthz`
- MCP endpoint: `http://localhost:8000/mcp`

## Run locally (stdio)

```bash
python -m xfloor_mcp.stdio
```

Use this mode for local MCP clients/tests that launch a subprocess transport.

## Test with MCP Inspector

### Against HTTP transport

```bash
npx @modelcontextprotocol/inspector
```

In Inspector:

- Transport: **Streamable HTTP**
- URL: `http://localhost:8000/mcp`
- Add header: `Authorization: Bearer <your-token>`

### Against stdio transport

```bash
npx @modelcontextprotocol/inspector \
  --transport stdio \
  --command python \
  --args "-m,xfloor_mcp.stdio"
```

## Available MCP tools

1. `xfloor_query_memory`
   - Calls `POST /agent/memory/query`
   - Input fields: `user_id`, `query`, `floor_ids`, optional `filters`, `k`, `include_metadata` (`"0"|"1"`), `summary_needed` (`"0"|"1"`), `app_id`

2. `xfloor_create_event`
   - Calls `POST /api/memory/events` (multipart/form-data)
   - Input fields: `input_info` (JSON string with required keys: `floor_id`, `block_id`, `user_id`, `title`, `description`; optional `block_type`), optional `app_id`, optional `files[]`
   - `files[]` item format: `{filename, content_base64, mime_type}`

3. `xfloor_recent_events`
   - Calls `GET /api/memory/recent/events`
   - Input fields: configurable query params (`floor_id`, `user_id`, `app_id`, `page`, `limit`, `start_time`, `end_time`, `event_type`) plus `extra_params`

4. `xfloor_get_floor_info`
   - Calls `GET /api/memory/floor/info/{floor_id}`

5. `xfloor_wait_for_ingestion`
   - Polls recent events until `match_text` is found in event `title`/`description`
   - Input fields: `floor_id`, `match_text`, optional `timeout_s` (default 30), `poll_interval_s` (default 2)

## Example tool calls (JSON)

`xfloor_query_memory`:

```json
{
  "user_id": "user-123",
  "query": "what was decided in standup?",
  "floor_ids": ["floor-1"],
  "include_metadata": "1",
  "summary_needed": "1",
  "k": 5
}
```

`xfloor_create_event`:

```json
{
  "input_info": "{\"floor_id\":\"floor-1\",\"block_id\":\"block-1\",\"user_id\":\"user-123\",\"title\":\"Meeting Notes\",\"description\":\"Action items collected\"}",
  "files": [
    {
      "filename": "notes.txt",
      "content_base64": "aGVsbG8gd29ybGQ=",
      "mime_type": "text/plain"
    }
  ]
}
```

`xfloor_recent_events`:

```json
{
  "floor_id": "floor-1",
  "limit": 20,
  "page": 1
}
```

`xfloor_get_floor_info`:

```json
{
  "floor_id": "floor-1"
}
```

`xfloor_wait_for_ingestion`:

```json
{
  "floor_id": "floor-1",
  "match_text": "Meeting Notes",
  "timeout_s": 30,
  "poll_interval_s": 2
}
```

## Docker deployment

Build and run app + nginx reverse proxy:

```bash
docker compose up --build
```

Services:

- `xfloor-mcp`: FastAPI app on internal `8000`
- `nginx`: public listener on `8080`

MCP endpoint through nginx:

- `http://localhost:8080/mcp`
