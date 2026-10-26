"""Tests for OpenRPC live discovery through ``rpc.discover`` — MFI-19.1 (#3979).

A JSON-RPC service is stood in for by an :class:`httpx.MockTransport` that answers
``rpc.discover`` with the Ethereum-shaped corpus document
(``apiome-ui/examples/openrpc/05-ethereum-json-rpc.json``), so the import runs end to end:
discovery → parse → normalize → lint.
"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from app import ssrf_guard
from app.canonical_model import ApiParadigm
from app.import_source import ImportSourceError, InputKind, get_import_source, load_builtin_import_sources
from app.lint_engine import lint_canonical_model
from app.openrpc_discovery import (
    DISCOVER_METHOD,
    discover_openrpc_service,
    discover_request,
    endpoint_url,
    parse_discover_response,
)
from app.openrpc_import_source import OpenRpcImportSource

_ETHEREUM = json.loads(
    (Path(__file__).resolve().parents[2] / "apiome-ui/examples/openrpc/05-ethereum-json-rpc.json").read_text(
        encoding="utf-8"
    )
)
_ENDPOINT = "https://rpc.example.com/v1/key123"
_PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolve host names to a public address (the sandbox has no DNS); IP literals and
    ``localhost`` keep their private addresses so the SSRF guard still sees them."""

    def resolve(host: str) -> List[str]:
        if host == "localhost":
            return ["127.0.0.1"]
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return [_PUBLIC_IP]
        return [host]

    monkeypatch.setattr(ssrf_guard, "_resolve_host_ips", resolve)


