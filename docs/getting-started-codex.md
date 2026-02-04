# Getting Started with Codex (stdio)

This is the fastest path: clone → run → paste config.

## 1) Install dependencies

```bash
uv sync --extra test
```

## 2) Run the MCP server (stdio)

```bash
make run
```

Alternate one‑liner:

```bash
./bin/mcp-catalog
```

## 3) Add the MCP server to Codex

Copy `configs/codex.config.toml` into your Codex config:

- `~/.codex/config.toml` (user‑level), or
- `./.codex/config.toml` (project‑level)

Example:

```toml
[mcp_servers.api_catalog]
command = "./bin/mcp-catalog"
# cwd = "/absolute/path/to/fastmcp-openapi"

[mcp_servers.api_catalog.env]
OPENAPI_DIR = "./specs"
OPENAPI_INDEX_PATH = "./.cache/api_catalog.sqlite"
OPENAPI_DEREF_MODE = "lazy"
OPENAPI_WATCH = "1"
OPENAPI_WATCH_INTERVAL = "2"
# OPENAPI_SEMANTIC = "1"
```

## 4) Try a prompt

See `PROMPTS.md` for copy/paste prompts. Example:

```
Create a pet
```

## 5) What you should see

The agent should:
1. `api_search` → top 3 operations
2. `api_get_operation` → contract details
3. `api_generate_request` → deterministic payload
4. `api_generate_snippets` → curl + SDK snippet

## Troubleshooting

- If you add new specs, set `OPENAPI_WATCH=1` and the index will auto‑refresh.
- If you want faster startup for large specs, set `OPENAPI_INDEX_PATH` to persist the index.
- Semantic search requires Python 3.13 or earlier (see `docs/tool-reference.md`).
