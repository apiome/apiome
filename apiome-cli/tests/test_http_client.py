"""Tests for the RestClient httpx factory (client/http.py)."""

from __future__ import annotations

import httpx
import pytest
import typer
from typer.testing import CliRunner

from apiome_cli.client.http import (
    DEFAULT_TIMEOUT,
    RestClient,
    _auth_headers,
    _session_headers,
)
from apiome_cli.config import API_KEY_HEADER, SESSION_AUTH_HEADER, CliSettings
from apiome_cli.exit_codes import EXIT_SUCCESS
from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(
    *,
    base_url: str = "http://localhost:8000",
    api_key: str | None = None,
    session_token: str | None = None,
) -> CliSettings:
    """Return a CliSettings instance built from keyword arguments only."""
    return CliSettings.model_validate(
        {
            "base_url": base_url,
            "api_key": api_key,
            "session_token": session_token,
        },
    )


# ---------------------------------------------------------------------------
# _auth_headers
# ---------------------------------------------------------------------------


def test_auth_headers_empty_without_api_key() -> None:
    """No API key → empty headers dict."""
    assert _auth_headers(_settings()) == {}


def test_auth_headers_includes_api_key_header() -> None:
    """API key is placed under X-API-Key."""
    headers = _auth_headers(_settings(api_key="secret-token"))
    assert headers == {API_KEY_HEADER: "secret-token"}


def test_session_headers_empty_without_token() -> None:
    """No session token → empty headers dict."""
    assert _session_headers(_settings()) == {}


def test_session_headers_includes_bearer() -> None:
    """Session token is sent as Authorization Bearer."""
    headers = _session_headers(_settings(session_token="obj_sess_abc"))
    assert headers == {SESSION_AUTH_HEADER: "Bearer obj_sess_abc"}


def test_rest_client_session_mode_uses_bearer_not_api_key() -> None:
    """session=True prefers bearer token and omits X-API-Key."""
    client = RestClient(
        _settings(api_key="workspace-key", session_token="obj_sess_xyz"),
        session=True,
    )
    assert client._headers == {SESSION_AUTH_HEADER: "Bearer obj_sess_xyz"}
    assert API_KEY_HEADER not in client._headers


# ---------------------------------------------------------------------------
# RestClient construction defaults
# ---------------------------------------------------------------------------


def test_rest_client_default_timeout() -> None:
    """Default timeout matches DEFAULT_TIMEOUT constant."""
    client = RestClient(_settings())
    assert client._timeout == DEFAULT_TIMEOUT


def test_rest_client_custom_timeout() -> None:
    """Custom timeout is stored correctly."""
    client = RestClient(_settings(), timeout=120.0)
    assert client._timeout == 120.0


def test_rest_client_verify_default_true() -> None:
    """TLS verify is True by default."""
    client = RestClient(_settings())
    assert client._verify is True


def test_rest_client_verify_false_when_insecure() -> None:
    """verify=False disables TLS certificate checking."""
    client = RestClient(_settings(), verify=False)
    assert client._verify is False


def test_rest_client_base_url_strips_trailing_slash() -> None:
    """Base URL stored without trailing slash."""
    client = RestClient(_settings(base_url="http://localhost:8000/"))
    assert not client._base_url.endswith("/")


def test_rest_client_api_key_header_stored() -> None:
    """Auth headers include X-API-Key when api_key is set."""
    client = RestClient(_settings(api_key="tok"))
    assert client._headers.get(API_KEY_HEADER) == "tok"


def test_rest_client_no_api_key_header_without_key() -> None:
    """No X-API-Key header when api_key is absent."""
    client = RestClient(_settings())
    assert API_KEY_HEADER not in client._headers


# ---------------------------------------------------------------------------
# RestClient.get
# ---------------------------------------------------------------------------


def test_rest_client_get_success(httpx_mock: object) -> None:
    """Successful GET returns the httpx Response with JSON body accessible."""
    httpx_mock.add_response(
        url="http://localhost:8000/health",
        json={"status": "ok"},
    )
    client = RestClient(_settings())
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_rest_client_get_builds_full_url(httpx_mock: object) -> None:
    """GET prepends base_url to path."""
    httpx_mock.add_response(
        url="http://api.example.com:9000/projects",
        json=[],
    )
    client = RestClient(_settings(base_url="http://api.example.com:9000"))
    response = client.get("/projects")
    assert response.status_code == 200


def test_rest_client_get_sends_api_key_header(httpx_mock: object) -> None:
    """GET includes X-API-Key when API key is configured."""
    httpx_mock.add_response(
        url="http://localhost:8000/projects",
        json=[],
        match_headers={API_KEY_HEADER: "my-key"},
    )
    client = RestClient(_settings(api_key="my-key"))
    response = client.get("/projects")
    assert response.status_code == 200


def test_rest_client_get_exits_on_4xx(httpx_mock: object) -> None:
    """HTTP 4xx causes typer.Exit via exit_on_api_error."""
    httpx_mock.add_response(
        url="http://localhost:8000/health",
        status_code=404,
        text="not found",
    )
    client = RestClient(_settings())
    with pytest.raises(typer.Exit):
        client.get("/health")


