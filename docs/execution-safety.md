# Execution Safety (api_execute_request)

`api_execute_request` is **opt‑in**.

## Enable execution

```bash
export OPENAPI_EXECUTION=1
```

## Base URL resolution

1. If `OPENAPI_BASE_URL` is set, it is used.
2. Otherwise, the server uses `servers[0].url` from the OpenAPI spec.

## Auth precedence

1. `auth_token` argument passed to the tool
2. `API_KEY` environment variable
3. `API_TOKEN` environment variable

If the token does not include a scheme, `Bearer` is used automatically.

## Recommended guardrails (hackathon mode)

- Keep `OPENAPI_EXECUTION` off by default.
- Use a staging or mock base URL.
- Provide read‑only API keys where possible.
