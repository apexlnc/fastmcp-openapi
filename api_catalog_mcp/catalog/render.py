from __future__ import annotations

from typing import Any

from .model import Operation, Schema, SpecMeta
from .resolve import deep_resolve_refs


def _sorted_dict(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _sorted_dict(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_sorted_dict(item) for item in value]
    return value


def render_catalog(specs: list[SpecMeta]) -> dict[str, Any]:
    return {
        "specs": [
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
            for spec in specs
        ]
    }


def render_operation(operation: Operation) -> dict[str, Any]:
    return {
        "specId": operation.spec_id,
        "operationId": operation.operation_id,
        "method": operation.method,
        "path": operation.path,
        "summary": operation.summary,
        "description": operation.description,
        "tags": list(operation.tags),
        "operation": _sorted_dict(operation.operation),
    }


def render_schema(schema: Schema) -> dict[str, Any]:
    return {
        "specId": schema.spec_id,
        "schemaName": schema.schema_name,
        "description": schema.description,
        "schema": _sorted_dict(schema.schema),
    }


def render_contract(
    operation: Operation,
    spec: dict[str, Any] | None = None,
    full: bool = True,
) -> dict[str, Any]:
    op: dict[str, Any] = operation.operation if isinstance(operation.operation, dict) else {}
    params_raw_any = op.get("parameters")
    params_raw: list[Any] = params_raw_any if isinstance(params_raw_any, list) else []
    parameters: list[dict[str, Any]] = []
    for param in params_raw:
        if not isinstance(param, dict):
            continue
        parameters.append(
            {
                "name": param.get("name"),
                "in": param.get("in"),
                "required": bool(param.get("required", False)),
                "description": param.get("description"),
                "schema": _sorted_dict(param.get("schema")) if isinstance(param.get("schema"), dict) else None,
            }
        )
    parameters.sort(key=lambda item: ((item.get("in") or ""), (item.get("name") or "")))

    request_body = op.get("requestBody") if isinstance(op.get("requestBody"), dict) else None
    responses = op.get("responses") if isinstance(op.get("responses"), dict) else None
    if full:
        if request_body:
            request_body = deep_resolve_refs(request_body, spec)
        if responses:
            responses = deep_resolve_refs(responses, spec)
    else:
        request_body = None
        responses = None

    return {
        "endpointId": operation.op_key,
        "specId": operation.spec_id,
        "operationId": operation.operation_id,
        "method": operation.method,
        "path": operation.path,
        "summary": operation.summary,
        "description": operation.description,
        "tags": list(operation.tags),
        "parameters": parameters,
        "requestBody": _sorted_dict(request_body) if request_body else None,
        "responses": _sorted_dict(responses) if responses else None,
    }