def test_rest_client_get_exits_on_connection_error(httpx_mock: object) -> None:
    """Transport error causes typer.Exit via exit_on_connection_error."""
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    client = RestClient(_settings())
    with pytest.raises(typer.Exit):
        client.get("/health")


# ---------------------------------------------------------------------------
# RestClient.post
# ---------------------------------------------------------------------------


def test_rest_client_post_success(httpx_mock: object) -> None:
    """Successful POST returns the httpx Response."""
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme-corp/imports/upload",
        method="POST",
        status_code=202,
        json={"job_id": "abc123"},
    )
    client = RestClient(_settings())
    response = client.post(
        "/v1/tenants/acme-corp/imports/upload", json={"spec": "..."}
    )
    assert response.status_code == 202
    assert response.json()["job_id"] == "abc123"


def test_rest_client_post_sends_api_key_header(httpx_mock: object) -> None:
    """POST includes X-API-Key when API key is configured."""
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme-corp/imports/upload",
        method="POST",
        json={"job_id": "x"},
        match_headers={API_KEY_HEADER: "post-key"},
    )
    client = RestClient(_settings(api_key="post-key"))
    response = client.post("/v1/tenants/acme-corp/imports/upload", json={})
    assert response.status_code == 200


def test_rest_client_post_merges_extra_headers(httpx_mock: object) -> None:
    """Additional headers supplied to post() are merged with defaults."""
    httpx_mock.add_response(
        url="http://localhost:8000/upload",
        method="POST",
        json={"ok": True},
        match_headers={"X-Custom": "value"},
    )
    client = RestClient(_settings())
    response = client.post("/upload", json={}, headers={"X-Custom": "value"})
    assert response.status_code == 200


def test_rest_client_post_exits_on_4xx(httpx_mock: object) -> None:
    """POST HTTP 4xx causes typer.Exit."""
    httpx_mock.add_response(
        url="http://localhost:8000/v1/tenants/acme-corp/imports/upload",
        method="POST",
        status_code=422,
        json={"code": 422, "message": "Bad request"},
    )
    client = RestClient(_settings())
    with pytest.raises(typer.Exit):
        client.post("/v1/tenants/acme-corp/imports/upload", json={})


def test_rest_client_post_exits_on_connection_error(httpx_mock: object) -> None:
    """POST transport error causes typer.Exit."""
    httpx_mock.add_exception(httpx.ConnectError("refused"))
    client = RestClient(_settings())
    with pytest.raises(typer.Exit):
        client.post("/v1/tenants/acme-corp/imports/upload", json={})


def test_rest_client_delete_success(httpx_mock: object) -> None:
    """Successful DELETE returns the httpx Response."""
    httpx_mock.add_response(
        url="http://localhost:8000/auth/personal-access-tokens/abc",
        method="DELETE",
        json={"revoked": True},
    )
    client = RestClient(_settings(session_token="obj_sess_t"), session=True)
    response = client.delete("/auth/personal-access-tokens/abc")
    assert response.status_code == 200
    assert response.json() == {"revoked": True}


# ---------------------------------------------------------------------------
# --insecure flag via CLI
# ---------------------------------------------------------------------------


def test_insecure_flag_in_root_help() -> None:
    """--insecure appears in root --help output."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == EXIT_SUCCESS
    assert "--insecure" in strip_ansi(result.stdout)


def test_insecure_flag_disables_tls_verify(httpx_mock: object) -> None:
    """health command with --insecure passes verify=False to httpx."""
    httpx_mock.add_response(
        url="http://localhost:8000/health",
        json={"status": "ok"},
    )
    result = runner.invoke(app, ["--insecure", "health"])
    assert result.exit_code == EXIT_SUCCESS


def test_without_insecure_flag_tls_verify_is_on(httpx_mock: object) -> None:
    """health command without --insecure succeeds (verify=True default)."""
    httpx_mock.add_response(
        url="http://localhost:8000/health",
        json={"status": "ok"},
    )
    result = runner.invoke(app, ["health"])
    assert result.exit_code == EXIT_SUCCESS


# ---------------------------------------------------------------------------
# Timeout propagation via --timeout flag
# ---------------------------------------------------------------------------


def test_timeout_flag_propagates_to_client(httpx_mock: object) -> None:
    """--timeout value from root is forwarded to the HTTP client."""
    httpx_mock.add_response(
        url="http://localhost:8000/health",
        json={"status": "ok"},
    )
    result = runner.invoke(app, ["--timeout", "5.0", "health"])
    assert result.exit_code == EXIT_SUCCESS


def test_timeout_default_applies_when_not_set(httpx_mock: object) -> None:
    """Default timeout is used when --timeout is not provided."""
    httpx_mock.add_response(
        url="http://localhost:8000/health",
        json={"status": "ok"},
    )
    result = runner.invoke(app, ["health"])
    assert result.exit_code == EXIT_SUCCESS
