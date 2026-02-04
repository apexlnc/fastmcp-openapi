.PHONY: run dev serve-http share lint format typecheck security test

OPENAPI_DIR ?= ./specs
OPENAPI_INDEX_PATH ?= ./.cache/api_catalog.sqlite
OPENAPI_DEREF_MODE ?= lazy
OPENAPI_WATCH ?= 1
OPENAPI_WATCH_INTERVAL ?= 2
MCP_HOST ?= 0.0.0.0
PORT ?= 8000


run:
	OPENAPI_DIR=$(OPENAPI_DIR) \
	OPENAPI_INDEX_PATH=$(OPENAPI_INDEX_PATH) \
	OPENAPI_DEREF_MODE=$(OPENAPI_DEREF_MODE) \
	OPENAPI_WATCH=$(OPENAPI_WATCH) \
	OPENAPI_WATCH_INTERVAL=$(OPENAPI_WATCH_INTERVAL) \
	uv run python -m api_catalog_mcp.server

dev: run

lint:
	uv run ruff check . --fix

format:
	uv run ruff format .

typecheck:
	uv run mypy api_catalog_mcp
	uv run pyright

security:
	uv run bandit -r api_catalog_mcp -x api_catalog_mcp/tests

test:
	uv run pytest

serve-http:
	OPENAPI_DIR=$(OPENAPI_DIR) \
	OPENAPI_INDEX_PATH=$(OPENAPI_INDEX_PATH) \
	OPENAPI_DEREF_MODE=$(OPENAPI_DEREF_MODE) \
	OPENAPI_WATCH=$(OPENAPI_WATCH) \
	OPENAPI_WATCH_INTERVAL=$(OPENAPI_WATCH_INTERVAL) \
	MCP_TRANSPORT=http \
	MCP_HOST=$(MCP_HOST) \
	PORT=$(PORT) \
	uv run python -m api_catalog_mcp.server

share:
	@echo "To share publicly, run:"
	@echo "  cloudflared tunnel --url http://localhost:$(PORT)"
	@echo "  or ngrok http $(PORT)"
