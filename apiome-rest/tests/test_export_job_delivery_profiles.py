"""Export jobs delivered with delivery profiles on completion — MFX-38.4 (#4331).

An export job submitted with ``delivery_profiles`` is delivered with each profile as soon as it
completes, through :func:`app.export_delivery_profile_routes.deliver_with_profile`:

* the request refuses a repeated or blank id and profiles on a dry run (422);
* the submit route needs ``versions:publish`` and existing profiles (400), and hands the submitter's
  context to the engine (kept in memory, never mirrored);
* on completion every profile is delivered in turn, each adding ``EXPORT_DELIVERED`` or
  ``EXPORT_DELIVERY_FAILED`` to the job — a delivery never changes the job's state, and one failing (or
  refused, or crashing) never stops the next;
* a failed job, a dry run or a job without profiles delivers nothing.

The source loader is faked as in ``test_export_job_engine.py``; the delivery itself is faked (its own
behaviour is ``test_export_delivery_profiles.py``).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import validate_authentication
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Service,
)
from app.export_delivery_profile_routes import ExportDeliveryAttemptModel
from app.export_job_engine import (
    ExportJobStartRequest,
    _jobs,
    get_export_job_status,
    schedule_export_job,
)
from app.export_source import ExportSource, ExportSourceError
from app.main import app
from app.permissions import Action, Resource

TENANT_SLUG = "acme"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
AUTH = {"tenant_id": TENANT_ID, "user_id": "u1", "auth_method": "jwt"}
PROFILE_A = "55555555-5555-4555-8555-555555555555"
PROFILE_B = "66666666-6666-4666-8666-666666666666"
DELIVER = "app.export_delivery_profile_routes.deliver_with_profile"

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_export_jobs_between_tests():
    _jobs.clear()
    yield
    _jobs.clear()


def _source() -> ExportSource:
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    api = CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="widgets"),
                       services=[Service(key="widgets", name="widgets", operations=[op])])
    return ExportSource(api=api, artifact_id="artifact-1", version_record_id="rev-uuid-1", version_label="1.0.0")


def _attempt(profile_id: str, **fields: Any) -> ExportDeliveryAttemptModel:
    values: Dict[str, Any] = dict(channel="object_storage", run_id="run-1", job_id="job", status="delivered",
                                  outcome="delivered", profile_id=profile_id, profile_name="lake",
                                  destination="data-lake/exports")
    values.update(fields)
    return ExportDeliveryAttemptModel(**values)


async def _events_until(job_id: str, codes: List[str]) -> Dict[str, Any]:
    """Poll until the job carries one event per expected delivery code; return the status."""
    for _ in range(500):
        status = (await get_export_job_status(TENANT_SLUG, job_id)).model_dump()
        seen = [e["code"] for e in status["events"] if e["code"].startswith("EXPORT_DELIVER")]
        if status["state"] in ("completed", "failed", "canceled") and len(seen) >= len(codes):
            return status
        await asyncio.sleep(0.01)
    raise AssertionError("the job's deliveries did not finish")


async def _drain(job_id: str) -> Dict[str, Any]:
    for _ in range(500):
        status = (await get_export_job_status(TENANT_SLUG, job_id)).model_dump()
        if status["state"] in ("completed", "failed", "canceled"):
            await asyncio.sleep(0.05)  # let the post-terminal delivery step run
            return status
        await asyncio.sleep(0.01)
    raise AssertionError("export job did not reach a terminal state")


# ===========================================================================
# The request
# ===========================================================================


@pytest.mark.parametrize("fields, message", [
    ({"delivery_profiles": [PROFILE_A, PROFILE_A]}, "cannot name a profile twice"),
    ({"delivery_profiles": [" "]}, "cannot contain a blank id"),
    ({"delivery_profiles": [PROFILE_A], "dry_run": True}, "A dry run has no files to deliver"),
    ({"delivery_profiles": []}, "at least 1"),
    ({"delivery_profiles": [str(i) for i in range(6)]}, "at most 5"),
])
def test_the_request_refuses_bad_delivery_profiles(fields: Dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError) as caught:
        ExportJobStartRequest(artifact="artifact-1", target="openapi", **fields)
    assert message in str(caught.value)


def test_profile_ids_are_trimmed() -> None:
    request = ExportJobStartRequest(artifact="a", target="openapi", delivery_profiles=[f" {PROFILE_A} "])
    assert request.delivery_profiles == [PROFILE_A]


# ===========================================================================
# The engine
# ===========================================================================


async def test_a_completed_job_is_delivered_with_every_profile_in_order() -> None:
    request = ExportJobStartRequest(artifact="artifact-1", target="openapi", delivery_profiles=[PROFILE_A, PROFILE_B])
    deliver = AsyncMock(side_effect=[_attempt(PROFILE_A), _attempt(PROFILE_B, outcome="failed", status="failed",
                                                                   error_code="export-object-storage-x",
                                                                   error_message="bucket missing")])
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(DELIVER, new=deliver):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request, auth_data=AUTH)
        status = await _events_until(accepted.job_id, ["EXPORT_DELIVERED", "EXPORT_DELIVERY_FAILED"])
    assert status["state"] == "completed"
    assert [call.args for call in deliver.call_args_list] == [
        (TENANT_SLUG, TENANT_ID, accepted.job_id, PROFILE_A, AUTH),
        (TENANT_SLUG, TENANT_ID, accepted.job_id, PROFILE_B, AUTH),
    ]
    delivered, failed = [e for e in status["events"] if e["code"].startswith("EXPORT_DELIVER")]
    assert delivered["code"] == "EXPORT_DELIVERED" and delivered["level"] == "info"
    assert delivered["context"]["destination"] == "data-lake/exports"
    assert failed["code"] == "EXPORT_DELIVERY_FAILED" and failed["level"] == "error"
    assert failed["context"]["error_code"] == "export-object-storage-x"
    assert "bucket missing" in failed["message"]


async def test_a_refused_or_crashing_delivery_never_stops_the_next() -> None:
    request = ExportJobStartRequest(artifact="artifact-1", target="openapi",
                                    delivery_profiles=[PROFILE_A, PROFILE_B, "77777777-7777-4777-8777-777777777777"])
    deliver = AsyncMock(side_effect=[
        HTTPException(status_code=404, detail="Delivery profile not found"),
        RuntimeError("boom"),
        _attempt(PROFILE_A),
    ])
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(DELIVER, new=deliver):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request, auth_data=AUTH)
        status = await _events_until(accepted.job_id, ["x", "y", "z"])
    codes = [(e["code"], (e.get("context") or {}).get("error_code")) for e in status["events"]
             if e["code"].startswith("EXPORT_DELIVER")]
    assert codes == [("EXPORT_DELIVERY_FAILED", None), ("EXPORT_DELIVERY_FAILED",
                                                        "export-delivery-profile-internal-error"),
                     ("EXPORT_DELIVERED", None)]
    refused = next(e for e in status["events"] if e["code"] == "EXPORT_DELIVERY_FAILED")
    assert refused["context"]["status_code"] == 404 and "could not start" in refused["message"]
    assert status["state"] == "completed"


async def test_a_failed_job_delivers_nothing() -> None:
    request = ExportJobStartRequest(artifact="artifact-1", target="openapi", delivery_profiles=[PROFILE_A])
    with patch("app.export_job_engine.load_export_source", side_effect=ExportSourceError("gone", status_code=404)), \
            patch(DELIVER, new=AsyncMock()) as deliver:
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request, auth_data=AUTH)
        status = await _drain(accepted.job_id)
    assert status["state"] == "failed"
    deliver.assert_not_called()


async def test_a_job_without_profiles_or_context_delivers_nothing() -> None:
    with patch("app.export_job_engine.load_export_source", return_value=_source()), \
            patch(DELIVER, new=AsyncMock()) as deliver:
        plain = await schedule_export_job(TENANT_SLUG, TENANT_ID,
                                          ExportJobStartRequest(artifact="artifact-1", target="openapi"),
                                          auth_data=AUTH)
        await _drain(plain.job_id)
        anonymous = await schedule_export_job(
            TENANT_SLUG, TENANT_ID,
            ExportJobStartRequest(artifact="artifact-1", target="openapi", delivery_profiles=[PROFILE_A]))
        await _drain(anonymous.job_id)
    deliver.assert_not_called()


async def test_the_submitter_s_context_is_never_mirrored() -> None:
    request = ExportJobStartRequest(artifact="artifact-1", target="openapi", delivery_profiles=[PROFILE_A])
    mirrored: List[Any] = []
    with patch("app.export_job_engine.load_export_source", return_value=_source()), \
            patch(DELIVER, new=AsyncMock(return_value=_attempt(PROFILE_A))), \
            patch("app.database.db.upsert_async_job", side_effect=lambda *a, **k: mirrored.append((a, k))):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request, auth_data=AUTH)
        await _events_until(accepted.job_id, ["EXPORT_DELIVERED"])
    assert mirrored, "the job should have been mirrored"
    assert "u1" not in repr(mirrored) and "auth_method" not in repr(mirrored)


# ===========================================================================
# The submit route
# ===========================================================================


def _body(**fields: Any) -> Dict[str, Any]:
    return {"artifact": "artifact-1", "target": "openapi", **fields}


def test_submitting_profiles_needs_versions_publish_and_existing_profiles() -> None:
    app.dependency_overrides[validate_authentication] = lambda: AUTH
    try:
        with patch("app.export_job_routes.enforce_permission") as guard, \
                patch("app.export_job_routes.db.get_export_delivery_profile", return_value=None), \
                patch("app.export_job_routes.schedule_export_job") as schedule:
            response = client.post(f"/v1/export/{TENANT_SLUG}/jobs", json=_body(delivery_profiles=[PROFILE_A]))
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "export-delivery-profile-unknown"
        assert [call.args[2:] for call in guard.call_args_list] == [(Resource.VERSIONS, Action.PUBLISH)]
        schedule.assert_not_called()

        with patch("app.export_job_routes.enforce_permission"), \
                patch("app.export_job_routes.db.get_export_delivery_profile", return_value={"id": PROFILE_A}), \
                patch("app.export_job_routes.schedule_export_job",
                      new=AsyncMock(return_value={"job_id": "j", "status_path": "/p"})) as schedule:
            response = client.post(f"/v1/export/{TENANT_SLUG}/jobs", json=_body(delivery_profiles=[PROFILE_A]))
        assert response.status_code == 202, response.text
        assert schedule.call_args.kwargs == {"auth_data": AUTH}

        with patch("app.export_job_routes.enforce_permission") as guard, \
                patch("app.export_job_routes.schedule_export_job",
                      new=AsyncMock(return_value={"job_id": "j", "status_path": "/p"})):
            assert client.post(f"/v1/export/{TENANT_SLUG}/jobs", json=_body()).status_code == 202
        guard.assert_not_called()
    finally:
        app.dependency_overrides.clear()
