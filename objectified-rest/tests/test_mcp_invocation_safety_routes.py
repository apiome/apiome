"""API tests for the MCP test-harness safety guards (V2-MCP-22.3 / MCAT-8.3, #3689).

Covers the logging & safety layer added on top of the test-harness route
(``POST /v1/mcp/{tenant_slug}/endpoints/{id}/test``):

- **Invocation logging** — every *dispatched* call is recorded in ``mcp_test_invocations`` with the
  arguments and response **redacted** (secret-named fields masked) and the auth headers never logged;
  the new row id is returned as ``invocationId``. Logging is best-effort: a DB failure does not fail
  the call.
- **Destructive confirm gate** — a tool annotated ``destructiveHint`` / ``openWorldHint`` is refused
  with ``428`` unless ``confirm=true`` is sent.
- **Per-endpoint rate limit** — accepted calls are throttled per endpoint (``429`` over the window).

The tests drive the real route while mocking the DB and the :mod:`app.mcp_invoke` helpers, so no
database or network is touched. The route-level rate limiter and settings are isolated per test so the
guards are exercised deterministically.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

import app.mcp_catalog_routes as routes
from app.auth import validate_authentication
from app.main import app
from app.mcp_client.errors import DiscoveryError, DiscoveryErrorCode
from app.mcp_invoke import InvocationResult
from app.models import (
    MCP_INVOCATION_REDACTION_MASK,
    redact_sensitive_args,
)
from app.rate_limit import FixedWindowRateLimiter

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}

# A distinct endpoint id from the sibling harness-route test file so the in-process per-endpoint
# rate-limit bucket never collides across files in one pytest session.
_EP = "33333333-3333-3333-3333-333333333333"
_V1 = "44444444-4444-4444-4444-444444444444"
_URL = "https://mcp.acme.example/mcp"

_ENDPOINT_ROW = {
    "id": _EP,
    "tenant_id": "t1",
    "name": "Acme Ops",
    "slug": "acme-ops",
    "endpoint_url": _URL,
    "transport": "streamable_http",
    "visibility": "private",
    "published": False,
    "enabled": True,
    "current_version_id": _V1,
}


def _tool_row(name="get_weather", *, schema=None, annotations=None, ordinal=0):
    """A ``mcp_capability_items`` row for a tool with optional schema + annotations."""
    return {
        "version_id": _V1,
        "item_type": "tool",
        "name": name,
        "title": None,
        "description": "A tool",
        "input_schema": schema if schema is not None else {"type": "object"},
        "output_schema": None,
        "annotations": annotations,
        "uri": None,
        "uri_template": None,
        "raw": {},
        "ordinal": ordinal,
    }


def _ok_tool_result(name="get_weather", **overrides):
    """A completed, successful ``tools/call`` result."""
    base = dict(
        method="tools/call",
        target=name,
        completed=True,
        latency_ms=12.3456,
        is_error=False,
        content=({"type": "text", "text": "Sunny, 25C"},),
        structured_content={"tempC": 25},
        raw_result={"content": []},
    )
    base.update(overrides)
    return InvocationResult(**base)


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@pytest.fixture(autouse=True)
def _isolated_rate_limiter(monkeypatch):
    """Give every test a fresh per-endpoint limiter and a generous default limit.

    Keeps the module-global counter from accumulating across tests/files and stops the rate-limit
    guard from interfering with the logging/confirm tests; the rate-limit tests set their own limit.
    """
    monkeypatch.setattr(routes, "_test_invocation_limiter", FixedWindowRateLimiter())
    monkeypatch.setattr(routes.settings, "rate_limit_enabled", True)
    monkeypatch.setattr(routes.settings, "mcp_test_rate_limit_per_minute", 1000)
    monkeypatch.setattr(routes.settings, "rate_limit_window_seconds", 60)
    yield


def _post(body):
    return client.post(f"/v1/mcp/acme/endpoints/{_EP}/test", json=body)


# ===========================================================================
# redact_sensitive_args — the pure redaction helper
# ===========================================================================


def test_redact_masks_secret_named_keys_recursively():
    raw = {
        "city": "Denver",
        "api_key": "sk-live-123",
        "Authorization": "Bearer abc",
        "nested": {"password": "hunter2", "keep": 7},
        "items": [{"token": "t1", "name": "ok"}],
    }
    out = redact_sensitive_args(raw)
    assert out["city"] == "Denver"
    assert out["api_key"] == MCP_INVOCATION_REDACTION_MASK
    assert out["Authorization"] == MCP_INVOCATION_REDACTION_MASK
    assert out["nested"]["password"] == MCP_INVOCATION_REDACTION_MASK
    assert out["nested"]["keep"] == 7
    assert out["items"][0]["token"] == MCP_INVOCATION_REDACTION_MASK
    assert out["items"][0]["name"] == "ok"
    # The original is never mutated.
    assert raw["api_key"] == "sk-live-123"


def test_redact_passes_through_non_containers():
    assert redact_sensitive_args("plain") == "plain"
    assert redact_sensitive_args(42) == 42
    assert redact_sensitive_args(None) is None


# ===========================================================================
# Invocation logging & redaction
# ===========================================================================


def test_successful_call_is_logged_redacted_and_returns_invocation_id():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        mdb.insert_mcp_test_invocation.return_value = {"id": "log-1"}
        inv.return_value = _ok_tool_result()
        r = _post(
            {
                "item_type": "tool",
                "item_name": "get_weather",
                "arguments": {"city": "Denver", "api_token": "sk-secret"},
            }
        )
    assert r.status_code == 200, r.text
    assert r.json()["invocationId"] == "log-1"

    mdb.insert_mcp_test_invocation.assert_called_once()
    kwargs = mdb.insert_mcp_test_invocation.call_args.kwargs
    assert kwargs["endpoint_id"] == _EP
    assert kwargs["version_id"] == _V1
    assert kwargs["item_type"] == "tool"
    assert kwargs["item_name"] == "get_weather"
    assert kwargs["invoked_by"] == "user-1"
    assert kwargs["is_error"] is False
    assert kwargs["latency_ms"] == 12  # rounded to an int
    # Secret-named argument is masked in the log; the ordinary one is kept verbatim.
    assert kwargs["arguments"]["city"] == "Denver"
    assert kwargs["arguments"]["api_token"] == MCP_INVOCATION_REDACTION_MASK
    # The response is logged (redacted) with the call outcome.
    assert kwargs["response"]["completed"] is True
    assert kwargs["response"]["content"] == [{"type": "text", "text": "Sunny, 25C"}]


def test_secret_echoed_in_response_is_redacted_in_log():
    leaky = _ok_tool_result(
        content=({"type": "text", "text": "ok"}, {"access_token": "leaked-xyz"}),
    )
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        mdb.insert_mcp_test_invocation.return_value = {"id": "log-2"}
        inv.return_value = leaky
        r = _post({"item_type": "tool", "item_name": "get_weather", "arguments": {}})
    assert r.status_code == 200, r.text
    logged = mdb.insert_mcp_test_invocation.call_args.kwargs["response"]
    assert logged["content"][1]["access_token"] == MCP_INVOCATION_REDACTION_MASK
    # The live response returned to the caller is NOT redacted — only the persisted log is.
    assert r.json()["content"][1]["access_token"] == "leaked-xyz"


def test_transport_failure_logs_is_error_true():
    failed = InvocationResult(
        method="tools/call",
        target="get_weather",
        completed=False,
        latency_ms=3.0,
        error=DiscoveryError(DiscoveryErrorCode.CONNECT_ERROR, "boom"),
    )
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        mdb.insert_mcp_test_invocation.return_value = {"id": "log-3"}
        inv.return_value = failed
        r = _post({"item_type": "tool", "item_name": "get_weather", "arguments": {}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["completed"] is False
    kwargs = mdb.insert_mcp_test_invocation.call_args.kwargs
    # A call that never returned is logged as an error, with its classified error in the response.
    assert kwargs["is_error"] is True
    assert kwargs["response"]["error"] is not None


def test_tool_level_error_logs_is_error_true():
    err = _ok_tool_result(is_error=True, content=({"type": "text", "text": "nope"},))
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        mdb.insert_mcp_test_invocation.return_value = {"id": "log-4"}
        inv.return_value = err
        r = _post({"item_type": "tool", "item_name": "get_weather", "arguments": {}})
    assert r.status_code == 200, r.text
    assert mdb.insert_mcp_test_invocation.call_args.kwargs["is_error"] is True


def test_logging_failure_does_not_fail_the_call():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        mdb.insert_mcp_test_invocation.side_effect = RuntimeError("db down")
        inv.return_value = _ok_tool_result()
        r = _post({"item_type": "tool", "item_name": "get_weather", "arguments": {}})
    # The live call already happened, so the response still succeeds — just with a null invocation id.
    assert r.status_code == 200, r.text
    assert r.json()["invocationId"] is None


def test_auth_headers_are_never_passed_to_the_logger():
    # An auth override carries a secret; it must shape headers for the call but never reach the log.
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        mdb.insert_mcp_test_invocation.return_value = {"id": "log-5"}
        inv.return_value = _ok_tool_result()
        r = _post(
            {
                "item_type": "tool",
                "item_name": "get_weather",
                "arguments": {"city": "Denver"},
                "auth_override": {"auth_type": "bearer", "payload": {"token": "super-secret"}},
            }
        )
    assert r.status_code == 200, r.text
    assert r.json()["authOverrideApplied"] is True
    # The log row has no header/credential field at all, and the secret appears nowhere in it.
    kwargs = mdb.insert_mcp_test_invocation.call_args.kwargs
    assert "super-secret" not in str(kwargs)


# ===========================================================================
# Destructive / open-world confirm gate
# ===========================================================================


@pytest.mark.parametrize("hint", ["destructiveHint", "openWorldHint"])
def test_dangerous_tool_requires_confirm(hint):
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [
            _tool_row(name="delete_all", annotations={hint: True})
        ]
        inv.return_value = _ok_tool_result(name="delete_all")
        r = _post({"item_type": "tool", "item_name": "delete_all", "arguments": {}})
    assert r.status_code == 428, r.text
    assert hint in r.json()["detail"]
    # The gate fires BEFORE the call leaves the server and before anything is logged.
    inv.assert_not_called()
    mdb.insert_mcp_test_invocation.assert_not_called()


def test_dangerous_tool_runs_with_confirm_true():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [
            _tool_row(name="delete_all", annotations={"destructiveHint": True})
        ]
        mdb.insert_mcp_test_invocation.return_value = {"id": "log-6"}
        inv.return_value = _ok_tool_result(name="delete_all")
        r = _post(
            {
                "item_type": "tool",
                "item_name": "delete_all",
                "arguments": {},
                "confirm": True,
            }
        )
    assert r.status_code == 200, r.text
    inv.assert_awaited_once()
    mdb.insert_mcp_test_invocation.assert_called_once()


def test_safe_tool_needs_no_confirm():
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [
            _tool_row(annotations={"readOnlyHint": True, "destructiveHint": False})
        ]
        mdb.insert_mcp_test_invocation.return_value = {"id": "log-7"}
        inv.return_value = _ok_tool_result()
        r = _post({"item_type": "tool", "item_name": "get_weather", "arguments": {}})
    assert r.status_code == 200, r.text


def test_non_boolean_hint_does_not_trigger_gate():
    # A hint published as a string (not a JSON bool) is treated as unset — no spurious confirm gate.
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [
            _tool_row(annotations={"destructiveHint": "true"})
        ]
        mdb.insert_mcp_test_invocation.return_value = {"id": "log-8"}
        inv.return_value = _ok_tool_result()
        r = _post({"item_type": "tool", "item_name": "get_weather", "arguments": {}})
    assert r.status_code == 200, r.text


# ===========================================================================
# Per-endpoint rate limit
# ===========================================================================


def test_rate_limit_returns_429_when_exhausted(monkeypatch):
    monkeypatch.setattr(routes.settings, "mcp_test_rate_limit_per_minute", 2)
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        mdb.insert_mcp_test_invocation.return_value = {"id": "log-rl"}
        inv.return_value = _ok_tool_result()
        body = {"item_type": "tool", "item_name": "get_weather", "arguments": {}}
        r1 = _post(body)
        r2 = _post(body)
        r3 = _post(body)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429, r3.text
    assert r3.headers["Retry-After"]
    assert "rate limit" in r3.json()["detail"]
    # The throttled call never dispatched and was never logged (only 2 calls went out).
    assert inv.await_count == 2
    assert mdb.insert_mcp_test_invocation.call_count == 2


def test_rate_limit_disabled_does_not_throttle(monkeypatch):
    monkeypatch.setattr(routes.settings, "rate_limit_enabled", False)
    monkeypatch.setattr(routes.settings, "mcp_test_rate_limit_per_minute", 1)
    with patch("app.mcp_catalog_routes.db") as mdb, patch(
        "app.mcp_catalog_routes.invoke_tool", new_callable=AsyncMock
    ) as inv, patch("app.mcp_catalog_routes.load_endpoint_auth_headers", return_value={}):
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_capability_items.return_value = [_tool_row()]
        mdb.insert_mcp_test_invocation.return_value = {"id": "log-x"}
        inv.return_value = _ok_tool_result()
        body = {"item_type": "tool", "item_name": "get_weather", "arguments": {}}
        statuses = [_post(body).status_code for _ in range(3)]
    assert statuses == [200, 200, 200]
