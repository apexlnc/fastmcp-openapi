from __future__ import annotations

from typing import Any


def deep_resolve_refs(value: Any, spec: dict[str, Any] | None, seen: set[str] | None = None) -> Any:
    if spec is None:
        return value
    if seen is None:
        seen = set()

    if isinstance(value, dict):
        ref = value.get("$ref")
        if isinstance(ref, str):
            if ref in seen:
                return {}
            target = _resolve_ref_pointer(spec, ref)
            if target is None:
                return value
            seen.add(ref)
            resolved = deep_resolve_refs(target, spec, seen)
            seen.remove(ref)
            return resolved

        return {key: deep_resolve_refs(val, spec, seen) for key, val in value.items()}

    if isinstance(value, list):
        return [deep_resolve_refs(item, spec, seen) for item in value]

    return value


def _resolve_ref_pointer(spec: dict[str, Any], ref: str) -> Any | None:
    if not ref.startswith("#/"):
        return None
    pointer = ref[2:]
    if not pointer:
        return spec

    current: Any = spec
    for part in pointer.split("/"):
        if not isinstance(current, dict):
            return None
        part = part.replace("~1", "/").replace("~0", "~")
        current = current.get(part)
        if current is None:
            return None
    return current
