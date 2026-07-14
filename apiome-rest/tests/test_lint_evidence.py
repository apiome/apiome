"""Revision-scoped lint evidence contract (CLX-1.1, #4848).

Covers the three layers of the evidence substrate:

- ``app.lint_evidence`` — the source-neutral finding envelope, redacted config fingerprints,
  outcome derivation, evidence-run builders, and the coverage view (a scanner that never ran
  must read ``not_run``, never clean).
- Persistence wiring — ``set_version_quality_score`` / ``set_mcp_version_score`` mirror every
  persisted native report into ``lint_evidence_runs`` without changing their own behaviour,
  and ``record_lint_evidence_run`` skips fingerprints that are already evidenced.
- The two read routes — ``GET …/lint/evidence`` for schema revisions and MCP endpoint
  versions — including tenant scoping and raw-artifact redaction (availability flag only,
  never the storage reference).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database
from app.lint_evidence import (
    COVERAGE_FULL,
    COVERAGE_PARTIAL,
    ENVELOPE_VERSION,
    MCP_CONFORMANCE_SCANNER_ID,
    MCP_POSTURE_SCANNER_ID,
    MCP_SCANNER_ID,
    NATIVE_ADAPTER_VERSION,
    NATIVE_SCANNER_ID,
    OUTCOME_FINDINGS,
    OUTCOME_NOT_RUN,
    OUTCOME_PASSED,
    SUBJECT_CATALOG_REVISION,
    SUBJECT_MCP_ENDPOINT_VERSION,
    coverage_entries,
    expected_scanners_for_subject,
    mcp_conformance_evidence_run,
    mcp_evidence_run,
    native_evidence_run,
    normalize_native_finding,
    normalize_native_findings,
    outcome_for_report,
    redacted_config_fingerprint,
)
from app.main import app
from app.schema_lint import lint_openapi_spec

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)

_REV = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_EP = "11111111-1111-1111-1111-111111111111"
_V1 = "22222222-2222-2222-2222-222222222222"
_RUN = "33333333-3333-3333-3333-333333333333"

_LEGACY_FINDING = {
    "id": "lint-abc123",
    "path": "components.schemas.pet",
    "category": "naming",
    "rule": "naming.schema-pascal-case",
    "severity": "warning",
    "message": "Component schema names should be PascalCase.",
}

_ENVELOPE_KEYS = {
    "rule_id",
    "message",
    "severity",
    "confidence",
    "category",
    "location",
    "remediation",
    "source_fingerprint",
}


def _report(findings=None, fingerprint="fp-1"):
    """A native report dict in the ``LintResult.report_dict()`` shape."""
    findings = list(findings) if findings is not None else [_LEGACY_FINDING]
    return {
        "score": 90,
        "grade": "A",
        "report_fingerprint": fingerprint,
        "rule_hits": {},
        "severity_counts": {"error": 0, "warning": len(findings), "info": 0},
        "findings": findings,
        "categories": [],
    }


def _evidence_row(**overrides):
    """A ``lint_evidence_runs`` row as the list queries return it."""
    row = {
        "id": _RUN,
        "subject_type": SUBJECT_CATALOG_REVISION,
        "version_record_id": _REV,
        "mcp_version_id": None,
        "scanner_id": NATIVE_SCANNER_ID,
        "scanner_version": None,
        "adapter_version": NATIVE_ADAPTER_VERSION,
        "profile": "import-capture",
        "started_at": None,
        "finished_at": None,
        "outcome": OUTCOME_FINDINGS,
        "input_fingerprint": None,
        "source_fingerprint": None,
        "config_fingerprint": None,
        "raw_artifact_ref": None,
        "report_fingerprint": "fp-1",
        "findings": [normalize_native_finding(_LEGACY_FINDING)],
        "coverage": {"state": COVERAGE_FULL},
        "envelope_version": ENVELOPE_VERSION,
        "created_at": _NOW,
    }
    row.update(overrides)
    return row


# ===========================================================================
# Finding envelope
# ===========================================================================


def test_envelope_maps_every_legacy_field():
    env = normalize_native_finding(_LEGACY_FINDING)
    assert set(env) == _ENVELOPE_KEYS
    assert env["rule_id"] == "naming.schema-pascal-case"
    assert env["message"] == _LEGACY_FINDING["message"]
    assert env["severity"] == "warning"
    assert env["category"] == "naming"
    assert env["location"] == {"path": "components.schemas.pet"}
    assert env["remediation"] is None
    # The engine's stable finding id survives as the source-local identity.
    assert env["source_fingerprint"] == "lint-abc123"


def test_envelope_confidence_is_high_for_deterministic_native_lint():
    assert normalize_native_finding(_LEGACY_FINDING)["confidence"] == "high"


def test_envelope_tolerates_missing_fields():
    env = normalize_native_finding({})
    assert set(env) == _ENVELOPE_KEYS
    assert env["rule_id"] is None and env["source_fingerprint"] is None
    assert env["location"] == {"path": None}


def test_normalize_native_findings_preserves_order():
    first = dict(_LEGACY_FINDING, id="lint-1")
    second = dict(_LEGACY_FINDING, id="lint-2")
    out = normalize_native_findings([first, second])
    assert [f["source_fingerprint"] for f in out] == ["lint-1", "lint-2"]


def test_envelope_matches_real_engine_output():
    """The envelope maps real schema_lint findings, and the run preserves the real fingerprint."""
    result = lint_openapi_spec({"openapi": "3.0.0", "info": {"title": "t"}, "paths": {}})
    run = native_evidence_run(_REV, result.report_dict())
    assert run["report_fingerprint"] == result.report_fingerprint
    assert len(run["findings"]) == len(result.findings)
    for env in run["findings"]:
        assert set(env) == _ENVELOPE_KEYS
        assert env["rule_id"]


# ===========================================================================
# Redacted config fingerprint
# ===========================================================================


def test_config_fingerprint_none_for_absent_config():
    assert redacted_config_fingerprint(None) is None
    assert redacted_config_fingerprint({}) is None


def test_config_fingerprint_is_stable_and_secret_blind():
    base = {"profile": "strict", "api_token": "s3cr3t", "nested": {"password": "x"}}
    rotated = {"profile": "strict", "api_token": "rotated!", "nested": {"password": "y"}}
    # Rotating secrets must not change the fingerprint (their values are redacted pre-hash) …
    assert redacted_config_fingerprint(base) == redacted_config_fingerprint(rotated)
    # … but changing non-secret configuration must.
    changed = dict(base, profile="lenient")
    assert redacted_config_fingerprint(base) != redacted_config_fingerprint(changed)


def test_config_fingerprint_is_a_hash_not_content():
    fp = redacted_config_fingerprint({"api_token": "s3cr3t"})
    assert len(fp) == 64 and "s3cr3t" not in fp


# ===========================================================================
# Outcomes and run builders
# ===========================================================================


def test_outcome_findings_vs_passed():
    assert outcome_for_report(_report()) == OUTCOME_FINDINGS
    assert outcome_for_report(_report(findings=[])) == OUTCOME_PASSED


def test_native_evidence_run_shape():
    run = native_evidence_run(_REV, _report(), config={"guide": "default", "token": "s"})
    assert run["subject_type"] == SUBJECT_CATALOG_REVISION
    assert run["version_record_id"] == _REV
    assert "mcp_version_id" not in run
    assert run["scanner_id"] == NATIVE_SCANNER_ID
    assert run["adapter_version"] == NATIVE_ADAPTER_VERSION
    assert run["outcome"] == OUTCOME_FINDINGS
    assert run["report_fingerprint"] == "fp-1"
    assert run["coverage"] == {"state": COVERAGE_FULL}
    assert run["envelope_version"] == ENVELOPE_VERSION
    assert run["config_fingerprint"] and len(run["config_fingerprint"]) == 64
    assert run["raw_artifact_ref"] is None
    assert set(run["findings"][0]) == _ENVELOPE_KEYS


def test_mcp_evidence_run_shape():
    run = mcp_evidence_run(_V1, _report(findings=[]), input_fingerprint="surface-fp")
    assert run["subject_type"] == SUBJECT_MCP_ENDPOINT_VERSION
    assert run["mcp_version_id"] == _V1
    assert "version_record_id" not in run
    assert run["scanner_id"] == MCP_SCANNER_ID
    assert run["outcome"] == OUTCOME_PASSED
    assert run["input_fingerprint"] == "surface-fp"
    assert run["findings"] == []


def _conformance_report(*, findings=None, skipped_rules=(), fingerprint="conf-fp"):
    """A conformance report in the ``ConformanceReport.report_dict()`` shape (CLX-3.1)."""
    findings = list(findings) if findings is not None else [_MCP_CONFORMANCE_FINDING]
    return {
        "profile": "mcp-conformance",
        "spec_version": "2025-06-18",
        "score": 88,
        "grade": "B",
        "report_fingerprint": fingerprint,
        "rule_hits": {},
        "severity_counts": {"error": 0, "warning": 0, "info": len(findings)},
        "findings": findings,
        "evaluated_rules": ["protocol.declared-capability-empty"],
        "skipped_rules": list(skipped_rules),
        "transcript_captured": not skipped_rules,
        "gate": {"passed": True, "fail_on": "error", "min_score": None, "reasons": []},
    }


_MCP_CONFORMANCE_FINDING = {
    "id": "mcp-conf-abc123",
    "path": "surface.capabilities.prompts",
    "category": "protocol",
    "rule": "protocol.declared-capability-empty",
    "severity": "info",
    "message": "Server declared the 'prompts' capability but listed no prompts.",
}


def test_mcp_conformance_evidence_run_is_stamped_with_its_own_scanner():
    """The conformance run is a distinct scanner, normalized into the shared envelope."""
    run = mcp_conformance_evidence_run(_V1, _conformance_report(), input_fingerprint="surface-fp")
    assert run["subject_type"] == SUBJECT_MCP_ENDPOINT_VERSION
    assert run["mcp_version_id"] == _V1
    assert "version_record_id" not in run
    # Not the surface-lint scanner: the two engines must never be conflated in evidence.
    assert run["scanner_id"] == MCP_CONFORMANCE_SCANNER_ID
    assert run["scanner_id"] != MCP_SCANNER_ID
    assert run["adapter_version"] == NATIVE_ADAPTER_VERSION
    assert run["envelope_version"] == ENVELOPE_VERSION
    assert run["outcome"] == OUTCOME_FINDINGS
    assert run["report_fingerprint"] == "conf-fp"
    assert run["input_fingerprint"] == "surface-fp"

    envelope = run["findings"][0]
    assert set(envelope) == _ENVELOPE_KEYS
    assert envelope["rule_id"] == "protocol.declared-capability-empty"
    assert envelope["category"] == "protocol"
    assert envelope["severity"] == "info"
    assert envelope["location"] == {"path": "surface.capabilities.prompts"}
    assert envelope["source_fingerprint"] == "mcp-conf-abc123"


def test_mcp_conformance_evidence_run_coverage_is_full_when_nothing_was_skipped():
    """A transcript-backed run covered its subject completely."""
    run = mcp_conformance_evidence_run(_V1, _conformance_report(findings=[]))
    assert run["outcome"] == OUTCOME_PASSED
    assert run["coverage"] == {"state": COVERAGE_FULL}


def test_mcp_conformance_evidence_run_coverage_is_partial_when_rules_were_skipped():
    """A run with no transcript is PARTIAL coverage carrying the skipped ids — never clean.

    Without this, a recompute-from-database run (which cannot evaluate the transcript-backed
    rules at all) would be indistinguishable from a run that observed the server's protocol
    behaviour and found it conformant.
    """
    skipped = ["protocol.list-result-missing-items", "protocol.response-id-not-echoed"]
    run = mcp_conformance_evidence_run(
        _V1, _conformance_report(findings=[], skipped_rules=skipped)
    )
    coverage = run["coverage"]
    assert coverage["state"] == COVERAGE_PARTIAL
    assert coverage["state"] != COVERAGE_FULL
    assert coverage["skipped_rules"] == skipped
    assert "transcript" in coverage["reason"]
    # A clean-but-partial run still reports "passed" for what it *did* evaluate; coverage is the
    # field that keeps the unevaluated half honest.
    assert run["outcome"] == OUTCOME_PASSED


# ===========================================================================
# Coverage view — absent scans are visible, never clean
# ===========================================================================


def test_expected_scanners_per_subject():
    assert expected_scanners_for_subject(SUBJECT_CATALOG_REVISION) == [NATIVE_SCANNER_ID]
    # An MCP snapshot is covered by three native engines: the surface lint, the
    # protocol-conformance / agent-readiness scanner (CLX-3.1, #4855), and the source /
    # supply-chain / trust-posture scanner (CLX-3.2, #4856). All are *expected*, so a snapshot
    # that has never been scanned by one of them renders as not_run rather than silently clean.
    assert expected_scanners_for_subject(SUBJECT_MCP_ENDPOINT_VERSION) == [
        MCP_SCANNER_ID,
        MCP_CONFORMANCE_SCANNER_ID,
        MCP_POSTURE_SCANNER_ID,
    ]


def test_coverage_synthesizes_not_run_for_missing_scanner():
    entries = coverage_entries([], [NATIVE_SCANNER_ID])
    assert len(entries) == 1
    entry = entries[0]
    assert entry["scanner_id"] == NATIVE_SCANNER_ID
    assert entry["outcome"] == OUTCOME_NOT_RUN
    assert entry["coverage"] == {"state": "none"}
    assert entry["run_id"] is None and entry["recorded_at"] is None


def test_coverage_uses_most_recent_run_per_scanner():
    newer = _evidence_row(id="newer", outcome=OUTCOME_PASSED, created_at=_NOW)
    older = _evidence_row(id="older", outcome=OUTCOME_FINDINGS)
    entries = coverage_entries([newer, older], [NATIVE_SCANNER_ID])
    assert len(entries) == 1
    assert entries[0]["run_id"] == "newer"
    assert entries[0]["outcome"] == OUTCOME_PASSED


def test_coverage_keeps_unexpected_scanners_visible():
    external = _evidence_row(id="ext-run", scanner_id="buf.lint", outcome=OUTCOME_FINDINGS)
    entries = coverage_entries([external], [NATIVE_SCANNER_ID])
    assert [e["scanner_id"] for e in entries] == [NATIVE_SCANNER_ID, "buf.lint"]
    assert entries[0]["outcome"] == OUTCOME_NOT_RUN  # expected scanner never ran
    assert entries[1]["outcome"] == OUTCOME_FINDINGS  # historical evidence stays listed


# ===========================================================================
# Persistence wiring — every persisted native report is evidenced
# ===========================================================================


def _bare_db():
    """A Database instance with a recording ``execute_query`` and no real connection."""
    inst = Database.__new__(Database)
    calls = []

    def fake_execute_query(query, params=None):
        calls.append((" ".join(query.split()), params))
        return [{"id": _RUN, "surface_fingerprint": "surface-fp"}]

    inst.execute_query = fake_execute_query
    return inst, calls


def test_set_version_quality_score_records_evidence():
    inst, calls = _bare_db()
    assert inst.set_version_quality_score(_REV, "t1", 90, "A", "fp-1", quality_report=_report())
    queries = [q for q, _ in calls]
    assert any("UPDATE apiome.versions" in q for q in queries)
    evidence = [(q, p) for q, p in calls if "INSERT INTO apiome.lint_evidence_runs" in q]
    assert len(evidence) == 1
    _, params = evidence[0]
    assert SUBJECT_CATALOG_REVISION in params and NATIVE_SCANNER_ID in params


def test_set_version_quality_score_skips_evidence_without_fingerprint():
    inst, calls = _bare_db()
    inst.set_version_quality_score(_REV, "t1", 90, "A", None, quality_report=None)
    assert not any("lint_evidence_runs" in q for q, _ in calls)


def test_set_version_quality_score_survives_evidence_failure():
    """Evidence capture is strictly additive: its failure must not break score persistence."""
    inst, calls = _bare_db()
    original = inst.execute_query

    def flaky(query, params=None):
        if "lint_evidence_runs" in query:
            raise RuntimeError("evidence substrate down")
        return original(query, params)

    inst.execute_query = flaky
    assert inst.set_version_quality_score(_REV, "t1", 90, "A", "fp-1", quality_report=_report())


def test_set_mcp_version_score_records_evidence_with_surface_fingerprint():
    inst, calls = _bare_db()
    assert inst.set_mcp_version_score(
        _V1, score=90, grade="A", report=_report(), report_fingerprint="fp-1"
    )
    evidence = [(q, p) for q, p in calls if "INSERT INTO apiome.lint_evidence_runs" in q]
    assert len(evidence) == 1
    _, params = evidence[0]
    assert SUBJECT_MCP_ENDPOINT_VERSION in params and MCP_SCANNER_ID in params
    assert "surface-fp" in params  # looked up from the snapshot row
    assert any("surface_fingerprint FROM apiome.mcp_endpoint_versions" in q for q, _ in calls)


def test_set_mcp_version_score_skips_evidence_for_placeholder_rows():
    inst, calls = _bare_db()
    inst.set_mcp_version_score(_V1, score=None, grade=None, report={}, report_fingerprint=None)
    assert not any("lint_evidence_runs" in q for q, _ in calls)


def test_record_lint_evidence_run_dedupes_by_fingerprint():
    """The insert is guarded so an already-evidenced fingerprint is not appended again."""
    inst, calls = _bare_db()
    inst.record_lint_evidence_run(native_evidence_run(_REV, _report()))
    query, params = calls[0]
    assert "WHERE NOT EXISTS" in query
    assert "RETURNING id" in query
    # The dedupe guard keys on scanner + fingerprint + subject.
    assert params.count(NATIVE_SCANNER_ID) == 2
    assert params.count("fp-1") == 2


# ===========================================================================
# GET /v1/versions/{tenant}/{project}/{rev}/lint/evidence
# ===========================================================================


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _revision_rows():
    return {"id": _REV, "project_id": "proj-1", "version_id": "1.0.0"}


def test_revision_evidence_lists_runs_and_coverage():
    with patch("app.lint_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1"}
        mdb.get_version_by_id.return_value = _revision_rows()
        mdb.get_version_source_projection.return_value = None
        mdb.list_lint_evidence_runs_for_version.return_value = [
            _evidence_row(raw_artifact_ref="s3://bucket/raw.json")
        ]
        r = client.get(f"/v1/versions/acme/proj-1/{_REV}/lint/evidence")
    assert r.status_code == 200
    body = r.json()
    assert body["subjectType"] == SUBJECT_CATALOG_REVISION
    assert body["subjectId"] == _REV
    assert body["count"] == 1
    run = body["runs"][0]
    assert run["scannerId"] == NATIVE_SCANNER_ID
    assert run["outcome"] == OUTCOME_FINDINGS
    assert run["reportFingerprint"] == "fp-1"
    assert run["envelopeVersion"] == ENVELOPE_VERSION
    assert run["recordedAt"] == _NOW.isoformat()
    finding = run["findings"][0]
    assert finding["ruleId"] == "naming.schema-pascal-case"
    assert finding["sourceFingerprint"] == "lint-abc123"
    assert finding["location"] == {"path": "components.schemas.pet"}
    # Coverage lists the native scanner as covered by this run.
    assert body["coverage"][0]["scannerId"] == NATIVE_SCANNER_ID
    assert body["coverage"][0]["runId"] == _RUN
    # Tenant scoping flows into the evidence query.
    mdb.list_lint_evidence_runs_for_version.assert_called_once_with(_REV, "t1")


def test_revision_evidence_redacts_raw_artifact_reference():
    with patch("app.lint_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1"}
        mdb.get_version_by_id.return_value = _revision_rows()
        mdb.get_version_source_projection.return_value = None
        mdb.list_lint_evidence_runs_for_version.return_value = [
            _evidence_row(raw_artifact_ref="s3://bucket/raw.json")
        ]
        r = client.get(f"/v1/versions/acme/proj-1/{_REV}/lint/evidence")
    run = r.json()["runs"][0]
    assert run["rawArtifactAvailable"] is True
    assert "s3://bucket/raw.json" not in r.text
    assert "rawArtifactRef" not in run and "raw_artifact_ref" not in run


def test_revision_evidence_never_displays_missing_scan_as_clean():
    """A never-scored revision has zero runs — coverage must read not_run, not passed."""
    with patch("app.lint_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1"}
        mdb.get_version_by_id.return_value = _revision_rows()
        mdb.get_version_source_projection.return_value = None
        mdb.list_lint_evidence_runs_for_version.return_value = []
        r = client.get(f"/v1/versions/acme/proj-1/{_REV}/lint/evidence")
    body = r.json()
    assert body["count"] == 0 and body["runs"] == []
    assert len(body["coverage"]) == 1
    entry = body["coverage"][0]
    assert entry["outcome"] == OUTCOME_NOT_RUN
    assert entry["coverage"] == {"state": "none"}
    assert entry["runId"] is None


def test_revision_evidence_404s():
    with patch("app.lint_routes.db") as mdb:
        mdb.get_project_by_id.return_value = None
        assert client.get(f"/v1/versions/acme/nope/{_REV}/lint/evidence").status_code == 404
    with patch("app.lint_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1"}
        mdb.get_version_by_id.return_value = None
        assert client.get(f"/v1/versions/acme/proj-1/{_REV}/lint/evidence").status_code == 404


def test_revision_evidence_rejects_cross_project_revision():
    with patch("app.lint_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1"}
        mdb.get_version_by_id.return_value = {"id": _REV, "project_id": "other-project"}
        r = client.get(f"/v1/versions/acme/proj-1/{_REV}/lint/evidence")
    assert r.status_code == 400


# ===========================================================================
# GET /v1/mcp/{tenant}/endpoints/{id}/versions/{vid}/lint/evidence
# ===========================================================================

_ENDPOINT_ROW = {"id": _EP, "tenant_id": "t1", "name": "Acme", "slug": "acme"}


def _mcp_row(**overrides):
    return _evidence_row(
        subject_type=SUBJECT_MCP_ENDPOINT_VERSION,
        version_record_id=None,
        mcp_version_id=_V1,
        scanner_id=MCP_SCANNER_ID,
        profile="discovery-capture",
        input_fingerprint="surface-fp",
        finished_at=_NOW,
        **overrides,
    )


def test_mcp_evidence_lists_runs_and_coverage():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = {"id": _V1, "endpoint_id": _EP}
        mdb.list_lint_evidence_runs_for_mcp_version.return_value = [_mcp_row()]
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint/evidence")
    assert r.status_code == 200
    body = r.json()
    assert body["subjectType"] == SUBJECT_MCP_ENDPOINT_VERSION
    assert body["subjectId"] == _V1
    run = body["runs"][0]
    assert run["scannerId"] == MCP_SCANNER_ID
    assert run["inputFingerprint"] == "surface-fp"
    assert run["finishedAt"] == _NOW.isoformat()
    assert body["coverage"][0]["scannerId"] == MCP_SCANNER_ID


def test_mcp_evidence_not_run_when_never_scored():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = {"id": _V1, "endpoint_id": _EP}
        mdb.list_lint_evidence_runs_for_mcp_version.return_value = []
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint/evidence")
    body = r.json()
    assert body["coverage"][0]["outcome"] == OUTCOME_NOT_RUN
    assert body["coverage"][0]["coverage"] == {"state": "none"}


def test_mcp_evidence_404_on_foreign_tenant_endpoint():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint/evidence")
    assert r.status_code == 404


def test_mcp_evidence_404_on_unknown_version():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint/evidence")
    assert r.status_code == 404
