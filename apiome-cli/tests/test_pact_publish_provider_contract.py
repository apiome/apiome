"""Tests for ``apiome pact publish-provider-contract`` — PFX-2.4 (#6928).

The CLI interprets no report: it base64-encodes the OpenAPI file and the evidence, names their
media types, PUTs them to the provider-contract endpoint, and prints what the server read.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from apiome_cli.client.pact_provider_contract import (
    build_publish_body,
    build_verification_results,
    contract_content_type,
    evidence_content_type,
    is_verified,
    summary_lines,
)
from apiome_cli.commands.pact import provider_contract_path
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

_URL = "http://localhost:8000/v1/tenants/acme-corp/pact-broker/contracts/provider/Ledger%20API/version/abc123"
_OAS = b'{"openapi": "3.1.0", "info": {"title": "Ledger API", "version": "1"}, "paths": {}}'
_JUNIT = b'<testsuite name="Dredd Tests" tests="1" failures="0"><testcase name="GET /invoices/abc1"/></testsuite>'


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _files(tmp_path: Path) -> tuple[Path, Path]:
    contract = tmp_path / "ledger-api.json"
    contract.write_bytes(_OAS)
    report = tmp_path / "dredd.xml"
    report.write_bytes(_JUNIT)
    return contract, report


def _response(status: str = "verified", verified: bool = True, **extra: Any) -> dict[str, Any]:
    return {
        "provider": {"name": "Ledger API"},
        "providerVersion": "abc123",
        "contentSha": "cd" * 32,
        "oasVersion": "3.1.0",
        "operationCount": 1,
        "selfVerification": {
            "status": status,
            "kind": "junit",
            "tool": "dredd",
            "digest": "sha256:" + "ab" * 32,
            "summary": {"tests": 1, "passed": 1, "failed": 0, "errors": 0, "skipped": 0},
            "providerContractVerified": verified,
            "unverifiedPolicy": "warn",
            **extra,
        },
        "comparisons": {
            "compared": 1,
            "alreadyCompared": 0,
            "errors": 0,
            "skipped": 0,
            "results": [{"consumer": "Billing Service", "consumerVersion": "2.0.0", "verdict": "pass"}],
        },
    }


# --- pure helpers ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [("a.xml", "application/xml"), ("a.json", "application/json"), ("a.ndjson", "application/x-ndjson"),
     ("a.jsonl", "application/x-ndjson"), ("a.TXT", "text/plain"), ("a.html", None)],
)
def test_the_evidence_type_comes_from_the_extension(name: str, expected: Any) -> None:
    assert evidence_content_type(Path(name), None) == expected
    assert evidence_content_type(Path(name), "text/xml") == "text/xml"


def test_the_contract_type_comes_from_the_extension() -> None:
    assert contract_content_type(Path("a.yml"), None) == "application/yaml"
    assert contract_content_type(Path("a.json"), None) == "application/json"
    assert contract_content_type(Path("a.oas"), None) is None


def test_a_report_file_defaults_to_success_and_is_base64(tmp_path: Path) -> None:
    _, report = _files(tmp_path)
    results = build_verification_results(
        evidence=report, evidence_content_type="application/xml", evidence_report=None,
        exit_code=None, verifier="dredd", verifier_version="14.1.0",
    )
    assert results == {
        "success": True,
        "content": base64.b64encode(_JUNIT).decode(),
        "contentType": "application/xml",
        "verifier": "dredd",
        "verifierVersion": "14.1.0",
    }


def test_an_exit_code_sets_success(tmp_path: Path) -> None:
    _, report = _files(tmp_path)
    failed = build_verification_results(
        evidence=report, evidence_content_type=None, evidence_report=None,
        exit_code=1, verifier=None, verifier_version=None,
    )
    assert failed is not None and failed["success"] is False and "contentType" not in failed


def test_an_apiome_report_leaves_success_to_the_report() -> None:
    results = build_verification_results(
        evidence=None, evidence_content_type=None, evidence_report=" 6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b ",
        exit_code=None, verifier=None, verifier_version=None,
    )
    assert results == {"providerVerificationReportId": "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"}


def test_no_evidence_options_send_no_results() -> None:
    assert build_verification_results(
        evidence=None, evidence_content_type=None, evidence_report=None,
        exit_code=None, verifier="dredd", verifier_version=None,
    ) is None


def test_both_a_report_file_and_an_apiome_report_are_refused(tmp_path: Path) -> None:
    _, report = _files(tmp_path)
    with pytest.raises(ValueError, match="not both"):
        build_verification_results(
            evidence=report, evidence_content_type=None, evidence_report="id",
            exit_code=None, verifier=None, verifier_version=None,
        )


def test_the_body_carries_only_what_was_given(tmp_path: Path) -> None:
    contract, _ = _files(tmp_path)
    body = build_publish_body(
        contract=contract, content_type="application/json", apiome_version=None, branch="main",
        tags=["prod"], build_url="https://ci.example.com/1", verification_results={"success": True},
    )
    assert body == {
        "contractType": "oas",
        "content": base64.b64encode(_OAS).decode(),
        "contentType": "application/json",
        "branch": "main",
        "tags": ["prod"],
        "buildUrl": "https://ci.example.com/1",
        "verificationResults": {"success": True},
    }
    by_reference = build_publish_body(
        contract=None, content_type=None, apiome_version="ledger-api@1.4.0", branch=None,
        tags=None, build_url=None, verification_results=None,
    )
    assert by_reference == {"contractType": "oas", "apiomeVersion": "ledger-api@1.4.0"}


@pytest.mark.parametrize("has_file, reference", [(True, "ledger@1"), (False, None)], ids=["both", "neither"])
def test_exactly_one_contract_source_is_required(tmp_path: Path, has_file: bool, reference: Any) -> None:
    contract, _ = _files(tmp_path)
    with pytest.raises(ValueError, match="exactly one"):
        build_publish_body(
            contract=contract if has_file else None, content_type=None, apiome_version=reference,
            branch=None, tags=None, build_url=None, verification_results=None,
        )


def test_the_summary_names_the_verdict_and_the_comparisons() -> None:
    lines = summary_lines(_response(), created=True)
    assert lines[0] == "Provider contract of Ledger API abc123 published"
    assert "self-verification: verified (junit, by dredd) — provider contract verified" in lines[2]
    assert any("tests: 1 total, 1 passed" in line for line in lines)
    assert lines[-1] == "    Billing Service 2.0.0: pass"


def test_an_unverified_summary_gives_the_reasons_and_the_policy() -> None:
    response = _response("failed", False, reasons=["the report records 1 failed"])
    lines = summary_lines(response, created=False)
    assert lines[0].endswith("already published (unchanged)")
    assert "provider contract UNVERIFIED" in lines[2]
    assert "    reason: the report records 1 failed" in lines
    assert "    its bi-directional comparisons read 'unverified' (warn)" in lines
    assert not is_verified(response)


def test_the_path_escapes_every_segment() -> None:
    assert provider_contract_path("acme", "Ledger API", "1.0/rc") == (
        "/v1/tenants/acme/pact-broker/contracts/provider/Ledger%20API/version/1.0%2Frc"
    )


# --- the command -------------------------------------------------------------------------------


@pytest.mark.usefixtures("api_key_env")
def test_publish_sends_the_contract_and_the_evidence(tmp_path: Path, httpx_mock: Any) -> None:
    contract, report = _files(tmp_path)
    httpx_mock.add_response(url=_URL, method="PUT", json=_response(), status_code=201)
    result = runner.invoke(
        app,
        ["pact", "publish-provider-contract", str(contract), "--provider", "Ledger API",
         "--provider-app-version", "abc123", "--branch", "main", "--evidence", str(report), "--verifier", "dredd"],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "provider contract verified" in result.output
    sent = json.loads(httpx_mock.get_requests()[0].content)
    assert sent["verificationResults"]["contentType"] == "application/xml"
    assert base64.b64decode(sent["verificationResults"]["content"]) == _JUNIT
    assert base64.b64decode(sent["content"]) == _OAS
    assert sent["branch"] == "main"


@pytest.mark.usefixtures("api_key_env")
def test_fail_on_unverified_exits_1(tmp_path: Path, httpx_mock: Any) -> None:
    contract, _ = _files(tmp_path)
    httpx_mock.add_response(url=_URL, method="PUT", json=_response("missing", False), status_code=201)
    result = runner.invoke(
        app,
        ["pact", "publish-provider-contract", str(contract), "--provider", "Ledger API",
         "--provider-app-version", "abc123", "--fail-on-unverified"],
    )
    assert result.exit_code == EXIT_ERROR, result.output
    assert "UNVERIFIED" in result.output


@pytest.mark.usefixtures("api_key_env")
def test_unverified_without_the_flag_still_exits_0(tmp_path: Path, httpx_mock: Any) -> None:
    contract, _ = _files(tmp_path)
    httpx_mock.add_response(url=_URL, method="PUT", json=_response("missing", False), status_code=201)
    result = runner.invoke(
        app, ["pact", "publish-provider-contract", str(contract), "--provider", "Ledger API", "-a", "abc123"]
    )
    assert result.exit_code == EXIT_SUCCESS, result.output


@pytest.mark.usefixtures("api_key_env")
def test_json_mode_prints_the_response(tmp_path: Path, httpx_mock: Any) -> None:
    contract, _ = _files(tmp_path)
    httpx_mock.add_response(url=_URL, method="PUT", json=_response(), status_code=200)
    result = runner.invoke(
        app,
        ["--json", "pact", "publish-provider-contract", str(contract), "--provider", "Ledger API", "-a", "abc123"],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.output)["selfVerification"]["status"] == "verified"


@pytest.mark.usefixtures("api_key_env")
def test_a_refused_report_exits_2_with_the_server_message(tmp_path: Path, httpx_mock: Any) -> None:
    contract, report = _files(tmp_path)
    detail = {
        "code": "provider-contract-evidence-invalid",
        "message": "the report is not well-formed XML",
        "pointer": "/verificationResults/content",
    }
    httpx_mock.add_response(url=_URL, method="PUT", json={"detail": detail}, status_code=422)
    result = runner.invoke(
        app,
        ["pact", "publish-provider-contract", str(contract), "--provider", "Ledger API", "-a", "abc123",
         "--evidence", str(report)],
    )
    assert result.exit_code == EXIT_USAGE, result.output


@pytest.mark.usefixtures("api_key_env")
def test_both_evidence_options_are_a_usage_error(tmp_path: Path) -> None:
    contract, report = _files(tmp_path)
    result = runner.invoke(
        app,
        ["pact", "publish-provider-contract", str(contract), "--provider", "Ledger API", "-a", "abc123",
         "--evidence", str(report), "--evidence-report", "6f1c2b3a-4d5e-4f60-8a7b-9c0d1e2f3a4b"],
    )
    assert result.exit_code == EXIT_USAGE
    assert "not both" in result.output


@pytest.mark.usefixtures("api_key_env")
def test_neither_a_file_nor_an_apiome_version_is_a_usage_error() -> None:
    result = runner.invoke(app, ["pact", "publish-provider-contract", "--provider", "Ledger API", "-a", "abc123"])
    assert result.exit_code == EXIT_USAGE
