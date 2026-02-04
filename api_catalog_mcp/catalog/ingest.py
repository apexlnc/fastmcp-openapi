from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Iterable

import yaml


@dataclass(frozen=True)
class SpecFile:
    path: str
    relative_path: str
    raw: dict[str, Any]
    spec_id: str


@dataclass(frozen=True)
class SpecFingerprint:
    path: str
    relative_path: str
    size: int
    mtime: float


def discover_spec_files(spec_dir: str) -> list[str]:
    paths: list[str] = []
    for root, _, files in os.walk(spec_dir):
        for name in files:
            lower = name.lower()
            if lower.endswith(".json") or lower.endswith(".yaml") or lower.endswith(".yml"):
                paths.append(os.path.join(root, name))
    paths.sort()
    return paths


def fingerprint_spec_files(spec_dir: str) -> list[SpecFingerprint]:
    spec_dir = os.path.abspath(spec_dir)
    paths = discover_spec_files(spec_dir)
    fingerprints: list[SpecFingerprint] = []
    for path in paths:
        stat = os.stat(path)
        rel = os.path.relpath(path, spec_dir)
        fingerprints.append(
            SpecFingerprint(
                path=path,
                relative_path=rel,
                size=stat.st_size,
                mtime=stat.st_mtime,
            )
        )
    return fingerprints


def load_raw_spec(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        if path.lower().endswith(".json"):
            return json.load(handle)
        return yaml.safe_load(handle)


def _default_spec_id(path: str) -> str:
    base = os.path.basename(path)
    name, _ = os.path.splitext(base)
    return name


def _spec_id_override(raw: dict[str, Any]) -> str | None:
    info = raw.get("info") if isinstance(raw, dict) else None
    if isinstance(info, dict):
        override = info.get("x-spec-id")
        if isinstance(override, str) and override.strip():
            return override.strip()
    return None


def _ensure_unique(base_id: str, used: set[str]) -> str:
    if base_id not in used:
        return base_id
    suffix = 2
    while f"{base_id}-{suffix}" in used:
        suffix += 1
    return f"{base_id}-{suffix}"


def build_spec_files(spec_dir: str) -> list[SpecFile]:
    spec_dir = os.path.abspath(spec_dir)
    files = discover_spec_files(spec_dir)
    used_ids: set[str] = set()
    specs: list[SpecFile] = []
    for path in files:
        raw = load_raw_spec(path)
        override = _spec_id_override(raw)
        base_id = override or _default_spec_id(path)
        spec_id = _ensure_unique(base_id, used_ids)
        used_ids.add(spec_id)
        rel = os.path.relpath(path, spec_dir)
        specs.append(SpecFile(path=path, relative_path=rel, raw=raw, spec_id=spec_id))
    return specs


def list_http_methods() -> Iterable[str]:
    return (
        "get",
        "post",
        "put",
        "patch",
        "delete",
        "options",
        "head",
        "trace",
    )
