"""``apiome sdk compatibility`` — SGD-2.1 (#4735).

The command renders the generator compatibility manifest from ``GET …/sdk-compatibility``. The mocked
response is apiome-rest's **golden manifest** (``apiome-rest/tests/golden/sdk_compat_manifest/
widgets.json``) — the same file the REST builder test pins and the dashboard's view-model test
renders — so the CLI and the dashboard are proven to read one document.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import EXIT_QUALITY_GATE, EXIT_SUCCESS
from apiome_cli.main import app
from apiome_cli.sdk_compat_output import all_findings, fails_threshold, render_manifest

pytestmark = pytest.mark.usefixtures("api_key_env")

runner = CliRunner()

GOLDEN = Path(__file__).resolve().parents[2] / "apiome-rest" / "tests" / "golden" / "sdk_compat_manifest" / "widgets.json"
MANIFEST = json.loads(GOLDEN.read_text())
URL = "http://localhost:8000/v1/tenants/acme-corp/projects/widgets/sdk-compatibility"


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


def test_it_renders_findings_with_their_actions(httpx_mock) -> None:
    httpx_mock.add_response(url=URL, json=MANIFEST)
    result = runner.invoke(app, ["sdk", "compatibility", "--project", "widgets"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    out = result.stdout
    assert f"{MANIFEST['findings_count']} finding(s)" in out
    for finding in all_findings(MANIFEST):
        assert f"{finding['artifact']} · {finding['code']} · {finding['subject']}" in out
        assert finding["action"] in out
    for artifact in MANIFEST["artifacts"]:
        assert artifact["id"] in out
    assert "pagination: manual (cursor, limit)" in out
    assert "Semver: non-breaking since 0.9.0" in out


def test_findings_come_before_artifacts(httpx_mock) -> None:
    httpx_mock.add_response(url=URL, json=MANIFEST)
    out = runner.invoke(app, ["sdk", "compatibility", "--project", "widgets"]).stdout
    assert out.index("Findings") < out.index("Artifacts")


def test_json_prints_the_manifest_as_served(httpx_mock) -> None:
    httpx_mock.add_response(url=URL, json=MANIFEST)
    result = runner.invoke(app, ["--json", "sdk", "compatibility", "--project", "widgets"])
    assert result.exit_code == EXIT_SUCCESS
    assert json.loads(result.stdout) == MANIFEST


def test_a_version_is_passed_as_a_query(httpx_mock) -> None:
    httpx_mock.add_response(url=f"{URL}?version=1.0.0", json=MANIFEST)
    result = runner.invoke(app, ["sdk", "compatibility", "--project", "widgets", "--version", "1.0.0"])
    assert result.exit_code == EXIT_SUCCESS


@pytest.mark.parametrize(("fail_on", "code"), [("warning", EXIT_QUALITY_GATE), ("error", EXIT_SUCCESS)])
def test_fail_on_gates_on_severity(httpx_mock, fail_on, code) -> None:
    httpx_mock.add_response(url=URL, json=MANIFEST)
    result = runner.invoke(app, ["sdk", "compatibility", "--project", "widgets", "--fail-on", fail_on])
    assert result.exit_code == code


def test_an_unknown_fail_on_is_a_usage_error() -> None:
    result = runner.invoke(app, ["sdk", "compatibility", "--project", "widgets", "--fail-on", "fatal"])
    assert result.exit_code == 2


def test_a_clean_manifest_says_so() -> None:
    clean = {**MANIFEST, "findings_count": 0, "artifacts": [{**a, "findings": []} for a in MANIFEST["artifacts"]]}
    assert "No findings" in "\n".join(render_manifest(clean))
    assert fails_threshold(clean, "info") is False


def test_findings_are_sorted_most_severe_first() -> None:
    error = {"severity": "error", "artifact": "z", "subject": "s", "code": "artifact-not-generated"}
    manifest = {**MANIFEST, "artifacts": [{**MANIFEST["artifacts"][0], "findings": [*MANIFEST["artifacts"][0]["findings"], error]}]}
    assert all_findings(manifest)[0]["severity"] == "error"


def test_an_unknown_semver_is_explained() -> None:
    unknown = {**MANIFEST, "semver": {"classification": "unknown"}}
    assert "Semver: unknown" in "\n".join(render_manifest(unknown))
