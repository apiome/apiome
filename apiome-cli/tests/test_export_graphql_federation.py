"""``apiome export graphql --federation`` — MFX-13.6 (#4344).

``--federation`` sends the GraphQL target's ``federation`` emit option with both the document request
(so the bytes are Federation v2 subgraph SDL) and the fidelity preview (so the summary counts each
synthesized ``@key`` as SYNTH). Without the flag neither request carries options.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_PREVIEW_LOSSLESS = json.loads((_FIXTURES / "export-preview-graphql-lossless.json").read_text())

_BASE = "http://localhost:8000"
_DOCUMENT_URL = f"{_BASE}/v1/export/acme-corp/document"
_PREVIEW_URL = f"{_BASE}/v1/export/acme-corp/preview"

_SUBGRAPH = (
    b'extend schema @link(url: "https://specs.apollo.dev/federation/v2.9", import: ["@key"])\n\n'
    b'type Query {\n  payment(id: ID!): Payment\n}\n\n'
    b'type Payment @key(fields: "id") {\n  id: ID!\n}\n'
)


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default API key + tenant scope for the tenant-scoped export routes."""
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock(httpx_mock: object) -> None:
    headers = {
        "Content-Type": "application/graphql",
        "Content-Disposition": 'attachment; filename="schema.graphql"',
    }
    httpx_mock.add_response(url=_DOCUMENT_URL, method="POST", content=_SUBGRAPH, headers=headers)
    httpx_mock.add_response(url=_PREVIEW_URL, method="POST", json=_PREVIEW_LOSSLESS)


def _args(out: str, *extra: str) -> list[str]:
    return ["export", "graphql", "--project", _PROJECT_ID, "--version", "1.0.0", "--output", out, *extra]


def _request_options(httpx_mock: object, path: str) -> dict | None:
    request = next(r for r in httpx_mock.get_requests() if r.url.path.endswith(path))
    return json.loads(request.content).get("options")


def test_federation_is_sent_to_the_document_and_the_preview(httpx_mock: object, tmp_path: Path) -> None:
    _mock(httpx_mock)
    out = tmp_path / "payments.graphql"

    result = runner.invoke(app, _args(str(out), "--federation"))

    assert result.exit_code == EXIT_SUCCESS, result.stderr
    assert _request_options(httpx_mock, "/document") == {"federation": True}
    assert _request_options(httpx_mock, "/preview") == {"federation": True}
    assert out.read_bytes() == _SUBGRAPH


def test_without_the_flag_no_options_are_sent(httpx_mock: object, tmp_path: Path) -> None:
    _mock(httpx_mock)

    result = runner.invoke(app, _args(str(tmp_path / "plain.graphql")))

    assert result.exit_code == EXIT_SUCCESS, result.stderr
    assert _request_options(httpx_mock, "/document") is None
    assert _request_options(httpx_mock, "/preview") is None


def test_graphql_help_documents_the_federation_flag() -> None:
    result = runner.invoke(app, ["export", "graphql", "--help"])
    assert result.exit_code == EXIT_SUCCESS
    assert "--federation" in result.stdout and "@key" in result.stdout
