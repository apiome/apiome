"""Tests for ``apiome pact export-postman`` — PFX-4.7 (#6944).

The server writes the collection; the CLI builds the body (a stored pact's selection or a local
Pact file inline), writes the collection where it was asked to, prints every notice, turns a coded
refusal into its message and exit 1, and exits 1 on a left-out interaction only with
``--fail-on-left-out``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from apiome_cli.client.pact_postman_export import (
    build_export_body,
    has_left_out,
    postman_export_path,
    refusal_message,
    summary_lines,
)
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS
from apiome_cli.main import app

runner = CliRunner()

_URL = "http://localhost:8000/v1/tenants/acme-corp/pact-postman-collections"
_COLLECTION = {
    "info": {"name": "Pact: web → orders", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
    "item": [{"name": "get order", "request": {"method": "GET", "url": "{{baseUrl}}/orders/1"}}],
    "variable": [{"key": "baseUrl", "value": ""}],
}
_LEFT_OUT = {
    "code": "pact-postman-message-left-out",
    "outcome": "left-out",
    "pointer": "/messages/0",
    "message": "a message interaction has no HTTP request for Postman to send",
    "description": "order shipped",
}
_STATES = {
    "code": "pact-postman-provider-states",
    "outcome": "info",
    "pointer": "",
    "message": "1 provider state(s) must be set up on the provider before the run",
    "paths": ["order 1 exists"],
}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")
    for name in ("PACT_BROKER_BASE_URL", "PACT_BROKER_TOKEN", "PACT_BROKER_PASSWORD", "PACT_BROKER_USERNAME"):
        monkeypatch.delenv(name, raising=False)


def _response(*notices: dict[str, Any]) -> dict[str, Any]:
    return {
        "collection": _COLLECTION,
        "pact": {"consumer": "web", "provider": "orders", "consumerVersion": "abc", "pactVersionSha": "ab" * 32},
        "counts": {"interactions": 2, "exported": 1, "leftOut": sum(1 for n in notices if n["outcome"] == "left-out")},
        "notices": list(notices),
    }


def _sent(httpx_mock: Any) -> dict[str, Any]:
    return json.loads(httpx_mock.get_requests()[0].content)


# --- pure helpers ------------------------------------------------------------------------------


def test_the_path_escapes_the_tenant() -> None:
    assert postman_export_path("acme corp") == "/v1/tenants/acme%20corp/pact-postman-collections"


def test_the_body_carries_only_what_was_given() -> None:
    blank = dict.fromkeys(
        ("provider", "consumer", "consumer_version", "tag", "branch", "pact_version", "pact", "provider_base_url")
    )
    assert build_export_body(**blank, tests=True) == {"tests": True}
    assert build_export_body(
        **{**blank, "provider": "orders", "consumer": "web", "tag": "prod", "provider_base_url": "http://x"},
        tests=False,
    ) == {"tests": False, "provider": "orders", "consumer": "web", "tag": "prod", "baseUrl": "http://x"}
    assert build_export_body(**{**blank, "pact": {"interactions": []}, "pact_version": "ab"}, tests=True) == {
        "tests": True,
        "pactVersionSha": "ab",
        "pact": {"interactions": []},
    }


def test_the_summary_names_every_notice() -> None:
    lines = summary_lines(_response(_LEFT_OUT, _STATES))
    assert lines[0] == "Postman collection for web version abc → orders: 1 request(s) from 2 interaction(s), 1 left out"
    assert lines[1] == "  notices: 2"
    assert lines[2] == (
        "    left-out [pact-postman-message-left-out] /messages/0 'order shipped': "
        "a message interaction has no HTTP request for Postman to send"
    )
    assert lines[3].endswith("before the run (order 1 exists)")
    assert has_left_out(_response(_LEFT_OUT)) and not has_left_out(_response(_STATES))


def test_a_coded_refusal_reads_as_its_message_and_notices() -> None:
    payload = {"detail": {"code": "pact-postman-no-http-interactions", "message": "no HTTP", "notices": [_LEFT_OUT]}}
    message = refusal_message(422, payload)
    assert message is not None
    assert message.splitlines()[0] == "HTTP 422 pact-postman-no-http-interactions: no HTTP"
    assert "/messages/0" in message.splitlines()[1]
    assert refusal_message(422, {"detail": [{"loc": ["body"]}]}) is None
    assert refusal_message(500, "oops") is None


# --- the command -------------------------------------------------------------------------------


def test_export_of_a_stored_pact_writes_the_collection(tmp_path: Path, httpx_mock: Any, api_key_env: None) -> None:
    httpx_mock.add_response(url=_URL, method="POST", json=_response(_STATES))
    target = tmp_path / "orders.postman_collection.json"
    result = runner.invoke(
        app,
        [
            "pact", "export-postman", "--provider", "orders", "--consumer", "web", "--branch", "main",
            "--provider-base-url", "http://localhost:8080", "-o", str(target),
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(target.read_text()) == _COLLECTION
    assert _sent(httpx_mock) == {
        "tests": True, "provider": "orders", "consumer": "web", "branch": "main", "baseUrl": "http://localhost:8080",
    }
    assert "1 request(s)" in result.output
    assert f"wrote {target}" in result.output


def test_export_without_output_prints_the_collection(httpx_mock: Any, api_key_env: None) -> None:
    httpx_mock.add_response(url=_URL, method="POST", json=_response())
    result = runner.invoke(app, ["pact", "export-postman", "--provider", "orders", "--consumer", "web", "--no-tests"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout) == _COLLECTION
    assert _sent(httpx_mock)["tests"] is False


def test_a_local_pact_file_is_sent_inline(tmp_path: Path, httpx_mock: Any, api_key_env: None) -> None:
    pact = {"consumer": {"name": "web"}, "provider": {"name": "orders"}, "interactions": []}
    source = tmp_path / "web-orders.json"
    source.write_text(json.dumps(pact))
    httpx_mock.add_response(url=_URL, method="POST", json=_response())
    result = runner.invoke(app, ["pact", "export-postman", "--pact-file", str(source), "-o", str(tmp_path / "c.json")])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _sent(httpx_mock) == {"tests": True, "pact": pact}


@pytest.mark.parametrize("content", ["not json", "[1, 2]"])
def test_a_pact_file_that_is_not_a_json_object_is_refused_before_sending(
    tmp_path: Path, httpx_mock: Any, api_key_env: None, content: str
) -> None:
    source = tmp_path / "bad.json"
    source.write_text(content)
    result = runner.invoke(app, ["pact", "export-postman", "--pact-file", str(source)])
    assert result.exit_code == EXIT_ERROR
    assert "Pact file" in result.output
    assert httpx_mock.get_requests() == []


def test_fail_on_left_out_exits_1(tmp_path: Path, httpx_mock: Any, api_key_env: None) -> None:
    httpx_mock.add_response(url=_URL, method="POST", json=_response(_LEFT_OUT))
    args = ["pact", "export-postman", "--provider", "orders", "--consumer", "web", "-o", str(tmp_path / "c.json")]
    result = runner.invoke(app, [*args, "--fail-on-left-out"])
    assert result.exit_code == EXIT_ERROR, result.output
    assert "left-out [pact-postman-message-left-out]" in result.output


def test_left_out_without_the_flag_still_succeeds(tmp_path: Path, httpx_mock: Any, api_key_env: None) -> None:
    httpx_mock.add_response(url=_URL, method="POST", json=_response(_LEFT_OUT))
    args = ["pact", "export-postman", "--provider", "orders", "--consumer", "web", "-o", str(tmp_path / "c.json")]
    assert runner.invoke(app, args).exit_code == EXIT_SUCCESS


def test_a_refusal_prints_its_code_and_exits_1(httpx_mock: Any, api_key_env: None) -> None:
    httpx_mock.add_response(
        url=_URL,
        method="POST",
        status_code=404,
        json={"detail": {"code": "pact-not-found", "message": "no pact between consumer 'web' and provider 'orders'"}},
    )
    result = runner.invoke(app, ["pact", "export-postman", "--provider", "orders", "--consumer", "web"])
    assert result.exit_code == EXIT_ERROR
    assert "HTTP 404 pact-not-found: no pact between consumer 'web'" in result.output


def test_an_uncoded_error_uses_the_generic_handling(httpx_mock: Any, api_key_env: None) -> None:
    httpx_mock.add_response(url=_URL, method="POST", status_code=422, json={"detail": [{"loc": ["body", "x"]}]})
    result = runner.invoke(app, ["pact", "export-postman", "--provider", "orders", "--consumer", "web"])
    assert result.exit_code == EXIT_ERROR


def test_json_mode_prints_the_whole_response(httpx_mock: Any, api_key_env: None) -> None:
    httpx_mock.add_response(url=_URL, method="POST", json=_response(_STATES))
    result = runner.invoke(app, ["--json", "pact", "export-postman", "--provider", "orders", "--consumer", "web"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout)["notices"] == [_STATES]
