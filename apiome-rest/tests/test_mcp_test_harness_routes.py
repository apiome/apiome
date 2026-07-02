"""API tests for the MCP test-harness route (V2-MCP-22.2 / MCAT-8.2, #3688).

Covers the single tenant-scoped route that exposes the invocation service (MCAT-8.1) to the
UI/CLI:

- ``POST /v1/mcp/{tenant_slug}/endpoints/{id}/test`` — invoke one cataloged capability live and
  report its content / tool error / classified transport failure with latency.

The tests drive the real route — capability lookup, argument-schema validation, ephemeral auth
override resolution, per-call timeout pass-through, and outcome shaping — while mocking the DB and
the three :mod:`app.mcp_invoke` helpers, so no database or network is touched. The invocation
helpers are mocked to return real :class:`~app.mcp_invoke.InvocationResult` objects, so the
``as_dict`` → wire-response shaping is exercised end-to-end.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.mcp_client.errors import DiscoveryError, DiscoveryErrorCode
from app.mcp_invoke import InvocationResult

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}

_EP = "11111111-1111-1111-1111-111111111111"
_V1 = "22222222-2222-2222-2222-222222222222"
_URL = "https://mcp.acme.example/mcp"

_ENDPOINT_ROW = {
    "id": _EP,
    "tenant_id": "t1",
    "name": "Acme Weather",
    "slug": "acme-weather",
    "endpoint_url": _URL,
    "transport": "streamable_http",
    "visibility": "private",
    "published": False,
    "enabled": True,
    "current_version_id": _V1,
}


def _tool_row(name="get_weather", *, schema=None, ordinal=0):
    """A ``mcp_capability_items`` row for a tool with the given input schema."""
    return {
        "version_id": _V1,
        "item_type": "tool",
        "name": name,
        "title": None,
        "description": "Get the weather",
        "input_schema": schema if schema is not None else {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"],
        },
        "output_schema": None,
        "annotations": None,
        "uri": None,
        "uri_template": None,
        "raw": {},
        "ordinal": ordinal,
    }


def _resource_row(name="readme", *, uri="file:///readme.md", ordinal=0):
    """A ``mcp_capability_items`` row for a concrete resource."""
    return {
        "version_id": _V1, "item_type": "resource", "name": name, "title": None,
        "description": None, "input_schema": None, "output_schema": None,
        "annotations": None, "uri": uri, "uri_template": None, "raw": {}, "ordinal": ordinal,
    }


def _prompt_row(name="summarize", *, arguments=None, ordinal=0):
    """A ``mcp_capability_items`` row for a prompt carrying declared arguments."""
    return {
        "version_id": _V1, "item_type": "prompt", "name": name, "title": None,
        "description": None, "input_schema": None, "output_schema": None,
        "annotations": None, "uri": None, "uri_template": None,
        "raw": {"arguments": arguments or []}, "ordinal": ordinal,
    }


def _ok_tool_result():
    """A completed, successful ``tools/call`` result."""
    return InvocationResult(
        method="tools/call", target="get_weather", completed=True, latency_ms=12.3456,
        is_error=False, content=({"type": "text", "text": "Sunny, 25C"},),
        structured_content={"tempC": 25}, raw_result={"content": []},
    )


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# Tool invocation — the three outcomes
# ===========================================================================


def test_test_tool_success():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch(
        "app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}
    ) as load_headers:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        inv.return_value = _ok_tool_result()
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "get_weather",
                  "arguments": {"city": "Denver"}},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["completed"] is True and body["isError"] is False
    assert body["method"] == "tools/call" and body["target"] == "get_weather"
    assert body["content"] == [{"type": "text", "text": "Sunny, 25C"}]
    assert body["structuredContent"] == {"tempC": 25}
    assert body["latencyMs"] == 12.346  # rounded to 3 dp by InvocationResult.as_dict
    assert body["error"] is None
    assert body["authOverrideApplied"] is False
    assert body["endpointId"] == _EP and body["itemType"] == "tool"
    # Stored credentials were loaded (no override), and the call carried the validated args.
    load_headers.assert_called_once_with(_EP)
    assert inv.await_args.args[1] == "get_weather"
    assert inv.await_args.args[2] == {"city": "Denver"}
    assert inv.await_args.kwargs["timeout"] == 30.0


def test_test_tool_level_error_is_in_band():
    err_result = InvocationResult(
        method="tools/call", target="get_weather", completed=True, latency_ms=5.0,
        is_error=True, content=({"type": "text", "text": "upstream 500"},),
    )
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        inv.return_value = err_result
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "get_weather", "arguments": {"city": "X"}},
        )
    assert r.status_code == 200
    body = r.json()
    # A tool-level error is a completed call reported in-band, NOT an HTTP error.
    assert body["completed"] is True and body["isError"] is True
    assert body["content"][0]["text"] == "upstream 500"
    assert body["error"] is None


def test_test_tool_transport_failure_is_in_band():
    failed = InvocationResult(
        method="tools/call", target="get_weather", completed=False, latency_ms=8.0,
        error=DiscoveryError(DiscoveryErrorCode.TIMEOUT, "read timed out"),
    )
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        inv.return_value = failed
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "get_weather", "arguments": {"city": "X"}},
        )
    assert r.status_code == 200
    body = r.json()
    # A remote failure is data, not a 5xx: completed False with a classified error.
    assert body["completed"] is False
    assert body["content"] == []
    assert body["error"]["code"] == "timeout"


# ===========================================================================
# Argument-schema validation
# ===========================================================================


def test_test_tool_arguments_violate_schema_422():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]  # requires "city"
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "get_weather", "arguments": {}},
        )
    assert r.status_code == 422
    assert "input schema" in r.json()["detail"]
    inv.assert_not_awaited()  # invalid args never reach the remote server


def test_test_tool_invalid_stored_schema_skips_local_validation():
    """A malformed stored inputSchema must not turn a test into a spurious 422."""
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [
            _tool_row(schema={"type": "not-a-real-type"})
        ]
        inv.return_value = _ok_tool_result()
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "get_weather", "arguments": {"city": "X"}},
        )
    assert r.status_code == 200
    inv.assert_awaited_once()


def test_test_tool_no_schema_accepts_any_arguments():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row(schema={})]
        inv.return_value = _ok_tool_result()
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "get_weather", "arguments": {"anything": 1}},
        )
    assert r.status_code == 200


# ===========================================================================
# Resource & prompt dispatch
# ===========================================================================


def test_test_resource_reads_stored_uri():
    res_result = InvocationResult(
        method="resources/read", target="file:///readme.md", completed=True, latency_ms=3.0,
        content=({"uri": "file:///readme.md", "text": "# Readme"},),
    )
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.read_resource", new_callable=AsyncMock
    ) as rr, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_resource_row()]
        rr.return_value = res_result
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "resource", "item_name": "readme"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["method"] == "resources/read"
    assert body["target"] == "file:///readme.md"
    # The resource name resolved to its stored concrete uri.
    assert rr.await_args.args[1] == "file:///readme.md"


def test_test_resource_without_uri_422():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.read_resource", new_callable=AsyncMock
    ) as rr, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_resource_row(uri=None)]
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "resource", "item_name": "readme"},
        )
    assert r.status_code == 422
    assert "uri" in r.json()["detail"]
    rr.assert_not_awaited()


def test_test_prompt_success():
    prompt_result = InvocationResult(
        method="prompts/get", target="summarize", completed=True, latency_ms=4.0,
        content=({"role": "user", "content": {"type": "text", "text": "hi"}},),
    )
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.get_prompt", new_callable=AsyncMock
    ) as gp, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [
            _prompt_row(arguments=[{"name": "topic", "required": True}])
        ]
        gp.return_value = prompt_result
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "prompt", "item_name": "summarize",
                  "arguments": {"topic": "weather"}},
        )
    assert r.status_code == 200
    assert r.json()["method"] == "prompts/get"
    assert gp.await_args.args[1] == "summarize"


def test_test_prompt_missing_required_argument_422():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.get_prompt", new_callable=AsyncMock
    ) as gp, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [
            _prompt_row(arguments=[{"name": "topic", "required": True}])
        ]
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "prompt", "item_name": "summarize", "arguments": {}},
        )
    assert r.status_code == 422
    assert "topic" in r.json()["detail"]
    gp.assert_not_awaited()


# ===========================================================================
# Ephemeral auth override (never persisted)
# ===========================================================================


def test_test_with_bearer_auth_override():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch(
        "app.mcp_catalog_routes.load_endpoint_auth_headers"
    ) as load_headers:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        inv.return_value = _ok_tool_result()
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={
                "item_type": "tool", "item_name": "get_weather", "arguments": {"city": "X"},
                "auth_override": {"auth_type": "bearer", "payload": {"token": "ephemeral-xyz"}},
            },
        )
    assert r.status_code == 200
    assert r.json()["authOverrideApplied"] is True
    # The override built the headers; the stored credential was never consulted...
    load_headers.assert_not_called()
    assert inv.await_args.kwargs["headers"] == {"Authorization": "Bearer ephemeral-xyz"}
    # ...and nothing about the override is persisted.
    mdb.upsert_mcp_endpoint_credentials.assert_not_called()


def test_test_auth_override_none_runs_anonymously():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch(
        "app.mcp_catalog_routes.load_endpoint_auth_headers"
    ) as load_headers:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        inv.return_value = _ok_tool_result()
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={
                "item_type": "tool", "item_name": "get_weather", "arguments": {"city": "X"},
                "auth_override": {"auth_type": "none", "payload": {}},
            },
        )
    assert r.status_code == 200
    assert r.json()["authOverrideApplied"] is True
    load_headers.assert_not_called()
    assert inv.await_args.kwargs["headers"] == {}


def test_test_auth_override_malformed_payload_422():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={
                "item_type": "tool", "item_name": "get_weather", "arguments": {"city": "X"},
                "auth_override": {"auth_type": "bearer", "payload": {}},  # missing token
            },
        )
    assert r.status_code == 422
    inv.assert_not_awaited()


# ===========================================================================
# Timeout pass-through
# ===========================================================================


def test_test_timeout_seconds_passed_through():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        inv.return_value = _ok_tool_result()
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "get_weather",
                  "arguments": {"city": "X"}, "timeout_seconds": 7.5},
        )
    assert r.status_code == 200
    assert inv.await_args.kwargs["timeout"] == 7.5


def test_test_timeout_out_of_range_422():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "get_weather", "timeout_seconds": 999},
        )
    assert r.status_code == 422


# ===========================================================================
# Not-found / not-discovered / bad-input guards
# ===========================================================================


def test_test_capability_not_on_surface_404():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row(name="other_tool")]
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "get_weather", "arguments": {"city": "X"}},
        )
    assert r.status_code == 404
    inv.assert_not_awaited()


def test_test_endpoint_not_discovered_409():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = {**_ENDPOINT_ROW, "current_version_id": None}
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "get_weather", "arguments": {"city": "X"}},
        )
    assert r.status_code == 409
    mdb.get_mcp_capability_items.assert_not_called()


def test_test_endpoint_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "get_weather", "arguments": {"city": "X"}},
        )
    assert r.status_code == 404
    mdb.get_mcp_capability_items.assert_not_called()


def test_test_rejects_resource_template_item_type():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "resource_template", "item_name": "x"},
        )
    assert r.status_code == 422  # request model restricts item_type to the testable set


def test_test_rejects_blank_item_name():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(
            f"/v1/mcp/acme/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "   "},
        )
    assert r.status_code == 422


def test_test_rejects_non_uuid_endpoint():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.post(
            "/v1/mcp/acme/endpoints/not-a-uuid/test",
            json={"item_type": "tool", "item_name": "get_weather"},
        )
    assert r.status_code == 422
    mdb.get_mcp_endpoint.assert_not_called()


# ===========================================================================
# Tenant scoping & auth
# ===========================================================================


def test_test_scoped_to_token_tenant():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        inv.return_value = _ok_tool_result()
        # A different URL slug must not widen scope — the token tenant scopes the lookup.
        client.post(
            f"/v1/mcp/other-slug/endpoints/{_EP}/test",
            json={"item_type": "tool", "item_name": "get_weather", "arguments": {"city": "X"}},
        )
        mdb.get_mcp_endpoint.assert_called_once_with("t1", _EP)


def test_test_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.post(
        f"/v1/mcp/acme/endpoints/{_EP}/test",
        json={"item_type": "tool", "item_name": "get_weather"},
    )
    assert r.status_code == 401
