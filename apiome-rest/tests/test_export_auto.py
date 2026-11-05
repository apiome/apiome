"""Auto-export on version publish — MFX-39.4 (#4336).

The rules (:mod:`app.export_auto`): the loss a job measured (critical for a severe / near-empty conversion,
a types-only result or a critical construct; warn for any other loss), the halt decision with and without
pre-approval, the export a publish runs and the inbox notice. The worker (:mod:`app.export_auto_worker`): the
publish hook never raises, a run halts (nothing delivered, people notified, audited) or delivers as the
publisher, a failed job / stale preset / full export slots, the sweep's reaping, and releasing a halted run.
The routes (:mod:`app.export_auto_routes`): permissions, refusals, audits. Last, the publish wiring, the
inbox vocabulary and the V359 migration.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg2 import errors as pg_errors

from app import export_auto_worker as worker
from app.auth import validate_authentication
from app.export_auto import build_auto_request, halt_notice, measure_loss, should_halt
from app.export_delivery_profile_routes import ExportDeliveryAttemptModel
from app.export_service import ExportError
from app.main import app
from app.notifications import NOTIFICATION_TYPES, TYPE_EXPORT_AUTO_HALTED
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_PRESET = "77777777-7777-4777-8777-777777777777"
_PROFILE = "55555555-5555-4555-8555-555555555555"
_SUB = "88888888-8888-4888-8888-888888888888"
_RUN = "99999999-9999-4999-8999-999999999999"
_PUBLISHER = "33333333-3333-4333-8333-333333333333"
_OWNER = "44444444-4444-4444-8444-444444444444"
_AUTH = {"tenant_id": _TENANT, "user_id": "u1", "auth_method": "jwt"}


def _target(
    tier: str = "lossless", verdict: str = "clean", critical: int = 0, preserved: int = 100, label: str = "openapi-3.1"
) -> SimpleNamespace:
    return SimpleNamespace(
        target=label,
        fidelity=SimpleNamespace(summary=SimpleNamespace(tier=tier)),
        guard=SimpleNamespace(verdict=verdict, critical_constructs=critical, preserved_percent=preserved),
    )


def _single(**kw: Any) -> SimpleNamespace:
    t = _target(**kw)
    return SimpleNamespace(targets=None, target=t.target, fidelity=t.fidelity, guard=t.guard)


# ===========================================================================
# The rules
# ===========================================================================


@pytest.mark.parametrize(
    "kw, severity",
    [
        ({}, "info"),
        ({"tier": "lossy", "verdict": "lossy", "preserved": 80}, "warn"),
        ({"tier": "lossy", "verdict": "severe", "preserved": 20}, "critical"),
        ({"verdict": "near-empty"}, "critical"),
        ({"tier": "types-only"}, "critical"),
        ({"tier": "lossy", "critical": 2}, "critical"),
    ],
)
def test_one_target_s_loss(kw: Dict[str, Any], severity: str) -> None:
    assert measure_loss(_single(**kw))[0] == severity


def test_the_worst_target_decides_and_every_reason_is_kept() -> None:
    result = SimpleNamespace(
        targets=[
            _target(),
            _target(tier="lossy", verdict="lossy", preserved=70, label="proto3"),
            _target(verdict="severe", preserved=10, label="avro"),
        ]
    )
    severity, reasons = measure_loss(result)
    assert severity == "critical"
    assert reasons == ["proto3: lossy (70% preserved)", "avro: a severe conversion (10% preserved)"]


def test_the_halt_decision() -> None:
    assert should_halt("critical", "critical", False) is True
    assert should_halt("warn", "critical", False) is False
    assert should_halt("warn", "warn", False) is True
    assert should_halt("critical", "critical", True) is False
    assert should_halt("info", "warn", False) is False


def test_the_export_a_publish_runs() -> None:
    preset = {
        "id": _PRESET,
        "name": "nightly",
        "targets": [{"target": "openapi", "options": {"openapi_version": "3.0"}}],
        "delivery_profile_id": _PROFILE,
    }
    request, profiles = build_auto_request(_PROJECT, "rev-1", preset)
    assert (request.artifact, request.version, request.target) == (_PROJECT, "rev-1", "openapi")
    assert request.options == {"openapi_version": "3.0"}
    assert request.confirm is True and request.preset is None and request.delivery_profiles is None
    assert profiles == [_PROFILE]


def test_the_inbox_notice() -> None:
    halted = halt_notice(
        {
            "id": _RUN,
            "status": "halted",
            "preset_name": "nightly",
            "loss_severity": "critical",
            "loss_reasons": ["avro: a severe conversion (10% preserved)"],
        },
        project_name="Orders API",
        version_label="1.4.0",
    )
    assert halted["summary"].startswith(
        "Auto-export 'nightly' of Orders API 1.4.0 was not delivered: the export's "
        "loss is critical — avro: a severe conversion"
    )
    assert halted["link"] == "/ade/dashboard/export/studio?tab=presets"
    failed = halt_notice({"status": "failed", "preset_name": "nightly", "error_message": "boom"})
    assert failed["summary"] == "Auto-export 'nightly' of the new version failed: boom"


# ===========================================================================
# The worker
# ===========================================================================


def test_the_publish_hook_never_raises() -> None:
    database = MagicMock()
    database.enqueue_export_auto_runs.return_value = 2
    assert (
        worker.enqueue_auto_export_on_publish(
            db=database, tenant_id=_TENANT, project_id=_PROJECT, version_record_id="rev-1", actor_id=_PUBLISHER
        )
        == 2
    )
    database.enqueue_export_auto_runs.assert_called_once_with(
        tenant_id=_TENANT, project_id=_PROJECT, version_record_id="rev-1", published_by=_PUBLISHER
    )
    database.enqueue_export_auto_runs.side_effect = RuntimeError("db down")
    assert (
        worker.enqueue_auto_export_on_publish(
            db=database, tenant_id=_TENANT, project_id=_PROJECT, version_record_id="rev-1"
        )
        == 0
    )
    assert (
        worker.enqueue_auto_export_on_publish(
            db=database, tenant_id="acme", project_id=_PROJECT, version_record_id="rev-1"
        )
        == 0
    )


def _claimed(**fields: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = dict(
        id=_RUN,
        tenant_id=_TENANT,
        project_id=_PROJECT,
        version_record_id="rev-1",
        subscription_id=_SUB,
        preset_id=_PRESET,
        preset_name="nightly",
        halt_at="critical",
        approve_loss=False,
        status="running",
        published_by=_PUBLISHER,
        tenant_slug="acme",
        project_name="Orders API",
        claim_token="tok",
        preset_targets=[{"target": "openapi", "options": {}}],
        preset_delivery_profile_id=_PROFILE,
    )
    values.update(fields)
    return values


def _database() -> MagicMock:
    database = MagicMock()
    database.get_export_auto_subscription.return_value = {"created_by": _OWNER}
    database.finish_export_auto_run.side_effect = lambda run_id, **kw: {
        "id": run_id,
        "tenant_id": _TENANT,
        "project_id": _PROJECT,
        **kw,
    }
    database.notify_export_auto_run.return_value = 2
    return database


def _status(state: str = "completed", result: Any = None, error: Any = None) -> SimpleNamespace:
    return SimpleNamespace(state=state, result=result, error=error)


async def _run(
    database: MagicMock, *, status: SimpleNamespace, run: Dict[str, Any] = None, deliver: Any = None
) -> tuple:
    with (
        patch.object(
            worker, "schedule_export_job", new=AsyncMock(return_value=SimpleNamespace(job_id="job-1"))
        ) as sched,
        patch.object(worker, "get_export_job_status", new=AsyncMock(return_value=status)),
        patch("app.export_delivery_profile_routes.deliver_with_profile", new=deliver or AsyncMock()) as dlv,
        patch.object(worker, "write_audit") as audit,
    ):
        closed = await worker.run_auto_export(database, run or _claimed())
    return closed, sched, dlv, audit


async def test_a_critical_loss_halts_auto_delivery_and_notifies() -> None:
    database = _database()
    closed, sched, deliver, audit = await _run(database, status=_status(result=_single(verdict="severe", preserved=5)))
    assert closed["status"] == "halted" and closed["loss_severity"] == "critical"
    deliver.assert_not_called()
    request = sched.call_args.args[2]
    assert request.confirm is True and request.delivery_profiles is None
    database.set_export_auto_run_job.assert_called_once_with(_RUN, "tok", "job-1")
    assert audit.call_args.kwargs["action"] == "export.auto_export.halted"
    assert audit.call_args.kwargs["auth_data"]["user_id"] == _PUBLISHER
    tenant, drafts = database.notify_export_auto_run.call_args.args
    assert tenant == _TENANT
    assert [(d.user_id, d.type) for d in drafts] == [
        (_PUBLISHER, TYPE_EXPORT_AUTO_HALTED),
        (_OWNER, TYPE_EXPORT_AUTO_HALTED),
    ]
    assert drafts[0].payload["summary"].startswith("Auto-export 'nightly' of Orders API was not delivered")


async def test_a_pre_approved_loss_is_delivered_as_the_publisher() -> None:
    database = _database()
    attempt = ExportDeliveryAttemptModel(
        channel="object_storage",
        run_id="dr1",
        job_id="job-1",
        status="delivered",
        outcome="delivered",
        profile_id=_PROFILE,
        profile_name="lake",
        destination="data-lake/x",
    )
    closed, _sched, deliver, audit = await _run(
        database,
        run=_claimed(approve_loss=True),
        status=_status(result=_single(verdict="severe")),
        deliver=AsyncMock(return_value=attempt),
    )
    assert closed["status"] == "delivered"
    assert closed["deliveries"][0]["outcome"] == "delivered" and closed["deliveries"][0]["profileName"] == "lake"
    args = deliver.call_args.args
    assert args[:4] == ("acme", _TENANT, "job-1", _PROFILE) and args[4]["user_id"] == _PUBLISHER
    assert audit.call_args.kwargs["action"] == "export.auto_export.completed"
    assert audit.call_args.kwargs["detail"]["approvedLoss"] is True
    database.notify_export_auto_run.assert_not_called()


async def test_a_mild_loss_is_delivered_and_a_failed_delivery_recorded() -> None:
    database = _database()
    closed, *_ = await _run(
        database,
        status=_status(result=_single(tier="lossy", verdict="lossy")),
        deliver=AsyncMock(side_effect=HTTPException(status_code=410, detail={"code": "gone"})),
    )
    assert closed["status"] == "delivery_failed" and closed["loss_severity"] == "warn"
    assert closed["deliveries"] == [
        {"profileId": _PROFILE, "outcome": "failed", "errorCode": "gone", "errorMessage": None}
    ]


async def test_no_delivery_profile_is_exported_only() -> None:
    closed, *_ = await _run(
        _database(), run=_claimed(preset_delivery_profile_id=None), status=_status(result=_single())
    )
    assert closed["status"] == "exported"


async def test_a_failed_job_fails_the_run_and_notifies() -> None:
    database = _database()
    closed, *_ = await _run(
        database, status=_status(state="failed", error=SimpleNamespace(code="SOURCE_LOAD_FAILED", message="gone"))
    )
    assert (closed["status"], closed["error_code"], closed["error_message"]) == ("failed", "SOURCE_LOAD_FAILED", "gone")
    database.notify_export_auto_run.assert_called_once()


async def test_a_deleted_or_stale_preset_fails_without_exporting() -> None:
    closed, sched, *_ = await _run(_database(), run=_claimed(preset_targets=None), status=_status())
    assert closed["error_code"] == "export-auto-preset-missing"
    sched.assert_not_called()
    closed, sched, *_ = await _run(
        _database(), run=_claimed(preset_targets=[{"target": "openapi", "options": {"x": 1}}]), status=_status()
    )
    assert closed["error_code"] == "export-auto-preset-invalid"
    sched.assert_not_called()


async def test_full_export_slots_hand_the_run_back() -> None:
    database = _database()
    with patch.object(worker, "schedule_export_job", new=AsyncMock(side_effect=ExportError("busy", status_code=429))):
        closed = await worker.run_auto_export(database, _claimed())
    assert closed["status"] == "pending"
    database.notify_export_auto_run.assert_not_called()


async def test_the_sweep_reaps_then_claims(monkeypatch) -> None:
    monkeypatch.setattr(worker.settings, "export_auto_enabled", True)
    monkeypatch.setattr(worker.settings, "export_auto_batch_size", 3)
    database = _database()
    database.reap_stale_export_auto_runs.return_value = [_claimed(status="failed", error_code="export-auto-lost")]
    database.claim_next_export_auto_run.side_effect = [_claimed(), None]
    with (
        patch.object(worker, "run_auto_export", new=AsyncMock(return_value={"status": "delivered"})) as run,
        patch.object(worker, "write_audit") as audit,
    ):
        assert await worker.process_auto_export_sweep(database) == 1
    assert run.call_args.args[1]["claim_token"]
    assert audit.call_args.kwargs["action"] == "export.auto_export.failed"
    database.notify_export_auto_run.assert_called_once()
    monkeypatch.setattr(worker.settings, "export_auto_enabled", False)
    assert await worker.process_auto_export_sweep(database) == 0


async def test_releasing_a_halted_run() -> None:
    database = _database()
    database.get_export_preset.return_value = {"delivery_profile_id": _PROFILE}
    attempt = ExportDeliveryAttemptModel(
        channel="git",
        run_id="g1",
        job_id="job-1",
        status="opened",
        outcome="delivered",
        profile_id=_PROFILE,
        profile_name="repo",
        destination="acme/specs",
    )
    with (
        patch("app.export_delivery_profile_routes.deliver_with_profile", new=AsyncMock(return_value=attempt)),
        patch.object(worker, "write_audit") as audit,
    ):
        released = await worker.release_halted_run(database, _claimed(status="halted", job_id="job-1"), _AUTH)
    assert released["status"] == "delivered"
    assert database.finish_export_auto_run.call_args.kwargs["released_by"] == "u1"
    assert audit.call_args.kwargs["action"] == "export.auto_export.released"
    with pytest.raises(HTTPException) as caught:
        await worker.release_halted_run(database, _claimed(status="delivered", job_id="job-1"), _AUTH)
    assert caught.value.status_code == 409
    database.get_export_preset.return_value = {"delivery_profile_id": None}
    with pytest.raises(HTTPException):
        await worker.release_halted_run(database, _claimed(status="halted", job_id="job-1"), _AUTH)


# ===========================================================================
# The routes
# ===========================================================================

_ROUTES = "app.export_auto_routes"


@pytest.fixture
def auth():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


def _tenant():
    return patch("app.export_git_delivery_routes.db.get_tenant_row_by_slug", return_value={"id": _TENANT})


def _sub_row(**fields: Any) -> Dict[str, Any]:
    values = dict(
        id=_SUB,
        project_id=_PROJECT,
        project_name="Orders API",
        preset_id=_PRESET,
        preset_name="nightly",
        halt_at="critical",
        approve_loss=False,
        active=True,
        created_by="u1",
    )
    values.update(fields)
    return values


def test_subscribing_needs_edit_and_publish(auth) -> None:
    body = {"projectId": _PROJECT, "preset": "nightly", "haltAt": "warn"}
    with (
        patch(f"{_ROUTES}.enforce_permission") as guard,
        _tenant(),
        patch(f"{_ROUTES}.db.get_export_preset", return_value={"id": _PRESET, "name": "nightly"}),
        patch(f"{_ROUTES}.db.get_project_by_id", return_value={"id": _PROJECT}),
        patch(f"{_ROUTES}.db.insert_export_auto_subscription", return_value=_sub_row(halt_at="warn")) as insert,
        patch(f"{_ROUTES}.write_audit") as audit,
    ):
        response = client.post("/v1/export/acme/auto-exports", json=body)
    assert response.status_code == 201, response.text
    assert [c.args[2:] for c in guard.call_args_list] == [
        (Resource.PROJECTS, Action.EDIT),
        (Resource.VERSIONS, Action.PUBLISH),
    ]
    assert insert.call_args.kwargs["halt_at"] == "warn" and insert.call_args.kwargs["preset_id"] == _PRESET
    assert response.json()["presetName"] == "nightly"
    assert audit.call_args.kwargs["action"] == "export.auto_export.subscription.created"


def test_subscribe_refusals(auth) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission"),
        _tenant(),
        patch(f"{_ROUTES}.db.get_export_preset", return_value=None),
        patch(f"{_ROUTES}.db.get_project_by_id", return_value=None),
    ):
        response = client.post("/v1/export/acme/auto-exports", json={"projectId": _PROJECT, "preset": "x"})
    assert response.status_code == 400 and len(response.json()["detail"]["errors"]) == 2
    with (
        patch(f"{_ROUTES}.enforce_permission"),
        _tenant(),
        patch(f"{_ROUTES}.db.get_export_preset", return_value={"id": _PRESET, "name": "nightly"}),
        patch(f"{_ROUTES}.db.get_project_by_id", return_value={"id": _PROJECT}),
        patch(f"{_ROUTES}.db.insert_export_auto_subscription", side_effect=pg_errors.UniqueViolation()),
    ):
        assert (
            client.post("/v1/export/acme/auto-exports", json={"projectId": _PROJECT, "preset": "x"}).status_code == 409
        )
    assert (
        client.post(
            "/v1/export/acme/auto-exports", json={"projectId": _PROJECT, "preset": "x", "haltAt": "info"}
        ).status_code
        == 422
    )


def test_turning_off_needs_only_edit_but_approving_needs_publish(auth) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission") as guard,
        _tenant(),
        patch(f"{_ROUTES}.db.get_export_auto_subscription", return_value=_sub_row()),
        patch(f"{_ROUTES}.db.update_export_auto_subscription", return_value=_sub_row(active=False)) as update,
        patch(f"{_ROUTES}.write_audit"),
    ):
        assert client.patch(f"/v1/export/acme/auto-exports/{_SUB}", json={"active": False}).status_code == 200
    assert [c.args[2:] for c in guard.call_args_list] == [(Resource.PROJECTS, Action.EDIT)]
    assert update.call_args.kwargs == {"halt_at": "critical", "approve_loss": False, "active": False, "actor_id": "u1"}
    with (
        patch(f"{_ROUTES}.enforce_permission") as guard,
        _tenant(),
        patch(f"{_ROUTES}.db.get_export_auto_subscription", return_value=_sub_row()),
        patch(f"{_ROUTES}.db.update_export_auto_subscription", return_value=_sub_row(approve_loss=True)),
        patch(f"{_ROUTES}.write_audit"),
    ):
        assert client.patch(f"/v1/export/acme/auto-exports/{_SUB}", json={"approveLoss": True}).status_code == 200
    assert (Resource.VERSIONS, Action.PUBLISH) in [c.args[2:] for c in guard.call_args_list]


def test_listing_deleting_and_runs(auth) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission"),
        _tenant(),
        patch(f"{_ROUTES}.db.get_export_preset", return_value={"id": _PRESET}),
        patch(f"{_ROUTES}.db.list_export_auto_subscriptions", return_value=[_sub_row()]) as listing,
    ):
        response = client.get("/v1/export/acme/auto-exports", params={"preset": "nightly"})
    assert response.json()["subscriptions"][0]["haltAt"] == "critical"
    listing.assert_called_once_with(_TENANT, project_id=None, preset_id=_PRESET)
    with (
        patch(f"{_ROUTES}.enforce_permission"),
        _tenant(),
        patch(f"{_ROUTES}.db.get_export_auto_subscription", return_value=_sub_row()),
        patch(f"{_ROUTES}.db.delete_export_auto_subscription", return_value=True),
        patch(f"{_ROUTES}.write_audit") as audit,
    ):
        assert client.delete(f"/v1/export/acme/auto-exports/{_SUB}").status_code == 204
    assert audit.call_args.kwargs["action"] == "export.auto_export.subscription.deleted"
    run = dict(_claimed(status="halted", loss_severity="critical", loss_reasons=["avro: severe"], deliveries=[]))
    with (
        patch(f"{_ROUTES}.enforce_permission"),
        _tenant(),
        patch(f"{_ROUTES}.db.list_export_auto_runs", return_value=[run]),
    ):
        runs = client.get("/v1/export/acme/auto-export-runs", params={"projectId": _PROJECT}).json()["runs"]
    assert (runs[0]["status"], runs[0]["lossSeverity"], runs[0]["lossReasons"]) == (
        "halted",
        "critical",
        ["avro: severe"],
    )


def test_releasing_needs_publish(auth) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission") as guard,
        _tenant(),
        patch(f"{_ROUTES}.db.get_export_auto_run", return_value=_claimed(status="halted", job_id="j")),
        patch(f"{_ROUTES}.release_halted_run", new=AsyncMock(return_value=_claimed(status="delivered", job_id="j"))),
    ):
        response = client.post(f"/v1/export/acme/auto-export-runs/{_RUN}/release")
    assert response.status_code == 200 and response.json()["status"] == "delivered"
    assert [c.args[2:] for c in guard.call_args_list] == [(Resource.VERSIONS, Action.PUBLISH)]
    with (
        patch(f"{_ROUTES}.enforce_permission"),
        _tenant(),
        patch(f"{_ROUTES}.db.get_export_auto_run", return_value=None),
    ):
        assert client.post(f"/v1/export/acme/auto-export-runs/{_RUN}/release").status_code == 404


# ===========================================================================
# Wiring
# ===========================================================================


def test_publishing_queues_auto_exports_after_its_response() -> None:
    from app import versions_routes

    source = inspect.getsource(versions_routes.publish_version)
    assert "background_tasks.add_task(\n        enqueue_auto_export_on_publish," in source


def test_the_inbox_knows_the_new_type() -> None:
    assert TYPE_EXPORT_AUTO_HALTED in NOTIFICATION_TYPES


def test_the_migration_carries_every_structural_promise() -> None:
    text = (Path(__file__).resolve().parents[2] / "apiome-db/scripts/V359__export_auto_on_publish_4336.sql").read_text()
    for fragment in (
        "CREATE TABLE IF NOT EXISTS export_auto_subscriptions (",
        "CONSTRAINT export_auto_subscriptions_unique UNIQUE (tenant_id, project_id, preset_id)",
        "CHECK (halt_at IN ('warn', 'critical'))",
        "CREATE TABLE IF NOT EXISTS export_auto_runs (",
        "subscription_id UUID REFERENCES export_auto_subscriptions(id) ON DELETE SET NULL",
        "CHECK (status IN ('pending', 'running', 'delivered', 'exported', 'halted', 'delivery_failed', 'failed'))",
        "'export_auto_halted',",
        "-- Rollback notes",
    ):
        assert fragment in text
    from app.export_auto import RUN_STATUSES

    assert all(f"'{status}'" in text for status in RUN_STATUSES)
