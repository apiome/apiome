"""Tests for ``apiome import openrpc`` and ``--discover`` (MFI-19.1, #3979).

``--discover`` calls a JSON-RPC service's ``rpc.discover`` method and uploads the OpenRPC document
it returns through the registry-dispatch import, against a mocked REST service and a mocked
JSON-RPC service.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from apiome_cli.import_.openrpc import (
    DISCOVER_REQUEST,
    discover_openrpc_document,
    openrpc_document_from_reply,
    openrpc_endpoint_url,
)
from apiome_cli.main import app
from helpers import strip_ansi

runner = CliRunner()

_EXAMPLE = (
    Path(__file__).resolve().parents[2]
    / "apiome-ui"
    / "examples"
    / "openrpc"
    / "05-ethereum-json-rpc.json"
)
_DOCUMENT = json.loads(_EXAMPLE.read_text(encoding="utf-8"))
_ENDPOINT = "https://rpc.example.com/v3/secret-key"
_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "efefefef-efef-4fef-8fef-efefefefefef"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_OPENRPC_SOURCE = {
    "key": "openrpc",
    "label": "OpenRPC",
    "description": "Import an OpenRPC JSON-RPC 2.0 service description with methods and schemas.",
    "icon": "workflow",
    "paradigm": "rpc",
    "input_kinds": ["file", "url", "paste", "discovery", "fileset"],
    "supports_live_discovery": True,
    "formats": ["openrpc", "jsonrpc"],
    "file_extensions": [
        ".openrpc.json",
        ".openrpc",
        ".json",
        ".zip",
        ".tar.gz",
        ".tgz",
        ".tar",
    ],
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_import(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=_SOURCES_URL, method="GET", json={"sources": [_OPENRPC_SOURCE]}
    )  # type: ignore[attr-defined]
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_IMPORT_URL,
        method="POST",
        status_code=202,
        json={"job_id": _JOB_ID, "state": "pending"},
    )
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_JOB_URL,
        method="GET",
        json={
            "state": "completed",
            "job_id": _JOB_ID,
            "summary": {
                "source": "openrpc",
                "paradigm": "rpc",
                "format": "openrpc",
                "fingerprint": "sha256:openrpc",
                "counts": {"services": 1, "operations": 4, "types": 3, "channels": 0},
                "lint": {
                    "score": 95,
                    "grade": "A",
                    "report_fingerprint": "fp",
                    "findings": 0,
                    "severity_counts": {},
                },
                "dry_run": False,
                "incremental_mode": False,
                "persisted": False,
            },
        },
    )


def _post_body(httpx_mock: object) -> dict:
    for request in httpx_mock.get_requests():  # type: ignore[attr-defined]
        if request.method == "POST" and str(request.url) == _IMPORT_URL:
            return json.loads(request.content.decode("utf-8"))
    raise AssertionError("no spec-import POST recorded")


def _reply(result: object = None, **extra: object) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": _DOCUMENT if result is None else result,
        **extra,
    }


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://rpc.example.com", "https://rpc.example.com/"),
        ("HTTPS://rpc.example.com/v3/k?x=1#f", "https://rpc.example.com/v3/k?x=1"),
    ],
)
def test_openrpc_endpoint_url(url: str, expected: str) -> None:
    assert openrpc_endpoint_url(url) == expected


@pytest.mark.parametrize("url", ["", "ws://rpc.example.com", "https:///nohost"])
def test_openrpc_endpoint_url_refuses_unusable_urls(url: str) -> None:
    with pytest.raises(ValueError):
        openrpc_endpoint_url(url)


def test_discover_posts_rpc_discover() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_reply())

    url, document = discover_openrpc_document(
        _ENDPOINT, client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert url == _ENDPOINT
    assert json.loads(document) == _DOCUMENT
    assert seen[0].method == "POST"
    assert json.loads(seen[0].content) == DISCOVER_REQUEST


@pytest.mark.parametrize(
    "body, match",
    [
        (
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "nope"}},
            "does not implement rpc.discover",
        ),
        (
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "busy"}},
            "with an error: busy",
        ),
        ({"jsonrpc": "2.0", "id": 1, "result": "0x1"}, "no OpenRPC document"),
    ],
)
def test_bad_replies_are_errors(body: dict, match: str) -> None:
    with pytest.raises(OSError, match=match):
        openrpc_document_from_reply(json.dumps(body), url=_ENDPOINT)


def test_an_http_error_is_an_error() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(405)))
    with pytest.raises(OSError, match="HTTP 405"):
        discover_openrpc_document(_ENDPOINT, client=client)


def test_discover_imports_the_returned_document(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    httpx_mock.add_response(url=_ENDPOINT, method="POST", json=_reply())  # type: ignore[attr-defined]
    result = runner.invoke(app, ["import", "openrpc", "--discover", _ENDPOINT])
    assert result.exit_code == 0, result.output
    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "openrpc"
    assert json.loads(base64.b64decode(body["document_base64"])) == _DOCUMENT
    # The upload is never named after the endpoint, whose path carries the API key.
    assert "secret-key" not in json.dumps(body["metadata"])
    assert f"Discovered OpenRPC document at {_ENDPOINT}" in strip_ansi(result.output)


def test_a_file_imports_without_discovery(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    result = runner.invoke(app, ["import", "openrpc", str(_EXAMPLE)])
    assert result.exit_code == 0, result.output
    assert (
        base64.b64decode(_post_body(httpx_mock)["document_base64"])
        == _EXAMPLE.read_bytes()
    )


def test_a_service_without_rpc_discover_fails(httpx_mock: object) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_ENDPOINT,
        method="POST",
        json={"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "x"}},
    )
    result = runner.invoke(app, ["import", "openrpc", "--discover", _ENDPOINT])
    assert result.exit_code == 1
    assert "does not implement rpc.discover" in strip_ansi(result.output)


def test_discover_is_the_only_input() -> None:
    result = runner.invoke(
        app, ["import", "openrpc", "api.json", "--discover", _ENDPOINT]
    )
    assert result.exit_code != 0
    assert "Provide only one input" in strip_ansi(result.output)
