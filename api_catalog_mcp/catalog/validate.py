from __future__ import annotations

from typing import Any

from openapi_schema_validator import OAS30Validator, OAS31Validator

from .payloads import _extract_request_body


def validate_payload(
    record: dict[str, Any],
    request: dict[str, Any],
    spec_version: str | None,
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    operation = record.get("operation")
    request_body = _extract_request_body(operation, spec)
    if not request_body:
        return {"ok": True, "errors": []}

    schema = request_body.get("schema")
    if not isinstance(schema, dict):
        return {"ok": True, "errors": []}

    body = _extract_body(request)
    if body is None:
        if request_body.get("required", False):
            return {
                "ok": False,
                "errors": [{"path": "body", "message": "Request body is required"}],
            }
        return {"ok": True, "errors": []}

    validator_cls = OAS31Validator if _is_oas31(spec_version) else OAS30Validator
    sanitized = _sanitize_for_validation(schema)
    validator = validator_cls(sanitized)
    errors = [
        {"path": _format_error_path(error.path), "message": error.message}
        for error in validator.iter_errors(body)
    ]
    errors.sort(key=lambda item: (item["path"], item["message"]))
    return {"ok": not errors, "errors": errors}


def _extract_body(request: dict[str, Any]) -> Any:
    if "request" in request and isinstance(request["request"], dict):
        return request["request"].get("body")
    if "body" in request:
        return request.get("body")
    return request


def _is_oas31(version: str | None) -> bool:
    return bool(version and version.startswith("3.1"))


def _format_error_path(path: Any) -> str:
    if not path:
        return ""
    return "/" + "/".join(str(item) for item in path)


def _sanitize_for_validation(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, val in value.items():
            if key == "discriminator":
                continue
            sanitized[key] = _sanitize_for_validation(val)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_for_validation(item) for item in value]
    return value
