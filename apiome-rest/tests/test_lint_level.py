"""Maturity levels in policy evaluations and the ``/lint/level`` reads — GVM-1.2 (#5855).

The database is mocked: these cover how :mod:`app.lint_policy_service` stores the level
(``gate_results.maturity`` + ``maturity_level``), surfaces the stored evaluation's id and time,
gathers ladder evidence, shapes the level response (including ``reason: no-ladder``), the lint
gate's matching maturity block, and both routes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.lint_evidence import SUBJECT_CATALOG_REVISION, SUBJECT_MCP_ENDPOINT_VERSION
from app.lint_policy_service import (
    build_lint_policy_response,
    ladder_evidence,
    level_response,
)
from app.main import app

client = TestClient(app)

_JWT = {"tenant_id": "t1", "user_id": "u1", "email": "a@b.c"}
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)

LADDER = {
    "name": "Maturity",
    "levels": [
        {
            "key": "bronze",
            "label": "Bronze",
            "rules": [{"ruleId": "naming.a", "maxSeverity": "warning"}],
            "axes": [],
            "evidence": [],
            "waiversSatisfy": True,
        },
        {
            "key": "silver",
            "label": "Silver",
            "rules": [],
            "axes": [{"axis": "quality", "minGrade": "B"}],
            "evidence": ["review_approved"],
            "waiversSatisfy": False,
        },
    ],
}


@pytest.fixture(autouse=True)
def _auth_override():
    app.dependency_overrides[validate_authentication] = lambda: _JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _pack(ladder=None):
    return {
        "id": "pv1",
        "guide_id": "g1",
        "version_number": 1,
        "content_fingerprint": "abc",
        "rules_snapshot": [],
        "axis_gates": {},
        "required_coverage": ["quality"],
        "ci_outcomes": {},
        "ladder": ladder,
    }


def _build(pack, *, findings=(), axes=None, evidence=None, stored=None):
    with patch(
        "app.lint_policy_service.db.record_lint_policy_evaluation_row",
        return_value=stored,
    ) as record:
        response = build_lint_policy_response(
            tenant_id="t1",
            subject_type=SUBJECT_CATALOG_REVISION,
            subject_id="v1",
            project_id="p1",
            policy_version=pack,
            findings=list(findings),
            axes=axes,
            evidence_run_id=None,
            axis_evaluation_id=None,
            evidence_fingerprint="ef",
            decisions=[],
            evidence=evidence,
        )
    return response, record


# ---------------------------------------------------------------------------
# Storing the level
# ---------------------------------------------------------------------------


def test_a_pack_with_a_ladder_stores_the_level_in_gate_results_and_the_column():
    response, record = _build(
        _pack(LADDER),
        axes=[{"axis": "quality", "assessed": True, "grade": "A", "score": 95}],
        evidence={"review_approved": True},
        stored={"id": "e1", "evaluated_at": NOW, "reused": False},
    )
    row = record.call_args.args[0]
    assert row["maturity_level"] == "silver"
    assert row["gate_results"]["maturity"]["level"] == "silver"
    # The CLX-1.3 gates are untouched.
    assert {"unwaived_errors", "required_coverage", "axis_gates"} <= set(row["gate_results"])
    assert response.evaluation.gate_results["maturity"]["level"] == "silver"
    assert response.evaluation.id == "e1"
    assert response.evaluation.evaluated_at == NOW.isoformat()


def test_a_pack_without_a_ladder_stores_no_maturity_block():
    _response, record = _build(_pack(None), stored={"id": "e1", "evaluated_at": NOW})
    row = record.call_args.args[0]
    assert "maturity" not in row["gate_results"]
    assert row["maturity_level"] is None


def test_a_subject_below_the_first_level_stores_a_null_level():
    _response, record = _build(
        _pack(LADDER),
        findings=[{"rule_id": "naming.a", "severity": "error", "source_fingerprint": "f1"}],
        stored={"id": "e1", "evaluated_at": NOW},
    )
    row = record.call_args.args[0]
    assert row["maturity_level"] is None
    assert row["gate_results"]["maturity"]["reason"] == "below-first-level"


def test_a_persistence_fault_still_returns_the_level():
    with patch(
        "app.lint_policy_service.db.record_lint_policy_evaluation_row",
        side_effect=RuntimeError("db down"),
    ):
        response = build_lint_policy_response(
            tenant_id="t1",
            subject_type=SUBJECT_CATALOG_REVISION,
            subject_id="v1",
            project_id="p1",
            policy_version=_pack(LADDER),
            findings=[],
            axes=None,
            evidence_run_id=None,
            axis_evaluation_id=None,
            evidence_fingerprint=None,
            decisions=[],
        )
    assert response.evaluation.id is None
    assert response.evaluation.gate_results["maturity"]["level"] == "bronze"


# ---------------------------------------------------------------------------
# The level response
# ---------------------------------------------------------------------------


def test_level_response_without_a_ladder_is_null_with_reason_no_ladder():
    response, _ = _build(_pack(None), stored={"id": "e1", "evaluated_at": NOW})
    level = level_response(response).model_dump(by_alias=True)
    assert level["level"] is None
    assert level["reason"] == "no-ladder"
    assert level["evaluationId"] == "e1"
    assert level["blockers"] == []


def test_level_response_carries_the_level_next_level_and_blockers():
    response, _ = _build(_pack(LADDER), evidence={"review_approved": False}, stored={"id": "e1", "evaluated_at": NOW})
    level = level_response(response).model_dump(by_alias=True, exclude_none=True)
    assert (level["level"], level["levelLabel"], level["levelIndex"]) == ("bronze", "Bronze", 0)
    assert (level["nextLevel"], level["nextLevelLabel"]) == ("silver", "Silver")
    assert level["unassessedAxes"] == ["quality"]
    kinds = {(b["kind"], b.get("axis") or b.get("evidence"), b["reason"]) for b in level["blockers"]}
    assert kinds == {("axis", "quality", "not_assessed"), ("evidence", "review_approved", "missing")}
    assert all(b["levelKey"] == "silver" for b in level["blockers"])


# ---------------------------------------------------------------------------
# Ladder evidence
# ---------------------------------------------------------------------------


def test_ladder_evidence_reads_only_the_kinds_the_ladder_requires():
    with patch("app.lint_policy_service._review_approved", return_value=True) as review, patch(
        "app.lint_policy_service._verification_passing"
    ) as verification:
        out = ladder_evidence(
            tenant_id="t1",
            subject_type=SUBJECT_CATALOG_REVISION,
            subject_id="v1",
            project_id="p1",
            ladder=LADDER,
        )
    assert out == {"review_approved": True}
    review.assert_called_once_with("t1", "p1", "v1")
    verification.assert_not_called()


def test_ladder_evidence_is_not_assessed_for_mcp_versions():
    with patch("app.lint_policy_service._review_approved") as review:
        out = ladder_evidence(
            tenant_id="t1",
            subject_type=SUBJECT_MCP_ENDPOINT_VERSION,
            subject_id="m1",
            project_id=None,
            ladder=LADDER,
        )
    assert out == {"review_approved": None}
    review.assert_not_called()


def test_an_evidence_fault_degrades_to_not_assessed():
    with patch("app.lint_policy_service._review_approved", side_effect=RuntimeError("boom")):
        out = ladder_evidence(
            tenant_id="t1",
            subject_type=SUBJECT_CATALOG_REVISION,
            subject_id="v1",
            project_id="p1",
            ladder=LADDER,
        )
    assert out == {"review_approved": None}


def test_ladder_evidence_without_a_ladder_is_empty():
    assert (
        ladder_evidence(
            tenant_id="t1",
            subject_type=SUBJECT_CATALOG_REVISION,
            subject_id="v1",
            project_id="p1",
            ladder=None,
        )
        == {}
    )


def test_review_approved_uses_one_approval_when_the_guide_requires_none():
    from app.approval_publish_gate import (
        STATUS_SATISFIED,
        ApprovalGateAssessment,
        ApprovalPolicy,
    )
    from app.lint_policy_service import _review_approved

    with patch("app.lint_policy_service.db.get_version_by_id", return_value={"id": "v1"}), patch(
        "app.approval_publish_gate.resolve_approval_policy", return_value=ApprovalPolicy()
    ), patch(
        "app.approval_publish_gate.assess_approval_gate",
        return_value=ApprovalGateAssessment(status=STATUS_SATISFIED),
    ) as assess:
        assert _review_approved("t1", "p1", "v1") is True
    assert assess.call_args.kwargs["policy"].required_approvals == 1


def test_verification_passing_reads_the_latest_evaluation():
    from app.lint_policy_service import _verification_passing

    with patch(
        "app.lint_policy_service.db.list_verification_policy_evaluations",
        side_effect=[[], [{"passed": True, "gate_results": []}], [{"passed": False, "gate_results": [{"g": 1}]}]],
    ):
        assert _verification_passing("t1", "v1") is None
        assert _verification_passing("t1", "v1") is None  # no gate judged
        assert _verification_passing("t1", "v1") is False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _fake_level():
    from app.models import LintLevelResponse

    return LintLevelResponse(
        subject_type="catalog_revision",
        subject_id="v1",
        evaluation_id="e1",
        evaluated_at=NOW.isoformat(),
        policy_version_id="pv1",
        policy_content_fingerprint="abc",
        ladder_name="Maturity",
        level="bronze",
        level_label="Bronze",
        level_index=0,
        next_level="silver",
        next_level_label="Silver",
        blockers=[],
        unassessed_axes=["quality"],
    )


@patch("app.lint_routes.db")
def test_catalog_level_route_returns_the_level(mdb):
    mdb.get_project_by_id.return_value = {"id": "p1"}
    mdb.get_version_by_id.return_value = {"id": "v1", "project_id": "p1"}
    with patch("app.lint_routes.evaluate_catalog_revision_level", return_value=_fake_level()) as evaluate:
        resp = client.get("/v1/versions/acme/p1/v1/lint/level?policyVersionId=pv1")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["level"], body["nextLevel"], body["evaluationId"]) == ("bronze", "silver", "e1")
    assert body["unassessedAxes"] == ["quality"]
    assert evaluate.call_args.kwargs["policy_version_id"] == "pv1"


@patch("app.lint_routes.db")
def test_catalog_level_route_checks_project_and_revision(mdb):
    mdb.get_project_by_id.return_value = None
    assert client.get("/v1/versions/acme/p1/v1/lint/level").status_code == 404
    mdb.get_project_by_id.return_value = {"id": "p1"}
    mdb.get_version_by_id.return_value = None
    assert client.get("/v1/versions/acme/p1/v1/lint/level").status_code == 404
    mdb.get_version_by_id.return_value = {"id": "v1", "project_id": "other"}
    assert client.get("/v1/versions/acme/p1/v1/lint/level").status_code == 400


@pytest.mark.parametrize("error, status", [(ValueError("no guide"), 409), (LookupError("no pack"), 404)])
@patch("app.lint_routes.db")
def test_catalog_level_route_maps_policy_errors(mdb, error, status):
    mdb.get_project_by_id.return_value = {"id": "p1"}
    mdb.get_version_by_id.return_value = {"id": "v1", "project_id": "p1"}
    with patch("app.lint_routes.evaluate_catalog_revision_level", side_effect=error):
        assert client.get("/v1/versions/acme/p1/v1/lint/level").status_code == status


def test_mcp_level_route_returns_the_level():
    endpoint = "00000000-0000-0000-0000-0000000000e1"
    version = "00000000-0000-0000-0000-0000000000f1"
    with patch("app.mcp_catalog_routes._require_tenant_endpoint"), patch(
        "app.mcp_catalog_routes.db.get_mcp_endpoint_version", return_value={"id": version}
    ), patch(
        "app.lint_policy_service.evaluate_mcp_version_level", return_value=_fake_level()
    ) as evaluate:
        resp = client.get(f"/v1/mcp/acme/endpoints/{endpoint}/versions/{version}/lint/level")
    assert resp.status_code == 200, resp.text
    assert resp.json()["level"] == "bronze"
    assert evaluate.call_args.kwargs["version_id"] == version


def test_mcp_level_route_404s_for_an_unknown_version():
    endpoint = "00000000-0000-0000-0000-0000000000e1"
    version = "00000000-0000-0000-0000-0000000000f1"
    with patch("app.mcp_catalog_routes._require_tenant_endpoint"), patch(
        "app.mcp_catalog_routes.db.get_mcp_endpoint_version", return_value=None
    ):
        resp = client.get(f"/v1/mcp/acme/endpoints/{endpoint}/versions/{version}/lint/level")
    assert resp.status_code == 404
