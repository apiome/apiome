"""Endpoint tests for the lint CI gate (CLX-4.2, #4860)."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}

PID = "00000000-0000-0000-0000-0000000000a1"
VID = "00000000-0000-0000-0000-0000000000b1"
BASE_VID = "00000000-0000-0000-0000-0000000000b0"
EP_ID = "00000000-0000-0000-0000-0000000000e1"
MCP_VID = "00000000-0000-0000-0000-0000000000c1"

SECRET_MARKER = "SECRETVALUE-abc123"

PACK = {
    "id": "00000000-0000-0000-0000-0000000000f1",
    "guide_id": "g1",
    "version_number": 1,
    "content_fingerprint": "packfp",
    "rules_snapshot": [],
    "axis_gates": {},
    "required_coverage": ["quality"],
    "ci_outcomes": {
        "failOnUnwaivedErrors": True,
        "failOnRequiredCoverage": True,
        "failOnAxisGates": True,
    },
}

AXIS_ROW = {
    "id": "00000000-0000-0000-0000-0000000000d1",
    "axes": [{"key": "quality", "assessed": True, "grade": "B", "score": 82}],
}


def _finding(fp: str, severity: str = "error", rule: str = "naming.rule") -> dict:
    return {
        "rule_id": rule,
        "message": f"finding {fp}",
        "severity": severity,
        "confidence": "high",
        "category": "naming",
        "location": {"path": "openapi.yaml", "start_line": 3, "start_column": 1},
        "remediation": None,
        "source_fingerprint": fp,
    }


def _run(run_id: str, scanner: str, findings: list, created: str) -> dict:
    return {
        "id": run_id,
        "subject_type": "catalog_revision",
        "version_record_id": VID,
        "mcp_version_id": None,
        "scanner_id": scanner,
        "scanner_version": "1.0",
        "adapter_version": "adapter-1",
        "profile": "default",
        "outcome": "findings" if findings else "passed",
        "input_fingerprint": f"input-{run_id}",
        "source_fingerprint": f"source-{run_id}",
        "config_fingerprint": f"config-{run_id}",
        "raw_artifact_ref": f"s3://bucket/{SECRET_MARKER}/{run_id}",
        "report_fingerprint": f"report-{run_id}",
        "findings": findings,
        "coverage": {"state": "full"},
        "envelope_version": 1,
        "created_at": created,
    }


def _override_auth():
    return _MOCK_AUTH


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = _override_auth
    yield
    app.dependency_overrides.clear()


def _version_row(vid: str):
    return {"id": vid, "project_id": PID, "version_id": "1.0.0", "metadata": None}


def _gate_patches(
    evidence_rows,
    *,
    decisions=None,
    baseline_rows=None,
    record_id="eval-1",
):
    """Standard patch stack for the catalog gate route."""

    def list_runs(vid, _tid):
        if baseline_rows is not None and vid == BASE_VID:
            return baseline_rows
        return evidence_rows

    return [
        patch("app.lint_routes.db.get_project_by_id", return_value={"id": PID}),
        patch(
            "app.lint_routes.db.get_version_by_id",
            side_effect=lambda vid, _tid: _version_row(vid),
        ),
        patch("app.lint_gate.resolve_policy_pack", return_value=dict(PACK)),
        patch("app.lint_gate.db.list_lint_evidence_runs_for_version", side_effect=list_runs),
        patch("app.lint_gate.db.get_version_quality_score", return_value={}),
        patch("app.lint_gate.db.get_latest_axis_evaluation_for_version", return_value=AXIS_ROW),
        patch(
            "app.lint_gate.db.list_lint_finding_decisions",
            return_value=list(decisions or []),
        ),
        patch("app.lint_gate.db.record_lint_policy_evaluation", return_value=record_id),
        patch(
            "app.lint_gate.db.list_active_push_webhook_subscription_ids", return_value=[]
        ),
    ]


def _get_gate(query: str = "", headers: dict | None = None):
    stack = _gate_patches(
        [
            _run("r2", "spectral", [_finding("fp-c", "warning", "spectral.rule")], "2026-07-02"),
            _run("r1", "apiome.lint", [_finding("fp-a"), _finding("fp-b", "info")], "2026-07-01"),
        ]
    )
    with stack[0], stack[1], stack[2], stack[3], stack[4], stack[5], stack[6], stack[7], stack[8]:
        return client.get(f"/v1/versions/acme/{PID}/{VID}/lint/gate{query}", headers=headers)


def test_gate_json_happy_path():
    r = _get_gate()
    assert r.status_code == 200
    body = r.json()
    assert body["subjectType"] == "catalog_revision"
    assert body["subjectId"] == VID
    assert body["policy"]["policyVersionId"] == PACK["id"]
    assert body["policy"]["contentFingerprint"] == "packfp"
    # fp-a is an unwaived error -> both the evaluation and the CI verdict fail.
    assert body["evaluation"]["passed"] is False
    assert body["gate"]["passed"] is False
    assert body["evaluation"]["evaluationId"] == "eval-1"
    assert body["counts"]["total"] == 3
    assert body["counts"]["unwaivedErrors"] == 1
    # Scanners merge in sorted id order: apiome.lint first, then spectral.
    assert [f["scannerId"] for f in body["findings"]] == [
        "apiome.lint",
        "apiome.lint",
        "spectral",
    ]
    # Per-scanner provenance carries fingerprints + evidence run ids (AC-4).
    scanners = {s["scannerId"]: s for s in body["scanners"]}
    assert scanners["apiome.lint"]["reportFingerprint"] == "report-r1"
    assert scanners["apiome.lint"]["inputFingerprint"] == "input-r1"
    assert scanners["spectral"]["evidenceRunId"] == "r2"
    # Finding/evidence links for CI output (AC-1).
    assert body["links"]["evidence"].endswith(f"{VID}/lint/evidence")
    assert body["links"]["policy"].endswith(f"{VID}/lint/policy")


def test_gate_persists_exactly_one_evaluation():
    stack = _gate_patches([_run("r1", "apiome.lint", [_finding("fp-a")], "2026-07-01")])
    with stack[0], stack[1], stack[2], stack[3], stack[4], stack[5], stack[6], stack[7] as rec, stack[8]:
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint/gate")
    assert r.status_code == 200
    assert rec.call_count == 1
    row = rec.call_args[0][0]
    assert row["subject_type"] == "catalog_revision"
    assert row["version_record_id"] == VID
    assert row["policy_version_id"] == PACK["id"]


def test_gate_baseline_compare_marks_regressions():
    head = [
        _run("r1", "apiome.lint", [_finding("fp-a"), _finding("fp-b")], "2026-07-02"),
        _run("r2", "newscanner", [_finding("fp-x")], "2026-07-02"),
    ]
    baseline = [_run("r0", "apiome.lint", [_finding("fp-a")], "2026-07-01")]
    stack = _gate_patches(head, baseline_rows=baseline)
    with stack[0], stack[1], stack[2], stack[3], stack[4], stack[5], stack[6], stack[7], stack[8]:
        r = client.get(
            f"/v1/versions/acme/{PID}/{VID}/lint/gate?baselineRevisionId={BASE_VID}"
        )
    assert r.status_code == 200
    body = r.json()
    # fp-b is new vs baseline; fp-x's scanner is absent from baseline -> all-new.
    assert sorted(body["newFingerprints"]) == ["fp-b", "fp-x"]
    flags = {f["sourceFingerprint"]: f["isNew"] for f in body["findings"]}
    assert flags == {"fp-a": False, "fp-b": True, "fp-x": True}
    assert body["baselineSubjectId"] == BASE_VID


def test_gate_baseline_must_belong_to_project():
    with patch("app.lint_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id",
        side_effect=lambda vid, _tid: (
            {"id": vid, "project_id": "other-project"} if vid == BASE_VID else _version_row(vid)
        ),
    ):
        r = client.get(
            f"/v1/versions/acme/{PID}/{VID}/lint/gate?baselineRevisionId={BASE_VID}"
        )
    assert r.status_code == 400
    assert "Baseline revision" in r.json()["detail"]


def test_gate_baseline_must_differ_from_head():
    with patch("app.lint_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id",
        side_effect=lambda vid, _tid: _version_row(vid),
    ):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint/gate?baselineRevisionId={VID}")
    assert r.status_code == 400


def test_gate_new_only_ignores_preexisting_errors():
    # Newest run repeats fp-a (error) from the scanner's previous run: not new.
    head = [
        _run("r2", "apiome.lint", [_finding("fp-a")], "2026-07-02"),
        _run("r1", "apiome.lint", [_finding("fp-a")], "2026-07-01"),
    ]
    stack = _gate_patches(head)
    with stack[0], stack[1], stack[2], stack[3], stack[4], stack[5], stack[6], stack[7], stack[8]:
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint/gate?newOnly=true")
    body = r.json()
    # Full evaluation still fails (the error exists) but the CI verdict passes (AC-3).
    assert body["evaluation"]["passed"] is False
    assert body["gate"]["passed"] is True
    assert body["newFingerprints"] == []


def test_gate_new_only_fails_on_new_error():
    head = [
        _run("r2", "apiome.lint", [_finding("fp-a"), _finding("fp-new")], "2026-07-02"),
        _run("r1", "apiome.lint", [_finding("fp-a")], "2026-07-01"),
    ]
    stack = _gate_patches(head)
    with stack[0], stack[1], stack[2], stack[3], stack[4], stack[5], stack[6], stack[7], stack[8]:
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint/gate?newOnly=true")
    body = r.json()
    assert body["gate"]["passed"] is False
    assert body["newFingerprints"] == ["fp-new"]


def _waived_decision(fp: str) -> dict:
    return {
        "id": "00000000-0000-0000-0000-0000000000aa",
        "tenant_id": "t1",
        "project_id": PID,
        "source_fingerprint": fp,
        "rule_id": "naming.rule",
        "state": "waived",
        "rationale": "accepted risk",
        "linked_ticket": None,
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "policy_version_id": PACK["id"],
    }


def test_gate_waived_error_passes_and_sarif_suppresses():
    head = [_run("r1", "apiome.lint", [_finding("fp-a")], "2026-07-01")]
    stack = _gate_patches(head, decisions=[_waived_decision("fp-a")])
    with stack[0], stack[1], stack[2], stack[3], stack[4], stack[5], stack[6], stack[7], stack[8]:
        rj = client.get(f"/v1/versions/acme/{PID}/{VID}/lint/gate")
    body = rj.json()
    assert body["gate"]["passed"] is True
    assert body["findings"][0]["waived"] is True
    assert body["findings"][0]["effectiveState"] == "waived"

    stack = _gate_patches(head, decisions=[_waived_decision("fp-a")])
    with stack[0], stack[1], stack[2], stack[3], stack[4], stack[5], stack[6], stack[7], stack[8]:
        rs = client.get(f"/v1/versions/acme/{PID}/{VID}/lint/gate?format=sarif")
    assert rs.status_code == 200
    assert rs.headers["content-type"].startswith("application/sarif+json")
    sarif = json.loads(rs.text)
    result = sarif["runs"][0]["results"][0]
    assert result["suppressions"][0] == {
        "kind": "external",
        "status": "accepted",
        "justification": "accepted risk",
    }
    assert result["properties"]["apiome"]["policyState"] == "waived"


def test_gate_sarif_preserves_rules_locations_and_provenance():
    r = _get_gate("?format=sarif")
    sarif = json.loads(r.text)
    assert sarif["$schema"].endswith("sarif-2.1.0.json")
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    # Verbatim scanner rule ids (AC-2), never prefixed.
    rule_ids = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
    assert rule_ids == {"naming.rule", "spectral.rule"}
    result = run["results"][0]
    loc = result["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "openapi.yaml"
    assert loc["region"] == {"startLine": 3, "startColumn": 1}
    assert result["fingerprints"]["primaryLocationLineHash"] == "fp-a"
    assert result["properties"]["apiome"]["scannerId"] == "apiome.lint"
    # Run-level provenance: input/scanner/policy/report fingerprints (AC-4).
    prov = run["properties"]["apiome"]
    assert prov["policy"]["contentFingerprint"] == "packfp"
    report_fps = {s["reportFingerprint"] for s in prov["scanners"]}
    assert report_fps == {"report-r1", "report-r2"}
    assert run["automationDetails"]["id"] == f"apiome/lint-gate/{VID}"


def test_gate_junit_and_markdown_and_accept_negotiation():
    rj = _get_gate("?format=junit")
    assert rj.headers["content-type"].startswith("application/junit+xml")
    assert "<testsuite" in rj.text and 'failures="2"' in rj.text
    assert "apiome.scanner.apiome.lint.reportFingerprint" in rj.text

    rm = _get_gate("?format=markdown")
    assert rm.headers["content-type"].startswith("text/markdown")
    assert "# Apiome lint gate: ❌ FAILED" in rm.text
    assert "packfp" in rm.text

    # Accept-header negotiation without ?format=.
    ra = _get_gate(headers={"accept": "application/sarif+json"})
    assert ra.headers["content-type"].startswith("application/sarif+json")
    json.loads(ra.text)


def test_gate_attestation_signed_and_tamper_evident():
    from app.config import settings
    from app.lint_attestation import verify_attestation_envelope

    with patch.object(settings, "lint_attestation_signing_secret", "topsecret"):
        r = _get_gate("?format=attestation")
    assert r.headers["content-type"].startswith("application/vnd.in-toto+json")
    envelope = json.loads(r.text)
    assert envelope["payloadType"] == "application/vnd.in-toto+json"
    assert envelope["signatures"][0]["alg"] == "hmac-sha256"
    assert verify_attestation_envelope(envelope, "topsecret") is True
    assert verify_attestation_envelope(envelope, "wrongsecret") is False
    tampered = dict(envelope)
    tampered["payload"] = envelope["payload"][:-4] + "AAA="
    assert verify_attestation_envelope(tampered, "topsecret") is False


def test_gate_attestation_unsigned_without_secret():
    from app.config import settings

    with patch.object(settings, "lint_attestation_signing_secret", None):
        r = _get_gate("?format=attestation")
    envelope = json.loads(r.text)
    assert envelope["signatures"] == []
    # Still a well-formed statement with per-scanner report fingerprint subjects.
    import base64

    statement = json.loads(base64.b64decode(envelope["payload"]))
    assert statement["predicateType"] == "https://apiome.dev/attestations/lint-gate/v1"
    subjects = {s["name"]: s["digest"]["apiome-report-fingerprint"] for s in statement["subject"]}
    assert subjects == {"apiome.lint": "report-r1", "spectral": "report-r2"}


def test_gate_artifacts_never_leak_protected_content():
    # The evidence rows carry a raw artifact ref with a secret marker; no emitted format
    # may contain it (AC-5) — artifacts identify inputs by fingerprint only.
    for fmt in ("", "?format=sarif", "?format=junit", "?format=markdown", "?format=attestation"):
        r = _get_gate(fmt)
        assert SECRET_MARKER not in r.text, f"secret leaked in format {fmt or 'json'}"
        assert "raw_artifact_ref" not in r.text and "rawArtifactRef" not in r.text


def test_gate_404s():
    with patch("app.lint_routes.db.get_project_by_id", return_value=None):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint/gate")
    assert r.status_code == 404

    with patch("app.lint_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id",
        side_effect=lambda vid, _tid: _version_row(vid),
    ), patch(
        "app.lint_gate.resolve_policy_pack", side_effect=LookupError("Policy version not found")
    ):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint/gate?policyVersionId=nope")
    assert r.status_code == 404


def test_gate_409_without_style_guide():
    with patch("app.lint_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "app.lint_routes.db.get_version_by_id",
        side_effect=lambda vid, _tid: _version_row(vid),
    ), patch(
        "app.lint_gate.resolve_policy_pack",
        side_effect=ValueError("No assignable style guide for this project"),
    ):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint/gate")
    assert r.status_code == 409


def test_mcp_gate_smoke():
    run = {
        **_run("m1", "apiome.mcp-lint", [_finding("fp-m", "warning")], "2026-07-01"),
        "subject_type": "mcp_endpoint_version",
        "version_record_id": None,
        "mcp_version_id": MCP_VID,
    }
    with patch("app.mcp_catalog_routes._require_tenant_endpoint"), patch(
        "app.mcp_catalog_routes.db.get_mcp_endpoint_version", return_value={"id": MCP_VID}
    ), patch("app.lint_gate.resolve_policy_pack", return_value=dict(PACK)), patch(
        "app.lint_gate.db.list_lint_evidence_runs_for_mcp_version", return_value=[run]
    ), patch("app.lint_gate.db.get_mcp_version_score", return_value={}), patch(
        "app.lint_gate.db.get_latest_axis_evaluation_for_mcp_version", return_value=AXIS_ROW
    ), patch("app.lint_gate.db.list_lint_finding_decisions", return_value=[]), patch(
        "app.lint_gate.db.record_lint_policy_evaluation", return_value="eval-m"
    ), patch(
        "app.lint_gate.db.list_active_push_webhook_subscription_ids", return_value=[]
    ):
        r = client.get(
            f"/v1/mcp/acme/endpoints/{EP_ID}/versions/{MCP_VID}/lint/gate"
        )
    assert r.status_code == 200
    body = r.json()
    assert body["subjectType"] == "mcp_endpoint_version"
    # A lone warning is not an unwaived error: the gate passes.
    assert body["gate"]["passed"] is True
    assert body["scanners"][0]["scannerId"] == "apiome.mcp-lint"
