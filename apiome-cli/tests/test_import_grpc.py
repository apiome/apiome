"""End-to-end tests for ``apiome import grpc`` (MFI-9.6, #3769).

gRPC / Protobuf has no dedicated import verb: it rides the registry-driven generic dispatch
(MFI-1.4), so once the REST registry advertises a ``grpc`` source the CLI imports a ``.proto``
with no new command code. These tests drive ``import grpc <input>`` over the committed self-contained
``.proto`` fixture against a mocked REST service, asserting the document bytes are forwarded verbatim
under ``source_kind: grpc`` and the RPC-paradigm preview summary is rendered. (The live reflection
path is a server-side crawl exercised in ``apiome-rest``; the CLI's role for the file path is to
upload the bytes.)
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
_JOB_ID = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

# The gRPC source as the REST registry (MFI-9.6) advertises it.
_GRPC_SOURCE = {
    "key": "grpc",
    "label": "gRPC / Protobuf",
    "description": "Import a gRPC / Protocol Buffers API from a .proto file or live server reflection.",
    "icon": "share-2",
    "paradigm": "rpc",
    "input_kinds": ["file", "url", "paste", "discovery"],
    "supports_live_discovery": True,
    "formats": ["protobuf"],
}

# The in-process adapter pipeline returns an RPC-paradigm preview summary.
_PREVIEW_SUMMARY = {
    "source": "grpc",
    "paradigm": "rpc",
    "format": "protobuf",
    "fingerprint": "sha256:grpc123",
    "counts": {"services": 1, "operations": 2, "types": 3, "channels": 0},
    "lint": {
        "score": 88,
        "grade": "B",
        "report_fingerprint": "grpclintfp",
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


def _mock_sources(httpx_mock: object) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_SOURCES_URL,
        method="GET",
        json={"sources": [_GRPC_SOURCE]},
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


def test_import_grpc_fixture_dispatches(httpx_mock: object) -> None:
    document = _FIXTURES / "echo-grpc.proto"
    _mock_sources(httpx_mock)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["import", "grpc", str(document)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "grpc"
    # The .proto bytes are sent verbatim (the CLI does not compile protobuf locally).
    assert base64.b64decode(body["document_base64"]) == document.read_bytes()

    text = strip_ansi(result.output)
    assert "Import preview completed." in text
    assert "grpc (protobuf)" in text
    assert "Paradigm: rpc" in text
    assert "Lint score: 88 (B)" in text


def test_import_grpc_from_url_flag(httpx_mock: object) -> None:
    _mock_sources(httpx_mock)
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url="https://example.com/echo.proto",
        method="GET",
        text='syntax = "proto3";\npackage echo.v1;\nservice Echo { }\n',
    )
    _mock_import_completed(httpx_mock)

    result = runner.invoke(
        app, ["import", "grpc", "--url", "https://example.com/echo.proto"]
    )
    assert result.exit_code == 0, result.output
    assert _post_body(httpx_mock)["metadata"]["source_kind"] == "grpc"


def test_import_grpc_dry_run(httpx_mock: object) -> None:
    document = _FIXTURES / "echo-grpc.proto"
    _mock_sources(httpx_mock)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["import", "grpc", str(document), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert _post_body(httpx_mock)["metadata"]["options"]["dry_run"] is True


def test_import_grpc_listed_in_sources(httpx_mock: object) -> None:
    _mock_sources(httpx_mock)
    result = runner.invoke(app, ["import", "--list"])
    assert result.exit_code == 0, result.output
    text = strip_ansi(result.output)
    assert "grpc" in text
    assert "rpc" in text
    # The registry advertises live discovery (reflection) for this source.
    assert "yes" in text


def test_import_grpc_unknown_format_when_absent(httpx_mock: object) -> None:
    # When the registry does not advertise grpc, a dispatch attempt fails with the actionable list.
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_SOURCES_URL,
        method="GET",
        json={"sources": []},
    )
    document = _FIXTURES / "echo-grpc.proto"
    result = runner.invoke(app, ["import", "grpc", str(document)])
    assert result.exit_code == 2, result.output
    assert "Unknown import format 'grpc'" in strip_ansi(result.output)
