"""Tests for OAuth 2.1 discovery of protected MCP servers (MCAT-6.3, #3679).

Three layers, all DB-free:

* **Parsing** — ``WWW-Authenticate`` challenges (quoted values, several challenges, token68).
* **URL rules** — RFC 9728 / RFC 8414 well-known URL construction, the https/SSRF guard and the
  resource ↔ endpoint match.
* **Discovery** — :func:`discover_oauth_metadata` against an ``httpx.MockTransport`` stand-in for
  a compliant server, plus every failure path; and the discovery engine storing the result in
  ``oauth_metadata`` when a run answers ``401``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from unittest.mock import MagicMock

import httpx
import pytest

from app import mcp_discovery_engine
from app.mcp_client import McpAuthRequiredError
from app.mcp_oauth_discovery import (
    OAuthDiscoveryError,
    authorization_server_metadata_url,
    bearer_challenge,
    check_metadata_url,
    discover_oauth_metadata,
    parse_www_authenticate,
    protected_resource_metadata_urls,
    resource_matches_endpoint,
)

_ENDPOINT = "https://mcp.acme.example/mcp"
_PRM_URL = "https://mcp.acme.example/.well-known/oauth-protected-resource/mcp"
_ISSUER = "https://auth.acme.example"
_AS_URL = "https://auth.acme.example/.well-known/oauth-authorization-server"
_CHALLENGE = f'Bearer realm="mcp", resource_metadata="{_PRM_URL}", scope="tools:read tools:call"'
_NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)

_PRM = {
    "resource": _ENDPOINT,
    "authorization_servers": [_ISSUER],
    "scopes_supported": ["tools:read", "tools:call"],
    "bearer_methods_supported": ["header"],
}
_ASM = {
    "issuer": _ISSUER,
    "authorization_endpoint": f"{_ISSUER}/authorize",
    "token_endpoint": f"{_ISSUER}/token",
    "registration_endpoint": f"{_ISSUER}/register",
    "scopes_supported": ["openid", "tools:read"],
    "response_types_supported": ["code"],
    "grant_types_supported": ["authorization_code", "refresh_token"],
    "token_endpoint_auth_methods_supported": ["none"],
    "code_challenge_methods_supported": ["S256"],
}


def _client(routes: Dict[str, Any], seen: List[str] | None = None) -> httpx.AsyncClient:
    """A client whose responses come from ``routes`` (URL → JSON body, status int or Response)."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if seen is not None:
            seen.append(url)
        value = routes.get(url, 404)
        if isinstance(value, httpx.Response):
            return value
        if isinstance(value, int):
            return httpx.Response(value)
        return httpx.Response(200, json=value)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ===========================================================================
# WWW-Authenticate parsing
# ===========================================================================


def test_parse_bearer_challenge_with_quoted_params():
    [challenge] = parse_www_authenticate(_CHALLENGE)
    assert challenge.scheme == "bearer"
    assert challenge.params == {
        "realm": "mcp",
        "resource_metadata": _PRM_URL,
        "scope": "tools:read tools:call",
    }


def test_parse_several_challenges_and_picks_bearer():
    header = 'Basic realm="legacy", Bearer error="invalid_token", error_description="expired \\"x\\""'
    challenges = parse_www_authenticate(header)
    assert [c.scheme for c in challenges] == ["basic", "bearer"]
    assert challenges[1].params["error_description"] == 'expired "x"'
    assert bearer_challenge(header).params["error"] == "invalid_token"


def test_parse_token68_unquoted_and_bare_schemes():
    assert parse_www_authenticate("Negotiate abc123==")[0].params == {"token68": "abc123=="}
    assert parse_www_authenticate("Bearer scope=read")[0].params == {"scope": "read"}
    assert [c.scheme for c in parse_www_authenticate("Bearer, Basic")] == ["bearer", "basic"]


