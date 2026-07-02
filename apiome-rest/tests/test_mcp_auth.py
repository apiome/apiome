"""Unit tests for the MCP outbound auth-type model (MCAT-6.1, #3677).

Covers :func:`app.mcp_auth.build_auth_headers` and :func:`app.mcp_auth.env_vars_for_payload`
for every ``auth_type`` (``none``/``bearer``/``header``/``oauth2``/``env``), plus the security
invariants the model enforces: tokens only ever in headers, header names validated, and
header-injection (CR/LF/control) characters rejected.
"""

import pytest

from app.mcp_auth import (
    AUTHORIZATION_HEADER,
    CredentialPayloadError,
    build_auth_headers,
    env_vars_for_payload,
)


# ---------------------------------------------------------------------------
# none
# ---------------------------------------------------------------------------
def test_none_yields_no_headers():
    assert build_auth_headers("none", {}) == {}
    # Payload content is ignored entirely for the anonymous scheme.
    assert build_auth_headers("none", {"token": "ignored"}) == {}


# ---------------------------------------------------------------------------
# bearer
# ---------------------------------------------------------------------------
def test_bearer_builds_authorization_header():
    headers = build_auth_headers("bearer", {"token": "s3cr3t-abc"})
    assert headers == {AUTHORIZATION_HEADER: "Bearer s3cr3t-abc"}


def test_bearer_token_is_never_placed_in_a_url():
    # The model only ever returns headers — it has no notion of a URL. Confirm the only output
    # is the Authorization header and nothing resembling a query string is produced.
    headers = build_auth_headers("bearer", {"token": "TOKENVALUE"})
    assert list(headers) == [AUTHORIZATION_HEADER]
    assert "TOKENVALUE" not in "".join(k for k in headers)  # token is in the value, not a key


def test_bearer_missing_token_raises():
    with pytest.raises(CredentialPayloadError, match="missing 'token'"):
        build_auth_headers("bearer", {})


def test_bearer_blank_token_raises():
    with pytest.raises(CredentialPayloadError, match="empty"):
        build_auth_headers("bearer", {"token": "   "})


def test_bearer_non_string_token_raises():
    with pytest.raises(CredentialPayloadError, match="must be a string"):
        build_auth_headers("bearer", {"token": 12345})


@pytest.mark.parametrize("evil", ["abc\r\nX-Inject: 1", "abc\ndef", "abc\x00def"])
def test_bearer_rejects_header_injection(evil):
    with pytest.raises(CredentialPayloadError, match="control characters"):
        build_auth_headers("bearer", {"token": evil})


# ---------------------------------------------------------------------------
# header
# ---------------------------------------------------------------------------
def test_header_builds_arbitrary_header():
    headers = build_auth_headers("header", {"name": "X-API-Key", "value": "abc123"})
    assert headers == {"X-API-Key": "abc123"}


def test_header_missing_name_raises():
    with pytest.raises(CredentialPayloadError, match="missing 'name'"):
        build_auth_headers("header", {"value": "abc123"})


def test_header_missing_value_raises():
    with pytest.raises(CredentialPayloadError, match="missing 'value'"):
        build_auth_headers("header", {"name": "X-API-Key"})


@pytest.mark.parametrize("bad_name", ["X-Bad Name", "X:Colon", "has\nnewline", ""])
def test_header_rejects_illegal_header_name(bad_name):
    with pytest.raises(CredentialPayloadError):
        build_auth_headers("header", {"name": bad_name, "value": "v"})


def test_header_rejects_injection_in_value():
    with pytest.raises(CredentialPayloadError, match="control characters"):
        build_auth_headers("header", {"name": "X-API-Key", "value": "a\r\nEvil: 1"})


# ---------------------------------------------------------------------------
# oauth2 (token-presentation only; full flow is MCAT-6.3/6.4)
# ---------------------------------------------------------------------------
def test_oauth2_presents_access_token_as_bearer():
    headers = build_auth_headers("oauth2", {"access_token": "at-xyz"})
    assert headers == {AUTHORIZATION_HEADER: "Bearer at-xyz"}


def test_oauth2_honours_explicit_token_type():
    headers = build_auth_headers(
        "oauth2", {"access_token": "at-xyz", "token_type": "DPoP"}
    )
    assert headers == {AUTHORIZATION_HEADER: "DPoP at-xyz"}


def test_oauth2_without_token_yields_no_headers():
    # No token acquired yet (flow not run): send nothing rather than guess.
    assert build_auth_headers("oauth2", {}) == {}


def test_oauth2_blank_access_token_raises():
    with pytest.raises(CredentialPayloadError, match="access_token"):
        build_auth_headers("oauth2", {"access_token": "   "})


# ---------------------------------------------------------------------------
# env (no HTTP headers; bundle surfaced separately)
# ---------------------------------------------------------------------------
def test_env_contributes_no_http_headers():
    assert build_auth_headers("env", {"vars": {"API_KEY": "abc"}}) == {}


def test_env_vars_extracted_for_future_stdio():
    payload = {"vars": {"API_KEY": "abc", "REGION": "us-east-1"}}
    assert env_vars_for_payload("env", payload) == {"API_KEY": "abc", "REGION": "us-east-1"}


def test_env_vars_empty_when_absent():
    assert env_vars_for_payload("env", {}) == {}


def test_env_vars_zero_for_non_env_auth_type():
    assert env_vars_for_payload("bearer", {"token": "x"}) == {}


def test_env_vars_rejects_non_mapping():
    with pytest.raises(CredentialPayloadError, match="must be an object"):
        env_vars_for_payload("env", {"vars": ["not", "a", "map"]})


def test_env_vars_rejects_non_string_value():
    with pytest.raises(CredentialPayloadError, match="must be a string"):
        env_vars_for_payload("env", {"vars": {"PORT": 8080}})


# ---------------------------------------------------------------------------
# unsupported
# ---------------------------------------------------------------------------
def test_unsupported_auth_type_raises():
    with pytest.raises(CredentialPayloadError, match="unsupported auth_type"):
        build_auth_headers("magic", {})
