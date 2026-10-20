"""Tests for ``apiome import xregistry`` (MFI-19.2, #3980).

The ``xregistry`` format has no dedicated verb: it rides the registry-driven generic dispatch
(MFI-1.4), so ``apiome import xregistry <document>`` resolves the adapter from
``GET /v1/import/sources`` and posts the document bytes verbatim under ``source_kind: xregistry``.
The REST service is mocked.
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

_DOCUMENT_PATH = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/xregistry/02-typical-order-events.json"
)
_DOCUMENT_BYTES = _DOCUMENT_PATH.read_bytes()

_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_XREGISTRY_SOURCE = {
    "key": "xregistry",
    "label": "CNCF xRegistry",
    "description": "Import a CNCF xRegistry document.",
    "icon": "cloud",
    "paradigm": "event",
    "input_kinds": ["file", "url", "paste", "fileset"],
    "supports_live_discovery": False,
    "formats": ["xregistry", "cloudevents-registry"],
}

_SUMMARY = {
    "source": "xregistry",
    "paradigm": "event",
    "format": "xregistry",
    "fingerprint": "sha256:xreg123",
    "counts": {"services": 1, "operations": 2, "types": 2, "channels": 2},
    "lint": {
        "score": 87,
        "grade": "B",
        "report_fingerprint": "xreglintfp",
        "findings": 7,
        "severity_counts": {"warning": 2, "info": 5},
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
        url=_SOURCES_URL, method="GET", json={"sources": [_XREGISTRY_SOURCE]}
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


def test_import_xregistry_file_dispatches_to_the_xregistry_adapter(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    result = runner.invoke(app, ["import", "xregistry", str(_DOCUMENT_PATH)])
    assert result.exit_code == 0, result.output
    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "xregistry"
    assert base64.b64decode(body["document_base64"]) == _DOCUMENT_BYTES
    assert "Paradigm: event" in strip_ansi(result.output)


def test_import_xregistry_dry_run_sets_the_option(httpx_mock: object) -> None:
    _mock_import(httpx_mock)
    result = runner.invoke(app, ["import", "xregistry", "--file", str(_DOCUMENT_PATH), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert _post_body(httpx_mock)["metadata"]["options"]["dry_run"] is True
