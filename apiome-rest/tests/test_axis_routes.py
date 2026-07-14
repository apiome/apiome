"""API tests for multi-axis score routes (CLX-1.2, #4849)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.axis_score import ALGORITHM_ID, AXIS_KEYS
from app.lint_evidence import SUBJECT_CATALOG_REVISION, SUBJECT_MCP_ENDPOINT_VERSION
from app.main import app

client = TestClient(app)

_REV = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_MCP_EP = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_MCP_VER = "cccccccc-cccc-cccc-cccc-cccccccccccc"
_NOW = datetime(2026, 7, 14, 18, 0, 0, tzinfo=timezone.utc)

_JWT_T1 = {"tenant_id": "t1", "user_id": "u1", "email": "a@b.c"}


def _axes_payload():
    return [
        {
            "key": "quality",
            "label": "Quality",
            "weight": 1.0,
            "assessed": True,
            "score": 90,
            "grade": "A",
            "severity_counts": {"error": 0, "warning": 0, "info": 0},
            "coverage": {"state": "full"},
            "not_assessed_reason": None,
        },
        {
            "key": "protocol",
            "label": "Protocol",
            "weight": 1.0,
            "assessed": False,
            "score": None,
            "grade": None,
            "severity_counts": {"error": 0, "warning": 0, "info": 0},
            "coverage": {"state": "none"},
            "not_assessed_reason": "No protocol-conformance scanner evidence yet",
        },
        {
            "key": "security",
            "label": "Security",
            "weight": 1.0,
            "assessed": False,
            "score": None,
            "grade": None,
            "severity_counts": {"error": 0, "warning": 0, "info": 0},
            "coverage": {"state": "none"},
            "not_assessed_reason": "No security scanner evidence for catalog revisions yet",
        },
        {
            "key": "supply_chain",
            "label": "Supply chain",
            "weight": 1.0,
            "assessed": False,
            "score": None,
            "grade": None,
            "severity_counts": {"error": 0, "warning": 0, "info": 0},
            "coverage": {"state": "none"},
            "not_assessed_reason": "No supply-chain scanner evidence yet",
        },
        {
            "key": "supportability",
            "label": "Supportability",
            "weight": 1.0,
            "assessed": False,
            "score": None,
            "grade": None,
            "severity_counts": {"error": 0, "warning": 0, "info": 0},
            "coverage": {"state": "none"},
            "not_assessed_reason": "No supportability scanner evidence yet",
        },
        {
            "key": "compatibility",
            "label": "Compatibility",
            "weight": 1.0,
            "assessed": False,
            "score": None,
            "grade": None,
            "severity_counts": {"error": 0, "warning": 0, "info": 0},
            "coverage": {"state": "none"},
            "not_assessed_reason": "No base-revision compatibility evidence",
        },
    ]


def _eval_row(**overrides):
    row = {
        "id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "subject_type": SUBJECT_CATALOG_REVISION,
        "version_record_id": _REV,
        "mcp_version_id": None,
        "algorithm_id": ALGORITHM_ID,
        "algorithm_version": "1",
        "axes": _axes_payload(),
        "composite_score": 90,
        "composite_grade": "A",
        "required_coverage_met": True,
        "source_report_fingerprint": "fp-1",
        "evaluated_at": _NOW,
        "created_at": _NOW,
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def test_revision_axes_returns_stored_evaluation():
    with patch("app.lint_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1"}
        mdb.get_version_by_id.return_value = {
            "id": _REV,
            "project_id": "proj-1",
            "version_id": "1.0.0",
        }
        mdb.get_latest_axis_evaluation_for_version.return_value = _eval_row()
        r = client.get(f"/v1/versions/acme/proj-1/{_REV}/lint/axes")
    assert r.status_code == 200
    body = r.json()
    ev = body["evaluation"]
    assert ev["subjectType"] == SUBJECT_CATALOG_REVISION
    assert ev["subjectId"] == _REV
    assert ev["algorithmId"] == ALGORITHM_ID
    assert ev["algorithmVersion"] == "1"
    assert ev["compositeScore"] == 90
    assert ev["requiredCoverageMet"] is True
    keys = [a["key"] for a in ev["axes"]]
    assert keys == list(AXIS_KEYS)
    quality = ev["axes"][0]
    assert quality["assessed"] is True and quality["score"] == 90
    protocol = next(a for a in ev["axes"] if a["key"] == "protocol")
    assert protocol["assessed"] is False
    assert protocol["score"] is None
    assert protocol["notAssessedReason"]
    assert protocol["coverage"]["state"] == "none"
    mdb.get_latest_axis_evaluation_for_version.assert_called_once_with(_REV, "t1")


def test_revision_axes_computes_when_missing():
    with patch("app.lint_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1"}
        mdb.get_version_by_id.return_value = {
            "id": _REV,
            "project_id": "proj-1",
            "version_id": "1.0.0",
        }
        mdb.get_latest_axis_evaluation_for_version.return_value = None
        mdb.get_version_quality_score.return_value = {
            "quality_score": 88,
            "quality_grade": "B",
            "quality_report_fingerprint": "fp-2",
            "quality_report": {
                "score": 88,
                "grade": "B",
                "findings": [],
                "severity_counts": {"error": 0, "warning": 0, "info": 0},
                "report_fingerprint": "fp-2",
            },
        }
        mdb.record_axis_evaluation.return_value = "new-id"
        r = client.get(f"/v1/versions/acme/proj-1/{_REV}/lint/axes")
    assert r.status_code == 200
    ev = r.json()["evaluation"]
    assert ev["algorithmId"] == ALGORITHM_ID
    assert ev["compositeScore"] == 88
    assert ev["axes"][0]["score"] == 88
    assert mdb.record_axis_evaluation.called


def test_revision_axes_404s():
    with patch("app.lint_routes.db") as mdb:
        mdb.get_project_by_id.return_value = None
        assert client.get(f"/v1/versions/acme/nope/{_REV}/lint/axes").status_code == 404


def test_mcp_axes_returns_stored_evaluation():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = {"id": _MCP_EP, "tenant_id": "t1"}
        mdb.get_mcp_endpoint_version.return_value = {
            "id": _MCP_VER,
            "version_seq": 1,
            "version_tag": None,
        }
        mcp_row = _eval_row(
            subject_type=SUBJECT_MCP_ENDPOINT_VERSION,
            version_record_id=None,
            mcp_version_id=_MCP_VER,
            axes=[
                *_axes_payload()[:2],
                {
                    "key": "security",
                    "label": "Security",
                    "weight": 1.0,
                    "assessed": True,
                    "score": 100,
                    "grade": "A",
                    "severity_counts": {"error": 0, "warning": 0, "info": 0},
                    "coverage": {"state": "full"},
                    "not_assessed_reason": None,
                },
                *_axes_payload()[3:],
            ],
        )
        mdb.get_latest_axis_evaluation_for_mcp_version.return_value = mcp_row
        r = client.get(
            f"/v1/mcp/acme/endpoints/{_MCP_EP}/versions/{_MCP_VER}/lint/axes"
        )
    assert r.status_code == 200
    ev = r.json()["evaluation"]
    assert ev["subjectType"] == SUBJECT_MCP_ENDPOINT_VERSION
    assert ev["subjectId"] == _MCP_VER
    security = next(a for a in ev["axes"] if a["key"] == "security")
    assert security["assessed"] is True
    assert security["score"] == 100


def test_not_assessed_never_serialized_as_zero_score():
    with patch("app.lint_routes.db") as mdb:
        mdb.get_project_by_id.return_value = {"id": "proj-1"}
        mdb.get_version_by_id.return_value = {
            "id": _REV,
            "project_id": "proj-1",
            "version_id": "1.0.0",
        }
        mdb.get_latest_axis_evaluation_for_version.return_value = _eval_row()
        r = client.get(f"/v1/versions/acme/proj-1/{_REV}/lint/axes")
    for axis in r.json()["evaluation"]["axes"]:
        if not axis["assessed"]:
            assert axis["score"] is None
            assert axis["grade"] is None
            assert axis["notAssessedReason"]
            assert axis["coverage"]["state"] == "none"
