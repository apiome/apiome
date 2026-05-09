"""REST import job API (#3306)."""

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.imports_routes import _weak_etag_import_job
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "tenant_slug": "acme",
    "user_id": "11111111-2222-3333-4444-555555555555",
    "auth_method": "jwt",
}

_JOB_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture(autouse=True)
def _auth():
    def _fake_validate(tenant_slug: str, authorization=None, x_api_key=None):
        _ = authorization
        _ = x_api_key
        if tenant_slug != "acme":
            raise HTTPException(status_code=403, detail="User does not have access to tenant: wrong")
        return _MOCK_AUTH

    app.dependency_overrides[validate_authentication] = _fake_validate
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _queued_row(**overrides):
    base = {
        "job_id": _JOB_ID,
        "tenant_id": _MOCK_AUTH["tenant_id"],
        "project_id": None,
        "state": "queued",
        "source_kind": "openapi",
        "blob_sha": None,
        "repository_source": None,
        "input": {},
        "events": [{"type": "queued", "at": "2026-05-09T12:00:00+00:00"}],
        "progress": None,
        "summary": None,
        "result": None,
        "percent": 0,
        "error": None,
        "created_by": _MOCK_AUTH["user_id"],
        "created_at": datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc),
        "finished_at": None,
        "expires_at": datetime(2026, 5, 16, 12, 0, 0, tzinfo=timezone.utc),
        "idempotency_key": None,
    }
    base.update(overrides)
    return base


_MIN_BODY = {
    "sourceKind": "openapi",
    "document": {"openapi": "3.0.0"},
    "project": {"name": "Payments API", "slug": "payments-api"},
    "version": {"versionId": "1.0.0"},
    "options": {},
}


def test_imports_wrong_tenant_slug_returns_403():
    r = client.post("/v1/imports/wrong-tenant", json=_MIN_BODY)
    assert r.status_code == 403


def test_create_import_job_201():
    row = _queued_row()
    with patch("app.imports_routes.db") as mdb:
        mdb.resolve_import_job_created_by_user_id.return_value = _MOCK_AUTH["user_id"]
        mdb.find_import_job_by_idempotency_key.return_value = None
        mdb.insert_import_job.return_value = row
        r = client.post("/v1/imports/acme", json=_MIN_BODY)
        assert r.status_code == 201
        data = r.json()
        assert data["jobId"] == _JOB_ID
        assert data["state"] == "queued"
        assert "ETag" in r.headers
        mdb.insert_workflow_audit.assert_called_once()
        assert mdb.insert_workflow_audit.call_args[0][3] == "import.job.create"


def test_create_import_job_idempotency_returns_200():
    row = _queued_row(idempotency_key="k1")
    with patch("app.imports_routes.db") as mdb:
        mdb.find_import_job_by_idempotency_key.return_value = row
        r = client.post(
            "/v1/imports/acme",
            json=_MIN_BODY,
            headers={"Idempotency-Key": "k1"},
        )
        assert r.status_code == 200
        assert r.json()["jobId"] == _JOB_ID
        mdb.insert_import_job.assert_not_called()


def test_create_unknown_existing_project_returns_400():
    with patch("app.imports_routes.db") as mdb:
        mdb.find_import_job_by_idempotency_key.return_value = None
        mdb.get_project_by_id.return_value = None
        body = {**_MIN_BODY, "existingProjectId": str(UUID(int=5))}
        r = client.post("/v1/imports/acme", json=body)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "UNKNOWN_PROJECT_ID"


def test_get_import_job_404():
    with patch("app.imports_routes.db") as mdb:
        mdb.get_import_job_row.return_value = None
        r = client.get(f"/v1/imports/acme/{_JOB_ID}")
    assert r.status_code == 404


def test_get_import_job_304_if_none_match():
    row = _queued_row()
    etag = _weak_etag_import_job(row["updated_at"], row["job_id"])
    with patch("app.imports_routes.db") as mdb:
        mdb.get_import_job_row.return_value = row
        r = client.get(
            f"/v1/imports/acme/{_JOB_ID}",
            headers={"If-None-Match": etag},
        )
    assert r.status_code == 304
    assert r.headers.get("ETag")


def test_commit_wrong_state_returns_409():
    row = _queued_row(state="failed")
    with patch("app.imports_routes.db") as mdb:
        mdb.get_import_job_row.return_value = row
        r = client.post(f"/v1/imports/acme/{_JOB_ID}/commit")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "IMPORT_JOB_INVALID_STATE"
    assert "hint" in detail


def test_commit_success():
    row = _queued_row(state="pending-approval")
    updated = {**row, "state": "committing"}
    with patch("app.imports_routes.db") as mdb:
        mdb.get_import_job_row.return_value = row
        mdb.update_import_job_state.return_value = updated
        r = client.post(f"/v1/imports/acme/{_JOB_ID}/commit")
    assert r.status_code == 200
    assert r.json()["state"] == "committing"


def test_cancel_terminal_returns_409():
    row = _queued_row(state="completed")
    with patch("app.imports_routes.db") as mdb:
        mdb.get_import_job_row.return_value = row
        r = client.post(f"/v1/imports/acme/{_JOB_ID}/cancel")
    assert r.status_code == 409


def test_cancel_success():
    row = _queued_row(state="running")
    updated = {**row, "state": "canceled", "finished_at": datetime.now(timezone.utc)}
    with patch("app.imports_routes.db") as mdb:
        mdb.get_import_job_row.return_value = row
        mdb.update_import_job_state.return_value = updated
        r = client.post(f"/v1/imports/acme/{_JOB_ID}/cancel")
    assert r.status_code == 200
    assert r.json()["state"] == "canceled"


def test_rollback_non_completed_returns_409():
    row = _queued_row(state="running")
    with patch("app.imports_routes.db") as mdb:
        mdb.get_import_job_row.return_value = row
        r = client.post(f"/v1/imports/acme/{_JOB_ID}/rollback")
    assert r.status_code == 409


def test_rollback_success():
    row = _queued_row(state="completed")
    updated = {**row, "state": "rolled-back"}
    with patch("app.imports_routes.db") as mdb:
        mdb.get_import_job_row.return_value = row
        mdb.update_import_job_state.return_value = updated
        r = client.post(f"/v1/imports/acme/{_JOB_ID}/rollback")
    assert r.status_code == 200
    assert r.json()["state"] == "rolled-back"


def test_commit_writes_workflow_audit():
    row = _queued_row(state="pending-approval")
    updated = {**row, "state": "committing"}
    with patch("app.imports_routes.db") as mdb:
        mdb.get_import_job_row.return_value = row
        mdb.update_import_job_state.return_value = updated
        client.post(f"/v1/imports/acme/{_JOB_ID}/commit")
        mdb.insert_workflow_audit.assert_called_once()
        args = mdb.insert_workflow_audit.call_args[0]
        assert args[3] == "import.job.commit"
        assert args[4] == "success"
