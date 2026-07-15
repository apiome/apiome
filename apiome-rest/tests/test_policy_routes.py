"""Route-level tests for policy packs and finding decisions (CLX-1.3, #4850)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.policy_evaluate import evaluate_policy

client = TestClient(app)

_JWT = {"tenant_id": "t1", "user_id": "u1", "email": "a@b.c"}


@pytest.fixture(autouse=True)
def _auth_override():
    app.dependency_overrides[validate_authentication] = lambda: _JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_evaluate_policy_separates_raw_from_decision():
    now = datetime(2026, 7, 14, tzinfo=timezone.utc)
    ev = evaluate_policy(
        findings=[
            {
                "source_fingerprint": "lint-1",
                "severity": "error",
                "rule_id": "r1",
            }
        ],
        decisions_by_fingerprint={
            "lint-1": {
                "state": "waived",
                "expires_at": now + timedelta(days=1),
                "rationale": "ok",
            }
        },
        axes=[{"key": "quality", "assessed": True, "grade": "A", "score": 95}],
        now=now,
    )
    row = ev.finding_decisions[0]
    assert row["raw_severity"] == "error"
    assert row["effective_state"] == "waived"
    assert row["waived"] is True
    assert ev.passed is True


@patch("app.lint_routes.db")
def test_upsert_waiver_requires_rationale_and_expiry(mdb):
    resp = client.post(
        "/v1/lint/decisions",
        json={
            "sourceFingerprint": "lint-x",
            "state": "waived",
            "rationale": "   ",
            "expiresAt": "2026-08-01T00:00:00Z",
        },
    )
    assert resp.status_code == 400
    assert "rationale" in resp.json()["detail"].lower()

    resp2 = client.post(
        "/v1/lint/decisions",
        json={
            "sourceFingerprint": "lint-x",
            "state": "waived",
            "rationale": "accepted",
        },
    )
    assert resp2.status_code == 400
    assert "expires" in resp2.json()["detail"].lower()


@patch("app.lint_routes.db")
def test_upsert_waiver_persists(mdb):
    # The CLX-4.1 guard resolves the current decision (none) and authorizes via the
    # mocked db (user_has_permission on a MagicMock is truthy).
    mdb.list_lint_finding_decisions.return_value = []
    mdb.upsert_lint_finding_decision.return_value = {
        "id": "d1",
        "tenant_id": "t1",
        "project_id": None,
        "source_fingerprint": "lint-x",
        "rule_id": "r1",
        "state": "waived",
        "owner_user_id": None,
        "rationale": "accepted",
        "linked_ticket": None,
        "expires_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "policy_version_id": None,
        "evidence_fingerprint_at_decision": "lint-x",
        "actor_user_id": "u1",
        "actor_label": "u1",
        "created_at": datetime(2026, 7, 14, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 7, 14, tzinfo=timezone.utc),
    }
    resp = client.post(
        "/v1/lint/decisions",
        json={
            "sourceFingerprint": "lint-x",
            "state": "waived",
            "rationale": "accepted",
            "expiresAt": "2026-08-01T00:00:00Z",
            "ruleId": "r1",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["state"] == "waived"
    assert body["sourceFingerprint"] == "lint-x"
    mdb.upsert_lint_finding_decision.assert_called_once()


@patch("app.lint_routes.db")
def test_lint_policy_route_returns_evaluation(mdb):
    mdb.get_project_by_id.return_value = {"id": "p1", "tenant_id": "t1"}
    mdb.get_version_by_id.return_value = {"id": "v1", "project_id": "p1"}

    from app.models import (
        LintPolicyEvaluationOut,
        LintPolicyResponse,
        StyleGuideCiOutcomesOut,
        StyleGuidePolicyVersionOut,
    )

    fake = LintPolicyResponse(
        policy_version=StyleGuidePolicyVersionOut(
            id="pv1",
            guide_id="g1",
            version_number=1,
            content_fingerprint="abc",
            axis_gates={},
            required_coverage=["quality"],
            ci_outcomes=StyleGuideCiOutcomesOut(),
        ),
        evaluation=LintPolicyEvaluationOut(
            id=None,
            subject_type="catalog_revision",
            subject_id="v1",
            policy_version_id="pv1",
            policy_content_fingerprint="abc",
            passed=True,
            gate_results={},
        ),
        findings=[],
    )

    with patch(
        "app.lint_routes.evaluate_catalog_revision_policy", return_value=fake
    ):
        resp = client.get("/v1/versions/slug/p1/v1/lint/policy")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["evaluation"]["passed"] is True
    assert body["policyVersion"]["id"] == "pv1"
