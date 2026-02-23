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

export XFLOOR_BASE_URL='https://api.example-xfloor.com'
export XFLOOR_API_KEY='your-api-key'
export XFLOOR_TIMEOUT_SECONDS=15
```

> `CORS_ALLOW_*` list values can be JSON arrays or comma-separated strings.

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

### Against stdio transport

```bash
npx @modelcontextprotocol/inspector \
  --transport stdio \
  --command python \
  --args "-m,xfloor_mcp.stdio"
```

## Development scripts

```bash
./scripts/dev.sh
./scripts/prod.sh
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

## Tool contract

This server registers two generic tools:

- `xfloor_get` with input:
  - `path: str`
  - `params: dict | null`
- `xfloor_post` with input:
  - `path: str`
  - `body: dict | null`

These proxy requests to your configured `XFLOOR_BASE_URL` using optional bearer auth from `XFLOOR_API_KEY`.
