"""API tests for the MCP trust-baseline / drift / shadowing routes (CLX-3.4, #4858).

Covers the four capabilities the surface exposes:

- ``POST .../trust-baseline`` — approve a baseline (rationale required; gating validated; policy event).
- ``GET  .../trust-baseline`` — the active baseline + history.
- ``GET  .../trust-drift``    — diff current vs approved baseline, classified, gated, optionally notified.
- ``GET  .../data-quality/shadowing`` — shadowed tool names across the enabled host scope.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import mcp_trust_baseline_routes as routes
from app.auth import validate_authentication
from app.config import settings
from app.main import app
from app.mcp_trust_manifest import build_trust_manifest

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)

_EP = "11111111-1111-1111-1111-111111111111"
_V1 = "22222222-2222-2222-2222-222222222222"
_BID = "33333333-3333-3333-3333-333333333333"
_BASE = f"/v1/mcp/acme/endpoints/{_EP}"

_ENDPOINT_ROW = {
    "id": _EP,
    "tenant_id": "t1",
    "name": "Acme",
    "slug": "acme",
    "endpoint_url": "https://mcp.acme.example/mcp",
    "transport": "streamable_http",
    "transport_metadata": None,
    "enabled": True,
    "current_version_id": _V1,
}


def _version_row(fp="fp1"):
    return {
        "id": _V1,
        "endpoint_id": _EP,
        "version_seq": 3,
        "version_tag": "2026-07-14T12:00Z",
        "protocol_version": "2025-06-18",
        "server_name": "acme",
        "server_title": None,
        "server_version": "1.0.0",
        "instructions": None,
        "capabilities": {},
        "surface_fingerprint": fp,
        "discovered_at": _NOW,
        "created_at": _NOW,
    }


def _tool_rows(annotations=None):
    return [
        {
            "version_id": _V1,
            "item_type": "tool",
            "name": "search",
            "title": None,
            "description": "Search.",
            "input_schema": {"type": "object", "properties": {}},
            "output_schema": None,
            "annotations": annotations,
            "uri": None,
            "uri_template": None,
            "raw": {},
            "ordinal": 0,
        }
    ]


def _manifest_envelope(annotations=None):
    return build_trust_manifest(
        endpoint_row=_ENDPOINT_ROW,
        version_row=_version_row(),
        capability_rows=_tool_rows(annotations),
    ).as_dict()


def _baseline_row(annotations=None, gating=None):
    return {
        "id": _BID,
        "tenant_id": "t1",
        "endpoint_id": _EP,
        "version_id": _V1,
        "manifest_fingerprint": _manifest_envelope(annotations)["fingerprint"],
        "manifest": _manifest_envelope(annotations),
        "rationale": "Reviewed and approved.",
        "gating_categories": gating or ["security_regression", "coverage_loss"],
        "approved_by": "user-1",
        "superseded_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# --- Approve baseline ----------------------------------------------------------------------------


def test_approve_requires_rationale():
    with patch("app.mcp_trust_baseline_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(f"{_BASE}/trust-baseline", json={"rationale": "   "})
    assert r.status_code == 400
    assert "rationale" in r.json()["detail"].lower()


def test_approve_rejects_unknown_gating_category():
    with patch("app.mcp_trust_baseline_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(
            f"{_BASE}/trust-baseline",
            json={"rationale": "ok", "gating_categories": ["not_a_category"]},
        )
    assert r.status_code == 400
    assert "unknown" in r.json()["detail"].lower()


def test_approve_composes_manifest_and_writes_policy_event():
    with patch("app.mcp_trust_baseline_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_latest_mcp_endpoint_version.return_value = _version_row()
        mdb.get_mcp_capability_items.return_value = _tool_rows({"readOnlyHint": True})
        mdb.list_mcp_endpoint_sources.return_value = []
        mdb.approve_mcp_trust_baseline.return_value = _baseline_row({"readOnlyHint": True})
        r = client.post(f"{_BASE}/trust-baseline", json={"rationale": "Approved for prod."})
    assert r.status_code == 201
    body = r.json()["baseline"]
    assert body["rationale"] == "Reviewed and approved."
    assert body["gatingCategories"] == ["security_regression", "coverage_loss"]
    # AC2: the approval also wrote a governance policy event.
    assert mdb.insert_registry_audit.called
    args, kwargs = mdb.insert_registry_audit.call_args
    assert args[1] == routes.ACTION_BASELINE_APPROVE
    assert kwargs["detail"]["rationale"] == "Approved for prod."


def test_approve_409_when_never_discovered():
    with patch("app.mcp_trust_baseline_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_latest_mcp_endpoint_version.return_value = None
        r = client.post(f"{_BASE}/trust-baseline", json={"rationale": "ok"})
    assert r.status_code == 409


# --- Get baseline --------------------------------------------------------------------------------


def test_get_baseline_returns_active_and_history():
    with patch("app.mcp_trust_baseline_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_active_mcp_trust_baseline.return_value = _baseline_row()
        mdb.list_mcp_trust_baselines.return_value = [_baseline_row()]
        r = client.get(f"{_BASE}/trust-baseline")
    assert r.status_code == 200
    body = r.json()
    assert body["baseline"]["id"] == _BID
    assert len(body["history"]) == 1


# --- Drift ---------------------------------------------------------------------------------------


def test_drift_404_without_baseline():
    with patch("app.mcp_trust_baseline_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_active_mcp_trust_baseline.return_value = None
        r = client.get(f"{_BASE}/trust-drift")
    assert r.status_code == 404


def test_drift_flags_security_regression_and_gate_is_advisory_by_default(monkeypatch):
    monkeypatch.setattr(settings, "mcp_trust_drift_gate_enabled", False)
    # Baseline approved 'search' as readOnly; current snapshot dropped readOnlyHint (escalation).
    with patch("app.mcp_trust_baseline_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_active_mcp_trust_baseline.return_value = _baseline_row({"readOnlyHint": True})
        mdb.get_latest_mcp_endpoint_version.return_value = _version_row(fp="fp2")
        mdb.get_mcp_endpoint_version.return_value = _version_row(fp="fp1")
        mdb.get_mcp_capability_items.side_effect = [
            _tool_rows({"readOnlyHint": True}),  # baseline surface caps
            _tool_rows(None),                    # current manifest caps
            _tool_rows(None),                    # current surface caps
        ]
        mdb.list_mcp_endpoint_sources.return_value = []
        r = client.get(f"{_BASE}/trust-drift")
    assert r.status_code == 200
    drift = r.json()["drift"]
    assert drift["alert_severity"] == "security_regression"
    assert drift["gate"]["status"] == "blocked"
    assert drift["gate"]["enforced"] is False  # advisory: gate flag off


def test_drift_notifies_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "mcp_trust_drift_notify_enabled", True)
    with patch("app.mcp_trust_baseline_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_active_mcp_trust_baseline.return_value = _baseline_row({"readOnlyHint": True})
        mdb.get_latest_mcp_endpoint_version.return_value = _version_row(fp="fp2")
        mdb.get_mcp_endpoint_version.return_value = _version_row(fp="fp1")
        mdb.get_mcp_capability_items.side_effect = [
            _tool_rows({"readOnlyHint": True}),
            _tool_rows(None),
            _tool_rows(None),
        ]
        mdb.list_mcp_endpoint_sources.return_value = []
        mdb.list_active_push_webhook_subscription_ids.return_value = ["sub-1"]
        mdb.enqueue_push_webhook_delivery.return_value = {"id": "deliv-1"}
        r = client.get(f"{_BASE}/trust-drift", params={"notify": "true"})
    assert r.status_code == 200
    assert r.json()["notified"] == ["deliv-1"]
    # The delivery was enqueued under the trust-drift event type.
    assert mdb.enqueue_push_webhook_delivery.call_args[0][2] == routes.EVENT_TYPE_TRUST_DRIFT


# --- Shadowing -----------------------------------------------------------------------------------


def test_shadowing_report_groups_names_across_enabled_endpoints():
    with patch("app.mcp_trust_baseline_routes.db") as mdb:
        mdb.list_mcp_enabled_capability_names.return_value = [
            {"endpoint_id": "ep1", "endpoint_name": "A", "endpoint_slug": "a",
             "endpoint_url": "https://a.example/mcp", "item_type": "tool", "name": "search"},
            {"endpoint_id": "ep2", "endpoint_name": "B", "endpoint_slug": "b",
             "endpoint_url": "https://b.example/mcp", "item_type": "tool", "name": "search"},
        ]
        r = client.get("/v1/mcp/acme/data-quality/shadowing")
    assert r.status_code == 200
    body = r.json()
    assert body["group_count"] == 1
    assert body["groups"][0]["name"] == "search"
    assert body["groups"][0]["endpoint_count"] == 2
