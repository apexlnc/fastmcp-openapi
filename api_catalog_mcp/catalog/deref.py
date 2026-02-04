from __future__ import annotations

from typing import Any

try:
    from prance import ResolvingParser
except Exception:  # pragma: no cover - fallback when prance isn't installed
    ResolvingParser = None


class DerefError(RuntimeError):
    pass


def dereference_spec(path: str) -> dict[str, Any]:
    if ResolvingParser is None:
        raise DerefError("prance is not installed; cannot resolve $ref")
    try:
        parser = ResolvingParser(path, lazy=True, strict=False)
        parser.parse()
        spec = parser.specification
        return spec if isinstance(spec, dict) else {}
    except Exception as exc:  # pragma: no cover - pass-through
        raise DerefError(f"Failed to resolve spec at {path}: {exc}") from exc
