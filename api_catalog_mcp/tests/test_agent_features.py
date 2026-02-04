import os
from unittest.mock import MagicMock, patch

from api_catalog_mcp.catalog.engine import CatalogEngine
from api_catalog_mcp.catalog.index import _sanitize_fts_query
from api_catalog_mcp.catalog.payloads import MAX_DEPTH, _guess_value, build_payload

# --- Heuristic Payload Tests ---


def test_heuristic_guess_email():
    schema = {"type": "string", "format": "email"}
    # Deterministic check: hash("user_email") -> predictable seed
    val1 = _guess_value("user_email", schema)
    val2 = _guess_value("user_email", schema)
    assert val1 is not None
    assert val2 is not None
    assert "@" in val1
    assert val1 == val2  # Should be deterministic


def test_heuristic_guess_uuid():
    schema = {"type": "string", "format": "uuid"}
    val = _guess_value("order_id", schema)
    assert val is not None
    # Basic UUID check (len 36, hyphens)
    assert len(val) == 36
    assert "-" in val


def test_heuristic_guess_integer_id():
    schema = {"type": "integer"}
    val = _guess_value("user_id", schema)
    assert val == 1


def test_heuristic_guess_age():
    schema = {"type": "integer"}
    val = _guess_value("user_age", schema)
    assert val == 30

# --- Recursion Tests ---


def test_recursion_limit():
    # A schema that refers to itself (simplified for test logic)
    # The build_payload function doesn't actually parse $ref, it relies on the caller
    # passing a resolved schema or the recursion happening in the structure.
    # We'll construct a deeply nested structure to simulate recursion expansion.

    # Create a structure 5 levels deep
    deep_schema = {"type": "object", "required": ["next"], "properties": {"next": {}}}
    current = deep_schema["properties"]["next"]
    for _ in range(MAX_DEPTH + 2):
        current["type"] = "object"
        current["required"] = ["next"]
        current["properties"] = {"next": {}}
        current = current["properties"]["next"]

    # We test _generate_from_schema directly or via build_payload
    # build_payload is easier to mock inputs for.
    endpoint_id = "test"
    record = {
        "method": "POST",
        "path": "/test",
        "operation": {
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": deep_schema
                    }
                }
            }
        }
    }

    result = build_payload(endpoint_id, record, {})
    # Navigate down to find the recursion limit
    body = result["request"]["body"]

    # We expect to find "<recursion_limit>" at some depth
    found_limit = False

    def walk(obj):
        nonlocal found_limit
        if obj == "<recursion_limit>":
            found_limit = True
            return
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)

    walk(body)
    assert found_limit, "Did not find <recursion_limit> in generated payload"

# --- Search Sanitization Tests ---


def test_sanitize_query():
    assert _sanitize_fts_query("api") == '"api"'
    assert _sanitize_fts_query('api " v1') == '"api v1"'  # Quotes stripped/handled
    assert _sanitize_fts_query("foo*bar") == '"foo bar"'  # Special chars handled
    assert _sanitize_fts_query("  spaces  ") == '"spaces"'

# --- Execution Proxy Tests ---


@patch("api_catalog_mcp.catalog.engine.httpx.Client")
def test_execution_proxy_flow(mock_client_cls):
    # Setup mock
    mock_client = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_client
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"id": 123}
    mock_client.request.return_value = mock_response

    # Setup Engine
    engine = CatalogEngine(spec_dir=".")

    # Inject a fake operation into the index directly/mock it
    # Easier: Mock get_operation_by_endpoint_id and _get_spec
    with patch.object(engine._index, "get_operation_by_endpoint_id") as mock_get_op:
        mock_get_op.return_value = {
            "specId": "test_spec",
            "method": "POST",
            "path": "/users",
            "operation": {}
        }

        with patch.object(engine, "_get_spec") as mock_get_spec:
            mock_get_spec.return_value = {
                "servers": [{"url": "https://api.example.com"}]
            }

            # 1. Test Disabled by Default
            if "OPENAPI_EXECUTION" in os.environ:
                del os.environ["OPENAPI_EXECUTION"]

            res_disabled = engine.execute_request("test_op", {})
            assert res_disabled["ok"] is False
            assert "disabled" in res_disabled["error"]

            # 2. Test Enabled
            with patch.dict(os.environ, {"OPENAPI_EXECUTION": "1"}):
                request_payload = {
                    "method": "POST",
                    "path": "/users",
                    "body": {"name": "Alice"}
                }

                res = engine.execute_request("test_op", request_payload)

                assert res["ok"] is True
                assert res["status"] == 201
                assert res["body"] == {"id": 123}

                # Verify call arguments
                mock_client.request.assert_called_once()
                args, kwargs = mock_client.request.call_args
                assert args[0] == "post"  # method
                assert args[1] == "https://api.example.com/users"  # url
                assert kwargs["json"] == {"name": "Alice"}
