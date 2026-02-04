# Tool Reference

This server exposes a small, deterministic tool surface that avoids endpoint‑per‑tool explosion.

## api_search
Search for relevant API operations.

**Input**
- `query` (string, required)
- `audience` (string, optional: `external` or `internal`)

**Output**
- `query`
- `audience`
- `matches[]`
  - `endpointId`, `specId`, `method`, `path`, `summary`, `description`
  - `matchSnippet` (FTS text snippet)

---

## api_get_operation
Get a single operation contract.

**Input**
- `endpoint_id` (string)
- `full` (bool, default `true`)
  - `true`: includes requestBody + responses
  - `false`: summary only

**Output**
- `endpointId`, `specId`, `operationId`, `method`, `path`, `summary`, `description`, `tags`
- `parameters[]`
- `requestBody` (if `full=true`)
- `responses` (if `full=true`)

---

## api_generate_request
Deterministically generate a request skeleton.

**Input**
- `endpoint_id` (string)
- `provided_fields` (object, optional)

**Output**
- `endpointId`
- `request`
  - `method`, `path`, `contentType`, `parameters`, `body`
- `unknownRequiredFields[]`

---

## api_validate_request
Validate a request object against the operation schema.

**Input**
- `endpoint_id` (string)
- `request` (object)

**Output**
- `ok` (bool)
- `errors[]` with `path` + `message`

---

## api_generate_snippets
Generate copy/paste snippets from a request object.

**Input**
- `request` (object)
- `lang` (array, optional; defaults to `curl`, `python`, `ts`)

**Output**
- `snippets` (object keyed by language)

---

## api_execute_request (opt‑in)
Execute a request using `httpx`.

**Input**
- `endpoint_id` (string)
- `request` (object)
- `auth_token` (string, optional)

**Output**
- `ok` (bool)
- `status` (int)
- `time` (string)
- `body` (object or text)

Execution is disabled unless `OPENAPI_EXECUTION=1`.

---

## Semantic search (optional)

Semantic search is **disabled by default**. To enable:

```bash
uv sync --extra semantic
export OPENAPI_SEMANTIC=1
```

Note: `fastembed` depends on `onnxruntime`, which currently supports Python 3.13 or earlier.
