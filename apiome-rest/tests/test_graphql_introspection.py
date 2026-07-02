"""Tests for GraphQL live introspection (MFI-10.3, #3772).

``graphql-core`` is a first-class Python dependency, so every test runs the real introspection
query / ``build_client_schema`` round-trip. The network is the only thing mocked: an
``httpx.MockTransport`` stands in for the endpoint and is fed the *real* introspection response
produced by running the standard query against a built schema (so the rebuilt SDL is exercised
end-to-end, not stubbed). The suite covers the two acceptance criteria — *introspects a sample
endpoint* and *graceful fallback when disabled* — plus the credential-vault auth wiring, the
SSRF guard, the response-classification matrix, and the pure ``graphql-core`` seams.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import httpx
import pytest
from graphql import GraphQLSchema, build_schema, graphql_sync

from app import ssrf_guard
from app.graphql_introspection import (
    GraphQlIntrospectionError,
    GraphQlIntrospectionResult,
    IntrospectionSource,
    build_introspection_query,
    introspect_endpoint,
    schema_from_introspection,
    sdl_from_introspection,
)
from app.graphql_parser import parse_graphql

# A small but representative schema: a custom Query root, an object type, a list/non-null
# wrapper, and an enum — enough to prove the rebuilt SDL is faithful.
_SAMPLE_SDL = """
type Query {
  user(id: ID!): User
  users: [User!]!
}

type User {
  id: ID!
  name: String
  status: Status
}

enum Status {
  ACTIVE
  DISABLED
}
"""

_ENDPOINT = "https://api.example.com/graphql"
_PUBLIC_IP = "93.184.216.34"


# ===========================================================================
# Helpers
# ===========================================================================


@contextmanager
def _resolve_public():
    """Make the SSRF guard see the test endpoint as a public host (no real DNS).

    This is an **SSRF guard integration seam**: we patch ``ssrf_guard._resolve_host_ips`` — an
    internal implementation detail of :func:`~app.ssrf_guard.build_guarded_client` — because it's
    the only way to control SSRF decisions for a host that doesn't resolve in our test environment.

    We *don't* mock ``build_guarded_client`` directly: those tests would skip the guarded client
    entirely and never exercise its redirect-loop / redirect-hop SSRF checks. Patching the IP
    resolver lets us keep the real guarded client while steering its policy decisions.

    If ``_resolve_host_ips`` is refactored or renamed, these tests will need to follow — see the
    "SSRF guard" heading in this file for the full set of affected tests.
    """
    with patch.object(ssrf_guard, "_resolve_host_ips", lambda host: [_PUBLIC_IP]):
        yield


def _introspection_data(sdl: str) -> Dict[str, Any]:
    """Run the standard introspection query against ``sdl`` to get a real ``data`` payload."""
    schema = build_schema(sdl)
    result = graphql_sync(schema, build_introspection_query())
    assert result.errors is None
    assert result.data is not None
    return result.data


def _mock_client(handler) -> httpx.Client:
    """An httpx client whose every request is served by ``handler`` (no network)."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def _schema_responder(sdl: str, *, captured: Optional[Dict[str, Any]] = None):
    """A MockTransport handler that answers any request with ``sdl``'s introspection result.

    When ``captured`` is given, the request headers and parsed JSON body are recorded into it so a
    test can assert on the auth headers / query that were actually sent.
    """
    data = _introspection_data(sdl)

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured["headers"] = dict(request.headers)
            captured["json"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"data": data})

    return handler


# ===========================================================================
# Pure graphql-core seams
# ===========================================================================


def test_build_introspection_query_is_a_real_query():
    query = build_introspection_query()
    assert "IntrospectionQuery" in query
    assert "__schema" in query
    # Descriptions requested by default.
    assert "description" in query


def test_build_introspection_query_can_drop_descriptions():
    assert "description" not in build_introspection_query(descriptions=False)


def test_schema_from_introspection_round_trips():
    schema = schema_from_introspection(_introspection_data(_SAMPLE_SDL))
    assert isinstance(schema, GraphQLSchema)
    assert schema.query_type is not None
    assert "User" in schema.type_map


def test_sdl_from_introspection_matches_canonical_sdl():
    # The rebuilt SDL, once re-parsed, must equal the canonical SDL of the original — proving the
    # introspection round-trip is lossless for the import pipeline.
    rebuilt = sdl_from_introspection(_introspection_data(_SAMPLE_SDL))
    assert parse_graphql(rebuilt).sdl == parse_graphql(_SAMPLE_SDL).sdl


