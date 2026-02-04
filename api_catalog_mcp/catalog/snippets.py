from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode


def generate_snippets(request: dict[str, Any], languages: list[str]) -> dict[str, str]:
    normalized = _normalize_request(request)
    if not normalized:
        return {}

    method = normalized["method"].upper()
    path = _render_path(normalized["path"], normalized["parameters"].get("path", {}))
    query_string = _render_query(normalized["parameters"].get("query", {}))
    url = "{{base_url}}" + path + query_string

    headers = dict(normalized["parameters"].get("header", {}))
    if normalized.get("contentType") and normalized.get("body") is not None:
        headers.setdefault("Content-Type", normalized["contentType"])

    body = normalized.get("body")
    payload = json.dumps(body, ensure_ascii=True, sort_keys=True, indent=2) if body is not None else None

    snippets: dict[str, str] = {}
    for lang in languages:
        if lang == "curl":
            snippets["curl"] = _curl_snippet(method, url, headers, payload)
        elif lang == "python":
            snippets["python"] = _python_snippet(method, url, headers, body)
        elif lang == "ts":
            snippets["ts"] = _ts_snippet(method, url, headers, payload)
    return snippets


def _normalize_request(request: dict[str, Any]) -> dict[str, Any] | None:
    if "request" in request and isinstance(request["request"], dict):
        return request["request"]
    if "method" in request and "path" in request:
        return request
    return None


def _render_path(path: str, path_params: dict[str, Any]) -> str:
    rendered = path
    for name, value in path_params.items():
        rendered = rendered.replace(f"{{{name}}}", str(value))
    return rendered


def _render_query(query_params: dict[str, Any]) -> str:
    if not query_params:
        return ""
    return "?" + urlencode(query_params, doseq=True)


def _curl_snippet(method: str, url: str, headers: dict[str, Any], payload: str | None) -> str:
    parts = ["curl", "-X", method, f"\"{url}\""]
    for name, value in headers.items():
        parts.extend(["-H", f"\"{name}: {value}\""])
    if payload is not None:
        parts.extend(["-d", f"'{payload}'"])
    return " ".join(parts)


def _python_snippet(method: str, url: str, headers: dict[str, Any], body: Any) -> str:
    lines = [
        "import requests",
        "",
        f"url = \"{url}\"",
    ]
    if headers:
        lines.append(f"headers = {json.dumps(headers, ensure_ascii=True, sort_keys=True, indent=2)}")
    else:
        lines.append("headers = {}")

    if body is not None:
        lines.append(f"payload = {json.dumps(body, ensure_ascii=True, sort_keys=True, indent=2)}")
        lines.append("response = requests.request(\"%s\", url, headers=headers, json=payload)" % method)
    else:
        lines.append("response = requests.request(\"%s\", url, headers=headers)" % method)

    lines.append("print(response.status_code)")
    lines.append("print(response.text)")
    return "\n".join(lines)


def _ts_snippet(method: str, url: str, headers: dict[str, Any], payload: str | None) -> str:
    lines = [
        "const url = \"%s\";" % url,
        "const headers = %s;" % json.dumps(headers, ensure_ascii=True, sort_keys=True, indent=2),
        "",
    ]
    if payload is not None:
        lines.append("const body = %s;" % payload)
    lines.append(
        "fetch(url, {\n  method: \"%s\",\n  headers,\n%s});"
        % (method, "  body: JSON.stringify(body)\n" if payload is not None else "")
    )
    return "\n".join(lines)
