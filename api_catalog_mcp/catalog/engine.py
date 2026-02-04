from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from collections.abc import Hashable, Mapping
from typing import Any, cast

import httpx
from openapi_spec_validator import validate
from openapi_spec_validator.validation.exceptions import OpenAPIValidationError

from .deref import DerefError, dereference_spec
from .index import CatalogIndex
from .ingest import build_spec_files, fingerprint_spec_files, list_http_methods
from .model import Operation, Schema, SpecMeta
from .payloads import build_payload
from .render import render_catalog, render_contract, render_operation, render_schema
from .semantic import SemanticIndex
from .snippets import generate_snippets
from .validate import validate_payload


class CatalogEngine:
    def __init__(
        self,
        spec_dir: str,
        index_path: str = ":memory:",
        deref_mode: str = "lazy",
    ) -> None:
        self.spec_dir = os.path.abspath(spec_dir)
        self.index_path = index_path
        self._index = CatalogIndex(self.index_path)
        self._specs: dict[str, dict[str, Any]] = {}
        self._spec_paths: dict[str, str] = {}
        self._spec_meta: list[SpecMeta] = []
        self._spec_versions: dict[str, str | None] = {}
        self._cache_meta_path = self._resolve_cache_meta_path()
        self._deref_mode = deref_mode
        self._lock = threading.RLock()
        self._semantic = SemanticIndex(model_name=os.getenv("OPENAPI_EMBED_MODEL"))
        self._semantic_enabled = os.getenv("OPENAPI_SEMANTIC", "0") == "1" and self._semantic.available
        if os.getenv("OPENAPI_SEMANTIC", "0") == "1" and not self._semantic.available:
            # Keep service working even if optional deps are missing.
            self._semantic_enabled = False

    def refresh(self, use_cache: bool = True) -> None:
        with self._lock:
            if use_cache and self._load_cache():
                if self._semantic_enabled:
                    self._semantic.load(self._index.load_operation_embeddings())
                return

            spec_files = build_spec_files(self.spec_dir)
            self._index.reset()
            self._specs.clear()
            self._spec_paths.clear()
            self._spec_meta.clear()
            self._spec_versions.clear()

            operations: list[Operation] = []
            schemas: list[Schema] = []

            for spec_file in spec_files:
                is_valid, validation_error = self._validate_spec(spec_file.raw)
                spec = self._load_spec(spec_file.path, spec_file.raw)
                self._specs[spec_file.spec_id] = spec
                self._spec_paths[spec_file.spec_id] = spec_file.path
                version_raw = spec.get("openapi") if isinstance(spec, dict) else None
                version = version_raw if isinstance(version_raw, str) else None
                self._spec_versions[spec_file.spec_id] = version

                info = spec.get("info", {}) if isinstance(spec, dict) else {}
                title = info.get("title") if isinstance(info, dict) else None
                version = info.get("version") if isinstance(info, dict) else None
                description = info.get("description") if isinstance(info, dict) else None

                if is_valid:
                    spec_operations = self._extract_operations(spec_file.spec_id, spec)
                    spec_schemas = self._extract_schemas(spec_file.spec_id, spec)
                else:
                    spec_operations = []
                    spec_schemas = []

                operations.extend(spec_operations)
                schemas.extend(spec_schemas)

                self._spec_meta.append(
                    SpecMeta(
                        spec_id=spec_file.spec_id,
                        title=title,
                        version=version,
                        description=description,
                        file_path=spec_file.relative_path,
                        operation_count=len(spec_operations),
                        schema_count=len(spec_schemas),
                        is_valid=is_valid,
                        validation_error=validation_error,
                    )
                )

            self._spec_meta.sort(key=lambda item: item.spec_id)
            self._index.add_operations(operations)
            self._index.add_schemas(schemas)
            if self._semantic_enabled:
                rows = [(op.op_key, _operation_text(op)) for op in operations]
                embeddings = self._semantic.build(rows)
                if embeddings:
                    self._index.add_operation_embeddings(embeddings)
            self._write_cache_meta()

    def get_catalog(self) -> dict[str, Any]:
        with self._lock:
            return render_catalog(self._spec_meta)

    def catalog_search(self, query: str, audience: str | None = None) -> dict[str, Any]:
        with self._lock:
            matches = self._search_operations(query=query)
            return {
                "query": query,
                "audience": audience or "external",
                "matches": matches,
            }

    def search_operations(self, query: str, spec_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return self._search_operations(query=query, spec_id=spec_id)

    def search_schemas(self, query: str, spec_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return self._index.search_schemas(query=query, spec_id=spec_id)

    def _search_operations(self, query: str, spec_id: str | None = None, limit: int = 25) -> list[dict[str, Any]]:
        limit = _safe_limit(limit)
        fts_matches = self._index.search_operations(query=query, spec_id=spec_id, limit=limit)
        if not self._semantic_enabled:
            return fts_matches

        semantic_ids = self._semantic.search(query, top_k=max(limit * 2, 50))
        if not semantic_ids:
            return fts_matches

        fts_ids = [match["endpointId"] for match in fts_matches]
        merged_ids = _rrf_merge(fts_ids, semantic_ids, limit=limit)
        fts_map = {match["endpointId"]: match for match in fts_matches}

        results: list[dict[str, Any]] = []
        for endpoint_id in merged_ids:
            match = fts_map.get(endpoint_id)
            if match is None:
                match = self._index.get_operation_match_by_id(endpoint_id)
            if match is None:
                continue
            if spec_id and match["specId"] != spec_id:
                continue
            results.append(match)
            if len(results) >= limit:
                break

        return results

    def get_operation_by_operation_id(self, spec_id: str, operation_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._index.get_operation_by_operation_id(spec_id, operation_id)
            if not record:
                return {}
            return render_operation(
                Operation(
                    spec_id=record["specId"],
                    operation_id=record["operationId"],
                    method=record["method"],
                    path=record["path"],
                    summary=record["summary"],
                    description=record["description"],
                    tags=record["tags"],
                    operation=record["operation"],
                )
            )

    def get_operation_by_path_method(self, spec_id: str, path: str, method: str) -> dict[str, Any]:
        with self._lock:
            record = self._index.get_operation_by_path_method(spec_id, path, method)
            if not record:
                return {}
            return render_operation(
                Operation(
                    spec_id=record["specId"],
                    operation_id=record["operationId"],
                    method=record["method"],
                    path=record["path"],
                    summary=record["summary"],
                    description=record["description"],
                    tags=record["tags"],
                    operation=record["operation"],
                )
            )

    def get_schema(self, spec_id: str, schema_name: str) -> dict[str, Any]:
        with self._lock:
            record = self._index.get_schema(spec_id, schema_name)
            if not record:
                return {}
            return render_schema(
                Schema(
                    spec_id=record["specId"],
                    schema_name=record["schemaName"],
                    description=record["description"],
                    schema=record["schema"],
                )
            )

    def endpoint_get(self, endpoint_id: str, full: bool = True) -> dict[str, Any]:
        with self._lock:
            record = self._index.get_operation_by_endpoint_id(endpoint_id)
            if not record:
                return {}
            operation = Operation(
                spec_id=record["specId"],
                operation_id=record["operationId"],
                method=record["method"],
                path=record["path"],
                summary=record["summary"],
                description=record["description"],
                tags=record["tags"],
                operation=record["operation"],
            )
            spec = self._get_spec(operation.spec_id) if full else None
            return render_contract(operation, spec, full=full)

    def payload_generate(
        self, endpoint_id: str, provided_fields: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with self._lock:
            record = self._index.get_operation_by_endpoint_id(endpoint_id)
            if not record:
                return {}
            spec = self._get_spec(record["specId"]) if record else None
            payload = build_payload(endpoint_id, record, provided_fields or {}, spec)
            return payload

    def payload_validate(self, endpoint_id: str, request: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            record = self._index.get_operation_by_endpoint_id(endpoint_id)
            if not record:
                return {"ok": False, "errors": [{"path": "", "message": "Unknown endpointId"}]}
            spec_version = self._spec_versions.get(record["specId"])
            spec = self._get_spec(record["specId"]) if record else None
            return validate_payload(record, request, spec_version=spec_version, spec=spec)

    def snippet_generate(self, request: dict[str, Any], lang: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            languages = lang if lang is not None else ["curl", "python", "ts"]
            return {"snippets": generate_snippets(request, languages)}

    def execute_request(
        self,
        endpoint_id: str,
        request: dict[str, Any],
        auth_token: str | None = None,
    ) -> dict[str, Any]:
        if os.getenv("OPENAPI_EXECUTION", "0") != "1":
            return {
                "ok": False,
                "error": "Execution disabled. Set OPENAPI_EXECUTION=1 to enable.",
            }

        with self._lock:
            record = self._index.get_operation_by_endpoint_id(endpoint_id)
            if not record:
                return {"ok": False, "error": "Unknown endpointId"}
            spec = self._get_spec(record["specId"]) if record else None

        base_url = _resolve_base_url(spec)
        if not base_url:
            return {"ok": False, "error": "No base URL found in spec servers[] or OPENAPI_BASE_URL"}

        normalized = _normalize_request_payload(request)
        if normalized is None:
            return {"ok": False, "error": "Invalid request payload"}

        url = _build_url(base_url, normalized)
        headers = dict(normalized.get("parameters", {}).get("header", {}))
        _apply_auth(headers, auth_token)
        if normalized.get("contentType") and normalized.get("body") is not None:
            headers.setdefault("Content-Type", normalized["contentType"])

        params = normalized.get("parameters", {}).get("query", {})
        body = normalized.get("body")
        method = normalized.get("method", "get").lower()

        start = time.perf_counter()
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(
                    method,
                    url,
                    headers=headers,
                    params=params if params else None,
                    json=body if _send_as_json(normalized) else None,
                    data=body if _send_as_form(normalized) else None,
                )
        except httpx.HTTPError as exc:
            return {"ok": False, "error": str(exc)}

        elapsed_ms = int((time.perf_counter() - start) * 1000)
        parsed_body = _parse_response_body(response)
        return {
            "ok": True,
            "status": response.status_code,
            "time": f"{elapsed_ms}ms",
            "body": parsed_body,
        }

    def semantic_enabled(self) -> bool:
        return self._semantic_enabled

    def _load_spec(self, path: str, raw: dict[str, Any]) -> dict[str, Any]:
        if self._deref_mode == "full":
            try:
                return dereference_spec(path)
            except DerefError:
                # Fallback to raw load if deref fails; keeps service usable while surfacing tooling issues.
                return raw

        return raw

    def _extract_operations(self, spec_id: str, spec: dict[str, Any]) -> list[Operation]:
        paths = spec.get("paths") if isinstance(spec, dict) else None
        if not isinstance(paths, dict):
            return []

        operations: list[Operation] = []
        for path, path_item in sorted(paths.items()):
            if not isinstance(path_item, dict):
                continue
            path_parameters = path_item.get("parameters")
            for method in list_http_methods():
                operation = path_item.get(method)
                if not isinstance(operation, dict):
                    continue
                merged_parameters = self._merge_parameters(path_parameters, operation.get("parameters"))
                operation_payload = dict(operation)
                if merged_parameters:
                    operation_payload["parameters"] = merged_parameters
                operation_id = operation.get("operationId")
                if not isinstance(operation_id, str):
                    operation_id = None
                summary = operation.get("summary")
                description = operation.get("description")
                tags = operation.get("tags")
                tags_list = sorted([tag for tag in tags if isinstance(tag, str)]) if tags else []
                operations.append(
                    Operation(
                        spec_id=spec_id,
                        operation_id=operation_id,
                        method=method,
                        path=path,
                        summary=summary,
                        description=description,
                        tags=tags_list,
                        operation=operation_payload,
                    )
                )
        operations.sort(key=lambda op: (op.path, op.method, op.operation_id or ""))
        return operations

    def _extract_schemas(self, spec_id: str, spec: dict[str, Any]) -> list[Schema]:
        components = spec.get("components") if isinstance(spec, dict) else None
        if not isinstance(components, dict):
            return []
        schemas_block = components.get("schemas")
        if not isinstance(schemas_block, dict):
            return []
        schemas: list[Schema] = []
        for name, schema in sorted(schemas_block.items()):
            if not isinstance(schema, dict):
                continue
            description = schema.get("description")
            schemas.append(
                Schema(
                    spec_id=spec_id,
                    schema_name=name,
                    description=description,
                    schema=schema,
                )
            )
        return schemas

    def _merge_parameters(self, path_params: Any, op_params: Any) -> list[dict[str, Any]]:
        merged: dict[tuple[str, str], dict[str, Any]] = {}

        def ingest(params: Any) -> None:
            if not isinstance(params, list):
                return
            for param in params:
                if not isinstance(param, dict):
                    continue
                name = param.get("name")
                location = param.get("in")
                if not isinstance(name, str) or not isinstance(location, str):
                    continue
                merged[(name, location)] = param

        ingest(path_params)
        ingest(op_params)

        ordered = sorted(merged.items(), key=lambda item: (item[0][1], item[0][0]))
        return [item[1] for item in ordered]

    def _resolve_cache_meta_path(self) -> Path | None:
        if self.index_path == ":memory:":
            return None
        path = Path(self.index_path)
        if path.parent and not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
        return path.with_suffix(path.suffix + ".meta.json")

    def _load_cache(self) -> bool:
        if self._cache_meta_path is None:
            return False
        if not self._cache_meta_path.exists():
            return False
        if not self._index.is_ready():
            return False

        try:
            meta = json.loads(self._cache_meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False

        cached_fingerprints = meta.get("fingerprints")
        if not isinstance(cached_fingerprints, list):
            return False

        current = fingerprint_spec_files(self.spec_dir)
        if not _fingerprints_match(current, cached_fingerprints):
            return False

        spec_meta = meta.get("specMeta")
        if not isinstance(spec_meta, list):
            return False

        spec_meta_entries: list[SpecMeta] = []
        for item in spec_meta:
            if not isinstance(item, dict):
                continue
            file_path_raw = item.get("filePath")
            file_path = file_path_raw if isinstance(file_path_raw, str) else ""
            spec_meta_entries.append(
                SpecMeta(
                    spec_id=item["specId"],
                    title=item.get("title"),
                    version=item.get("version"),
                    description=item.get("description"),
                    file_path=file_path,
                    operation_count=item.get("operationCount", 0),
                    schema_count=item.get("schemaCount", 0),
                    is_valid=bool(item.get("isValid", True)),
                    validation_error=item.get("validationError"),
                )
            )
        self._spec_meta = spec_meta_entries

        spec_versions = meta.get("specVersions")
        if isinstance(spec_versions, dict):
            self._spec_versions = {
                key: value if isinstance(value, str) else None for key, value in spec_versions.items()
            }

        self._specs.clear()
        self._spec_paths.clear()
        for item in cached_fingerprints:
            if not isinstance(item, dict):
                continue
            spec_id = item.get("specId")
            rel = item.get("relativePath")
            if not isinstance(spec_id, str) or not isinstance(rel, str):
                continue
            self._spec_paths[spec_id] = os.path.join(self.spec_dir, rel)

        self._spec_meta.sort(key=lambda entry: entry.spec_id)
        return True

    def _write_cache_meta(self) -> None:
        if self._cache_meta_path is None:
            return

        fingerprints = []
        for spec_id, path in self._spec_paths.items():
            try:
                stat = os.stat(path)
            except OSError:
                continue
            rel = os.path.relpath(path, self.spec_dir)
            fingerprints.append(
                {
                    "specId": spec_id,
                    "relativePath": rel,
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            )

        meta = {
            "version": 1,
            "specDir": self.spec_dir,
            "fingerprints": sorted(fingerprints, key=lambda item: str(item.get("relativePath", ""))),
            "specMeta": [
                {
                    "specId": spec.spec_id,
                    "title": spec.title,
                    "version": spec.version,
                    "description": spec.description,
                    "filePath": spec.file_path,
                    "operationCount": spec.operation_count,
                    "schemaCount": spec.schema_count,
                    "isValid": spec.is_valid,
                    "validationError": spec.validation_error,
                }
                for spec in self._spec_meta
            ],
            "specVersions": self._spec_versions,
        }

        try:
            self._cache_meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
        except OSError:
            return

    def _get_spec(self, spec_id: str) -> dict[str, Any] | None:
        cached = self._specs.get(spec_id)
        if cached is not None:
            return cached
        path = self._spec_paths.get(spec_id)
        if not path:
            return None
        from .ingest import load_raw_spec

        raw = load_raw_spec(path)
        spec = self._load_spec(path, raw)
        self._specs[spec_id] = spec
        version_raw = spec.get("openapi") if isinstance(spec, dict) else None
        self._spec_versions[spec_id] = version_raw if isinstance(version_raw, str) else None
        return spec

    def _validate_spec(self, raw: dict[str, Any]) -> tuple[bool, str | None]:
        try:
            validate(cast(Mapping[Hashable, Any], raw))
        except OpenAPIValidationError as exc:
            return False, _validation_error_message(exc)
        except Exception as exc:
            return False, _validation_error_message(exc)
        return True, None


def _fingerprints_match(current: list[Any], cached: list[Any]) -> bool:
    if len(current) != len(cached):
        return False

    current_sorted = sorted(current, key=lambda item: item.relative_path)
    cached_sorted = sorted(
        [item for item in cached if isinstance(item, dict)], key=lambda item: item.get("relativePath", "")
    )

    for cur, cache in zip(current_sorted, cached_sorted):
        if cur.relative_path != cache.get("relativePath"):
            return False
        if cur.size != cache.get("size"):
            return False
        if cur.mtime != cache.get("mtime"):
            return False
    return True


def _validation_error_message(error: Exception) -> str:
    message = str(error).strip()
    return message if message else error.__class__.__name__


def _operation_text(operation: Operation) -> str:
    parts = [
        operation.operation_id or "",
        operation.summary or "",
        operation.description or "",
        operation.method,
        operation.path,
        " ".join(operation.tags),
    ]
    return " ".join(part for part in parts if part).strip()


def _rrf_merge(
    fts_ids: list[str],
    semantic_ids: list[str],
    limit: int,
    k: int = 60,
    weight_fts: float = 0.7,
    weight_sem: float = 0.3,
) -> list[str]:
    scores: dict[str, float] = {}
    for rank, endpoint_id in enumerate(fts_ids, start=1):
        scores[endpoint_id] = scores.get(endpoint_id, 0.0) + weight_fts / (k + rank)
    for rank, endpoint_id in enumerate(semantic_ids, start=1):
        scores[endpoint_id] = scores.get(endpoint_id, 0.0) + weight_sem / (k + rank)
    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return [item[0] for item in ranked[:limit]]


def _safe_limit(value: int | None, default: int = 25) -> int:
    if value is None or value <= 0:
        return default
    return value


def _normalize_request_payload(request: dict[str, Any]) -> dict[str, Any] | None:
    if "request" in request and isinstance(request["request"], dict):
        return request["request"]
    if "method" in request and "path" in request:
        return request
    return None


def _resolve_base_url(spec: dict[str, Any] | None) -> str | None:
    override = os.getenv("OPENAPI_BASE_URL")
    if override:
        return override.rstrip("/")
    if not isinstance(spec, dict):
        return None
    servers = spec.get("servers")
    if not isinstance(servers, list) or not servers:
        return None
    first = servers[0]
    if not isinstance(first, dict):
        return None
    url = first.get("url")
    if not isinstance(url, str):
        return None
    variables = first.get("variables")
    if isinstance(variables, dict):
        for name, payload in variables.items():
            if not isinstance(payload, dict):
                continue
            default = payload.get("default")
            if default is not None:
                url = url.replace(f"{{{name}}}", str(default))
    return url.rstrip("/")


def _build_url(base_url: str, request: dict[str, Any]) -> str:
    path = request.get("path", "")
    path_params = request.get("parameters", {}).get("path", {})
    for key, value in path_params.items():
        path = path.replace(f"{{{key}}}", str(value))
    return f"{base_url}{path}"


def _apply_auth(headers: dict[str, Any], auth_token: str | None) -> None:
    token = auth_token or os.getenv("API_KEY") or os.getenv("API_TOKEN")
    if not token:
        return
    value = token if " " in token else f"Bearer {token}"
    headers["Authorization"] = value


def _send_as_form(request: dict[str, Any]) -> bool:
    content_type = request.get("contentType") or ""
    return "application/x-www-form-urlencoded" in content_type


def _send_as_json(request: dict[str, Any]) -> bool:
    return not _send_as_form(request)


def _parse_response_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text