def test_schema_from_introspection_rejects_missing_schema_key():
    with pytest.raises(GraphQlIntrospectionError, match="__schema"):
        schema_from_introspection({"not_schema": {}})


def test_schema_from_introspection_rejects_malformed_payload():
    with pytest.raises(GraphQlIntrospectionError, match="could not rebuild"):
        schema_from_introspection({"__schema": {"garbage": True}})


# ===========================================================================
# Acceptance: introspects a sample endpoint
# ===========================================================================


def test_introspects_sample_endpoint():
    with _resolve_public():
        result = introspect_endpoint(
            _ENDPOINT, client=_mock_client(_schema_responder(_SAMPLE_SDL))
        )

    assert isinstance(result, GraphQlIntrospectionResult)
    assert result.ok is True
    assert result.introspection_ok is True
    assert result.fallback_used is False
    assert result.source == IntrospectionSource.INTROSPECTION
    assert result.reason is None
    # The canonical SDL matches what parsing the original SDL would produce.
    assert result.sdl == parse_graphql(_SAMPLE_SDL).sdl
    assert result.parse_result is not None
    assert result.parse_result.root_operations.query == "Query"
    assert "User" in result.parse_result.type_names
    assert "Status" in result.parse_result.type_names


def test_introspection_posts_the_query():
    captured: Dict[str, Any] = {}
    with _resolve_public():
        introspect_endpoint(
            _ENDPOINT, client=_mock_client(_schema_responder(_SAMPLE_SDL, captured=captured))
        )
    assert "IntrospectionQuery" in captured["json"]["query"]
    assert captured["headers"]["content-type"] == "application/json"


# ===========================================================================
# Acceptance: graceful fallback when introspection is disabled
# ===========================================================================


def _disabled_handler(request: httpx.Request) -> httpx.Response:
    """Mimic a server with introspection turned off (the common production hardening)."""
    return httpx.Response(
        200,
        json={
            "errors": [
                {"message": "GraphQL introspection is not allowed by Apollo Server"}
            ]
        },
    )


def test_fallback_to_uploaded_sdl_when_disabled():
    with _resolve_public():
        result = introspect_endpoint(
            _ENDPOINT,
            fallback_sdl=_SAMPLE_SDL,
            client=_mock_client(_disabled_handler),
        )

    assert result.ok is True
    assert result.introspection_ok is False
    assert result.fallback_used is True
    assert result.source == IntrospectionSource.FALLBACK_SDL
    assert result.reason is not None
    assert "introspection is disabled" in result.reason
    # Even via the fallback the canonical artifact is identical.
    assert result.sdl == parse_graphql(_SAMPLE_SDL).sdl


def test_disabled_without_fallback_reports_reason():
    with _resolve_public():
        result = introspect_endpoint(_ENDPOINT, client=_mock_client(_disabled_handler))

    assert result.ok is False
    assert result.introspection_ok is False
    assert result.fallback_used is False
    assert result.source is None
    assert "introspection is disabled" in (result.reason or "")
    # The reason is also surfaced as a diagnostic on the parse result.
    assert result.parse_result is not None
    assert result.parse_result.errors


def test_fallback_used_but_sdl_invalid_reports_both():
    with _resolve_public():
        result = introspect_endpoint(
            _ENDPOINT,
            fallback_sdl="type Query { bad: DoesNotExist }",
            client=_mock_client(_disabled_handler),
        )

    assert result.ok is False
    assert result.fallback_used is True
    assert result.source is None
    assert "fallback also failed" in result.reason


# ===========================================================================
# Response-classification matrix (all "unavailable" → fall back, never raise)
# ===========================================================================


def test_http_error_status_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad request"})

    with _resolve_public():
        result = introspect_endpoint(_ENDPOINT, client=_mock_client(handler))
    assert result.ok is False
    assert "HTTP 400" in result.reason


def test_network_failure_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with _resolve_public():
        result = introspect_endpoint(
            _ENDPOINT, fallback_sdl=_SAMPLE_SDL, client=_mock_client(handler)
        )
    # A transient failure still rescues via the uploaded SDL.
    assert result.ok is True
    assert result.fallback_used is True
    assert "could not reach endpoint" in result.reason


def test_non_json_response_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not graphql</html>")

    with _resolve_public():
        result = introspect_endpoint(_ENDPOINT, client=_mock_client(handler))
    assert result.ok is False
    assert "JSON" in result.reason


def test_missing_schema_payload_is_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {}})

    with _resolve_public():
        result = introspect_endpoint(_ENDPOINT, client=_mock_client(handler))
    assert result.ok is False
    assert "__schema" in result.reason


