"""End-to-end tests for ``apiome import asyncapi`` (MFI-8.5, #3763).

AsyncAPI has no dedicated import verb: it rides the registry-driven generic dispatch
(MFI-1.4), so once the REST registry advertises an ``asyncapi`` source the CLI imports
it with no new command code. These tests drive ``import asyncapi <input>`` over the
committed 2.6 / 3.0 / 3.1 fixtures against a mocked REST service, asserting the document
bytes are forwarded verbatim under ``source_kind: asyncapi`` and the event-paradigm
preview summary is rendered.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.main import app

from helpers import strip_ansi

runner = CliRunner()

_FIXTURES = Path(__file__).parent / "fixtures"

_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

# The AsyncAPI source as the REST registry (MFI-8.5) advertises it.
_ASYNCAPI_SOURCE = {
    "key": "asyncapi",
    "label": "AsyncAPI",
    "description": "Import an AsyncAPI 2.x or 3.x event-driven API description.",
    "icon": "radio",
    "paradigm": "event",
    "input_kinds": ["file", "url", "paste"],
    "supports_live_discovery": False,
    "formats": ["asyncapi-2", "asyncapi-3"],
}

# The in-process adapter pipeline returns an event-paradigm preview summary.
_PREVIEW_SUMMARY = {
    "source": "asyncapi",
    "paradigm": "event",
    "format": "asyncapi-3",
    "fingerprint": "sha256:async123",
    "counts": {"services": 1, "operations": 1, "types": 0, "channels": 1},
    "lint": {
        "score": 92,
        "grade": "A",
        "report_fingerprint": "asynclintfp",
        "findings": 1,
        "severity_counts": {"warning": 1},
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


def _mock_sources(httpx_mock: object) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_SOURCES_URL,
        method="GET",
        json={"sources": [_ASYNCAPI_SOURCE]},
    )


def _mock_import_completed(httpx_mock: object) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_IMPORT_URL,
        method="POST",
        status_code=202,
        json={"job_id": _JOB_ID, "state": "pending"},
    )
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_JOB_URL,
        method="GET",
        json={"state": "completed", "job_id": _JOB_ID, "summary": _PREVIEW_SUMMARY},
    )


def _post_body(httpx_mock: object) -> dict:
    for request in httpx_mock.get_requests():  # type: ignore[attr-defined]
        if request.method == "POST" and str(request.url) == _IMPORT_URL:
            return json.loads(request.content.decode("utf-8"))
    raise AssertionError("no spec-import POST recorded")


@pytest.mark.parametrize(
    "fixture",
    [
        "streetlights-asyncapi-2.6.yaml",
        "user-events-asyncapi-3.0.json",
        "account-asyncapi-3.1.yaml",
    ],
)
def test_import_asyncapi_fixture_dispatches(
    httpx_mock: object, fixture: str
) -> None:
    document = _FIXTURES / fixture
    _mock_sources(httpx_mock)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["import", "asyncapi", str(document)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "asyncapi"
    # The document bytes are sent verbatim (the CLI does not parse AsyncAPI locally).
    assert base64.b64decode(body["document_base64"]) == document.read_bytes()

    text = strip_ansi(result.output)
    assert "Import preview completed." in text
    assert "asyncapi (asyncapi-3)" in text
    assert "Lint score: 92 (A)" in text


def test_import_asyncapi_from_url_flag(httpx_mock: object) -> None:
    _mock_sources(httpx_mock)
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url="https://example.com/asyncapi.yaml",
        method="GET",
        text="asyncapi: '3.0.0'\ninfo:\n  title: Remote\n  version: '1'\n",
    )
    _mock_import_completed(httpx_mock)

    result = runner.invoke(
        app, ["import", "asyncapi", "--url", "https://example.com/asyncapi.yaml"]
    )
    assert result.exit_code == 0, result.output
    assert _post_body(httpx_mock)["metadata"]["source_kind"] == "asyncapi"


def test_import_asyncapi_dry_run(httpx_mock: object) -> None:
    document = _FIXTURES / "user-events-asyncapi-3.0.json"
    _mock_sources(httpx_mock)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(
        app, ["import", "asyncapi", str(document), "--dry-run"]
    )
    assert result.exit_code == 0, result.output
    assert _post_body(httpx_mock)["metadata"]["options"]["dry_run"] is True


def test_import_asyncapi_listed_in_sources(httpx_mock: object) -> None:
    _mock_sources(httpx_mock)
    result = runner.invoke(app, ["import", "--list"])
    assert result.exit_code == 0, result.output
    text = strip_ansi(result.output)
    assert "asyncapi" in text
    assert "event" in text
