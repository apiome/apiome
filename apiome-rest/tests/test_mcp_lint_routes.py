"""API tests for MCP version lint — fetch stored / recompute (V2-MCP-21.5 / MCAT-7.5, #3686).

Covers the two tenant-scoped routes added under
``/v1/mcp/{tenant_slug}/endpoints/{id}/versions/{vid}``:

- ``GET  …/versions/{vid}/lint`` — the stored lint report, or a live recompute when unscored
- ``POST …/versions/{vid}/lint`` — recompute the report and persist the refreshed score

The recompute path exercises the real deterministic scorer (:func:`app.mcp_score.score_mcp_surface`)
over a surface reconstructed from mocked capability-item rows, so the score/grade/fingerprint and
their persistence are verified end-to-end without a database.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_NOW = datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc)

_EP = "11111111-1111-1111-1111-111111111111"
_V1 = "22222222-2222-2222-2222-222222222222"

_ENDPOINT_ROW = {
    "id": _EP,
    "tenant_id": "t1",
    "name": "Acme Weather",
    "slug": "acme-weather",
    "endpoint_url": "https://mcp.acme.example/mcp",
    "transport": "streamable_http",
    "visibility": "private",
    "published": False,
    "enabled": True,
    "current_version_id": _V1,
}


def _version_row(version_id=_V1, seq=1, *, tag="2026-06-27T12:00Z"):
    """A row shaped like ``get_mcp_endpoint_version`` returns (identity fields only)."""
    return {
        "id": version_id,
        "endpoint_id": _EP,
        "version_seq": seq,
        "version_tag": tag,
        "protocol_version": "2025-06-18",
        "server_name": "acme",
        "server_title": None,
        "server_version": "1.0.0",
        "instructions": None,
        "capabilities": {"tools": {"listChanged": True}},
        "surface_fingerprint": "fp1",
        "discovered_at": _NOW,
        "created_at": _NOW,
    }


def _tool_row(name, description, ordinal=0):
    """A minimal ``mcp_capability_items`` row for a tool."""
    return {
        "version_id": _V1,
        "item_type": "tool",
        "name": name,
        "title": None,
        "description": description,
        "input_schema": {"type": "object"},
        "output_schema": None,
        "annotations": None,
        "uri": None,
        "uri_template": None,
        "raw": {},
        "ordinal": ordinal,
    }


def _stored_report():
    """A persisted ``mcp_version_scores.report`` JSONB payload (full key set)."""
    return {
        "score": 84,
        "grade": "B",
        "report_fingerprint": "deadbeef",
        "rule_hits": {"naming.tool-snake-case": 1},
        "severity_counts": {"error": 0, "warning": 1, "info": 0},
        "findings": [
            {
                "id": "mcp-lint-abc",
                "path": "tools.getWeather",
                "category": "naming",
                "rule": "naming.tool-snake-case",
                "severity": "warning",
                "message": "Tool name should be snake_case.",
            }
        ],
    }


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# GET …/lint — stored report
# ===========================================================================


def test_get_lint_returns_stored_report():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row()
        mdb.get_mcp_version_score.return_value = {
            "score": 84,
            "grade": "B",
            "report": _stored_report(),
            "report_fingerprint": "deadbeef",
            "scored_at": _NOW,
        }
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "stored"
    assert body["score"] == 84 and body["grade"] == "B"
    assert body["reportFingerprint"] == "deadbeef"
    assert body["scoredAt"] == _NOW.isoformat()
    assert body["versionId"] == _V1 and body["versionSeq"] == 1
    assert body["severityCounts"] == {"error": 0, "warning": 1, "info": 0}
    assert len(body["findings"]) == 1
    assert body["findings"][0]["rule"] == "naming.tool-snake-case"
    # A stored hit must NOT recompute the surface.
    mdb.get_mcp_capability_items.assert_not_called()


def test_get_lint_computes_live_when_unscored():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row()
        mdb.get_mcp_version_score.return_value = None
        mdb.get_mcp_capability_items.return_value = [_tool_row("get_weather", "Get the weather")]
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "computed"
    assert isinstance(body["score"], int) and 0 <= body["score"] <= 100
    assert body["grade"] in {"A", "B", "C", "D", "F"}
    assert body["reportFingerprint"]
    assert body["scoredAt"] is None
    # A GET must stay read-only — no persistence on the compute path.
    mdb.set_mcp_version_score.assert_not_called()


def test_get_lint_computes_live_when_stored_report_empty():
    """A placeholder score row with an empty report falls through to a live recompute."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row()
        mdb.get_mcp_version_score.return_value = {
            "score": None,
            "grade": None,
            "report": {},
            "report_fingerprint": None,
            "scored_at": _NOW,
        }
        mdb.get_mcp_capability_items.return_value = [_tool_row("get_weather", "Get the weather")]
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint")
    assert r.status_code == 200
    assert r.json()["source"] == "computed"
    mdb.get_mcp_capability_items.assert_called_once_with(_V1)


