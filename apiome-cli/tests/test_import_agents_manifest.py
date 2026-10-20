"""Tests for ``apiome import agents-manifest`` and its ``--discover`` resolution (MFI-18.3, #3976).

The ``agents-manifest`` verb rides the registry-driven adapter import (MFI-1.4) and adds
``--discover SITE_URL``, which tries the site's well-known manifest paths in order before
importing the first one that serves a manifest. The REST service is mocked; the document bytes
must reach it verbatim under ``source_kind: agents-manifest``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from apiome_cli.import_.agents_manifest import (
    discover_site_manifest_url,
    looks_like_manifest,
    site_manifest_urls,
)
from apiome_cli.main import app
from helpers import strip_ansi

runner = CliRunner()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui/examples"
_MANIFEST_PATH = _EXAMPLES / "agents-manifest/02-typical-northwind-agents.json"
_MANIFEST_BYTES = _MANIFEST_PATH.read_bytes()
_A2A_CARD = (_EXAMPLES / "a2a/02-typical-travel-concierge.json").read_text(
    encoding="utf-8"
)

_SITE = "https://shop.example.com"
_AGENTS_JSON = f"{_SITE}/agents.json"
_AGENT_JSON = f"{_SITE}/.well-known/agent.json"
_AGENTS_TXT = f"{_SITE}/agents.txt"
_LLMS_TXT = f"{_SITE}/llms.txt"

_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_SOURCE = {
    "key": "agents-manifest",
    "label": "Agentic-web Site Manifest",
    "description": "Import a site's agentic-web manifest.",
    "icon": "globe",
    "paradigm": "agent",
    "input_kinds": ["file", "url", "paste", "discovery", "fileset"],
    "supports_live_discovery": True,
    "formats": ["agents-manifest"],
}

_SUMMARY = {
    "source": "agents-manifest",
    "paradigm": "agent",
    "format": "agents-manifest",
    "fingerprint": "sha256:site123",
    "counts": {"services": 3, "operations": 4, "types": 0, "channels": 0},
    "lint": {
        "score": 100,
        "grade": "A",
        "report_fingerprint": "sitelintfp",
        "findings": 0,
        "severity_counts": {},
    },
    "dry_run": False,
    "incremental_mode": False,
    "persisted": False,
}


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_import(httpx_mock: object) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_SOURCES_URL, method="GET", json={"sources": [_SOURCE]}
    )
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_IMPORT_URL,
        method="POST",
        status_code=202,
        json={"job_id": _JOB_ID, "state": "pending"},
    )
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_JOB_URL,
        method="GET",
        json={"state": "completed", "job_id": _JOB_ID, "summary": _SUMMARY},
    )


def _post_body(httpx_mock: object) -> dict:
    for request in httpx_mock.get_requests():  # type: ignore[attr-defined]
        if request.method == "POST" and str(request.url) == _IMPORT_URL:
            return json.loads(request.content.decode("utf-8"))
    raise AssertionError("no spec-import POST recorded")


def _client(routes: dict) -> httpx.Client:
    """An httpx client that serves ``routes`` (url → body or (status, body)) and 404s the rest."""

    def handler(request: httpx.Request) -> httpx.Response:
        route = routes.get(str(request.url))
        if route is None:
            return httpx.Response(404)
        status, body = route if isinstance(route, tuple) else (200, route)
        return httpx.Response(status, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize(
    ("site", "expected"),
    [
        (_SITE, [_AGENTS_JSON, _AGENT_JSON, _AGENTS_TXT, _LLMS_TXT]),
        (f"{_SITE}/docs/?x=1", [_AGENTS_JSON, _AGENT_JSON, _AGENTS_TXT, _LLMS_TXT]),
        (
            "HTTPS://shop.example.com",
            [_AGENTS_JSON, _AGENT_JSON, _AGENTS_TXT, _LLMS_TXT],
        ),
        (f"{_SITE}/docs/llms.txt", [f"{_SITE}/docs/llms.txt"]),
        (f"{_AGENTS_JSON}?v=2", [_AGENTS_JSON]),
    ],
)
def test_site_manifest_urls(site: str, expected: list) -> None:
    assert site_manifest_urls(site) == expected


@pytest.mark.parametrize(
    "bad", ["", "ftp://shop.example.com", "https://", "shop.example.com"]
)
def test_site_manifest_urls_reject_bad_input(bad: str) -> None:
    with pytest.raises(ValueError):
        site_manifest_urls(bad)


@pytest.mark.parametrize(
    ("url", "body", "expected"),
    [
        (_AGENTS_JSON, '{"site": {}}', True),
        (_AGENTS_TXT, "MCP: https://x.example/mcp", True),
        (_AGENTS_JSON, "  <!doctype html><html></html>", False),
        (_AGENTS_JSON, "", False),
        (_AGENT_JSON, '{"awp_version": "0.2", "domain": "x"}', True),
        (_AGENT_JSON, _A2A_CARD, False),
        (_AGENT_JSON, "not json", False),
    ],
)
def test_looks_like_manifest(url: str, body: str, expected: bool) -> None:
    assert looks_like_manifest(url, body) is expected


def test_discovery_skips_missing_html_and_a2a_paths() -> None:
    routes = {
        _AGENTS_JSON: "<html>app shell</html>",
        _AGENT_JSON: _A2A_CARD,
        _AGENTS_TXT: "MCP: https://shop.example.com/mcp\n",
    }
    with _client(routes) as client:
        assert discover_site_manifest_url(_SITE, client=client) == _AGENTS_TXT


def test_discovery_reports_failures() -> None:
    with _client({}) as client, pytest.raises(OSError, match="No site manifest found"):
        discover_site_manifest_url(_SITE, client=client)
    with (
        _client({_AGENTS_JSON: (503, "down")}) as client,
        pytest.raises(OSError, match="HTTP 503"),
    ):
        discover_site_manifest_url(_SITE, client=client)


def test_a_direct_url_is_returned_without_a_content_check() -> None:
    with _client({_LLMS_TXT: "<p>served as html</p>"}) as client:
        assert discover_site_manifest_url(_LLMS_TXT, client=client) == _LLMS_TXT


def test_import_file_dispatches_to_the_agents_manifest_adapter(
    httpx_mock: object,
) -> None:
    _mock_import(httpx_mock)
    result = runner.invoke(app, ["import", "agents-manifest", str(_MANIFEST_PATH)])
    assert result.exit_code == 0, result.output
    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "agents-manifest"
    assert base64.b64decode(body["document_base64"]) == _MANIFEST_BYTES
    assert "Paradigm: agent" in strip_ansi(result.output)


def test_import_discover_imports_the_first_manifest(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_AGENTS_JSON, method="GET", content=_MANIFEST_BYTES, is_reusable=True
    )

    result = runner.invoke(
        app, ["import", "agents-manifest", "--discover", _SITE, "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "agents-manifest"
    assert body["metadata"]["options"]["dry_run"] is True
    assert base64.b64decode(body["document_base64"]) == _MANIFEST_BYTES
    assert f"Discovered site manifest at {_AGENTS_JSON}" in strip_ansi(result.output)


def test_import_rejects_discover_with_another_input() -> None:
    result = runner.invoke(
        app, ["import", "agents-manifest", str(_MANIFEST_PATH), "--discover", _SITE]
    )
    assert result.exit_code == 2
    assert "Provide only one input" in strip_ansi(result.output)


def test_import_rejects_a_bad_site_url() -> None:
    result = runner.invoke(
        app, ["import", "agents-manifest", "--discover", "shop.example.com"]
    )
    assert result.exit_code == 2
    assert "http or https" in strip_ansi(result.output)
