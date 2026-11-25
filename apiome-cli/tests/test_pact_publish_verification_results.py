"""Tests for ``apiome pact publish-verification-results`` — PFX-3.5 (#6935).

The CLI interprets no report: it names the report's media type, builds the query and POSTs the file
to the external-verification-results endpoint, then prints the verdict and the server's notices.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from typer.testing import CliRunner

from apiome_cli.client.pact_external_verification import (
    external_results_path,
    report_content_type,
    summary_lines,
)
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()

_SHA = "ab" * 32
_BASE = f"http://localhost:8000/v1/tenants/acme-corp/pact-broker/pacts/provider/Ledger%20API/consumer/Billing/pact-version/{_SHA}"
_REPORT = b'{"result": false, "errors": [{"interactionId": "a1", "mismatch": "404"}]}'


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def _response(success: bool = False, **extra: Any) -> dict[str, Any]:
    return {
        "providerName": "Ledger API",
        "providerApplicationVersion": "abc123",
        "success": success,
        "_links": {"self": {"href": f"{_BASE}/verification-results/1"}},
        "ingestion": {
            "format": "pact-verifier-json",
            "interactions": 1,
            "notices": [
                {
                    "pointer": "/output",
                    "reason": "1 line(s) of verifier log output are not stored",
                }
            ],
            **extra,
        },
    }


def _invoke(*extra: str, report: Path, **kwargs: Any) -> Any:
    return runner.invoke(
        app,
        [
            "pact",
            "publish-verification-results",
            str(report),
            "--provider",
            "Ledger API",
            "--consumer",
            "Billing",
            "--pact-version",
            _SHA,
            "--provider-app-version",
            "abc123",
            *extra,
        ],
        **kwargs,
    )


# --- pure helpers ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("r.json", "application/json"),
        ("r.XML", "application/xml"),
        ("r.txt", "application/octet-stream"),
    ],
)
def test_the_content_type_comes_from_the_extension(name: str, expected: str) -> None:
    assert report_content_type(Path(name), None) == expected
    assert report_content_type(Path(name), "text/xml") == "text/xml"


def test_the_path_carries_the_version_and_only_the_options_given() -> None:
    path = external_results_path(
        "acme-corp", "Ledger API", "Billing", _SHA, provider_app_version="abc 123"
    )
    assert path.startswith(
        "/v1/tenants/acme-corp/pact-broker/pacts/provider/Ledger%20API/consumer/Billing/"
    )
    assert parse_qs(urlparse(path).query) == {"providerApplicationVersion": ["abc 123"]}


def test_every_option_reaches_the_query() -> None:
    path = external_results_path(
        "acme-corp",
        "p",
        "c",
        _SHA,
        provider_app_version="1",
        build_url="https://ci/1",
        branch="main",
        tags=["prod", "qa"],
        report_format="junit",
        verifier="jest",
        verifier_version="29",
        report_id="r-1",
    )
    assert parse_qs(urlparse(path).query) == {
        "providerApplicationVersion": ["1"],
        "buildUrl": ["https://ci/1"],
        "branch": ["main"],
        "format": ["junit"],
        "verifier": ["jest"],
        "verifierVersion": ["29"],
        "providerVerificationReportId": ["r-1"],
        "tag": ["prod", "qa"],
    }


def test_an_unknown_format_is_refused() -> None:
    with pytest.raises(ValueError):
        external_results_path(
            "t", "p", "c", _SHA, provider_app_version="1", report_format="tap"
        )


def test_the_summary_shows_the_verdict_and_every_notice() -> None:
    lines = summary_lines(_response())
    assert (
        lines[0]
        == "Verification of Ledger API abc123 FAILED (pact-verifier-json report, 1 interaction(s))"
    )
    assert lines[1].endswith("/verification-results/1")
    assert lines[2] == "  note /output: 1 line(s) of verifier log output are not stored"
    assert "passed" in summary_lines(_response(True))[0]


# --- the command -------------------------------------------------------------------------------


def test_the_report_is_posted_as_is(
    tmp_path: Path, api_key_env: None, httpx_mock: Any
) -> None:
    report = tmp_path / "report.json"
    report.write_bytes(_REPORT)
    httpx_mock.add_response(
        url=f"{_BASE}/external-verification-results?providerApplicationVersion=abc123&branch=main&tag=prod",
        method="POST",
        json=_response(),
        status_code=201,
    )
    result = _invoke("--branch", "main", "--tag", "prod", report=report)
    assert result.exit_code == EXIT_SUCCESS, result.output
    request = httpx_mock.get_requests()[0]
    assert request.content == _REPORT
    assert request.headers["content-type"] == "application/json"
    assert "FAILED" in result.output and "note /output" in result.output


def test_junit_is_sent_as_xml(
    tmp_path: Path, api_key_env: None, httpx_mock: Any
) -> None:
    report = tmp_path / "junit.xml"
    report.write_bytes(b"<testsuite><testcase name='a'/></testsuite>")
    httpx_mock.add_response(
        method="POST", json=_response(True, format="junit"), status_code=201
    )
    result = _invoke(report=report)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert httpx_mock.get_requests()[0].headers["content-type"] == "application/xml"
    assert "passed (junit report" in result.output


def test_fail_on_failure_exits_1_only_for_a_failed_result(
    tmp_path: Path, api_key_env: None, httpx_mock: Any
) -> None:
    report = tmp_path / "report.json"
    report.write_bytes(_REPORT)
    httpx_mock.add_response(method="POST", json=_response(False), status_code=201)
    httpx_mock.add_response(method="POST", json=_response(True), status_code=201)
    assert _invoke("--fail-on-failure", report=report).exit_code == EXIT_ERROR
    assert _invoke("--fail-on-failure", report=report).exit_code == EXIT_SUCCESS


def test_json_mode_prints_the_response(
    tmp_path: Path, api_key_env: None, httpx_mock: Any
) -> None:
    report = tmp_path / "report.json"
    report.write_bytes(_REPORT)
    httpx_mock.add_response(method="POST", json=_response(), status_code=201)
    result = runner.invoke(
        app,
        [
            "--json",
            "pact",
            "publish-verification-results",
            str(report),
            "--provider",
            "p",
            "--consumer",
            "c",
            "--pact-version",
            _SHA,
            "--provider-app-version",
            "1",
        ],
    )
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.output)["ingestion"]["format"] == "pact-verifier-json"


def test_a_refused_report_exits_2_with_the_server_message(
    tmp_path: Path, api_key_env: None, httpx_mock: Any
) -> None:
    report = tmp_path / "report.json"
    report.write_bytes(b"{}")
    httpx_mock.add_response(
        method="POST",
        status_code=422,
        json={
            "detail": {
                "code": "pact-verification-invalid",
                "message": "(report): proves nothing",
                "pointer": "",
            }
        },
    )
    result = _invoke(report=report)
    assert result.exit_code == EXIT_USAGE or result.exit_code == 2
    assert "proves nothing" in result.output


def test_an_unknown_format_is_a_usage_error_before_any_request(
    tmp_path: Path, api_key_env: None, httpx_mock: Any
) -> None:
    report = tmp_path / "report.json"
    report.write_bytes(_REPORT)
    result = _invoke("--format", "tap", report=report)
    assert result.exit_code == 2
    assert httpx_mock.get_requests() == []
