"""Tests for the CLX-4.2 lint subcommands: gate / evidence / verify-attestation (#4860)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

_PROJECT_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_VERSION_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_BASE_VERSION_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

_PROJECT = {
    "id": _PROJECT_ID,
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "name": "Payments API",
    "slug": "payments-api",
    "source": "manual",
    "enabled": True,
}
_VERSION = {
    "id": _VERSION_ID,
    "project_id": _PROJECT_ID,
    "version": "1.0.0",
    "slug": "1.0.0",
    "source": "import",
    "enabled": True,
}

_GATE_URL = (
    f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}/lint/gate"
)


def _gate_payload(*, passed: bool, unwaived_errors: int = 0) -> dict:
    return {
        "schemaVersion": 1,
        "subjectType": "catalog_revision",
        "subjectId": _VERSION_ID,
        "projectId": _PROJECT_ID,
        "baselineSubjectId": None,
        "newOnly": False,
        "policy": {"policyVersionId": "pv1", "contentFingerprint": "packfp", "ciOutcomes": {}},
        "evaluation": {"evaluationId": "e1", "passed": passed, "gateResults": {}},
        "gate": {
            "passed": passed,
            "newOnly": False,
            "gateResults": {
                "unwaived_errors": {"passed": unwaived_errors == 0},
                "required_coverage": {"passed": True},
                "axis_gates": {"passed": True},
            },
        },
        "counts": {"total": 2, "new": 0, "unwaivedErrors": unwaived_errors, "waived": 1},
        "newFingerprints": [],
        "findings": [],
        "scanners": [{"scannerId": "apiome.lint", "reportFingerprint": "rf1"}],
        "links": {"evidence": "/e", "policy": "/p", "workspace": "/w"},
    }


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _mock_scope(httpx_mock: object) -> None:
    httpx_mock.add_response(
        url="http://localhost:8000/v1/projects/acme-corp/by-slug/payments-api",
        json=_PROJECT,
    )
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/1.0.0",
        json=_VERSION,
    )


def _invoke_gate(*extra: str):
    return runner.invoke(
        app, ["lint", "gate", "--project", "payments-api", "--version", "1.0.0", *extra]
    )


def test_gate_passes_exits_zero(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=f"{_GATE_URL}?format=json", json=_gate_payload(passed=True))
    result = _invoke_gate()
    assert result.exit_code == EXIT_SUCCESS
    assert "Lint gate: PASSED" in result.stdout
    assert "Policy pack: pv1" in result.stdout


def test_gate_fails_exits_one(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"{_GATE_URL}?format=json", json=_gate_payload(passed=False, unwaived_errors=1)
    )
    result = _invoke_gate()
    assert result.exit_code == EXIT_ERROR
    assert "Lint gate: FAILED" in result.stdout
    assert "Failed gates: unwaived_errors" in result.stdout


def test_gate_findings_without_policy_failure_exit_zero(httpx_mock: object) -> None:
    """AC-1: findings alone never fail CI — only configured policy failures do."""
    _mock_scope(httpx_mock)
    payload = _gate_payload(passed=True)
    payload["counts"] = {"total": 7, "new": 2, "unwaivedErrors": 0, "waived": 3}
    httpx_mock.add_response(url=f"{_GATE_URL}?format=json", json=payload)
    result = _invoke_gate()
    assert result.exit_code == EXIT_SUCCESS
    assert "7 total" in result.stdout


def test_gate_json_mode_emits_payload(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=f"{_GATE_URL}?format=json", json=_gate_payload(passed=True))
    result = runner.invoke(
        app,
        ["--json", "lint", "gate", "--project", "payments-api", "--version", "1.0.0"],
    )
    assert result.exit_code == EXIT_SUCCESS
    payload = json.loads(result.stdout)
    assert payload["gate"]["passed"] is True
    assert payload["policy"]["policyVersionId"] == "pv1"


def test_gate_sarif_output_writes_artifact(httpx_mock: object, tmp_path: Path) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(url=f"{_GATE_URL}?format=json", json=_gate_payload(passed=True))
    sarif_body = '{"version": "2.1.0", "runs": []}'
    httpx_mock.add_response(url=f"{_GATE_URL}?format=sarif", text=sarif_body)
    out = tmp_path / "gate.sarif"
    result = _invoke_gate("--format", "sarif", "--output", str(out))
    assert result.exit_code == EXIT_SUCCESS
    assert out.read_text(encoding="utf-8") == sarif_body
    assert "Artifact written" in result.stdout


def test_gate_new_only_and_base_version_params(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    httpx_mock.add_response(
        url=f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/by-version/0.9.0",
        json={**_VERSION, "id": _BASE_VERSION_ID, "version": "0.9.0", "slug": "0.9.0"},
    )
    httpx_mock.add_response(
        url=(
            f"{_GATE_URL}?format=json&baselineRevisionId={_BASE_VERSION_ID}"
            "&policyVersionId=pv7&newOnly=true"
        ),
        json=_gate_payload(passed=True),
    )
    result = _invoke_gate(
        "--base-version", "0.9.0", "--policy-version", "pv7", "--new-only"
    )
    assert result.exit_code == EXIT_SUCCESS


def test_gate_rejects_unknown_format() -> None:
    result = _invoke_gate("--format", "pdf")
    assert result.exit_code == EXIT_USAGE


def test_lint_bare_group_still_requires_project() -> None:
    """The callback refactor must keep the pre-#4860 usage contract."""
    result = runner.invoke(app, ["lint", "--version", "1.0.0"])
    assert result.exit_code == EXIT_USAGE
    result = runner.invoke(app, ["lint", "--project", "payments-api"])
    assert result.exit_code == EXIT_USAGE


