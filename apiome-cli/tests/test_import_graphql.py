"""End-to-end tests for ``apiome import graphql`` (MFI-10.6, #3775).

GraphQL has no dedicated import verb: it rides the registry-driven generic dispatch
(MFI-1.4), so once the REST registry advertises a ``graphql`` source the CLI imports it
with no new command code. These tests drive ``import graphql <input>`` over the committed
SDL fixtures against a mocked REST service, asserting the document bytes are forwarded
verbatim under ``source_kind: graphql`` and the graph-paradigm preview summary is rendered.
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

# The GraphQL source as the REST registry (MFI-10.6) advertises it.
_GRAPHQL_SOURCE = {
    "key": "graphql",
    "label": "GraphQL",
    "description": "Import a GraphQL schema from SDL or live endpoint introspection.",
    "icon": "waypoints",
    "paradigm": "graph",
    "input_kinds": ["file", "url", "paste", "discovery"],
    "supports_live_discovery": True,
    "formats": ["graphql"],
}

# The in-process adapter pipeline returns a graph-paradigm preview summary.
_PREVIEW_SUMMARY = {
    "source": "graphql",
    "paradigm": "graph",
    "format": "graphql",
    "fingerprint": "sha256:graphql123",
    "counts": {"services": 2, "operations": 3, "types": 3, "channels": 0},
    "lint": {
        "score": 88,
        "grade": "B",
        "report_fingerprint": "graphqllintfp",
        "findings": 2,
        "severity_counts": {"warning": 2},
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
        json={"sources": [_GRAPHQL_SOURCE]},
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
        "blog-graphql.graphql",
        "inventory-graphql.gql",
    ],
)
def test_import_graphql_fixture_dispatches(httpx_mock: object, fixture: str) -> None:
    document = _FIXTURES / fixture
    _mock_sources(httpx_mock)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["import", "graphql", str(document)])
    assert result.exit_code == 0, result.output

    body = _post_body(httpx_mock)
    assert body["metadata"]["source_kind"] == "graphql"
    # The SDL bytes are sent verbatim (the CLI does not parse GraphQL locally).
    assert base64.b64decode(body["document_base64"]) == document.read_bytes()

    text = strip_ansi(result.output)
    assert "Import preview completed." in text
    assert "graphql (graphql)" in text
    assert "Paradigm: graph" in text
    assert "Lint score: 88 (B)" in text


def test_import_graphql_from_url_flag(httpx_mock: object) -> None:
    _mock_sources(httpx_mock)
    httpx_mock.add_response(  # type: ignore[attr-defined]
        url="https://example.com/schema.graphql",
        method="GET",
        text="type Query {\n  hello: String\n}\n",
    )
    _mock_import_completed(httpx_mock)

    result = runner.invoke(
        app, ["import", "graphql", "--url", "https://example.com/schema.graphql"]
    )
    assert result.exit_code == 0, result.output
    assert _post_body(httpx_mock)["metadata"]["source_kind"] == "graphql"


def test_import_graphql_dry_run(httpx_mock: object) -> None:
    document = _FIXTURES / "blog-graphql.graphql"
    _mock_sources(httpx_mock)
    _mock_import_completed(httpx_mock)

    result = runner.invoke(app, ["import", "graphql", str(document), "--dry-run"])
    assert result.exit_code == 0, result.output
    assert _post_body(httpx_mock)["metadata"]["options"]["dry_run"] is True


def test_import_graphql_listed_in_sources(httpx_mock: object) -> None:
    _mock_sources(httpx_mock)
    result = runner.invoke(app, ["import", "--list"])
    assert result.exit_code == 0, result.output
    text = strip_ansi(result.output)
    assert "graphql" in text
    assert "graph" in text
    # GraphQL advertises live discovery (introspection) in the sources table.
    assert "yes" in text