def test_get_lint_scoped_to_token_tenant():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row()
        mdb.get_mcp_version_score.return_value = {
            "score": 84, "grade": "B", "report": _stored_report(),
            "report_fingerprint": "deadbeef", "scored_at": _NOW,
        }
        client.get(f"/v1/mcp/other-slug/endpoints/{_EP}/versions/{_V1}/lint")
        mdb.get_mcp_endpoint.assert_called_once_with("t1", _EP)


def test_get_lint_endpoint_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint")
    assert r.status_code == 404
    mdb.get_mcp_endpoint_version.assert_not_called()


def test_get_lint_version_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint")
    assert r.status_code == 404
    mdb.get_mcp_version_score.assert_not_called()


def test_get_lint_rejects_non_uuid():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/not-a-uuid/lint")
    assert r.status_code == 422
    mdb.get_mcp_endpoint_version.assert_not_called()


def test_get_lint_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint")
    assert r.status_code == 401


# ===========================================================================
# POST …/lint — recompute + persist
# ===========================================================================


def test_post_lint_recomputes_and_persists():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row()
        mdb.get_mcp_capability_items.return_value = [_tool_row("get_weather", "Get the weather")]
        mdb.get_mcp_version_score.return_value = {
            "score": 100, "grade": "A", "report": {"report_fingerprint": "x"},
            "report_fingerprint": "x", "scored_at": _NOW,
        }
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "computed"
    assert body["scoredAt"] == _NOW.isoformat()
    assert body["reportFingerprint"]
    # The refreshed score was upserted with the computed score/grade/fingerprint.
    mdb.set_mcp_version_score.assert_called_once()
    kwargs = mdb.set_mcp_version_score.call_args.kwargs
    assert kwargs["score"] == body["score"]
    assert kwargs["grade"] == body["grade"]
    assert kwargs["report_fingerprint"] == body["reportFingerprint"]
    assert kwargs["report"]["findings"] is not None


def test_post_lint_deterministic_matches_stored_capture():
    """Recomputing an unchanged surface reproduces the same score/grade/fingerprint."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row()
        mdb.get_mcp_capability_items.return_value = [_tool_row("get_weather", "Get the weather")]
        mdb.get_mcp_version_score.return_value = None
        first = client.post(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint").json()
        second = client.post(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint").json()
    assert first["score"] == second["score"]
    assert first["grade"] == second["grade"]
    assert first["reportFingerprint"] == second["reportFingerprint"]


def test_post_lint_endpoint_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint")
    assert r.status_code == 404
    mdb.set_mcp_version_score.assert_not_called()


def test_post_lint_version_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = None
        r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint")
    assert r.status_code == 404
    mdb.set_mcp_version_score.assert_not_called()


def test_post_lint_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.post(f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/lint")
    assert r.status_code == 401
