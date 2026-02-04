from __future__ import annotations

from typing import Any
import hashlib

from faker import Faker

from .resolve import deep_resolve_refs

MAX_DEPTH = 3


def build_payload(
    endpoint_id: str,
    record: dict[str, Any],
    provided_fields: dict[str, Any],
    spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    operation = record["operation"]
    parameters = operation.get("parameters", []) if isinstance(operation, dict) else []
    provided = _normalize_provided_fields(provided_fields)

    request_body = _extract_request_body(operation, spec)
    body_schema = request_body.get("schema") if request_body else None
    content_type = request_body.get("contentType") if request_body else None
    body_required = request_body.get("required", False) if request_body else False

    param_payload, param_unknowns = _build_parameters(parameters, provided)
    body_payload, body_unknowns = _build_body(body_schema, provided.get("body"))

    unknowns = sorted(set(param_unknowns + body_unknowns))
    if body_required and (body_payload is None or body_payload == {}):
        unknowns.append("body")
        unknowns = sorted(set(unknowns))

    request = {
        "method": record["method"],
        "path": record["path"],
        "contentType": content_type,
        "parameters": param_payload,
        "body": body_payload,
    }

    return {
        "endpointId": endpoint_id,
        "request": request,
        "unknownRequiredFields": unknowns,
    }


def _normalize_provided_fields(provided_fields: dict[str, Any]) -> dict[str, Any]:
    if any(key in provided_fields for key in ("path", "query", "header", "body", "parameters")):
        parameters = provided_fields.get("parameters")
        if isinstance(parameters, dict):
            return {
                "path": parameters.get("path", provided_fields.get("path", {})),
                "query": parameters.get("query", provided_fields.get("query", {})),
                "header": parameters.get("header", provided_fields.get("header", {})),
                "body": provided_fields.get("body", {}),
            }
        return {
            "path": provided_fields.get("path", {}),
            "query": provided_fields.get("query", {}),
            "header": provided_fields.get("header", {}),
            "body": provided_fields.get("body", {}),
        }

    return {"path": {}, "query": {}, "header": {}, "body": provided_fields}


def _extract_request_body(
    operation: dict[str, Any] | None, spec: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    if not isinstance(operation, dict):
        return None
    request_body = operation.get("requestBody")
    if not isinstance(request_body, dict):
        return None
    content = request_body.get("content")
    if not isinstance(content, dict) or not content:
        return None

    content_type = "application/json" if "application/json" in content else sorted(content.keys())[0]
    media = content.get(content_type)
    schema = None
    if isinstance(media, dict):
        schema = media.get("schema") if isinstance(media.get("schema"), dict) else None
        if schema is not None:
            schema = deep_resolve_refs(schema, spec)
    return {
        "required": bool(request_body.get("required", False)),
        "contentType": content_type,
        "schema": schema,
    }


def _build_parameters(
    parameters: list[Any], provided: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    buckets: dict[str, dict[str, Any]] = {"path": {}, "query": {}, "header": {}}
    unknowns: list[str] = []

    for param in parameters:
        if not isinstance(param, dict):
            continue
        name = param.get("name")
        location = param.get("in")
        if not isinstance(name, str) or not isinstance(location, str):
            continue
        if location not in buckets:
            continue

        required = bool(param.get("required", False))
        provided_value = provided.get(location, {}).get(name)
        has_provided = provided_value is not None

        if not required and not has_provided:
            continue

        if has_provided:
            buckets[location][name] = provided_value
        else:
            placeholder = _placeholder_for_schema(param.get("schema"), name)
            buckets[location][name] = placeholder
            unknowns.append(f"params.{location}.{name}")

    return buckets, unknowns


def _build_body(schema: dict[str, Any] | None, provided: Any) -> tuple[Any, list[str]]:
    unknowns: list[str] = []
    if schema is None:
        return None, unknowns

    value = _generate_from_schema(schema, provided, "body", unknowns, depth=0, field_name="body")
    return value, unknowns


def _generate_from_schema(
    schema: dict[str, Any],
    provided: Any,
    path: str,
    unknowns: list[str],
    depth: int,
    field_name: str | None = None,
) -> Any:
    if depth > MAX_DEPTH:
        return "<recursion_limit>"

    selected_schema, discriminator = _select_union_schema(schema, provided)
    schema = _normalize_schema(selected_schema)

    if provided is not None:
        if isinstance(provided, dict) and schema.get("type") == "object":
            return _generate_object(schema, provided, path, unknowns, discriminator, depth)
        if isinstance(provided, list) and schema.get("type") == "array":
            items_raw = schema.get("items")
            items_schema: dict[str, Any] = items_raw if isinstance(items_raw, dict) else {}
            return [
                _generate_from_schema(
                    items_schema,
                    item,
                    f"{path}[{idx}]",
                    unknowns,
                    depth=depth + 1,
                    field_name=field_name,
                )
                for idx, item in enumerate(provided)
            ]
        return provided

    if "const" in schema:
        return schema["const"]

    if "default" in schema:
        return schema["default"]

    if "enum" in schema and isinstance(schema["enum"], list) and schema["enum"]:
        return schema["enum"][0]

    schema_type = schema.get("type")
    if schema_type == "object":
        return _generate_object(schema, {}, path, unknowns, discriminator, depth)
    if schema_type == "array":
        items_raw = schema.get("items")
        array_items_schema: dict[str, Any] = items_raw if isinstance(items_raw, dict) else {}
        item_value = _generate_from_schema(
            array_items_schema,
            None,
            f"{path}[0]",
            unknowns,
            depth=depth + 1,
            field_name=field_name,
        )
        return [item_value]
    guess = _guess_value(field_name or path, schema)
    if guess is not None:
        return guess
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return False
    return "<string>"


def _generate_object(
    schema: dict[str, Any],
    provided: dict[str, Any],
    path: str,
    unknowns: list[str],
    discriminator: dict[str, Any] | None = None,
    depth: int = 0,
) -> dict[str, Any]:
    properties_raw = schema.get("properties")
    properties: dict[str, Any] = properties_raw if isinstance(properties_raw, dict) else {}
    required_raw = schema.get("required")
    required: list[str] = (
        [item for item in required_raw if isinstance(item, str)] if isinstance(required_raw, list) else []
    )
    required_set = set(required)
    output: dict[str, Any] = {}
    discriminator_name = discriminator.get("name") if discriminator else None
    discriminator_value = discriminator.get("value") if discriminator else None

    for prop_name in sorted(properties.keys()):
        prop_schema = properties[prop_name]
        if not isinstance(prop_schema, dict):
            continue
        prop_provided = provided.get(prop_name)
        is_required = prop_name in required_set

        if is_required and prop_provided is None:
            unknowns.append(f"{path}.{prop_name}")

        if is_required or prop_provided is not None:
            output[prop_name] = _generate_from_schema(
                prop_schema,
                prop_provided,
                f"{path}.{prop_name}",
                unknowns,
                depth=depth + 1,
                field_name=prop_name,
            )

    if discriminator_name and discriminator_name not in output:
        if discriminator_name in properties:
            prop_schema = properties[discriminator_name]
            if isinstance(prop_schema, dict):
                output[discriminator_name] = (
                    discriminator_value
                    if discriminator_value is not None
                    else _placeholder_for_schema(prop_schema)
                )
        elif discriminator_value is not None:
            output[discriminator_name] = discriminator_value

    return output


def _normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {}

    if "allOf" in schema and isinstance(schema["allOf"], list):
        merged: dict[str, Any] = {}
        properties: dict[str, Any] = {}
        required: set[str] = set()
        for sub in schema["allOf"]:
            if not isinstance(sub, dict):
                continue
            sub_schema = _normalize_schema(sub)
            sub_props = sub_schema.get("properties")
            if isinstance(sub_props, dict):
                for key, value in sub_props.items():
                    properties[key] = value
            sub_required = sub_schema.get("required")
            if isinstance(sub_required, list):
                required.update([item for item in sub_required if isinstance(item, str)])
            for key, value in sub_schema.items():
                if key in ("properties", "required"):
                    continue
                if key not in merged:
                    merged[key] = value
        if properties:
            merged["properties"] = properties
            merged["type"] = merged.get("type", "object")
        if required:
            merged["required"] = sorted(required)
        schema = {**schema, **merged}

    if "type" not in schema:
        if isinstance(schema.get("properties"), dict):
            schema["type"] = "object"
        elif isinstance(schema.get("items"), dict):
            schema["type"] = "array"

    return schema


def _placeholder_for_schema(schema: Any, field_name: str | None = None) -> Any:
    if not isinstance(schema, dict):
        return "<string>"
    selected_schema, _ = _select_union_schema(schema, None)
    schema = _normalize_schema(selected_schema)
    if "const" in schema:
        return schema["const"]
    guess = _guess_value(field_name or "", schema)
    if guess is not None:
        return guess
    schema_type = schema.get("type")
    if schema_type == "integer":
        return 0
    if schema_type == "number":
        return 0.0
    if schema_type == "boolean":
        return False
    if schema_type == "array":
        items_schema = schema.get("items") if isinstance(schema.get("items"), dict) else {}
        return [_placeholder_for_schema(items_schema, field_name)]
    if schema_type == "object":
        return {}
    return "<string>"


def _select_union_schema(
    schema: dict[str, Any] | None, provided: Any
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not isinstance(schema, dict):
        return {}, None

    for key in ("oneOf", "anyOf"):
        options = schema.get(key)
        if not isinstance(options, list) or not options:
            continue

        discriminator = schema.get("discriminator") if isinstance(schema.get("discriminator"), dict) else None
        if discriminator:
            prop_name = discriminator.get("propertyName")
            mapping = discriminator.get("mapping") if isinstance(discriminator.get("mapping"), dict) else None
            if isinstance(prop_name, str):
                provided_value = None
                if isinstance(provided, dict):
                    provided_value = provided.get(prop_name)
                if provided_value is not None:
                    selected = _select_by_discriminator(options, prop_name, provided_value, mapping)
                    if selected:
                        return selected, {"name": prop_name, "value": provided_value}
                if mapping:
                    mapping_key = sorted(mapping.keys())[0]
                    selected = _select_by_discriminator(options, prop_name, mapping_key, mapping)
                    if selected:
                        return selected, {"name": prop_name, "value": mapping_key}
                    return options[0], {"name": prop_name, "value": mapping_key}
                inferred = _infer_discriminator_option(options, prop_name)
                if inferred:
                    return inferred["schema"], {"name": prop_name, "value": inferred["value"]}

        first = options[0]
        if isinstance(first, dict):
            return first, None

    return schema, None


def _select_by_discriminator(
    options: list[Any],
    prop_name: str,
    value: Any,
    mapping: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if mapping and value in mapping:
        target = mapping[value]
        if isinstance(target, dict):
            return target
        if isinstance(target, str):
            for option in options:
                if not isinstance(option, dict):
                    continue
                if option.get("$ref") == target or option.get("$id") == target or option.get("title") == target:
                    return option

    for option in options:
        if not isinstance(option, dict):
            continue
        if _option_matches_discriminator(option, prop_name, value):
            return option

    return None


def _infer_discriminator_option(
    options: list[Any], prop_name: str
) -> dict[str, Any] | None:
    for option in options:
        if not isinstance(option, dict):
            continue
        value = _infer_discriminator_value(option, prop_name)
        if value is not None:
            return {"schema": option, "value": value}
    return None


def _option_matches_discriminator(option: dict[str, Any], prop_name: str, value: Any) -> bool:
    schema = _normalize_schema(option)
    properties_raw = schema.get("properties")
    properties: dict[str, Any] = properties_raw if isinstance(properties_raw, dict) else {}
    prop_schema = properties.get(prop_name)
    if not isinstance(prop_schema, dict):
        return False
    if "const" in prop_schema:
        return prop_schema["const"] == value
    enum = prop_schema.get("enum")
    if isinstance(enum, list) and value in enum:
        return True
    default = prop_schema.get("default")
    if default == value:
        return True
    return False


def _infer_discriminator_value(option: dict[str, Any], prop_name: str) -> Any | None:
    schema = _normalize_schema(option)
    properties_raw = schema.get("properties")
    properties: dict[str, Any] = properties_raw if isinstance(properties_raw, dict) else {}
    prop_schema = properties.get(prop_name)
    if not isinstance(prop_schema, dict):
        return None
    if "const" in prop_schema:
        return prop_schema["const"]
    enum = prop_schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    if "default" in prop_schema:
        return prop_schema["default"]
    return None


def _guess_value(field_name: str, schema: dict[str, Any]) -> Any | None:
    schema_type = schema.get("type")
    schema_format = schema.get("format")
    name = (field_name or "").lower()

    if schema_type == "string":
        faker = _faker_for_key(field_name)
        if schema_format == "email" or "email" in name:
            return faker.email()
        if schema_format in {"uuid", "uuid4"} or "uuid" in name:
            return faker.uuid4()
        if "name" in name:
            if "first" in name:
                return faker.first_name()
            if "last" in name:
                return faker.last_name()
            return faker.name()
        if "phone" in name:
            return faker.phone_number()
        if "zip" in name or "postal" in name:
            return faker.postcode()
        if "city" in name:
            return faker.city()
        if "country" in name:
            return faker.country_code()
        if "address" in name:
            return faker.street_address()
        if "url" in name or schema_format in {"uri", "url"}:
            return faker.url()
        if "date" in name or schema_format == "date":
            return faker.date()
        if "time" in name or schema_format in {"date-time", "datetime"}:
            return faker.iso8601()
        if "currency" in name:
            return faker.currency_code()
        if name.endswith("id") or name.endswith("_id"):
            return faker.uuid4()
        return faker.word()

    if schema_type == "integer":
        if "age" in name:
            return 30
        if "count" in name:
            return 1
        if "limit" in name:
            return 10
        if "lives" in name:
            return 9
        if name.endswith("id") or name.endswith("_id"):
            return 1
        return 0

    if schema_type == "number":
        if any(key in name for key in ("amount", "price", "total", "cost")):
            return 100.0
        return 0.0

    if schema_type == "boolean":
        return False

    return None


def _faker_for_key(key: str) -> Faker:
    faker = Faker()
    seed = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16)
    faker.seed_instance(seed)
    return faker