def test_malformed_schema_payload_falls_back():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"__schema": {"nope": 1}}})

    with _resolve_public():
        result = introspect_endpoint(
            _ENDPOINT, fallback_sdl=_SAMPLE_SDL, client=_mock_client(handler)
        )
    assert result.ok is True
    assert result.fallback_used is True
    assert result.source == IntrospectionSource.FALLBACK_SDL


def test_partial_data_with_errors_still_uses_schema():
    # A spec-legal partial response carrying both a full ``__schema`` and advisory errors must
    # use the schema, not fall back.
    data = _introspection_data(_SAMPLE_SDL)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": data, "errors": [{"message": "deprecation advisory"}]}
        )

    with _resolve_public():
        result = introspect_endpoint(_ENDPOINT, client=_mock_client(handler))
    assert result.ok is True
    assert result.source == IntrospectionSource.INTROSPECTION


# ===========================================================================
# Credential-vault auth
# ===========================================================================


def test_bearer_credential_sets_authorization_header():
    captured: Dict[str, Any] = {}
    with _resolve_public():
        introspect_endpoint(
            _ENDPOINT,
            auth_type="bearer",
            auth_payload={"token": "s3cret-token"},
            client=_mock_client(_schema_responder(_SAMPLE_SDL, captured=captured)),
        )
    assert captured["headers"]["authorization"] == "Bearer s3cret-token"


def test_custom_header_credential_is_sent():
    captured: Dict[str, Any] = {}
    with _resolve_public():
        introspect_endpoint(
            _ENDPOINT,
            auth_type="header",
            auth_payload={"name": "X-Api-Key", "value": "abc123"},
            client=_mock_client(_schema_responder(_SAMPLE_SDL, captured=captured)),
        )
    assert captured["headers"]["x-api-key"] == "abc123"


def test_none_auth_sends_no_authorization():
    captured: Dict[str, Any] = {}
    with _resolve_public():
        introspect_endpoint(
            _ENDPOINT,
            auth_type="none",
            client=_mock_client(_schema_responder(_SAMPLE_SDL, captured=captured)),
        )
    assert "authorization" not in captured["headers"]


def test_extra_headers_do_not_override_auth():
    captured: Dict[str, Any] = {}
    with _resolve_public():
        introspect_endpoint(
            _ENDPOINT,
            auth_type="bearer",
            auth_payload={"token": "keep-me"},
            headers={"X-Tenant": "acme"},
            client=_mock_client(_schema_responder(_SAMPLE_SDL, captured=captured)),
        )
    assert captured["headers"]["authorization"] == "Bearer keep-me"
    assert captured["headers"]["x-tenant"] == "acme"


def test_malformed_credential_raises():
    # A bearer credential with no token is a caller error, not a fall-back condition.
    with _resolve_public():
        with pytest.raises(GraphQlIntrospectionError, match="token"):
            introspect_endpoint(
                _ENDPOINT,
                auth_type="bearer",
                auth_payload={},
                client=_mock_client(_schema_responder(_SAMPLE_SDL)),
            )


# ===========================================================================
# SSRF guard
# ===========================================================================


def test_private_endpoint_is_rejected():
    with patch.object(ssrf_guard, "_resolve_host_ips", lambda host: ["169.254.169.254"]):
        with pytest.raises(GraphQlIntrospectionError, match="non-public"):
            introspect_endpoint("https://metadata.internal/graphql")


def test_non_http_scheme_is_rejected():
    with pytest.raises(GraphQlIntrospectionError, match="scheme"):
        introspect_endpoint("ftp://example.com/graphql")


def test_redirect_to_private_host_is_rejected():
    """Verify that a redirect-to-SSRF-hop is caught by the guard's real request hook."""
    # The guard's request hook fires on the redirect hop; a guarded client surfaces it as an
    # SSRFError, which the orchestrator turns into a caller-facing error.
    # We patch ``_resolve_host_ips`` (like ``_resolve_public``) to make the guarded client's
    # internal policy evaluate private IPs — mocking ``build_guarded_client`` here would skip the
    # guard entirely and miss this behavior.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://169.254.169.254/graphql"})

    def resolve(host: str) -> List[str]:
        return ["169.254.169.254"] if host == "169.254.169.254" else [_PUBLIC_IP]

    guarded = ssrf_guard.build_guarded_client(
        transport=httpx.MockTransport(handler), follow_redirects=True
    )
    try:
        with patch.object(ssrf_guard, "_resolve_host_ips", resolve):
            with pytest.raises(GraphQlIntrospectionError, match="non-public"):
                introspect_endpoint(_ENDPOINT, client=guarded)
    finally:
        guarded.close()
