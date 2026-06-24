"""Endpoint tests for the quality-scoring / lint API (#3609)."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.app.auth import validate_authentication
from src.app.main import app

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}

PID = "00000000-0000-0000-0000-0000000000a1"
VID = "00000000-0000-0000-0000-0000000000b1"
BASE_VID = "00000000-0000-0000-0000-0000000000b0"

HEAD_SPEC = {
    "openapi": "3.1.0",
    "info": {"title": "Payments", "version": "1.0.0"},  # missing description -> a finding
    "paths": {},
    "components": {
        "schemas": {
            "Payment": {
                "type": "object",
                "description": "A payment.",
                "properties": {
                    "amount": {"type": "integer", "description": "cents", "example": 1},
                },
            }
        }
    },
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


def test_lint_returns_score_and_findings():
    with patch("src.app.lint_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "src.app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("src.app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["score"], int)
    assert body["grade"] in {"A", "B", "C", "D", "F"}
    assert body["versionRecordId"] == VID
    assert body["versionId"] == "1.0.0"
    assert "reportFingerprint" in body
    rules = {f["rule"] for f in body["findings"]}
    assert "documentation.info-missing-description" in rules
    assert body["baseRevisionId"] is None
    assert body["compatibilityOverall"] is None


def test_lint_is_deterministic_for_fixed_input():
    with patch("src.app.lint_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "src.app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("src.app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC):
        a = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()
        b = client.get(f"/v1/versions/acme/{PID}/{VID}/lint").json()
    assert a["reportFingerprint"] == b["reportFingerprint"]
    assert a["score"] == b["score"]


def test_lint_project_not_found():
    with patch("src.app.lint_routes.db.get_project_by_id", return_value=None):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint")
    assert r.status_code == 404


def test_lint_revision_not_found():
    with patch("src.app.lint_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "src.app.lint_routes.db.get_version_by_id", return_value=None
    ):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint")
    assert r.status_code == 404


def test_lint_revision_wrong_project():
    other = {"id": VID, "project_id": "different", "version_id": "1.0.0", "metadata": None}
    with patch("src.app.lint_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "src.app.lint_routes.db.get_version_by_id", return_value=other
    ):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint")
    assert r.status_code == 400


def test_lint_with_base_revision_folds_compatibility():
    rows = {VID: _version_row(VID), BASE_VID: _version_row(BASE_VID)}
    with patch("src.app.lint_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "src.app.lint_routes.db.get_version_by_id", side_effect=lambda vid, tid: rows.get(vid)
    ), patch("src.app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint?baseRevisionId={BASE_VID}")
    assert r.status_code == 200
    body = r.json()
    assert body["baseRevisionId"] == BASE_VID
    # Identical head/base specs are compatible.
    assert body["compatibilityOverall"] == "safe"


def test_lint_base_revision_must_differ():
    with patch("src.app.lint_routes.db.get_project_by_id", return_value={"id": PID}), patch(
        "src.app.lint_routes.db.get_version_by_id", return_value=_version_row(VID)
    ), patch("src.app.lint_routes.openapi_for_revision", return_value=HEAD_SPEC):
        r = client.get(f"/v1/versions/acme/{PID}/{VID}/lint?baseRevisionId={VID}")
    assert r.status_code == 400