def test_evidence_emits_json(httpx_mock: object) -> None:
    _mock_scope(httpx_mock)
    evidence = {"subjectType": "catalog_revision", "subjectId": _VERSION_ID, "runs": []}
    httpx_mock.add_response(
        url=(
            f"http://localhost:8000/v1/versions/acme-corp/{_PROJECT_ID}/{_VERSION_ID}"
            "/lint/evidence"
        ),
        json=evidence,
    )
    result = runner.invoke(
        app, ["lint", "evidence", "--project", "payments-api", "--version", "1.0.0"]
    )
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout) == evidence


def _signed_envelope(secret: str) -> dict:
    payload_type = "application/vnd.in-toto+json"
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [],
        "predicateType": "https://apiome.dev/attestations/lint-gate/v1",
        "predicate": {
            "subjectType": "catalog_revision",
            "subjectId": _VERSION_ID,
            "gate": {"passed": True},
        },
    }
    payload = json.dumps(statement, sort_keys=True, separators=(",", ":")).encode("utf-8")
    type_bytes = payload_type.encode("utf-8")
    pae = b" ".join(
        [
            b"DSSEv1",
            str(len(type_bytes)).encode("ascii"),
            type_bytes,
            str(len(payload)).encode("ascii"),
            payload,
        ]
    )
    return {
        "payloadType": payload_type,
        "payload": base64.b64encode(payload).decode("ascii"),
        "signatures": [
            {
                "keyid": "apiome-lint-hmac-v1",
                "alg": "hmac-sha256",
                "sig": hmac.new(secret.encode("utf-8"), pae, hashlib.sha256).hexdigest(),
            }
        ],
    }


def test_verify_attestation_roundtrip(tmp_path: Path) -> None:
    envelope_file = tmp_path / "gate.att"
    envelope_file.write_text(json.dumps(_signed_envelope("shared")), encoding="utf-8")
    result = runner.invoke(
        app,
        ["lint", "verify-attestation", "--file", str(envelope_file), "--secret", "shared"],
    )
    assert result.exit_code == EXIT_SUCCESS
    assert "Attestation verified." in result.stdout
    assert f"Subject: {_VERSION_ID}" in result.stdout
    assert "Gate passed: True" in result.stdout


def test_verify_attestation_wrong_secret_fails(tmp_path: Path) -> None:
    envelope_file = tmp_path / "gate.att"
    envelope_file.write_text(json.dumps(_signed_envelope("shared")), encoding="utf-8")
    result = runner.invoke(
        app,
        ["lint", "verify-attestation", "--file", str(envelope_file), "--secret", "wrong"],
    )
    assert result.exit_code == EXIT_ERROR


def test_verify_attestation_secret_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APIOME_LINT_ATTESTATION_SECRET", "shared")
    envelope_file = tmp_path / "gate.att"
    envelope_file.write_text(json.dumps(_signed_envelope("shared")), encoding="utf-8")
    result = runner.invoke(app, ["lint", "verify-attestation", "--file", str(envelope_file)])
    assert result.exit_code == EXIT_SUCCESS


def test_verify_attestation_unreadable_file_is_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "lint",
            "verify-attestation",
            "--file",
            str(tmp_path / "missing.att"),
            "--secret",
            "s",
        ],
    )
    assert result.exit_code == EXIT_USAGE
