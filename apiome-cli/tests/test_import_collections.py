"""Tests for ``apiome import har|insomnia|bruno`` (MFI-32.6, #4408).

The three collection formats of MFI-EPIC-32 have no dedicated CLI verbs: each rides the
registry-driven adapter import (MFI-1.4), so ``apiome import <format> <input>`` works because the
REST registry advertises the source. These tests drive that dispatch against a mocked REST service
with the committed corpus examples (``apiome-ui/examples/<format>/``) — a HAR capture, an Insomnia
v5 export and a zipped Bruno collection — and with a secrets-seeded capture, which must reach the
server byte for byte (the server's secret-scrub gate, not the CLI, removes credentials; MFI-32.5)
and must never be echoed back by the CLI.
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

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"

_SOURCES_URL = "http://localhost:8000/v1/import/sources"
_IMPORT_URL = "http://localhost:8000/v1/tenants/acme-corp/imports"
_JOB_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
_JOB_URL = f"http://localhost:8000/v1/tenants/acme-corp/imports/{_JOB_ID}"

_ARCHIVE_SUFFIXES = [".zip", ".tar.gz", ".tgz", ".tar"]


def _descriptor(key: str, label: str, icon: str, own_suffixes: list[str]) -> dict:
    """The registry descriptor the REST service advertises for a collection format."""
    return {
        "key": key,
        "label": label,
        "description": f"Import a {label}.",
        "icon": icon,
        "paradigm": "rest",
        "input_kinds": ["file", "url", "paste", "fileset"],
        "supports_live_discovery": False,
        "formats": [key],
        "file_extensions": own_suffixes + _ARCHIVE_SUFFIXES,
    }


_SOURCES = [
    _descriptor("bruno", "Bruno collection", "send", [".bru", ".json"]),
    _descriptor("har", "HAR (inferred)", "activity", [".har"]),
    _descriptor("insomnia", "Insomnia collection", "send", [".json", ".yaml", ".yml"]),
]

#: One committed example per format: ``(format, path)``.
_EXAMPLE_CASES = [
    ("har", _EXAMPLES / "har" / "02-typical-devtools-crud.har"),
    ("insomnia", _EXAMPLES / "insomnia" / "02-typical-v5-users-collection.yaml"),
    ("bruno", _EXAMPLES / "bruno" / "03-users-collection.zip"),
]


def _summary(fmt: str) -> dict:
    """The preview summary a completed adapter import job returns."""
    return {
        "source": fmt,
        "paradigm": "rest",
        "format": fmt,
        "fingerprint": f"sha256:{fmt}",
        "counts": {"services": 1, "operations": 4, "types": 2, "channels": 0},
        "lint": {
            "score": 92,
            "grade": "A",
            "report_fingerprint": f"{fmt}lintfp",
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


def _mock_import(httpx_mock: object, fmt: str) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_SOURCES_URL, method="GET", json={"sources": _SOURCES}
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
        json={"state": "completed", "job_id": _JOB_ID, "summary": _summary(fmt)},
    )


def _post_body(httpx_mock: object) -> dict:
    for request in httpx_mock.get_requests():  # type: ignore[attr-defined]
        if request.method == "POST" and str(request.url) == _IMPORT_URL:
            return json.loads(request.content.decode("utf-8"))
    raise AssertionError("no spec-import POST recorded")


@pytest.mark.parametrize(
    "fmt,path", _EXAMPLE_CASES, ids=[case[0] for case in _EXAMPLE_CASES]
)
def test_import_dispatches_to_the_collection_adapter(
    httpx_mock: object, fmt: str, path: Path
) -> None:
    _mock_import(httpx_mock, fmt)

    result = runner.invoke(app, ["import", fmt, str(path)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == fmt
    assert body["filename"] == path.name
    # Sent verbatim — a zipped Bruno collection included — for the server to unpack and read.
    assert base64.b64decode(body["document_base64"]) == path.read_bytes()
    text = strip_ansi(result.output)
    assert "Paradigm: rest" in text
    assert "Lint score: 92 (A)" in text


def test_import_bruno_archive_forwards_the_root(httpx_mock: object) -> None:
    _mock_import(httpx_mock, "bruno")
    path = _EXAMPLES / "bruno" / "03-users-collection.zip"

    result = runner.invoke(
        app,
        [
            "import",
            "bruno",
            str(path),
            "--root",
            "03-users-collection/bruno.json",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output

    options = _post_body(httpx_mock)["metadata"]["options"]
    assert options["archive_root"] == "03-users-collection/bruno.json"
    assert options["dry_run"] is True


def test_import_list_shows_the_collection_formats(httpx_mock: object) -> None:
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url=_SOURCES_URL, method="GET", json={"sources": _SOURCES}
    )

    result = runner.invoke(app, ["--json", "import", "--list"])
    assert result.exit_code == 0, result.output
    keys = [source["key"] for source in json.loads(result.output)["sources"]]
    assert keys == ["bruno", "har", "insomnia"]


def test_import_secrets_seeded_capture_is_sent_verbatim_and_never_echoed(
    httpx_mock: object, tmp_path: Path
) -> None:
    # Credential-shaped only, and assembled from fragments so no secret literal is committed.
    token = "eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiJjbGkifQ" + ".c2VlZGVk"
    session = "s%3A" + "Y2xpLXNlZWRlZC1zZXNzaW9u" + ".Qx7"
    capture = {
        "log": {
            "version": "1.2",
            "creator": {"name": "seeded", "version": "1"},
            "entries": [
                {
                    "request": {
                        "method": "GET",
                        "url": "https://api.example.com/v1/orders/42",
                        "headers": [
                            {"name": "Authorization", "value": f"Bearer {token}"},
                            {"name": "Cookie", "value": f"session={session}"},
                        ],
                        "cookies": [{"name": "session", "value": session}],
                    },
                    "response": {
                        "status": 200,
                        "headers": [
                            {"name": "Content-Type", "value": "application/json"}
                        ],
                        "content": {
                            "mimeType": "application/json",
                            "text": '{"id": 42}',
                        },
                    },
                }
            ],
        }
    }
    path = tmp_path / "seeded-orders.har"
    path.write_text(json.dumps(capture), encoding="utf-8")
    _mock_import(httpx_mock, "har")

    result = runner.invoke(app, ["import", "har", str(path)])
    assert result.exit_code == 0, result.output

    assert (
        base64.b64decode(_post_body(httpx_mock)["document_base64"]) == path.read_bytes()
    )
    for secret in (token, session):
        assert secret not in result.output
