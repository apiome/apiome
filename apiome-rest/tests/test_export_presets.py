"""Export presets: the rules, the routes and applying one to a job — MFX-39.3 (#4335).

The pure half (:mod:`app.export_presets`): names, 1–16 targets each validated against its emitter's
options schema (MFX-1.4), no two targets of one format, the delivery profile kept / replaced / cleared on
an update, and :func:`apply_preset` turning a job request naming a preset into the request it stands
for. Then the routes (:mod:`app.export_preset_routes`): tenant-scoped CRUD with 400 / 404 / 409 refusals
and audits, and the job submit expanding ``preset`` before it schedules. Last, the database's
by-id-or-name lookup and the V358 migration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from psycopg2 import errors as pg_errors
from pydantic import ValidationError

from app.auth import validate_authentication
from app.database import Database
from app.export_job_engine import ExportJobStartRequest
from app.export_presets import (
    ExportPresetCreate,
    ExportPresetRequestError,
    ExportPresetUpdate,
    apply_preset,
    normalize_create,
    normalize_update,
    validate_targets,
)
from app.main import app
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PRESET = "77777777-7777-4777-8777-777777777777"
_PROFILE = "55555555-5555-4555-8555-555555555555"
_AUTH = {"tenant_id": _TENANT, "user_id": "u1", "auth_method": "jwt"}
_PRESETS = "/v1/export/acme/presets"
_ROUTES = "app.export_preset_routes"


def _row(**fields: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = dict(
        id=_PRESET, tenant_id=_TENANT, name="nightly-sync", description="Nightly",
        targets=[{"target": "openapi", "options": {"openapi_version": "3.0"}}, {"target": "protobuf", "options": {}}],
        delivery_profile_id=_PROFILE, delivery_profile_name="lake",
    )
    values.update(fields)
    return values


# ===========================================================================
# The rules
# ===========================================================================


def test_a_preset_keeps_its_targets_and_options_in_order() -> None:
    preset = normalize_create(ExportPresetCreate.model_validate({
        "name": " nightly-sync ", "targets": [{"target": "openapi", "options": {"openapi_version": "3.0"}},
                                              {"target": " protobuf "}],
        "deliveryProfileId": _PROFILE,
    }))
    assert preset.name == "nightly-sync"
    assert preset.targets == [{"target": "openapi", "options": {"openapi_version": "3.0"}},
                              {"target": "protobuf", "options": {}}]
    assert preset.delivery_profile_id == _PROFILE


def test_every_target_is_checked_against_its_emitter_schema() -> None:
    problems = validate_targets([
        {"target": "openapi", "options": {"bogus": 1}},
        {"target": "nope"},
        {"target": ""},
        {"target": "graphql"},
    ])
    assert len(problems) == 3
    assert problems[0].startswith("targets[0] (openapi): ") and "bogus" in problems[0]
    assert problems[1].startswith("targets[1] (nope): Unsupported export target")
    assert problems[2] == "targets[2]: target is required"


def test_two_targets_of_one_format_are_refused() -> None:
    problems = validate_targets([{"target": "openapi"}, {"target": "openapi-3.1"}])
    assert len(problems) == 1
    assert problems[0].startswith("targets[1] (openapi-3.1): resolves to the same format as 'openapi'")
    valid = [{"target": "openapi", "options": {"openapi_version": "3.0"}}, {"target": "protobuf"}]
    assert validate_targets(valid) == []


def test_a_bad_preset_names_every_problem() -> None:
    with pytest.raises(ExportPresetRequestError) as caught:
        normalize_create(ExportPresetCreate.model_validate({"name": "", "targets": [{"target": "nope"}]}))
    assert caught.value.errors[0] == "name is required"
    assert caught.value.errors[1].startswith("targets[0] (nope)")
    with pytest.raises(ValidationError):
        ExportPresetCreate.model_validate({"name": "x", "targets": []})
    with pytest.raises(ValidationError):
        ExportPresetCreate.model_validate({"name": "x", "targets": [{"target": "a", "secret": "s"}]})


def test_an_update_keeps_replaces_or_clears_the_delivery_profile() -> None:
    kept = normalize_update(ExportPresetUpdate(name="renamed"), _row())
    assert (kept.name, kept.delivery_profile_id, kept.targets) == ("renamed", _PROFILE, _row()["targets"])
    cleared = normalize_update(ExportPresetUpdate.model_validate({"deliveryProfileId": None}), _row())
    assert cleared.delivery_profile_id is None
    replaced = normalize_update(ExportPresetUpdate.model_validate({"targets": [{"target": "graphql"}]}), _row())
    assert replaced.targets == [{"target": "graphql", "options": {}}]
    with pytest.raises(ExportPresetRequestError):
        normalize_update(ExportPresetUpdate.model_validate({"targets": [{"target": "nope"}]}), _row())


def test_applying_a_multi_target_preset_fills_targets_and_delivery() -> None:
    request = ExportJobStartRequest(artifact="a1", version="1.0.0", preset="nightly-sync", confirm=True)
    expanded = apply_preset(request, _row())
    assert expanded.preset is None
    assert expanded.target is None
    assert [(t.target, t.options) for t in expanded.targets] == [
        ("openapi", {"openapi_version": "3.0"}), ("protobuf", None)]
    assert (expanded.artifact, expanded.version, expanded.confirm) == ("a1", "1.0.0", True)
    assert expanded.delivery_profiles == [_PROFILE]


def test_applying_a_single_target_preset_and_merging_delivery_profiles() -> None:
    other = "66666666-6666-4666-8666-666666666666"
    request = ExportJobStartRequest(artifact="a1", preset="p", delivery_profiles=[other, _PROFILE])
    expanded = apply_preset(request, _row(targets=[{"target": "openapi", "options": {"openapi_version": "3.0"}}]))
    assert (expanded.target, expanded.options, expanded.targets) == ("openapi", {"openapi_version": "3.0"}, None)
    assert expanded.delivery_profiles == [_PROFILE, other]


def test_a_dry_run_with_a_preset_drops_its_delivery() -> None:
    expanded = apply_preset(ExportJobStartRequest(artifact="a1", preset="p", dry_run=True), _row())
    assert expanded.dry_run is True and expanded.delivery_profiles is None


def test_a_stale_preset_is_refused_when_applied() -> None:
    with pytest.raises(ExportPresetRequestError) as caught:
        apply_preset(ExportJobStartRequest(artifact="a1", preset="p"),
                     _row(targets=[{"target": "openapi", "options": {"removed_option": True}}]))
    assert caught.value.errors[0].startswith("preset 'nightly-sync': targets[0] (openapi)")


def test_a_job_naming_a_preset_cannot_also_name_targets() -> None:
    for extra in ({"target": "openapi"}, {"targets": [{"target": "openapi"}]}, {"options": {}}):
        with pytest.raises(ValidationError) as caught:
            ExportJobStartRequest(artifact="a1", preset="p", **extra)
        assert "names its own targets" in str(caught.value)
    with pytest.raises(ValidationError):
        ExportJobStartRequest(artifact="a1", preset="  ")
    with pytest.raises(ValidationError) as caught:
        ExportJobStartRequest(artifact="a1")
    assert "or a 'preset'" in str(caught.value)


# ===========================================================================
# The routes
# ===========================================================================


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


def _tenant(tenant_id: str = _TENANT):
    return patch("app.export_git_delivery_routes.db.get_tenant_row_by_slug", return_value={"id": tenant_id})


def test_creating_a_preset_validates_audits_and_answers_201() -> None:
    body = {"name": "nightly-sync", "targets": [{"target": "openapi", "options": {"openapi_version": "3.0"}}],
            "deliveryProfileId": _PROFILE}
    with patch(f"{_ROUTES}.enforce_permission") as guard, _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value={"id": _PROFILE}), \
            patch(f"{_ROUTES}.db.insert_export_preset", return_value=_row(targets=body["targets"])) as insert, \
            patch(f"{_ROUTES}.write_audit") as audit:
        response = client.post(_PRESETS, json=body)
    assert response.status_code == 201, response.text
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.EDIT)]
    kwargs = insert.call_args.kwargs
    assert kwargs["targets"] == body["targets"] and kwargs["delivery_profile_id"] == _PROFILE
    assert kwargs["actor_id"] == "u1"
    assert response.json()["deliveryProfileName"] == "lake"
    assert audit.call_args.kwargs["action"] == "export.preset.created"
    assert audit.call_args.kwargs["detail"]["targets"] == ["openapi"]


def test_create_refusals() -> None:
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), patch(f"{_ROUTES}.db.insert_export_preset") as insert:
        bad = {"name": "x", "targets": [{"target": "openapi", "options": {"bogus": 1}}]}
        response = client.post(_PRESETS, json=bad)
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "export-preset-invalid"
    insert.assert_not_called()
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value=None):
        response = client.post(_PRESETS, json={"name": "x", "targets": [{"target": "openapi"}],
                                               "deliveryProfileId": _PROFILE})
    assert response.status_code == 400
    assert response.json()["detail"]["errors"][0].startswith("deliveryProfileId")
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.insert_export_preset", side_effect=pg_errors.UniqueViolation()):
        response = client.post(_PRESETS, json={"name": "x", "targets": [{"target": "openapi"}]})
    assert response.status_code == 409
    with patch(f"{_ROUTES}.enforce_permission"), _tenant("someone-else"):
        assert client.get(_PRESETS).status_code == 404


def test_listing_and_reading_by_name() -> None:
    with patch(f"{_ROUTES}.enforce_permission") as guard, _tenant(), \
            patch(f"{_ROUTES}.db.list_export_presets", return_value=[_row()]):
        response = client.get(_PRESETS)
    assert response.status_code == 200
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.VIEW)]
    assert response.json()["presets"][0]["targets"][0] == {"target": "openapi", "options": {"openapi_version": "3.0"}}
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_preset", return_value=_row()) as lookup:
        assert client.get(f"{_PRESETS}/nightly-sync").json()["id"] == _PRESET
    lookup.assert_called_once_with(_TENANT, "nightly-sync")
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), patch(f"{_ROUTES}.db.get_export_preset", return_value=None):
        assert client.get(f"{_PRESETS}/nope").status_code == 404


def test_patching_and_deleting() -> None:
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_preset", return_value=_row()), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile") as profile_lookup, \
            patch(f"{_ROUTES}.db.update_export_preset", return_value=_row(delivery_profile_id=None)) as update, \
            patch(f"{_ROUTES}.write_audit") as audit:
        response = client.patch(f"{_PRESETS}/nightly-sync", json={"deliveryProfileId": None})
    assert response.status_code == 200, response.text
    assert update.call_args.args[:2] == (_TENANT, _PRESET)
    assert update.call_args.kwargs["delivery_profile_id"] is None
    profile_lookup.assert_not_called()
    assert audit.call_args.kwargs["action"] == "export.preset.updated"
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_preset", return_value=_row()), \
            patch(f"{_ROUTES}.db.delete_export_preset", return_value=True) as delete, \
            patch(f"{_ROUTES}.write_audit") as audit:
        assert client.delete(f"{_PRESETS}/nightly-sync").status_code == 204
    delete.assert_called_once_with(_TENANT, _PRESET)
    assert audit.call_args.kwargs["action"] == "export.preset.deleted"
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), patch(f"{_ROUTES}.db.get_export_preset", return_value=None):
        assert client.delete(f"{_PRESETS}/nope").status_code == 404


def test_the_job_submit_expands_a_preset_before_scheduling() -> None:
    schedule = AsyncMock(return_value={"job_id": "j", "status_path": "/p"})
    with patch(f"{_ROUTES}.db.get_export_preset", return_value=_row(delivery_profile_id=None)) as lookup, \
            patch("app.export_job_routes.schedule_export_job", new=schedule):
        response = client.post("/v1/export/acme/jobs", json={"artifact": "a1", "preset": "nightly-sync"})
    assert response.status_code == 202, response.text
    lookup.assert_called_once_with(_TENANT, "nightly-sync")
    scheduled = schedule.call_args.args[2]
    assert scheduled.preset is None and [t.target for t in scheduled.targets] == ["openapi", "protobuf"]


def test_the_job_submit_checks_the_preset_s_delivery_profile_too() -> None:
    with patch(f"{_ROUTES}.db.get_export_preset", return_value=_row()), \
            patch("app.export_job_routes.enforce_permission") as guard, \
            patch("app.export_job_routes.db.get_export_delivery_profile", return_value=None), \
            patch("app.export_job_routes.schedule_export_job") as schedule:
        response = client.post("/v1/export/acme/jobs", json={"artifact": "a1", "preset": "nightly-sync"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "export-delivery-profile-unknown"
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.VERSIONS, Action.PUBLISH)]
    schedule.assert_not_called()


def test_the_job_submit_refuses_an_unknown_or_unusable_preset() -> None:
    with patch(f"{_ROUTES}.db.get_export_preset", return_value=None):
        response = client.post("/v1/export/acme/jobs", json={"artifact": "a1", "preset": "nope"})
    assert response.status_code == 400 and response.json()["detail"]["code"] == "export-preset-unknown"
    with patch(f"{_ROUTES}.db.get_export_preset", return_value=_row(delivery_profile_id=None)):
        response = client.post("/v1/export/acme/jobs", json={"artifact": "a1", "preset": "nightly-sync",
                                                              "acknowledged_snapshot": "abc"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "export-preset-request-invalid"
    with patch(f"{_ROUTES}.db.get_export_preset",
               return_value=_row(targets=[{"target": "openapi", "options": {"gone": 1}}], delivery_profile_id=None)):
        response = client.post("/v1/export/acme/jobs", json={"artifact": "a1", "preset": "nightly-sync"})
    assert response.status_code == 400 and response.json()["detail"]["code"] == "export-preset-invalid"


async def test_the_engine_refuses_an_unexpanded_preset() -> None:
    from app.export_job_engine import schedule_export_job
    from app.export_service import ExportError

    with pytest.raises(ExportError) as caught:
        await schedule_export_job("acme", _TENANT, ExportJobStartRequest(artifact="a1", preset="p"))
    assert caught.value.status_code == 400


# ===========================================================================
# The database
# ===========================================================================


def test_a_preset_is_found_by_id_then_by_name() -> None:
    database = Database.__new__(Database)
    database.execute_query = MagicMock(side_effect=[[], [_row()]])
    assert database.get_export_preset(_TENANT, _PRESET)["name"] == "nightly-sync"
    by_id, by_name = database.execute_query.call_args_list
    assert by_id.args[1] == (_TENANT, _PRESET) and by_name.args[1] == (_TENANT, _PRESET)
    database.execute_query = MagicMock(return_value=[_row()])
    database.get_export_preset(_TENANT, "nightly-sync")
    assert database.execute_query.call_count == 1
    assert "x.name = %s" in database.execute_query.call_args.args[0]
    assert database.get_export_preset("acme", "x") is None
    assert database.get_export_preset(_TENANT, " ") is None
    assert database.delete_export_preset(_TENANT, "nope") is False


def test_the_migration_carries_every_structural_promise() -> None:
    text = (Path(__file__).resolve().parents[2] / "apiome-db/scripts/V358__export_presets_4335.sql").read_text()
    for fragment in (
        "CREATE TABLE IF NOT EXISTS export_presets (",
        "tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE",
        "CONSTRAINT export_presets_name_unique UNIQUE (tenant_id, name)",
        "jsonb_array_length(targets) BETWEEN 1 AND 16",
        "delivery_profile_id UUID REFERENCES export_delivery_profiles(id) ON DELETE SET NULL",
        "-- Rollback notes",
    ):
        assert fragment in text
