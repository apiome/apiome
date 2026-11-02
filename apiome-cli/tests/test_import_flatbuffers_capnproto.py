"""Tests for ``apiome import flatbuffers`` / ``apiome import capnproto`` (MFI-19.4, #3982).

The committed fixtures — a FlatBuffers schema (namespace, enum, struct, union, a table with explicit
field ids and a deprecated slot, root type) and a Cap'n Proto schema (file id, structs with a union,
an enum, and an interface whose results are parenthesized types) — reach the server verbatim under
their ``source_kind``.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.main import app

runner = CliRunner()

_FIXTURES = Path(__file__).parent / "fixtures"
_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "bcdebcde-bcde-4cde-8cde-bcdebcdebcde"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_SOURCES = {
    "flatbuffers": {
        "key": "flatbuffers",
        "label": "FlatBuffers",
        "description": "Import a FlatBuffers schema (.fbs) with tables, structs, enums, and root types.",
        "icon": "boxes",
        "paradigm": "data_schema",
        "input_kinds": ["file", "url", "paste", "fileset"],
        "supports_live_discovery": False,
        "formats": ["flatbuffers", "fbs"],
        "file_extensions": [".fbs", ".zip", ".tar.gz", ".tgz", ".tar"],
    },
    "capnproto": {
        "key": "capnproto",
        "label": "Cap'n Proto",
        "description": "Import a Cap'n Proto schema (.capnp) with structs, enums, and RPC interfaces.",
        "icon": "zap",
        "paradigm": "rpc",
        "input_kinds": ["file", "url", "paste", "fileset"],
        "supports_live_discovery": False,
        "formats": ["capnproto", "capnp"],
        "file_extensions": [".capnp", ".zip", ".tar.gz", ".tgz", ".tar"],
    },
}

_FIXTURE_FILES = [
    pytest.param("flatbuffers", "monsters-flatbuffers.fbs", id="flatbuffers"),
    pytest.param("capnproto", "addressbook-capnproto.capnp", id="capnproto"),
]


@pytest.fixture(autouse=True)
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tier-2 import commands require an API key and tenant scope."""
    monkeypatch.setenv("APIOME_API_KEY", "test-import-key")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_import(httpx_mock: object, source_format: str) -> None:
    httpx_mock.add_response(url=_SOURCES_URL, method="GET", json={"sources": [_SOURCES[source_format]]})  # type: ignore[attr-defined]
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_IMPORT_URL, method="POST", status_code=202, json={"job_id": _JOB_ID, "state": "pending"}
    )
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_JOB_URL,
        method="GET",
        json={
            "state": "completed",
            "job_id": _JOB_ID,
            "summary": {
                "source": source_format,
                "paradigm": _SOURCES[source_format]["paradigm"],
                "format": source_format,
                "fingerprint": f"sha256:{source_format}",
                "counts": {"services": 1, "operations": 3, "types": 4, "channels": 0},
                "lint": {"score": 100, "grade": "A", "report_fingerprint": "fp", "findings": 0, "severity_counts": {}},
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


@pytest.mark.parametrize("source_format, fixture", _FIXTURE_FILES)
def test_a_fixture_imports_verbatim(httpx_mock: object, source_format: str, fixture: str) -> None:
    _mock_import(httpx_mock, source_format)
    path = _FIXTURES / fixture
    result = runner.invoke(app, ["import", source_format, str(path)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == source_format
    assert base64.b64decode(body["document_base64"]) == path.read_bytes()


@pytest.mark.parametrize(
    "fixture, marker",
    [
        ("monsters-flatbuffers.fbs", "namespace Game.Monsters;"),
        ("monsters-flatbuffers.fbs", "(id: 4, deprecated)"),
        ("monsters-flatbuffers.fbs", "union Equipment"),
        ("monsters-flatbuffers.fbs", "struct Vec3"),
        ("monsters-flatbuffers.fbs", "root_type Monster;"),
        ("addressbook-capnproto.capnp", "@0x9eb32e19f86ee174;"),
        ("addressbook-capnproto.capnp", ":union {"),
        ("addressbook-capnproto.capnp", "-> (people :List(Person));"),
        ("addressbook-capnproto.capnp", "interface Directory"),
    ],
)
def test_the_fixtures_are_what_they_claim(fixture: str, marker: str) -> None:
    assert marker in (_FIXTURES / fixture).read_text(encoding="utf-8")
