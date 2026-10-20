"""Tests for ``apiome import acp`` and its ``--discover`` URL resolution (MFI-18.2, #3975).

The ``acp`` verb rides the registry-driven adapter import (MFI-1.4) and adds
``--discover SERVER_URL``, which derives the server's ``/agents`` listing URL before importing
it. The REST service is mocked; the document bytes must reach it verbatim under
``source_kind: acp``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.import_.acp import acp_agents_url
from apiome_cli.main import app
from helpers import strip_ansi

runner = CliRunner()

_LISTING_PATH = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/acp/03-composition-agent-list.json"
)
_LISTING_BYTES = _LISTING_PATH.read_bytes()

_SERVER = "https://acp.example.com"
_AGENTS_URL = f"{_SERVER}/agents"

_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_ACP_SOURCE = {
    "key": "acp",
    "label": "ACP Agent Manifest",
    "description": "Import ACP agent metadata.",
    "icon": "bot",
    "paradigm": "agent",
    "input_kinds": ["file", "url", "paste", "discovery", "fileset"],
    "supports_live_discovery": True,
    "formats": ["acp"],
}

_SUMMARY = {
    "source": "acp",
    "paradigm": "agent",
    "format": "acp",
    "fingerprint": "sha256:acp123",
    "counts": {"services": 3, "operations": 5, "types": 0, "channels": 0},
    "lint": {
        "score": 99,
        "grade": "A",
        "report_fingerprint": "acplintfp",
        "findings": 1,
        "severity_counts": {"info": 1},
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
        url=_SOURCES_URL, method="GET", json={"sources": [_ACP_SOURCE]}
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


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        (_SERVER, _AGENTS_URL),
        (f"{_SERVER}/", _AGENTS_URL),
        ("https://example.com/acp?x=1", "https://example.com/acp/agents"),
        (_AGENTS_URL, _AGENTS_URL),
        (f"{_SERVER}/agents/chat", f"{_SERVER}/agents/chat"),
        ("HTTPS://acp.example.com", _AGENTS_URL),
    ],
)
def test_acp_agents_url(base: str, expected: str) -> None:
    assert acp_agents_url(base) == expected


@pytest.mark.parametrize("bad", ["", "ftp://acp.example.com", "https://", "acp.example.com"])
def test_acp_agents_url_rejects_bad_input(bad: str) -> None:
    with pytest.raises(ValueError):
        acp_agents_url(bad)


def test_import_acp_file_dispatches_to_the_acp_adapter(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    result = runner.invoke(app, ["import", "acp", str(_LISTING_PATH)])
    assert result.exit_code == 0, result.output
    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "acp"
    assert base64.b64decode(body["document_base64"]) == _LISTING_BYTES
    assert "Paradigm: agent" in strip_ansi(result.output)


def test_import_acp_discover_imports_the_agents_listing(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    httpx_mock.add_response(url=_AGENTS_URL, method="GET", content=_LISTING_BYTES)  # type: ignore[attr-defined]

    result = runner.invoke(app, ["import", "acp", "--discover", _SERVER, "--dry-run"])
    assert result.exit_code == 0, result.output
    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "acp"
    assert body["metadata"]["options"]["dry_run"] is True
    assert base64.b64decode(body["document_base64"]) == _LISTING_BYTES
    assert f"Discovered ACP agent listing at {_AGENTS_URL}" in strip_ansi(result.output)


def test_import_acp_discover_reports_a_missing_listing(httpx_mock: object) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_SOURCES_URL, method="GET", json={"sources": [_ACP_SOURCE]}
    )
    httpx_mock.add_response(url=_AGENTS_URL, method="GET", status_code=404)  # type: ignore[attr-defined]
    result = runner.invoke(app, ["import", "acp", "--discover", _SERVER])
    assert result.exit_code != 0
    assert "HTTP 404" in strip_ansi(result.output)


def test_import_acp_rejects_discover_with_another_input() -> None:
    result = runner.invoke(app, ["import", "acp", str(_LISTING_PATH), "--discover", _SERVER])
    assert result.exit_code == 2
    assert "Provide only one input" in strip_ansi(result.output)


def test_import_acp_rejects_a_bad_server_url() -> None:
    result = runner.invoke(app, ["import", "acp", "--discover", "acp.example.com"])
    assert result.exit_code == 2
    assert "http or https" in strip_ansi(result.output)
