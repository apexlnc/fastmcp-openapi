from __future__ import annotations

import os
import sys
import threading
import time
from typing import Any

from fastmcp import FastMCP

from .catalog import CatalogEngine
from .catalog.ingest import fingerprint_spec_files

mcp = FastMCP("api-catalog-mcp")
engine = CatalogEngine(
    spec_dir=os.getenv("OPENAPI_DIR", "./specs"),
    index_path=os.getenv("OPENAPI_INDEX_PATH", ":memory:"),
    deref_mode=os.getenv("OPENAPI_DEREF_MODE", "lazy"),
)


@mcp.tool(name="api_search")
def api_search(query: str, audience: str | None = None) -> dict[str, Any]:
    """Search for relevant API operations and return ranked matches with rationale."""
    return engine.catalog_search(query=query, audience=audience)


@mcp.tool(name="api_get_operation")
def api_get_operation(endpoint_id: str, full: bool = True) -> dict[str, Any]:
    """Return a single operation contract by endpointId."""
    return engine.endpoint_get(endpoint_id, full=full)


@mcp.tool(name="api_generate_request")
def api_generate_request(endpoint_id: str, provided_fields: dict[str, Any] | None = None) -> dict[str, Any]:
    """Generate a deterministic request skeleton for an operation."""
    return engine.payload_generate(endpoint_id, provided_fields or {})


@mcp.tool(name="api_validate_request")
def api_validate_request(endpoint_id: str, request: dict[str, Any]) -> dict[str, Any]:
    """Validate a request object against the operation schema."""
    return engine.payload_validate(endpoint_id, request)


@mcp.tool(name="api_generate_snippets")
def api_generate_snippets(request: dict[str, Any], lang: list[str] | None = None) -> dict[str, Any]:
    """Generate deterministic curl + SDK snippets for a request object."""
    return engine.snippet_generate(request, lang)


@mcp.tool(name="api_execute_request")
def api_execute_request(
    endpoint_id: str,
    request: dict[str, Any],
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Execute a request against the API (opt-in via OPENAPI_EXECUTION=1)."""
    return engine.execute_request(endpoint_id, request, auth_token=auth_token)


app = mcp.http_app()


def _print_banner() -> None:
    prompts_path = os.path.join(os.getcwd(), "PROMPTS.md")
    sys.stderr.write("Connected! Try these prompts:\\n")
    sys.stderr.write(f"  - See {prompts_path}\\n")
    if os.getenv("OPENAPI_EXECUTION", "0") != "1":
        sys.stderr.write("Execution is disabled. Set OPENAPI_EXECUTION=1 to enable api_execute_request.\\n")
    if os.getenv("OPENAPI_SEMANTIC", "0") == "1" and not engine.semantic_enabled():
        sys.stderr.write("Semantic search disabled (install extras: uv sync --extra semantic).\\n")
    sys.stderr.flush()


def _start_watch_thread() -> None:
    watch = os.getenv("OPENAPI_WATCH", "0")
    if watch != "1":
        return

    interval = float(os.getenv("OPENAPI_WATCH_INTERVAL", "2"))
    spec_dir = engine.spec_dir
    last = fingerprint_spec_files(spec_dir)

    def loop() -> None:
        nonlocal last
        while True:
            time.sleep(interval)
            current = fingerprint_spec_files(spec_dir)
            if _fingerprints_changed(last, current):
                engine.refresh(use_cache=False)
                last = current

    thread = threading.Thread(target=loop, daemon=True)
    thread.start()


def _fingerprints_changed(prev: list[Any], current: list[Any]) -> bool:
    if len(prev) != len(current):
        return True
    prev_sorted = sorted(prev, key=lambda item: item.relative_path)
    curr_sorted = sorted(current, key=lambda item: item.relative_path)
    for left, right in zip(prev_sorted, curr_sorted):
        if left.relative_path != right.relative_path:
            return True
        if left.size != right.size or left.mtime != right.mtime:
            return True
    return False


if __name__ == "__main__":
    _print_banner()
    _start_watch_thread()
    mode = os.getenv("MCP_TRANSPORT", "stdio")
    if mode == "http":
        mcp.run(
            transport="http",
            host=os.getenv("MCP_HOST", "0.0.0.0"),  # nosec B104
            port=int(os.getenv("PORT", "8000")),
        )
    else:
        mcp.run()
