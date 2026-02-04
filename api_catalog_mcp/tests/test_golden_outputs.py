from __future__ import annotations

import json
from pathlib import Path

from api_catalog_mcp.catalog.engine import CatalogEngine

ROOT = Path(__file__).resolve().parent
SPECS = ROOT / "specs"
GOLDEN = ROOT / "golden"


def _read_golden(name: str) -> dict:
    data = (GOLDEN / name).read_text(encoding="utf-8")
    return json.loads(data)


def _assert_golden(name: str, value: dict) -> None:
    expected = _read_golden(name)
    assert value == expected


def test_golden_outputs() -> None:
    engine = CatalogEngine(spec_dir=str(SPECS))
    engine.refresh()

    _assert_golden("get_api_catalog.json", engine.get_catalog())

    _assert_golden("catalog_search.json", engine.catalog_search("pets", audience="external"))

    _assert_golden("endpoint_get.json", engine.endpoint_get("pets:createPet"))

    payload = engine.payload_generate("pets:createPet", provided_fields={})
    _assert_golden("payload_generate.json", payload)

    validation = engine.payload_validate("pets:createPet", payload["request"])
    _assert_golden("payload_validate.json", validation)

    snippets = engine.snippet_generate(payload["request"], ["curl", "python", "ts"])
    _assert_golden("snippet_generate.json", snippets)