@pytest.mark.parametrize("header", [None, "", "   ", ",,", '="x"'])
def test_parse_blank_or_malformed_is_empty_and_never_raises(header):
    assert parse_www_authenticate(header) == []
    assert bearer_challenge(header) is None


# ===========================================================================
# URL rules
# ===========================================================================


def test_protected_resource_urls_hint_then_path_then_root():
    assert protected_resource_metadata_urls("https://h.example/v1/mcp?x=1", "https://h.example/prm") == [
        "https://h.example/prm",
        "https://h.example/.well-known/oauth-protected-resource/v1/mcp",
        "https://h.example/.well-known/oauth-protected-resource",
    ]
    # No path: the two derived URLs collapse into one.
    assert protected_resource_metadata_urls("https://h.example/", None) == [
        "https://h.example/.well-known/oauth-protected-resource"
    ]


def test_authorization_server_url_inserts_well_known_before_path():
    assert authorization_server_metadata_url("https://as.example") == (
        "https://as.example/.well-known/oauth-authorization-server"
    )
    assert authorization_server_metadata_url("https://as.example/tenant1/") == (
        "https://as.example/.well-known/oauth-authorization-server/tenant1"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://auth.example/x",  # plaintext to a public host
        "https://10.0.0.5/x",  # RFC 1918
        "https://169.254.169.254/latest",  # cloud metadata (link-local)
        "https://user:pw@auth.example/x",  # embedded credentials
        "https://auth.example/x#frag",
        "ftp://auth.example/x",
        "/relative",
    ],
)
def test_check_metadata_url_refuses_unsafe(url):
    with pytest.raises(OAuthDiscoveryError) as info:
        check_metadata_url(url)
    assert info.value.code == "invalid_url"


@pytest.mark.parametrize("url", ["https://auth.example/x", "http://127.0.0.1:8080/x", "http://localhost/x"])
def test_check_metadata_url_allows_https_and_loopback_http(url):
    assert check_metadata_url(url) == url


@pytest.mark.parametrize(
    ("resource", "matches"),
    [
        ("https://mcp.acme.example/mcp", True),
        ("https://mcp.acme.example/mcp/", True),
        ("https://mcp.acme.example", True),
        ("https://MCP.acme.example:443/", True),
        ("https://mcp.acme.example/other", False),
        ("https://mcp.acme.example/mc", False),
        ("https://evil.example/mcp", False),
        ("http://mcp.acme.example/mcp", False),
    ],
)
def test_resource_matches_endpoint(resource, matches):
    assert resource_matches_endpoint(resource, _ENDPOINT) is matches


# ===========================================================================
# Discovery
# ===========================================================================


