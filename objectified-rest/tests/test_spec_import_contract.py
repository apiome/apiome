"""Contract tests for specification import REST surface (#3329)."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.models import SpecImportJobStatus

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "550e8400-e29b-41d4-a716-446655440000",
    "tenant_slug": "acme",
    "user_id": "660e8400-e29b-41d4-a716-446655440001",
    "auth_method": "jwt",
}


@pytest.fixture(autouse=True)
def _auth_override():
    def _fake_auth(tenant_slug: str):
        return {**_MOCK_AUTH, "tenant_slug": tenant_slug}

    app.dependency_overrides[validate_authentication] = _fake_auth
    app.openapi_schema = None
    yield
    app.dependency_overrides.pop(validate_authentication, None)
    app.openapi_schema = None


@pytest.fixture(autouse=True)
def _clear_spec_import_jobs_between_tests():
    from app import spec_import_engine as sie

    sie._jobs.clear()
    yield
    sie._jobs.clear()


@pytest.fixture
def spec_import_fake_worker(monkeypatch):
    async def _fake(payload: dict) -> dict:
        jid = payload["rest_job_id"]
        md = payload["metadata"]
        return {
            "ok": True,
            "job_id": jid,
            "status": {
                "job_id": jid,
                "state": "completed",
                "percent": 100,
                "events": [],
                "summary": {},
                "result": {
                    "project_id": "550e8400-e29b-41d4-a716-446655440099",
                    "project_slug": md["project"]["slug"],
                    "version_id": md["version"]["version_id"],
                    "version_record_id": "660e8400-e29b-41d4-a716-446655440088",
                },
            },
        }

    monkeypatch.setattr("app.spec_import_engine._worker_runner", _fake)


@pytest.fixture
def spec_import_pending_worker(monkeypatch):
    async def _fake(payload: dict) -> dict:
        jid = payload["rest_job_id"]
        md = payload["metadata"]
        return {
            "ok": True,
            "job_id": jid,
            "status": {
                "job_id": jid,
                "state": "pending-approval",
                "percent": 100,
                "events": [],
                "summary": {},
                "result": {
                    "project_id": "550e8400-e29b-41d4-a716-446655440099",
                    "project_slug": md["project"]["slug"],
                    "version_id": md["version"]["version_id"],
                    "version_record_id": "660e8400-e29b-41d4-a716-446655440088",
                },
            },
        }

    monkeypatch.setattr("app.spec_import_engine._worker_runner", _fake)


def _wait_completed(job_id: str) -> dict:
    for _ in range(200):
        r = client.get(f"/v1/tenants/acme/imports/{job_id}")
        assert r.status_code == 200, r.text
        body = r.json()
        if body["state"] in ("completed", "failed", "pending-approval", "canceled", "rolled-back"):
            return body
        time.sleep(0.01)
    raise AssertionError("import job did not reach a gate state")


def test_openapi_lists_spec_import_paths_and_operations():
    spec = app.openapi()
    paths = spec["paths"]
    base = "/v1/tenants/{tenant_slug}/imports"
    upload = f"{base}/upload"
    job = f"{base}/{{job_id}}"
    assert base in paths
    assert "get" in paths[base]
    assert "post" in paths[base]
    assert upload in paths
    assert job in paths
    assert "get" in paths[job]
    assert "delete" in paths[job]
    assert f"{job}/commit" in paths
    assert f"{job}/rollback" in paths


def test_list_spec_import_jobs_empty():
    r = client.get("/v1/tenants/acme/imports")
    assert r.status_code == 200, r.text
    assert r.json() == {"jobs": []}


def test_list_spec_import_jobs_includes_started_job(spec_import_fake_worker):
    body = {
        "metadata": {
            "source_kind": "openapi-3",
            "project": {"name": "Payments", "slug": "payments-api"},
            "version": {"version_id": "1.0.0"},
            "options": {},
        },
        "document_base64": "b3BlbmFwaTogMy4xLjA=",
        "filename": "spec.yaml",
    }
    started = client.post("/v1/tenants/acme/imports", json=body)
    assert started.status_code == 202, started.text
    job_id = started.json()["job_id"]

    listed = client.get("/v1/tenants/acme/imports")
    assert listed.status_code == 200, listed.text
    rows = listed.json()["jobs"]
    assert any(j["job_id"] == job_id for j in rows)
    match = next(j for j in rows if j["job_id"] == job_id)
    assert match["status_path"].endswith(f"/imports/{job_id}")
    assert "state" in match and "percent" in match

    _wait_completed(job_id)


def test_start_spec_import_json_returns_202(spec_import_fake_worker):
    body = {
        "metadata": {
            "source_kind": "openapi-3",
            "project": {"name": "Payments", "slug": "payments-api"},
            "version": {"version_id": "1.0.0"},
            "options": {},
        },
        "document_base64": "b3BlbmFwaTogMy4xLjA=",
        "filename": "spec.yaml",
    }
    r = client.post("/v1/tenants/acme/imports", json=body)
    assert r.status_code == 202, r.text
    data = r.json()
    assert "job_id" in data and data["job_id"]
    assert data["status_path"].endswith(f"/imports/{data['job_id']}")

    final = _wait_completed(data["job_id"])
    assert final["state"] == "completed"
    assert final["result"]["project_slug"] == "payments-api"


def test_start_spec_import_multipart_returns_202(spec_import_fake_worker):
    meta = json.dumps(
        {
            "source_kind": "openapi-3",
            "project": {"name": "Payments", "slug": "payments-api"},
            "version": {"version_id": "1.0.0"},
            "options": {},
        }
    )
    r = client.post(
        "/v1/tenants/acme/imports/upload",
        files={"file": ("spec.yaml", b"openapi: 3.1.0\n", "application/yaml")},
        data={"metadata": meta},
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    final = _wait_completed(job_id)
    assert final["state"] == "completed"


def test_get_cancel_commit_rollback(spec_import_fake_worker):
    body = {
        "metadata": {
            "source_kind": "openapi-3",
            "project": {"name": "Payments", "slug": "payments-api"},
            "version": {"version_id": "1.0.0"},
            "options": {},
        },
        "document_base64": "e30=",
    }
    r = client.post("/v1/tenants/acme/imports", json=body)
    job_id = r.json()["job_id"]
    _wait_completed(job_id)

    r = client.get(f"/v1/tenants/acme/imports/{job_id}")
    assert r.status_code == 200
    assert r.json()["state"] == "completed"

    r = client.post(f"/v1/tenants/acme/imports/{job_id}/commit")
    assert r.status_code == 200
    c = r.json()
    assert c["project_slug"] == "payments-api"
    assert c["version_id"] == "1.0.0"

    r = client.post(f"/v1/tenants/acme/imports/{job_id}/commit")
    assert r.status_code == 200

    r = client.post(f"/v1/tenants/acme/imports/{job_id}/rollback")
    assert r.status_code == 409

    r = client.delete(f"/v1/tenants/acme/imports/{job_id}")
    assert r.status_code == 204


def test_commit_returns_501_when_pending_approval(spec_import_pending_worker):
    body = {
        "metadata": {
            "source_kind": "openapi-3",
            "project": {"name": "Payments", "slug": "payments-api"},
            "version": {"version_id": "1.0.0"},
            "options": {},
        },
        "document_base64": "e30=",
    }
    r = client.post("/v1/tenants/acme/imports", json=body)
    job_id = r.json()["job_id"]
    final = _wait_completed(job_id)
    assert final["state"] == "pending-approval"

    r = client.post(f"/v1/tenants/acme/imports/{job_id}/commit")
    assert r.status_code == 501

    r = client.post(f"/v1/tenants/acme/imports/{job_id}/rollback")
    assert r.status_code == 501


def test_resolve_spec_import_worker_argv_env_json(monkeypatch):
    monkeypatch.setenv("SPEC_IMPORT_WORKER_ARGV", '["/bin/true"]')
    from app.spec_import_engine import resolve_spec_import_worker_argv

    assert resolve_spec_import_worker_argv() == ["/bin/true"]


def test_resolve_worker_subprocess_stream_limit_default(monkeypatch):
    monkeypatch.delenv("SPEC_IMPORT_WORKER_STREAM_LIMIT", raising=False)
    monkeypatch.delenv("OBJECTIFIED_SPEC_IMPORT_WORKER_STREAM_LIMIT", raising=False)
    from app.spec_import_engine import (
        _DEFAULT_WORKER_STREAM_LIMIT,
        _resolve_worker_subprocess_stream_limit,
    )

    assert _resolve_worker_subprocess_stream_limit() == _DEFAULT_WORKER_STREAM_LIMIT


def test_resolve_worker_subprocess_stream_limit_from_env(monkeypatch):
    monkeypatch.delenv("OBJECTIFIED_SPEC_IMPORT_WORKER_STREAM_LIMIT", raising=False)
    monkeypatch.setenv("SPEC_IMPORT_WORKER_STREAM_LIMIT", "2097152")
    from app.spec_import_engine import _resolve_worker_subprocess_stream_limit

    assert _resolve_worker_subprocess_stream_limit() == 2097152


def test_resolve_worker_subprocess_stream_limit_prefers_first_env(monkeypatch):
    monkeypatch.setenv("SPEC_IMPORT_WORKER_STREAM_LIMIT", "131072")
    monkeypatch.setenv("OBJECTIFIED_SPEC_IMPORT_WORKER_STREAM_LIMIT", "262144")
    from app.spec_import_engine import _resolve_worker_subprocess_stream_limit

    assert _resolve_worker_subprocess_stream_limit() == 131072


def test_resolve_worker_subprocess_stream_limit_invalid_falls_back(monkeypatch):
    monkeypatch.delenv("OBJECTIFIED_SPEC_IMPORT_WORKER_STREAM_LIMIT", raising=False)
    monkeypatch.setenv("SPEC_IMPORT_WORKER_STREAM_LIMIT", "not-int")
    from app.spec_import_engine import (
        _DEFAULT_WORKER_STREAM_LIMIT,
        _resolve_worker_subprocess_stream_limit,
    )

    assert _resolve_worker_subprocess_stream_limit() == _DEFAULT_WORKER_STREAM_LIMIT


def test_resolve_worker_subprocess_stream_limit_below_min_ignored(monkeypatch):
    monkeypatch.delenv("OBJECTIFIED_SPEC_IMPORT_WORKER_STREAM_LIMIT", raising=False)
    monkeypatch.setenv("SPEC_IMPORT_WORKER_STREAM_LIMIT", "1000")
    from app.spec_import_engine import (
        _DEFAULT_WORKER_STREAM_LIMIT,
        _resolve_worker_subprocess_stream_limit,
    )

    assert _resolve_worker_subprocess_stream_limit() == _DEFAULT_WORKER_STREAM_LIMIT


def test_resolve_spec_import_worker_argv_prefers_yarn_when_on_path(monkeypatch):
    monkeypatch.delenv("SPEC_IMPORT_WORKER_ARGV", raising=False)
    monkeypatch.delenv("OBJECTIFIED_SPEC_IMPORT_WORKER_ARGV", raising=False)

    def _which(cmd: str):
        return f"/fake/{cmd}" if cmd == "yarn" else None

    monkeypatch.setattr("app.spec_import_engine.shutil.which", _which)
    from app.spec_import_engine import resolve_spec_import_worker_argv

    argv = resolve_spec_import_worker_argv()
    assert argv[:4] == ["yarn", "workspace", "objectified-ui", "exec"]


async def test_apply_streaming_spec_import_status_updates_percent():
    """Partial worker lines should refresh poll-visible percent/progress before the job finishes."""
    from app import spec_import_engine as sie

    jid = "11111111-1111-1111-1111-111111111111"
    sie._jobs[jid] = sie._JobRecord(
        tenant_slug="acme",
        job_id=jid,
        state="running",
        status=SpecImportJobStatus(job_id=jid, state="running", percent=0, events=[]),
    )
    await sie._apply_streaming_spec_import_status(
        jid,
        {
            "job_id": jid,
            "state": "running",
            "percent": 37,
            "events": [],
            "progress": {
                "phase": "creating-classes",
                "total": 10,
                "completed": 3,
                "current_item": "Pet",
            },
        },
    )
    assert sie._jobs[jid].status.percent == 37
    assert sie._jobs[jid].status.progress is not None
    assert sie._jobs[jid].status.progress.completed == 3

    await sie._apply_streaming_spec_import_status(
        jid,
        {"job_id": "wrong-id", "state": "running", "percent": 99, "events": []},
    )
    assert sie._jobs[jid].status.percent == 37


def test_resolve_spec_import_worker_argv_falls_back_to_npm(monkeypatch):
    monkeypatch.delenv("SPEC_IMPORT_WORKER_ARGV", raising=False)
    monkeypatch.delenv("OBJECTIFIED_SPEC_IMPORT_WORKER_ARGV", raising=False)

    def _which(cmd: str):
        return f"/fake/{cmd}" if cmd == "npm" else None

    monkeypatch.setattr("app.spec_import_engine.shutil.which", _which)
    from app.spec_import_engine import resolve_spec_import_worker_argv

    argv = resolve_spec_import_worker_argv()
    assert argv[:3] == ["npm", "exec", "--workspace=objectified-ui"]


def test_resolve_spec_import_worker_invocation_uses_local_tsx_bin(monkeypatch, tmp_path):
    monkeypatch.delenv("SPEC_IMPORT_WORKER_ARGV", raising=False)
    monkeypatch.delenv("OBJECTIFIED_SPEC_IMPORT_WORKER_ARGV", raising=False)
    repo = tmp_path
    ui = repo / "objectified-ui"
    scripts = ui / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "rest-spec-import-worker.ts").write_text("//", encoding="utf-8")
    bin_dir = ui / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    tsx_sh = bin_dir / "tsx"
    tsx_sh.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr("app.spec_import_engine._REPO_ROOT", repo)
    monkeypatch.setattr("app.spec_import_engine.shutil.which", lambda _: None)

    from app.spec_import_engine import resolve_spec_import_worker_invocation

    argv, cwd = resolve_spec_import_worker_invocation()
    assert cwd == ui
    assert argv[0] == str(tsx_sh)
    assert argv[1] == "scripts/rest-spec-import-worker.ts"


def test_resolve_spec_import_worker_invocation_raises_without_runner(monkeypatch, tmp_path):
    monkeypatch.delenv("SPEC_IMPORT_WORKER_ARGV", raising=False)
    monkeypatch.delenv("OBJECTIFIED_SPEC_IMPORT_WORKER_ARGV", raising=False)
    repo = tmp_path
    ui = repo / "objectified-ui"
    scripts = ui / "scripts"
    scripts.mkdir(parents=True)
    (scripts / "rest-spec-import-worker.ts").write_text("//", encoding="utf-8")
    monkeypatch.setattr("app.spec_import_engine._REPO_ROOT", repo)
    monkeypatch.setattr("app.spec_import_engine.shutil.which", lambda _: None)

    from app.spec_import_engine import resolve_spec_import_worker_invocation

    with pytest.raises(RuntimeError, match="SPEC_IMPORT_WORKER_ARGV"):
        resolve_spec_import_worker_invocation()
