"""Export limits — X5 (#6226).

One test (or more) per limit, each proving the refusal names the limit it hit:

* **size** — an artifact over ``APIOME_EXPORT_ARTIFACT_MAX_BYTES`` fails ``EXPORT_ARTIFACT_TOO_LARGE``;
* **time** — a job past ``APIOME_EXPORT_JOB_TIMEOUT_SECONDS`` fails ``EXPORT_JOB_TIMED_OUT``;
* **batch** — more than ``MAX_BATCH_ITEMS`` item × target pairs (or version × target items) is a 422;
* **retention** — an artifact past ``APIOME_EXPORT_ARTIFACT_RETENTION_HOURS`` is removed from memory by
  the next submit or list (not only by a download) and its download is 410; the shared store's rows
  are reaped by the scheduled sweep (``tests/test_async_job_retention_sweep.py``);
* **concurrency** — past ``APIOME_EXPORT_MAX_CONCURRENT_JOBS_PER_TENANT`` queued + running jobs, a
  submit is a 429; other tenants are unaffected, the shared store's active jobs count, and a slot
  frees when a job finishes.

The source loader is faked (``tests/test_export_job_routes.py``'s ``_source``); the emitter is real.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import export_job_engine as eje
from app.auth import validate_authentication
from app.config import settings
from app.database import db
from app.export_job_engine import MAX_BATCH_ITEMS, MAX_BATCH_VERSIONS
from app.main import app
from tests.test_export_job_routes import _source

client = TestClient(app)


@pytest.fixture(autouse=True)
def _auth_and_store(monkeypatch):
    """Any tenant slug authenticates; the job store starts empty; no shared store answers."""
    app.dependency_overrides[validate_authentication] = lambda tenant_slug: {
        "tenant_id": f"tenant-{tenant_slug}",
        "tenant_slug": tenant_slug,
        "user_id": "user-1",
        "auth_method": "jwt",
    }
    monkeypatch.setattr(db, "list_async_jobs", _no_shared_store, raising=False)
    eje._jobs.clear()
    yield
    app.dependency_overrides.pop(validate_authentication, None)
    eje._jobs.clear()


def _no_shared_store(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
    raise RuntimeError("no shared store in this test")


def _submit(tenant: str = "acme", **body: Any):
    return client.post(f"/v1/export/{tenant}/jobs", json={"artifact": "artifact-1", "target": "openapi", **body})


def _wait(job_id: str, tenant: str = "acme", states=("completed", "failed", "canceled")) -> Dict[str, Any]:
    for _ in range(600):
        body = client.get(f"/v1/export/{tenant}/jobs/{job_id}").json()
        if body["state"] in states:
            return body
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} never reached {states}")


# ---------------------------------------------------------------------------
# Size
# ---------------------------------------------------------------------------


def test_an_artifact_over_the_size_cap_fails_naming_the_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "export_artifact_max_bytes", 16)
    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        body = _wait(_submit().json()["job_id"])
    assert body["state"] == "failed"
    error = body["error"]
    assert error["code"] == "EXPORT_ARTIFACT_TOO_LARGE"
    assert error["context"]["max_bytes"] == 16
    assert "APIOME_EXPORT_ARTIFACT_MAX_BYTES" in error["message"]


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------


def test_a_job_past_the_time_cap_fails_naming_the_cap(monkeypatch) -> None:
    monkeypatch.setattr(eje, "export_job_timeout_seconds", lambda: 0.2)
    release = threading.Event()

    def slow_source(*_args: Any, **_kwargs: Any):
        release.wait(5)
        return _source()

    try:
        with patch("app.export_job_engine.load_export_source", side_effect=slow_source):
            body = _wait(_submit().json()["job_id"])
    finally:
        release.set()
    assert body["state"] == "failed"
    error = body["error"]
    assert error["code"] == "EXPORT_JOB_TIMED_OUT"
    assert error["category"] == "resource"
    assert "APIOME_EXPORT_JOB_TIMEOUT_SECONDS" in error["message"]
    assert "APIOME_EXPORT_JOB_TIMEOUT_SECONDS" in error["remediation"]
    assert error["context"] == {"timeout_seconds": 0}  # 0.2 s, reported in whole seconds


def test_the_time_cap_reads_its_setting_and_turns_off_at_zero(monkeypatch) -> None:
    monkeypatch.setattr(settings, "export_job_timeout_seconds", 900)
    assert eje.export_job_timeout_seconds() == 900.0
    monkeypatch.setattr(settings, "export_job_timeout_seconds", 0)
    assert eje.export_job_timeout_seconds() is None


def test_a_job_inside_the_time_cap_completes(monkeypatch) -> None:
    monkeypatch.setattr(eje, "export_job_timeout_seconds", lambda: 30.0)
    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        assert _wait(_submit().json()["job_id"])["state"] == "completed"


# ---------------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------------


def test_too_many_items_is_refused_naming_the_cap() -> None:
    items = [{"artifact": f"item-{n}"} for n in range(MAX_BATCH_ITEMS + 1)]
    response = client.post("/v1/export/acme/jobs", json={"items": items, "target": "openapi"})
    assert response.status_code == 422
    # The list itself is capped, so the request model's own message names the cap.
    assert f"at most {MAX_BATCH_ITEMS} items" in response.text


def test_too_many_versions_is_refused_naming_the_cap() -> None:
    versions = [f"1.{n}.0" for n in range(MAX_BATCH_VERSIONS + 1)]
    response = _submit(versions=versions)
    assert response.status_code == 422
    assert str(MAX_BATCH_VERSIONS) in response.text


def test_items_times_targets_count_against_the_cap() -> None:
    items = [{"artifact": f"item-{n}"} for n in range(MAX_BATCH_ITEMS // 2 + 1)]
    response = client.post(
        "/v1/export/acme/jobs",
        json={"items": items, "targets": [{"target": "openapi"}, {"target": "asyncapi"}]},
    )
    assert response.status_code == 422
    assert f"at most {MAX_BATCH_ITEMS} item × target pairs" in response.text


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


def _expire(job_id: str) -> None:
    eje._jobs[job_id].artifact_expires_at_ms = int(time.time() * 1000) - 1


@pytest.mark.parametrize("trigger", ["submit", "list"])
def test_an_expired_artifact_is_removed_without_a_download(trigger) -> None:
    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        job_id = _submit().json()["job_id"]
        assert _wait(job_id)["state"] == "completed"
        # A single-file job keeps its bytes as the emit result; a bundle as the retained download.
        held = eje._jobs[job_id]
        assert held.emit_result is not None or held.retained_download is not None
        _expire(job_id)
        if trigger == "submit":
            _wait(_submit().json()["job_id"])
        else:
            client.get("/v1/export/acme/jobs")
    record = eje._jobs[job_id]
    assert record.retained_download is None
    assert record.emit_result is None
    assert client.get(f"/v1/export/acme/jobs/{job_id}/download").status_code == 410


def test_retention_follows_its_setting(monkeypatch) -> None:
    monkeypatch.setattr(settings, "export_artifact_retention_hours", 2)
    assert eje._artifact_expiry_from(0) == 2 * 3_600_000
    monkeypatch.setattr(settings, "export_artifact_retention_hours", 0)
    assert eje._artifact_expiry_from(0) is None


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


@pytest.fixture
def held_jobs():
    """Jobs whose source load blocks until released, so they stay running."""
    release = threading.Event()

    def held_source(*_args: Any, **_kwargs: Any):
        release.wait(10)
        return _source()

    with patch("app.export_job_engine.load_export_source", side_effect=held_source):
        yield release
    release.set()


def test_a_submit_past_the_concurrency_cap_is_refused_naming_the_cap(monkeypatch, held_jobs) -> None:
    monkeypatch.setattr(settings, "export_max_concurrent_jobs_per_tenant", 2)
    first = _submit().json()["job_id"]
    second = _submit().json()["job_id"]

    refused = _submit()
    assert refused.status_code == 429
    detail = refused.json()["detail"]
    assert "at most 2 at once" in detail
    assert "APIOME_EXPORT_MAX_CONCURRENT_JOBS_PER_TENANT" in detail

    # Another workspace has its own allowance.
    assert _submit("globex").status_code == 202

    # A finished job frees its slot.
    held_jobs.set()
    for job_id in (first, second):
        _wait(job_id)
    assert _submit().status_code == 202


def test_a_canceled_job_frees_its_slot(monkeypatch, held_jobs) -> None:
    monkeypatch.setattr(settings, "export_max_concurrent_jobs_per_tenant", 1)
    job_id = _submit().json()["job_id"]
    assert _submit().status_code == 429
    assert client.delete(f"/v1/export/acme/jobs/{job_id}").status_code == 204
    held_jobs.set()
    _wait(job_id)
    assert _submit().status_code == 202


def test_active_jobs_on_other_instances_count(monkeypatch, held_jobs) -> None:
    monkeypatch.setattr(settings, "export_max_concurrent_jobs_per_tenant", 2)
    asked: List[Dict[str, Any]] = []

    def shared(tenant_slug, kind, **kwargs):
        asked.append({"tenant": tenant_slug, "kind": kind, **kwargs})
        row = {"status": {"job_id": f"remote-{kwargs['state']}"}}
        return {"jobs": [row], "total": 1, "limit": 200, "offset": 0}

    monkeypatch.setattr(db, "list_async_jobs", shared, raising=False)
    # One remote queued + one remote running fill both slots.
    refused = _submit()
    assert refused.status_code == 429
    assert "already has 2 export jobs" in refused.json()["detail"]
    assert {entry["state"] for entry in asked} == {"queued", "running"}
    assert all(entry["kind"] == "export" and entry["created_after"] is not None for entry in asked)


def test_a_job_on_both_views_counts_once(monkeypatch, held_jobs) -> None:
    monkeypatch.setattr(settings, "export_max_concurrent_jobs_per_tenant", 2)
    local = _submit().json()["job_id"]
    monkeypatch.setattr(
        db,
        "list_async_jobs",
        lambda *_a, **k: {"jobs": [{"status": {"job_id": local}}] if k["state"] == "running" else [], "total": 1},
        raising=False,
    )
    assert _submit().status_code == 202


def test_the_concurrency_cap_turns_off_at_zero(monkeypatch, held_jobs) -> None:
    monkeypatch.setattr(settings, "export_max_concurrent_jobs_per_tenant", 0)
    for _ in range(4):
        assert _submit().status_code == 202