def _service(seen: List[httpx.Request], *, reply: Any = None, status: int = 200) -> httpx.Client:
    """A client whose JSON-RPC endpoint answers ``rpc.discover`` with ``reply``.

    ``reply`` defaults to a JSON-RPC success carrying the Ethereum document; a ``str`` is sent
    verbatim (to test non-JSON bodies).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status)
        call = json.loads(request.content)
        body: Any = reply if reply is not None else {"jsonrpc": "2.0", "id": call["id"], "result": _ETHEREUM}
        if isinstance(body, str):
            return httpx.Response(200, text=body)
        return httpx.Response(200, json=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


# ===========================================================================
# The call
# ===========================================================================


def test_discover_request_is_a_json_rpc_2_call():
    assert discover_request() == {"jsonrpc": "2.0", "id": 1, "method": "rpc.discover", "params": []}
    assert DISCOVER_METHOD == "rpc.discover"


@pytest.mark.parametrize(
    "url, expected",
    [
        ("https://rpc.example.com", "https://rpc.example.com/"),
        ("HTTPS://rpc.example.com/v1/key?x=1#frag", "https://rpc.example.com/v1/key?x=1"),
        ("  http://rpc.example.com/rpc  ", "http://rpc.example.com/rpc"),
    ],
)
def test_endpoint_url_keeps_path_and_query(url: str, expected: str):
    assert endpoint_url(url) == expected


@pytest.mark.parametrize("url", ["", "ws://rpc.example.com", "file:///etc/passwd", "https://"])
def test_endpoint_url_needs_http(url: str):
    with pytest.raises(ImportSourceError):
        endpoint_url(url)


def test_discover_posts_rpc_discover_and_returns_the_result():
    seen: List[httpx.Request] = []
    discovery = discover_openrpc_service(_ENDPOINT, client=_service(seen))
    assert discovery.endpoint_url == _ENDPOINT
    assert json.loads(discovery.document) == _ETHEREUM
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "POST"
    assert str(request.url) == _ENDPOINT
    assert request.headers["content-type"] == "application/json"
    assert json.loads(request.content)["method"] == "rpc.discover"


def test_credentials_travel_in_headers():
    seen: List[httpx.Request] = []
    discover_openrpc_service(
        _ENDPOINT,
        auth_type="bearer",
        auth_payload={"token": "s3cret"},
        headers={"X-Extra": "1"},
        client=_service(seen),
    )
    assert seen[0].headers["authorization"] == "Bearer s3cret"
    assert seen[0].headers["x-extra"] == "1"
    assert "s3cret" not in str(seen[0].url)


def test_a_one_element_batch_reply_is_accepted():
    body = json.dumps([{"jsonrpc": "2.0", "id": 1, "result": {"openrpc": "1.2.6"}}])
    assert json.loads(parse_discover_response(body, url=_ENDPOINT)) == {"openrpc": "1.2.6"}


@pytest.mark.parametrize(
    "reply, code",
    [
        ({"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "Method not found"}}, "SOURCE_NOT_FOUND"),
        ({"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "rate limited"}}, "SOURCE_UNREACHABLE"),
        ({"jsonrpc": "2.0", "id": 1, "result": "0x1"}, "INPUT_MALFORMED"),
        ({"jsonrpc": "2.0", "id": 1}, "INPUT_MALFORMED"),
        ("<html>gateway</html>", "INPUT_MALFORMED"),
        ([], "INPUT_MALFORMED"),
    ],
)
def test_bad_replies_map_to_intake_codes(reply: Any, code: str):
    with pytest.raises(ImportSourceError) as exc:
        discover_openrpc_service(_ENDPOINT, client=_service([], reply=reply))
    assert exc.value.code == code


@pytest.mark.parametrize(
    "status, code",
    [
        (404, "SOURCE_NOT_FOUND"),
        (401, "SOURCE_AUTH_REQUIRED"),
        (403, "SOURCE_AUTH_REQUIRED"),
        (502, "SOURCE_UNREACHABLE"),
    ],
)
def test_http_failures_map_to_intake_codes(status: int, code: str):
    with pytest.raises(ImportSourceError) as exc:
        discover_openrpc_service(_ENDPOINT, client=_service([], status=status))
    assert exc.value.code == code


@pytest.mark.parametrize("url", ["http://127.0.0.1/rpc", "http://localhost:8545/", "http://10.0.0.5/"])
def test_a_private_endpoint_is_refused_before_any_request(url: str):
    seen: List[httpx.Request] = []
    with pytest.raises(ImportSourceError, match="not allowed"):
        discover_openrpc_service(url, client=_service(seen))
    assert seen == []


# ===========================================================================
# The adapter
# ===========================================================================


def test_the_adapter_declares_live_discovery():
    load_builtin_import_sources()
    adapter = get_import_source("openrpc")
    assert adapter.supports_live_discovery is True
    assert InputKind.DISCOVERY in adapter.input_kinds


def test_discover_imports_normalizes_and_lints_a_live_service():
    adapter = OpenRpcImportSource()
    document = adapter.discover(_ENDPOINT, client=_service([]))
    assert document.discovery_url == _ENDPOINT
    api = adapter.normalize(document)
    assert api.paradigm is ApiParadigm.RPC
    assert api.extras["openrpc_discovery_url"] == _ENDPOINT
    names = {op.name for op in api.services[0].operations}
    assert {"eth_blockNumber", "eth_getBalance"} <= names
    # The live document lints like an upload: the OpenRPC pack runs on it.
    result = lint_canonical_model(api)
    assert not [f for f in result.findings if f.rule.startswith("openrpc.") and f.severity == "error"]


def test_an_uploaded_document_records_no_discovery_url():
    adapter = OpenRpcImportSource()
    api = adapter.normalize(adapter.parse(json.dumps(_ETHEREUM)))
    assert "openrpc_discovery_url" not in api.extras


def test_discover_surfaces_a_document_that_does_not_parse():
    reply: Dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "result": {"openrpc": "1.2.6", "info": {}}}
    with pytest.raises(ImportSourceError, match="info.title"):
        OpenRpcImportSource().discover(_ENDPOINT, client=_service([], reply=reply))