async def test_resolves_compliant_server_from_challenge_hint():
    seen: List[str] = []
    async with _client({_PRM_URL: _PRM, _AS_URL: _ASM}, seen) as client:
        metadata = await discover_oauth_metadata(_ENDPOINT, _CHALLENGE, client=client, now=_NOW)
    assert seen == [_PRM_URL, _AS_URL]
    assert metadata == {
        "source": "oauth_discovery",
        "discovered_at": "2026-11-08T12:00:00+00:00",
        "resource": _ENDPOINT,
        "resource_metadata_url": _PRM_URL,
        "authorization_servers": [_ISSUER],
        "issuer": _ISSUER,
        "authorization_server_metadata_url": _AS_URL,
        "authorization_endpoint": f"{_ISSUER}/authorize",
        "token_endpoint": f"{_ISSUER}/token",
        "registration_endpoint": f"{_ISSUER}/register",
        "revocation_endpoint": None,
        "scopes_supported": ["tools:read", "tools:call"],
        "challenge_scopes": ["tools:read", "tools:call"],
        "bearer_methods_supported": ["header"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "response_types_supported": ["code"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "pkce_s256_supported": True,
    }


async def test_falls_back_to_well_known_urls_without_a_challenge():
    root = "https://mcp.acme.example/.well-known/oauth-protected-resource"
    prm = {**_PRM, "resource": "https://mcp.acme.example", "scopes_supported": []}
    seen: List[str] = []
    async with _client({root: prm, _AS_URL: _ASM}, seen) as client:
        metadata = await discover_oauth_metadata(_ENDPOINT, None, client=client, now=_NOW)
    assert seen == [_PRM_URL, root, _AS_URL]
    assert metadata["resource"] == "https://mcp.acme.example"
    # The resource lists no scopes, so the authorization server's list is used.
    assert metadata["scopes_supported"] == ["openid", "tools:read"]
    assert metadata["challenge_scopes"] == []


async def test_tries_next_authorization_server_when_first_fails():
    other = "https://login.acme.example/realm"
    other_url = "https://login.acme.example/.well-known/oauth-authorization-server/realm"
    prm = {**_PRM, "authorization_servers": [_ISSUER, other]}
    async with _client({_PRM_URL: prm, _AS_URL: 500, other_url: {**_ASM, "issuer": other}}) as client:
        metadata = await discover_oauth_metadata(_ENDPOINT, _CHALLENGE, client=client, now=_NOW)
    assert metadata["issuer"] == other
    assert metadata["authorization_server_metadata_url"] == other_url


async def test_pkce_flag_false_when_s256_not_advertised():
    asm = {k: v for k, v in _ASM.items() if k != "code_challenge_methods_supported"}
    async with _client({_PRM_URL: _PRM, _AS_URL: asm}) as client:
        metadata = await discover_oauth_metadata(_ENDPOINT, _CHALLENGE, client=client, now=_NOW)
    assert metadata["pkce_s256_supported"] is False
    assert metadata["code_challenge_methods_supported"] == []


async def _discover_error(routes: Dict[str, Any], challenge: str | None = _CHALLENGE) -> str:
    async with _client(routes) as client:
        with pytest.raises(OAuthDiscoveryError) as info:
            await discover_oauth_metadata(_ENDPOINT, challenge, client=client, now=_NOW)
    return info.value.code


async def test_no_protected_resource_metadata_is_not_found():
    assert await _discover_error({}, challenge=None) == "not_found"


async def test_resource_for_another_server_is_rejected():
    prm = {**_PRM, "resource": "https://evil.example/mcp"}
    assert await _discover_error({_PRM_URL: prm, _AS_URL: _ASM}) == "resource_mismatch"


async def test_issuer_mismatch_is_rejected():
    asm = {**_ASM, "issuer": "https://evil.example"}
    assert await _discover_error({_PRM_URL: _PRM, _AS_URL: asm}) == "issuer_mismatch"


@pytest.mark.parametrize(
    "prm",
    [
        {"authorization_servers": [_ISSUER]},  # no resource
        {"resource": _ENDPOINT},  # no authorization servers
        {"resource": _ENDPOINT, "authorization_servers": "not-a-list"},
    ],
)
async def test_invalid_protected_resource_metadata(prm):
    assert await _discover_error({_PRM_URL: prm, _AS_URL: _ASM}) == "invalid_metadata"


async def test_authorization_server_without_token_endpoint_is_invalid():
    asm = {k: v for k, v in _ASM.items() if k != "token_endpoint"}
    assert await _discover_error({_PRM_URL: _PRM, _AS_URL: asm}) == "invalid_metadata"


async def test_authorization_server_with_plaintext_endpoint_is_refused():
    asm = {**_ASM, "token_endpoint": "http://auth.acme.example/token"}
    assert await _discover_error({_PRM_URL: _PRM, _AS_URL: asm}) == "invalid_url"


async def test_challenge_hint_to_private_address_is_refused():
    challenge = 'Bearer resource_metadata="https://169.254.169.254/latest/meta-data"'
    assert await _discover_error({}, challenge=challenge) == "invalid_url"


async def test_non_json_and_non_object_bodies_are_refused():
    html = httpx.Response(200, text="<html>login</html>")
    assert await _discover_error({_PRM_URL: html}) == "fetch_failed"
    assert await _discover_error({_PRM_URL: [1, 2]}) == "invalid_metadata"


async def test_redirects_are_not_followed():
    redirect = httpx.Response(302, headers={"Location": "https://evil.example/prm"})
    assert await _discover_error({_PRM_URL: redirect}) == "fetch_failed"


async def test_oversized_body_is_refused(monkeypatch):
    monkeypatch.setattr("app.mcp_oauth_discovery.MAX_METADATA_BYTES", 64)
    big = httpx.Response(200, content=json.dumps({**_PRM, "pad": "x" * 200}).encode())
    assert await _discover_error({_PRM_URL: big}) == "fetch_failed"


async def test_network_error_is_fetch_failed():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(OAuthDiscoveryError) as info:
            await discover_oauth_metadata(_ENDPOINT, _CHALLENGE, client=client)
    assert info.value.code == "fetch_failed"


# ===========================================================================
# Discovery engine: a 401 stores the metadata
# ===========================================================================

_EP_UUID = "11111111-1111-1111-1111-111111111111"
_JOB_UUID = "22222222-2222-2222-2222-222222222222"
_ENDPOINT_ROW = {"id": _EP_UUID, "tenant_id": "t1", "endpoint_url": _ENDPOINT, "transport": "streamable_http"}


def _engine(monkeypatch, exc: Exception, discover=None) -> MagicMock:
    async def _runner(_endpoint, _headers):
        raise exc

    monkeypatch.setattr(mcp_discovery_engine, "_discovery_runner", _runner)
    monkeypatch.setattr(mcp_discovery_engine, "load_endpoint_auth_headers", lambda _eid: {})
    monkeypatch.setattr(mcp_discovery_engine, "refresh_endpoint_auth_headers", lambda _eid: None)
    if discover is not None:
        monkeypatch.setattr(mcp_discovery_engine, "discover_oauth_metadata", discover)
    mdb = MagicMock()
    mdb.mark_mcp_discovery_job_running.return_value = {"id": _JOB_UUID, "state": "running"}
    mdb.record_mcp_discovery_failure.return_value = None
    monkeypatch.setattr(mcp_discovery_engine, "db", mdb)
    return mdb


async def test_engine_stores_oauth_metadata_on_401(monkeypatch):
    calls: List[Any] = []

    async def _discover(url, header, now=None):
        calls.append((url, header))
        return {"issuer": _ISSUER, "resource": _ENDPOINT, "authorization_endpoint": "a", "token_endpoint": "t"}

    mdb = _engine(monkeypatch, McpAuthRequiredError("", _CHALLENGE), _discover)
    await mcp_discovery_engine._drive_discovery_job(_JOB_UUID, _ENDPOINT_ROW)

    assert calls == [(_ENDPOINT, _CHALLENGE)]
    mdb.merge_mcp_endpoint_oauth_metadata.assert_called_once()
    assert mdb.merge_mcp_endpoint_oauth_metadata.call_args.args[0] == _EP_UUID
    assert mdb.merge_mcp_endpoint_oauth_metadata.call_args.args[1]["issuer"] == _ISSUER
    finish = mdb.finish_mcp_discovery_job.call_args
    assert finish.args[1] == "failed"
    assert finish.kwargs["result"]["error"]["code"] == "auth_required"
    assert finish.kwargs["result"]["oauth_discovery"] == {
        "status": "resolved",
        "issuer": _ISSUER,
        "resource": _ENDPOINT,
        "authorization_endpoint": "a",
        "token_endpoint": "t",
    }


async def test_engine_records_oauth_failure_without_storing(monkeypatch):
    async def _discover(url, header, now=None):
        raise OAuthDiscoveryError("not_found", "no protected resource metadata")

    mdb = _engine(monkeypatch, McpAuthRequiredError("", None), _discover)
    await mcp_discovery_engine._drive_discovery_job(_JOB_UUID, _ENDPOINT_ROW)

    mdb.merge_mcp_endpoint_oauth_metadata.assert_not_called()
    result = mdb.finish_mcp_discovery_job.call_args.kwargs["result"]
    assert result["oauth_discovery"] == {
        "status": "failed",
        "error": {"code": "not_found", "message": "no protected resource metadata"},
    }


async def test_engine_survives_a_store_failure(monkeypatch):
    async def _discover(url, header, now=None):
        return {"issuer": _ISSUER, "resource": _ENDPOINT, "authorization_endpoint": "a", "token_endpoint": "t"}

    mdb = _engine(monkeypatch, McpAuthRequiredError("", _CHALLENGE), _discover)
    mdb.merge_mcp_endpoint_oauth_metadata.side_effect = RuntimeError("db down")
    await mcp_discovery_engine._drive_discovery_job(_JOB_UUID, _ENDPOINT_ROW)

    result = mdb.finish_mcp_discovery_job.call_args.kwargs["result"]
    assert result["oauth_discovery"]["status"] == "failed"
    assert result["oauth_discovery"]["error"]["code"] == "store_failed"


async def test_engine_skips_oauth_discovery_for_other_failures(monkeypatch):
    async def _discover(url, header, now=None):  # pragma: no cover - must not run
        raise AssertionError("oauth discovery ran for a non-401 failure")

    mdb = _engine(monkeypatch, httpx.ConnectError("refused"), _discover)
    await mcp_discovery_engine._drive_discovery_job(_JOB_UUID, _ENDPOINT_ROW)

    mdb.merge_mcp_endpoint_oauth_metadata.assert_not_called()
    assert "oauth_discovery" not in mdb.finish_mcp_discovery_job.call_args.kwargs["result"]


async def test_engine_retries_once_with_a_refreshed_oauth_token(monkeypatch):
    """MCAT-6.4: a 401 on a stored OAuth token refreshes it and retries before giving up."""
    seen: List[Any] = []

    async def _runner(_endpoint, headers):
        seen.append(headers)
        raise McpAuthRequiredError("", _CHALLENGE)

    async def _discover(url, header, now=None):
        return {"issuer": _ISSUER, "resource": _ENDPOINT, "authorization_endpoint": "a", "token_endpoint": "t"}

    mdb = _engine(monkeypatch, McpAuthRequiredError("", _CHALLENGE), _discover)
    monkeypatch.setattr(mcp_discovery_engine, "_discovery_runner", _runner)
    monkeypatch.setattr(
        mcp_discovery_engine, "load_endpoint_auth_headers", lambda _eid: {"Authorization": "Bearer old"}
    )
    monkeypatch.setattr(
        mcp_discovery_engine, "refresh_endpoint_auth_headers", lambda _eid: {"Authorization": "Bearer new"}
    )
    await mcp_discovery_engine._drive_discovery_job(_JOB_UUID, _ENDPOINT_ROW)

    assert seen == [{"Authorization": "Bearer old"}, {"Authorization": "Bearer new"}]
    assert mdb.finish_mcp_discovery_job.call_args.kwargs["result"]["error"]["code"] == "auth_required"


async def test_engine_does_not_retry_without_a_refreshable_token(monkeypatch):
    seen: List[Any] = []

    async def _runner(_endpoint, headers):
        seen.append(headers)
        raise McpAuthRequiredError("", _CHALLENGE)

    async def _discover(url, header, now=None):
        return {"issuer": _ISSUER, "resource": _ENDPOINT, "authorization_endpoint": "a", "token_endpoint": "t"}

    _engine(monkeypatch, McpAuthRequiredError("", _CHALLENGE), _discover)
    monkeypatch.setattr(mcp_discovery_engine, "_discovery_runner", _runner)
    await mcp_discovery_engine._drive_discovery_job(_JOB_UUID, _ENDPOINT_ROW)

    assert seen == [{}]
