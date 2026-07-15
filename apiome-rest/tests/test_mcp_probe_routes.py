"""API tests for the MCP dynamic-probe routes (CLX-3.3, #4857).

Covers the four capabilities the probe surface exposes:

- ``GET  /v1/mcp/probes/catalog`` — the probe/profile/classification catalog.
- ``POST|GET|DELETE .../probe-targets`` — the active-probe allowlist.
- ``POST .../versions/{vid}/probe`` — run a profile (passive default; active gated + audited).
- ``GET  .../probe-runs`` — the audit trail.

The passive run exercises the *real* engine over a transcript reconstructed from mocked rows. The
active-run tests verify the gate refusals (kill switch, not-allowlisted) are recorded as audit rows,
and — with a fake probe runner registered — that a full active run completes and writes its outcome.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import mcp_probe as mp
from app import mcp_probe_routes as routes
from app.auth import validate_authentication, validate_session_credentials
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)

_EP = "11111111-1111-1111-1111-111111111111"
_V1 = "22222222-2222-2222-2222-222222222222"
_TID = "44444444-4444-4444-4444-444444444444"

_BASE = f"/v1/mcp/acme/endpoints/{_EP}"
_PROBE_URL = f"{_BASE}/versions/{_V1}/probe"
_TARGETS_URL = f"{_BASE}/probe-targets"

_ENDPOINT_ROW = {
    "id": _EP,
    "tenant_id": "t1",
    "name": "Acme",
    "slug": "acme",
    "endpoint_url": "https://mcp.acme.example/mcp",
    "transport": "streamable_http",
    "enabled": True,
    "current_version_id": _V1,
}


def _version_row():
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
        "capabilities": {"authentication": {"required": True}},
        "surface_fingerprint": "fp1",
        "discovered_at": _NOW,
        "created_at": _NOW,
    }


def _tool_rows():
    return [
        {
            "version_id": _V1,
            "item_type": "tool",
            "name": "echo",
            "title": None,
            "description": "Echoes text.",
            "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
            "output_schema": None,
            "annotations": None,
            "uri": None,
            "uri_template": None,
            "raw": {},
            "ordinal": 0,
        }
    ]


def _transcript_row():
    return {
        "transcript": {
            "redacted": True,
            "requested_version": "2025-06-18",
            "negotiated_version": "2025-06-18",
            "exchanges": [
                {"method": "tools/list", "request_id": "1", "id_echoed": False, "jsonrpc": "2.0"},
            ],
        }
    }


def _target_row(**overrides):
    row = {
        "id": _TID,
        "tenant_id": "t1",
        "endpoint_id": _EP,
        "transport": "http",
        "locator": "https://mcp.acme.example/mcp",
        "ownership_declared": True,
        "test_credential_id": "cred-1",
        "enrolled_by": "user-1",
        "retired_at": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    app.dependency_overrides[validate_session_credentials] = lambda: _JWT_T1
    routes.register_probe_runner(None)  # default: no runner
    yield
    app.dependency_overrides.pop(validate_authentication, None)
    app.dependency_overrides.pop(validate_session_credentials, None)
    routes.register_probe_runner(None)


class _FakeTransport:
    async def send(self, method, params):
        if method == "tools/list":
            return mp.ProbeResponse(ok=True, error_code=None, result_keys=("tools",))
        if method.startswith("$apiome.probe/"):
            return mp.ProbeResponse(ok=True, error_code=-32601)  # correct rejection
        return mp.ProbeResponse(ok=True)


# --- Catalog -------------------------------------------------------------------------------------


def test_probe_catalog_lists_profiles_probes_and_tiers():
    body = client.get("/v1/mcp/probes/catalog").json()
    assert {p["profile_id"] for p in body["profiles"]} == {
        "passive",
        "safe-active",
        "payload-fuzzing",
    }
    assert {c["value"] for c in body["classifications"]} == {
        "suspected",
        "observed",
        "exploited-in-test",
    }
    assert any(p["probe_id"].startswith("passive.") for p in body["probes"])


def test_probe_catalog_filters_by_profile():
    body = client.get("/v1/mcp/probes/catalog", params={"profile": "payload-fuzzing"}).json()
    assert body["probes"]
    assert all(p["profile"] == "payload-fuzzing" for p in body["probes"])


# --- Allowlist -----------------------------------------------------------------------------------


def test_enroll_requires_ownership_declaration():
    with patch("app.mcp_probe_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.post(_TARGETS_URL, json={"ownership_declared": False})
    assert r.status_code == 400
    assert "ownership" in r.json()["detail"].lower()


def test_enroll_and_list_targets():
    with patch("app.mcp_probe_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.enroll_mcp_probe_target.return_value = _target_row()
        r = client.post(
            _TARGETS_URL, json={"ownership_declared": True, "test_credential_id": "cred-1"}
        )
    assert r.status_code == 201
    assert r.json()["target"]["ownershipDeclared"] is True

    with patch("app.mcp_probe_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_probe_targets.return_value = [_target_row()]
        r = client.get(_TARGETS_URL)
    assert r.status_code == 200
    assert r.json()["targets"][0]["transport"] == "http"


# --- Passive run (read-only) ---------------------------------------------------------------------


def test_passive_probe_runs_read_only_over_transcript():
    with patch("app.mcp_probe_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row()
        mdb.get_mcp_capability_items.return_value = _tool_rows()
        mdb.get_mcp_protocol_transcript.return_value = _transcript_row()
        r = client.post(_PROBE_URL, json={"profile": "passive"})
    assert r.status_code == 200
    body = r.json()
    assert body["profile"] == "passive"
    assert body["requests_sent"] == 0
    assert body["exploited_count"] == 0
    # the id-not-echoed passive probe fired, as an OBSERVED finding
    assert any(f["classification"] == "observed" for f in body["findings"])
    # no audit row is written for a passive run (it sends nothing)
    mdb.start_mcp_probe_run.assert_not_called()


def test_unknown_profile_is_rejected():
    with patch("app.mcp_probe_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row()
        r = client.post(_PROBE_URL, json={"profile": "nonsense"})
    assert r.status_code == 400


# --- Active run gate refusals are audited --------------------------------------------------------


def test_active_run_refused_by_kill_switch_is_recorded():
    with patch("app.mcp_probe_routes.db") as mdb, patch(
        "app.mcp_probe_routes.settings"
    ) as msettings:
        msettings.mcp_probe_enabled = False
        msettings.mcp_probe_max_concurrent_per_tenant = 2
        msettings.mcp_probe_max_runs_per_hour_per_tenant = 20
        msettings.mcp_probe_max_requests_per_run = 50
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row()
        mdb.get_mcp_capability_items.return_value = _tool_rows()
        mdb.get_mcp_probe_target.return_value = _target_row()
        mdb.get_mcp_probe_tenant_usage.return_value = {"active_runs": 0, "runs_last_hour": 0}
        mdb.start_mcp_probe_run.return_value = "run-x"
        r = client.post(_PROBE_URL, json={"profile": "safe-active"})
    assert r.status_code == 403
    assert "kill switch" in r.json()["detail"].lower()
    # the refused attempt is audited, not dropped
    mdb.start_mcp_probe_run.assert_called_once()
    mdb.refuse_mcp_probe_run.assert_called_once()


def test_active_run_refused_when_not_allowlisted():
    with patch("app.mcp_probe_routes.db") as mdb, patch(
        "app.mcp_probe_routes.settings"
    ) as msettings:
        msettings.mcp_probe_enabled = True
        msettings.mcp_probe_max_concurrent_per_tenant = 2
        msettings.mcp_probe_max_runs_per_hour_per_tenant = 20
        msettings.mcp_probe_max_requests_per_run = 50
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row()
        mdb.get_mcp_capability_items.return_value = _tool_rows()
        mdb.get_mcp_probe_target.return_value = None  # not enrolled
        mdb.get_mcp_probe_tenant_usage.return_value = {"active_runs": 0, "runs_last_hour": 0}
        mdb.start_mcp_probe_run.return_value = "run-y"
        r = client.post(_PROBE_URL, json={"profile": "safe-active"})
    assert r.status_code == 403
    assert "allowlist" in r.json()["detail"].lower()
    mdb.refuse_mcp_probe_run.assert_called_once()


def test_active_run_503_when_no_runner_configured():
    with patch("app.mcp_probe_routes.db") as mdb, patch(
        "app.mcp_probe_routes.settings"
    ) as msettings:
        msettings.mcp_probe_enabled = True
        msettings.mcp_probe_max_concurrent_per_tenant = 2
        msettings.mcp_probe_max_runs_per_hour_per_tenant = 20
        msettings.mcp_probe_max_requests_per_run = 50
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row()
        mdb.get_mcp_capability_items.return_value = _tool_rows()
        mdb.get_mcp_probe_target.return_value = _target_row()
        mdb.get_mcp_probe_tenant_usage.return_value = {"active_runs": 0, "runs_last_hour": 0}
        # runner is None (default) -> gates pass, then 503
        r = client.post(_PROBE_URL, json={"profile": "safe-active"})
    assert r.status_code == 503
    assert "runner" in r.json()["detail"].lower()


def test_active_run_completes_with_registered_runner_and_writes_audit():
    async def _factory(endpoint, consent, isolation):
        return _FakeTransport()

    routes.register_probe_runner(_factory)
    with patch("app.mcp_probe_routes.db") as mdb, patch(
        "app.mcp_probe_routes.settings"
    ) as msettings:
        msettings.mcp_probe_enabled = True
        msettings.mcp_probe_max_concurrent_per_tenant = 2
        msettings.mcp_probe_max_runs_per_hour_per_tenant = 20
        msettings.mcp_probe_max_requests_per_run = 50
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = _version_row()
        mdb.get_mcp_capability_items.return_value = _tool_rows()
        mdb.get_mcp_probe_target.return_value = _target_row()
        mdb.get_mcp_probe_tenant_usage.return_value = {"active_runs": 0, "runs_last_hour": 0}
        mdb.start_mcp_probe_run.return_value = "run-z"
        r = client.post(_PROBE_URL, json={"profile": "safe-active"})
    assert r.status_code == 200
    body = r.json()
    assert body["profile"] == "safe-active"
    assert body["run_id"] == "run-z"
    # the auth-bypass probe demonstrated an exploit against the fake server
    assert body["exploited_count"] == 1
    mdb.start_mcp_probe_run.assert_called_once()
    mdb.complete_mcp_probe_run.assert_called_once()


# --- Audit trail ---------------------------------------------------------------------------------


def test_probe_runs_audit_trail_lists_rows():
    run_row = {
        "id": "run-1",
        "endpoint_id": _EP,
        "version_id": _V1,
        "profile": "safe-active",
        "target_locator": "https://mcp.acme.example/mcp",
        "transport": "http",
        "status": "completed",
        "refusal_reason": None,
        "requests_sent": 2,
        "observed_count": 1,
        "exploited_count": 1,
        "consent": {"allowlisted": True},
        "limits": {"max_requests": 50},
        "isolation": None,
        "report_fingerprint": "fp",
        "started_at": _NOW,
        "completed_at": _NOW,
    }
    with patch("app.mcp_probe_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_probe_runs.return_value = [run_row]
        r = client.get(f"{_BASE}/probe-runs")
    assert r.status_code == 200
    row = r.json()["runs"][0]
    assert row["status"] == "completed"
    assert row["exploitedCount"] == 1
