"""Tests for ``apiome export evidence`` — projection evidence paging (EFP-2.1, #4813).

The CLI leg of the evidence surface: the command POSTs the configured export to
``/v1/export/{tenant}/projection-evidence`` and either passes the machine-readable
response through (``--json``) or renders the snapshot line + evidence table. Options,
cursor, limit, and redaction flags must reach the request body unchanged, because the
server folds options into the snapshot hash.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_SUCCESS
from apiome_cli.export_output import evidence_rows
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_BASE = "http://localhost:8000"
_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_PROJECT = {"id": _PROJECT_ID, "name": "Payments API", "slug": "payments-api", "enabled": True}
_EVIDENCE_URL = f"{_BASE}/v1/export/acme-corp/projection-evidence"

_HASH = "954963401e3a5ec14bd3a0a4a87096d641dab86950081ce93818e323a73368af"

_RESPONSE = {
    "artifact": _PROJECT_ID,
    "version": "1.0.0",
    "version_record_id": "rev-uuid-1",
    "version_label": "1.0.0",
    "summary": {
        "manifest_hash": _HASH,
        "total_constructs": 5,
        "evidence_count": 7,
        "is_lossless": False,
    },
    "page": {
        "manifest_hash": _HASH,
        "edges": [
            {
                "id": "projects:GET /users/{id}#0",
                "relation": "projects",
                "source": "canonical:GET /users/{id}",
                "target": None,
                "status": "dropped",
                "reason": "destination_unsupported",
                "severity": "warn",
                "detail": "operations are not representable",
                "explanation": "The destination format cannot represent `GET /users/{id}`.",
            },
            {
                "id": "projects:User#0",
                "relation": "projects",
                "source": "canonical:User",
                "target": "target:User",
                "status": "retained",
                "reason": None,
                "severity": "info",
                "detail": "carried faithfully",
                "explanation": None,
            },
        ],
        "nodes": [],
        "next_cursor": "Mg==",
        "total": 7,
    },
    "redacted": False,
}


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", _BASE)
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_scope(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url=f"{_BASE}/v1/projects/acme-corp/by-slug/payments-api", json=_PROJECT
    )


def _args(*extra: str) -> list[str]:
    return [
        "export",
        "evidence",
        "--project",
        "payments-api",
        "--version",
        "1.0.0",
        "--target",
        "avro",
        *extra,
    ]


def test_evidence_json_passes_the_response_through(httpx_mock: object) -> None:
    """--json emits the raw evidence response (summary + page with next_cursor)."""
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_EVIDENCE_URL, json=_RESPONSE)

    result = runner.invoke(app, ["--json", *_args()])
    assert result.exit_code == EXIT_SUCCESS, result.output

    payload = json.loads(result.output)
    assert payload["summary"]["manifest_hash"] == _HASH
    assert payload["page"]["next_cursor"] == "Mg=="
    assert len(payload["page"]["edges"]) == 2


def test_evidence_request_body_carries_the_configuration(httpx_mock: object) -> None:
    """Options, cursor, limit, and redaction all reach the request body unchanged."""
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_EVIDENCE_URL, json=_RESPONSE)

    result = runner.invoke(
        app,
        [
            "--json",
            *_args(
                "--option",
                "namespace=corpus.test",
                "--cursor",
                "Mg==",
                "--limit",
                "25",
                "--redact-source",
            ),
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output

    request = httpx_mock.get_requests()[-1]
    body = json.loads(request.content)
    assert body["artifact"] == _PROJECT_ID
    assert body["version"] == "1.0.0"
    assert body["target"] == "avro"
    assert body["options"] == {"namespace": "corpus.test"}
    assert body["cursor"] == "Mg=="
    assert body["limit"] == 25
    assert body["redact_source"] is True


def test_evidence_human_view_prints_snapshot_line_and_table(httpx_mock: object) -> None:
    """The human view shows the snapshot reference, the rows, and the next-page hint."""
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=_EVIDENCE_URL, json=_RESPONSE)

    result = runner.invoke(app, _args())
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _HASH[:12] in result.output
    assert "GET /users/{id}" in result.output
    assert "destination_unsupported" in result.output
    assert "--cursor Mg==" in result.output


def test_evidence_rows_flatten_edges_and_prefer_reviewed_explanations() -> None:
    """Row derivation strips the canonical prefix and prefers the EFP-1.2 explanation."""
    rows = evidence_rows(_RESPONSE["page"])
    assert [row["construct"] for row in rows] == ["GET /users/{id}", "User"]
    assert rows[0]["explanation"].startswith("The destination format cannot represent")
    assert rows[1]["explanation"] == "carried faithfully"  # falls back to the report detail
    assert rows[1]["reason"] == ""


def test_evidence_rows_tolerate_a_missing_page() -> None:
    assert evidence_rows(None) == []
    assert evidence_rows({}) == []
    assert evidence_rows({"edges": "not-a-list"}) == []
