"""Tests for the discovery job status/polling API (V2-MCP-17.4 / MCAT-3.4, #3666).

Two layers, all DB-free:

* **Routes** — ``GET .../endpoints/{id}/jobs`` and ``.../jobs/{job_id}`` behaviour:
  the status-snapshot contract (state, timings, version_id/error), tenant scoping,
  endpoint/job mismatch, and 404/422/401 edges (``db`` is patched, so no real DB).
* **Projection** — ``mcp_discovery_job_status_from_row`` lifts ``version_id`` /
  ``changed`` / structured error out of ``result``, derives ``terminal`` and
  ``duration_ms``, and builds ``status_path``.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import models
from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_EP_UUID = "11111111-1111-1111-1111-111111111111"
_JOB_UUID = "22222222-2222-2222-2222-222222222222"
_STARTED = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)
_FINISHED = datetime(2026, 6, 26, 12, 0, 2, tzinfo=timezone.utc)  # +2s
_CREATED = datetime(2026, 6, 26, 11, 59, 59, tzinfo=timezone.utc)

_ENDPOINT_ROW = {
    "id": _EP_UUID,
    "tenant_id": "t1",
    "name": "Acme Weather",
    "slug": "acme-weather",
    "endpoint_url": "https://mcp.acme.example/mcp",
    "transport": "streamable_http",
}

_QUEUED_JOB = {
    "id": _JOB_UUID,
    "endpoint_id": _EP_UUID,
    "tenant_id": "t1",
    "state": "queued",
    "trigger": "manual",
    "started_at": None,
    "finished_at": None,
    "error": None,
    "result": {},
    "created_at": _CREATED,
}

_COMPLETED_JOB = {
    **_QUEUED_JOB,
    "state": "completed",
    "started_at": _STARTED,
    "finished_at": _FINISHED,
    "result": {"version_id": "ver-1", "version_seq": 1, "changed": True},
}

_FAILED_JOB = {
    **_QUEUED_JOB,
    "state": "failed",
    "started_at": _STARTED,
    "finished_at": _FINISHED,
    "error": "transport_error: connection refused",
    "result": {"error": {"code": "transport_error", "message": "connection refused"}},
}


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# ROUTES — single job poll
# ===========================================================================


def test_get_job_completed_returns_terminal_with_version_id():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_discovery_job.return_value = _COMPLETED_JOB
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/jobs/{_JOB_UUID}")
    assert r.status_code == 200
    job = r.json()["job"]
    assert job["state"] == "completed"
    assert job["terminal"] is True
    assert job["version_id"] == "ver-1"
    assert job["changed"] is True
    assert job["error"] is None
    assert job["error_detail"] is None
    # 2s run reported in whole milliseconds.
    assert job["duration_ms"] == 2000
    # Re-poll URL echoes the slug from the request path.
    assert job["status_path"] == f"/v1/mcp/acme/endpoints/{_EP_UUID}/jobs/{_JOB_UUID}"
    mdb.get_mcp_discovery_job.assert_called_once_with("t1", _JOB_UUID)


def test_get_job_failed_returns_structured_error():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_discovery_job.return_value = _FAILED_JOB
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/jobs/{_JOB_UUID}")
    assert r.status_code == 200
    job = r.json()["job"]
    assert job["state"] == "failed"
    assert job["terminal"] is True
    assert job["version_id"] is None
    assert job["error"] == "transport_error: connection refused"
    assert job["error_detail"] == {"code": "transport_error", "message": "connection refused"}


def test_get_job_queued_is_not_terminal():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_discovery_job.return_value = _QUEUED_JOB
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/jobs/{_JOB_UUID}")
    job = r.json()["job"]
    assert job["state"] == "queued"
    assert job["terminal"] is False
    assert job["version_id"] is None
    assert job["duration_ms"] is None  # never started/finished


def test_get_job_scoped_to_token_tenant_not_slug():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_discovery_job.return_value = _COMPLETED_JOB
        client.get(f"/v1/mcp/other-slug/endpoints/{_EP_UUID}/jobs/{_JOB_UUID}")
        # The token tenant (t1), never the URL slug, scopes the lookup.
        mdb.get_mcp_discovery_job.assert_called_once_with("t1", _JOB_UUID)


def test_get_job_endpoint_mismatch_404():
    """A job belonging to a different endpoint is not reachable under this one."""
    job = {**_COMPLETED_JOB, "endpoint_id": "99999999-9999-9999-9999-999999999999"}
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_discovery_job.return_value = job
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/jobs/{_JOB_UUID}")
    assert r.status_code == 404


def test_get_job_not_found_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_discovery_job.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/jobs/{_JOB_UUID}")
    assert r.status_code == 404


def test_get_job_rejects_non_uuid_422():
    with patch("app.mcp_catalog_routes.db") as mdb:
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/jobs/not-a-uuid")
    assert r.status_code == 422
    mdb.get_mcp_discovery_job.assert_not_called()


def test_get_job_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/jobs/{_JOB_UUID}")
    assert r.status_code == 401


# ===========================================================================
# ROUTES — list jobs
# ===========================================================================


def test_list_jobs_ok():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_discovery_jobs.return_value = [_COMPLETED_JOB, _QUEUED_JOB]
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/jobs")
    assert r.status_code == 200
    jobs = r.json()["jobs"]
    assert [j["state"] for j in jobs] == ["completed", "queued"]
    assert jobs[0]["version_id"] == "ver-1"
    mdb.list_mcp_discovery_jobs.assert_called_once_with("t1", _EP_UUID)


def test_list_jobs_empty():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_discovery_jobs.return_value = []
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/jobs")
    assert r.status_code == 200
    assert r.json()["jobs"] == []


def test_list_jobs_endpoint_not_found_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/jobs")
    assert r.status_code == 404
    mdb.list_mcp_discovery_jobs.assert_not_called()


def test_list_jobs_scoped_to_token_tenant():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.list_mcp_discovery_jobs.return_value = []
        client.get(f"/v1/mcp/other-slug/endpoints/{_EP_UUID}/jobs")
        mdb.get_mcp_endpoint.assert_called_once_with("t1", _EP_UUID)


def test_list_jobs_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.get(f"/v1/mcp/acme/endpoints/{_EP_UUID}/jobs")
    assert r.status_code == 401


# ===========================================================================
# PROJECTION — mcp_discovery_job_status_from_row
# ===========================================================================


def test_status_projection_lifts_completed_fields():
    status = models.mcp_discovery_job_status_from_row(_COMPLETED_JOB, "acme")
    assert status.terminal is True
    assert status.version_id == "ver-1"
    assert status.changed is True
    assert status.error is None
    assert status.error_detail is None
    assert status.duration_ms == 2000
    assert status.status_path.endswith(f"/endpoints/{_EP_UUID}/jobs/{_JOB_UUID}")
    # Full raw payload is preserved for callers needing more than the lifted fields.
    assert status.result["version_seq"] == 1


def test_status_projection_lifts_failed_error():
    status = models.mcp_discovery_job_status_from_row(_FAILED_JOB, "acme")
    assert status.terminal is True
    assert status.version_id is None
    assert status.error_detail["code"] == "transport_error"


def test_status_projection_without_slug_has_no_status_path():
    status = models.mcp_discovery_job_status_from_row(_QUEUED_JOB)
    assert status.status_path is None
    assert status.terminal is False


def test_status_projection_unchanged_run_keeps_version_id():
    """An 'unchanged' completed run still reports the prior version_id with changed=False."""
    job = {
        **_COMPLETED_JOB,
        "result": {"version_id": "ver-7", "version_seq": 7, "changed": False},
    }
    status = models.mcp_discovery_job_status_from_row(job, "acme")
    assert status.version_id == "ver-7"
    assert status.changed is False


def test_status_projection_handles_string_timestamps():
    """Timings provided as ISO strings (e.g. a JSONB round-trip) still yield a duration."""
    job = {
        **_COMPLETED_JOB,
        "started_at": _STARTED.isoformat(),
        "finished_at": _FINISHED.isoformat(),
    }
    status = models.mcp_discovery_job_status_from_row(job, "acme")
    assert status.duration_ms == 2000


def test_status_projection_negative_duration_is_none():
    """Clock skew (finish before start) reports no duration rather than a negative one."""
    job = {**_COMPLETED_JOB, "started_at": _FINISHED, "finished_at": _STARTED}
    status = models.mcp_discovery_job_status_from_row(job, "acme")
    assert status.duration_ms is None
