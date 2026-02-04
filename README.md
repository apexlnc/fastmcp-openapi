# fastmcp-openapi

ReAPI-style OpenAPI catalog built on FastMCP with deterministic indexing and search.

## Vision

**Autocomplete for API Operations.** Just as IntelliSense helps a developer write code by knowing the available methods, `fastmcp-openapi` helps an AI agent build correct API calls by knowing the available endpoints and their exact requirements.

## The Problem

LLMs are great at writing code, but they are terrible at guessing strict API contracts:
- **Hallucination**: The model guesses field names or payload shapes that don't exist.
- **Context bloat**: Pasting a multi‑MB OpenAPI spec into context is slow and noisy.
- **The gap**: The model writes code, the user runs it, it fails (400), and momentum dies.

## The Solution

`fastmcp-openapi` is a deterministic catalog + contract engine that bridges intent to spec without tool explosion:
- **Discovery**: Search across many services and return the best operations.
- **Construction**: Generate a schema‑driven request skeleton with unknown required fields.
- **Execution (opt‑in)**: Optionally run the request for closed‑loop verification (`OPENAPI_EXECUTION=1`).

## Tool Surface

- `api_search(query, audience="external|internal")`
- `api_get_operation(endpoint_id, full=True)`
- `api_generate_request(endpoint_id, provided_fields)`
- `api_validate_request(endpoint_id, request)`
- `api_generate_snippets(request, lang=["curl","python","ts"])`
- `api_execute_request(endpoint_id, request, auth_token=None)` (opt-in)

## Quickstart (stdio)

```bash
make run
```

Alternate one-liner:

```bash
./bin/mcp-catalog
```

Set the spec directory:

```bash
export OPENAPI_DIR=./specs
```

Enable index caching (recommended for large specs):

```bash
export OPENAPI_INDEX_PATH=./.cache/api_catalog.sqlite
```

Switch deref mode:

```bash
# "lazy" (default) avoids full deref on startup
# "full" uses prance to fully resolve $ref
export OPENAPI_DEREF_MODE=lazy
```

Enable execution (opt-in):

```bash
export OPENAPI_EXECUTION=1
export OPENAPI_BASE_URL=http://localhost:8000
```

Optional auth (fallback if tool call doesn't pass auth_token):

```bash
export API_KEY=...
# or
export API_TOKEN=...
```

## Codex Config (stdio)

Codex reads MCP server definitions from `~/.codex/config.toml` or a project-scoped `./.codex/config.toml`.

Use the ready-to-copy snippet in `configs/codex.config.toml` and adjust `cwd` if needed.

## DeepAgents Demo (optional)

Install optional dependencies:

```bash
uv sync --extra agents
```

Run the demo script:

```bash
uv run python examples/deepagents_demo.py
```

The demo uses LangChain's MCP adapters to load tools from the stdio server.

## Demo Assets

- Example specs: `specs/`
- Prompt cards: `PROMPTS.md`
- Golden intent examples: `examples/`
- Codex config snippet: `configs/codex.config.toml`

## Docs

- Codex setup: `docs/getting-started-codex.md`
- DeepAgents setup: `docs/getting-started-deepagents.md`
- Tool reference: `docs/tool-reference.md`
- Execution safety: `docs/execution-safety.md`

## Quality (Lint/Typecheck/Tests)

Install dev + test tooling:

```bash
uv sync --extra dev --extra test
```

Run the checks:

```bash
make lint
make format
make typecheck
make test
make security
```

## Optional: Streamable HTTP (later)

You can expose Streamable HTTP for a shared service without changing the tool logic:

```bash
make serve-http
```

## Optional: Semantic Search (fastembed + numpy)

Enable local semantic search (hybrid RRF with FTS5):

```bash
uv sync --extra semantic
export OPENAPI_SEMANTIC=1
```

Optional: set an embedding model:

```bash
export OPENAPI_EMBED_MODEL=BAAI/bge-small-en-v1.5
```

Note: `fastembed` depends on `onnxruntime`, which currently publishes wheels up to Python 3.13. If you are on Python 3.14, create a 3.13 virtual environment to enable semantic search.
