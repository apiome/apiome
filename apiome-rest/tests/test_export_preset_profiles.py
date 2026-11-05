"""Export presets deliver with several profiles — MFX-46.4 (#4382).

A preset holds up to five delivery profiles, in order (``deliveryProfileIds``); ``deliveryProfileId``
stays the first, for older clients. Covered here: the request rules (precedence, de-duplication, the
limit, keep / replace / clear on an update), :func:`preset_profile_ids` on old and new rows,
:func:`apply_preset` delivering with every profile, the routes checking each profile and reporting the
list, the database writing the join rows in the preset's transaction, the auto-export worker releasing
to every profile, and the V361 migration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth import validate_authentication
from app.database import Database, _preset_profile_ids
from app.export_job_engine import MAX_EXPORT_DELIVERY_PROFILES, ExportJobStartRequest
from app.export_presets import (
    ExportPresetCreate,
    ExportPresetRequestError,
    ExportPresetUpdate,
    apply_preset,
    normalize_create,
    normalize_update,
    preset_profile_ids,
)
from app.main import app

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_PRESET = "77777777-7777-4777-8777-777777777777"
_A = "55555555-5555-4555-8555-555555555555"
_B = "66666666-6666-4666-8666-666666666666"
_C = "88888888-8888-4888-8888-888888888888"
_AUTH = {"tenant_id": _TENANT, "user_id": "u1", "auth_method": "jwt"}
_PRESETS = "/v1/export/acme/presets"
_ROUTES = "app.export_preset_routes"
_TARGETS = [{"target": "openapi", "options": {"openapi_version": "3.0"}}]


def _row(**fields: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = dict(
        id=_PRESET, tenant_id=_TENANT, name="nightly-sync", description=None, targets=_TARGETS,
        delivery_profile_id=_A, delivery_profile_name="lake",
        delivery_profile_ids=[_A, _B], delivery_profile_names=["lake", "bucket"],
    )
    values.update(fields)
    return values


# ===========================================================================
# The rules
# ===========================================================================


def test_a_new_preset_takes_an_ordered_list_ahead_of_the_single_profile() -> None:
    listed = normalize_create(ExportPresetCreate.model_validate(
        {"name": "x", "targets": _TARGETS, "deliveryProfileIds": [_B, " ", _A, _B], "deliveryProfileId": _C}))
    assert listed.delivery_profile_ids == [_B, _A]
    assert listed.delivery_profile_id == _B
    single = normalize_create(ExportPresetCreate.model_validate(
        {"name": "x", "targets": _TARGETS, "deliveryProfileId": f" {_C} "}))
    assert single.delivery_profile_ids == [_C]
    none = normalize_create(ExportPresetCreate.model_validate({"name": "x", "targets": _TARGETS}))
    assert none.delivery_profile_ids == [] and none.delivery_profile_id is None


def test_a_preset_names_at_most_five_profiles() -> None:
    six = [f"{index}5555555-5555-4555-8555-555555555555" for index in range(MAX_EXPORT_DELIVERY_PROFILES + 1)]
    with pytest.raises(ValidationError):
        ExportPresetCreate.model_validate({"name": "x", "targets": _TARGETS, "deliveryProfileIds": six})
    with pytest.raises(ValidationError):
        ExportPresetUpdate.model_validate({"deliveryProfileIds": six})


def test_an_update_keeps_replaces_or_clears_the_profile_list() -> None:
    kept = normalize_update(ExportPresetUpdate(name="renamed"), _row())
    assert kept.delivery_profile_ids == [_A, _B]
    replaced = normalize_update(ExportPresetUpdate.model_validate({"deliveryProfileIds": [_C, _A]}), _row())
    assert replaced.delivery_profile_ids == [_C, _A]
    cleared = normalize_update(ExportPresetUpdate.model_validate({"deliveryProfileIds": []}), _row())
    assert cleared.delivery_profile_ids == []
    single = normalize_update(ExportPresetUpdate.model_validate({"deliveryProfileId": _C}), _row())
    assert single.delivery_profile_ids == [_C]
    nulled = normalize_update(ExportPresetUpdate.model_validate({"deliveryProfileId": None}), _row())
    assert nulled.delivery_profile_ids == []
    both = normalize_update(ExportPresetUpdate.model_validate(
        {"deliveryProfileIds": [_B], "deliveryProfileId": _C}), _row())
    assert both.delivery_profile_ids == [_B]


def test_a_row_s_profiles_fall_back_to_the_single_column() -> None:
    assert preset_profile_ids(_row()) == [_A, _B]
    assert preset_profile_ids(_row(delivery_profile_ids=[])) == [_A]
    assert preset_profile_ids({"delivery_profile_id": _C}) == [_C]
    assert preset_profile_ids(_row(delivery_profile_ids=None, delivery_profile_id=None)) == []
    assert preset_profile_ids({}) == []


def test_applying_a_preset_delivers_with_every_profile_in_order() -> None:
    request = ExportJobStartRequest(artifact="a1", preset="p", delivery_profiles=[_C, _A])
    assert apply_preset(request, _row()).delivery_profiles == [_A, _B, _C]
    assert apply_preset(ExportJobStartRequest(artifact="a1", preset="p"), _row()).delivery_profiles == [_A, _B]
    dry = apply_preset(ExportJobStartRequest(artifact="a1", preset="p", dry_run=True), _row())
    assert dry.delivery_profiles is None


def test_the_preset_and_the_request_together_stay_within_the_limit() -> None:
    four = [f"{index}5555555-5555-4555-8555-555555555555" for index in range(4)]
    request = ExportJobStartRequest(artifact="a1", preset="p", delivery_profiles=[_B, _C])
    with pytest.raises(ExportPresetRequestError) as caught:
        apply_preset(request, _row(delivery_profile_ids=four, delivery_profile_id=four[0]))
    assert "delivery profiles" in caught.value.errors[0]


# ===========================================================================
# The routes
# ===========================================================================


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


def _tenant():
    return patch("app.export_git_delivery_routes.db.get_tenant_row_by_slug", return_value={"id": _TENANT})


def test_creating_a_preset_stores_and_reports_every_profile() -> None:
    body = {"name": "nightly-sync", "targets": _TARGETS, "deliveryProfileIds": [_A, _B]}
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value={"id": "p"}) as lookup, \
            patch(f"{_ROUTES}.db.insert_export_preset", return_value=_row()) as insert, \
            patch(f"{_ROUTES}.write_audit") as audit:
        response = client.post(_PRESETS, json=body)
    assert response.status_code == 201, response.text
    assert [call.args[1] for call in lookup.call_args_list] == [_A, _B]
    kwargs = insert.call_args.kwargs
    assert kwargs["delivery_profile_ids"] == [_A, _B] and kwargs["delivery_profile_id"] == _A
    payload = response.json()
    assert payload["deliveryProfileIds"] == [_A, _B]
    assert payload["deliveryProfileNames"] == ["lake", "bucket"]
    assert payload["deliveryProfileId"] == _A
    assert audit.call_args.kwargs["detail"]["deliveryProfileIds"] == [_A, _B]


def test_every_unknown_profile_is_named() -> None:
    known = {_A: {"id": _A}}
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", side_effect=lambda _t, pid: known.get(pid)), \
            patch(f"{_ROUTES}.db.insert_export_preset") as insert:
        response = client.post(_PRESETS, json={"name": "x", "targets": _TARGETS,
                                               "deliveryProfileIds": [_B, _A, _C]})
    assert response.status_code == 400
    errors = response.json()["detail"]["errors"]
    assert [error.split(":")[0] for error in errors] == ["deliveryProfileIds[0]", "deliveryProfileIds[2]"]
    insert.assert_not_called()


def test_patching_checks_profiles_only_when_the_list_changes() -> None:
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_preset", return_value=_row()), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile") as lookup, \
            patch(f"{_ROUTES}.db.update_export_preset", return_value=_row()) as update, \
            patch(f"{_ROUTES}.write_audit"):
        assert client.patch(f"{_PRESETS}/nightly-sync", json={"name": "renamed"}).status_code == 200
    lookup.assert_not_called()
    assert update.call_args.kwargs["delivery_profile_ids"] == [_A, _B]
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_preset", return_value=_row()), \
            patch(f"{_ROUTES}.db.get_export_delivery_profile", return_value={"id": "p"}) as lookup, \
            patch(f"{_ROUTES}.db.update_export_preset", return_value=_row(delivery_profile_ids=[_C, _A])) as update, \
            patch(f"{_ROUTES}.write_audit"):
        response = client.patch(f"{_PRESETS}/nightly-sync", json={"deliveryProfileIds": [_C, _A]})
    assert response.status_code == 200, response.text
    assert [call.args[1] for call in lookup.call_args_list] == [_C, _A]
    assert update.call_args.kwargs["delivery_profile_ids"] == [_C, _A]
    assert update.call_args.kwargs["delivery_profile_id"] == _C


def test_a_row_stored_before_the_list_still_reports_its_profile() -> None:
    old = _row(delivery_profile_ids=None, delivery_profile_names=None)
    with patch(f"{_ROUTES}.enforce_permission"), _tenant(), \
            patch(f"{_ROUTES}.db.get_export_preset", return_value=old):
        payload = client.get(f"{_PRESETS}/nightly-sync").json()
    assert payload["deliveryProfileIds"] == [_A] and payload["deliveryProfileNames"] == []


# ===========================================================================
# The database
# ===========================================================================


def _insert(database: Database, **fields: Any) -> Any:
    return database.insert_export_preset(tenant_id=_TENANT, name="x", description=None, targets=_TARGETS, **fields)


def _database(returning: Dict[str, Any] | None) -> tuple[Database, MagicMock, MagicMock]:
    database = Database.__new__(Database)
    cursor = MagicMock()
    cursor.fetchone.return_value = returning
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    database.connect = MagicMock(return_value=conn)
    database._export_preset_by_id = MagicMock(return_value=_row())
    return database, conn, cursor


def _statements(cursor: MagicMock) -> List[tuple[str, tuple]]:
    return [(" ".join(call.args[0].split()), call.args[1]) for call in cursor.execute.call_args_list]


def test_inserting_writes_the_join_rows_in_the_same_transaction() -> None:
    database, conn, cursor = _database({"id": _PRESET})
    assert _insert(database, delivery_profile_ids=[_B, _A, _B, "nope"])
    insert, delete, first, second = _statements(cursor)
    assert insert[0].startswith("INSERT INTO apiome.export_presets") and insert[1][4] == _B
    assert delete[0].startswith("DELETE FROM apiome.export_preset_delivery_profiles") and delete[1] == (_PRESET,)
    assert first[1] == (_PRESET, _B, 0) and second[1] == (_PRESET, _A, 1)
    conn.commit.assert_called_once()


def test_inserting_with_the_single_profile_still_writes_one_row() -> None:
    database, _conn, cursor = _database({"id": _PRESET})
    _insert(database, delivery_profile_id=_C)
    statements = _statements(cursor)
    assert statements[0][1][4] == _C
    assert statements[-1][1] == (_PRESET, _C, 0)


def test_updating_replaces_the_join_rows_or_clears_them() -> None:
    database, conn, cursor = _database({"id": _PRESET})
    database.update_export_preset(_TENANT, _PRESET, name="x", description=None, targets=_TARGETS,
                                  delivery_profile_id=None, delivery_profile_ids=[])
    update, delete = _statements(cursor)
    assert update[0].startswith("UPDATE apiome.export_presets SET") and update[1][3] is None
    assert delete[1] == (_PRESET,)
    conn.commit.assert_called_once()
    database, _conn, cursor = _database(None)
    assert database.update_export_preset(_TENANT, _PRESET, name="x", description=None, targets=_TARGETS,
                                         delivery_profile_id=None, delivery_profile_ids=[_A]) is None
    assert len(cursor.execute.call_args_list) == 1


def test_a_failed_join_write_rolls_the_preset_back() -> None:
    database, conn, cursor = _database({"id": _PRESET})
    cursor.execute.side_effect = [None, None, RuntimeError("fk")]
    with pytest.raises(RuntimeError):
        _insert(database, delivery_profile_ids=[_A])
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_the_profile_list_helper_keeps_uuids_once_and_at_most_five() -> None:
    many = [f"{index}5555555-5555-4555-8555-555555555555" for index in range(7)]
    assert _preset_profile_ids(many, None) == many[:5]
    assert _preset_profile_ids(None, _A) == [_A]
    assert _preset_profile_ids([], _A) == []
    assert _preset_profile_ids(None, "not-a-uuid") == []


def test_every_preset_read_and_the_auto_run_claim_aggregate_the_list() -> None:
    source = (Path(__file__).resolve().parents[1] / "src/app/database.py").read_text()
    assert source.count("FROM apiome.export_preset_delivery_profiles pd WHERE pd.preset_id = x.id") >= 2
    assert "AS delivery_profile_names" in source and "AS preset_delivery_profile_ids" in source


# ===========================================================================
# The auto-export worker
# ===========================================================================


async def test_releasing_a_halted_run_delivers_to_every_profile() -> None:
    from app import export_auto_worker

    run = {"id": "r1", "status": "halted", "job_id": "j1", "preset_id": _PRESET, "tenant_id": _TENANT,
           "tenant_slug": "acme", "project_id": "p1", "preset_name": "nightly-sync"}
    deliver = MagicMock()

    async def fake_deliver(_run, _slug, _job, profiles, _auth):
        deliver(profiles)
        return [{"profileId": p, "status": "delivered"} for p in profiles]

    database = MagicMock()
    database.get_export_preset.return_value = _row()
    database.finish_export_auto_run.return_value = {"id": "r1"}
    with patch.object(export_auto_worker, "_deliver", new=fake_deliver), \
            patch.object(export_auto_worker, "write_audit"):
        await export_auto_worker.release_halted_run(database, run, _AUTH)
    deliver.assert_called_once_with([_A, _B])
    database.get_export_preset.return_value = _row(delivery_profile_ids=[], delivery_profile_id=None)
    with pytest.raises(Exception) as caught:
        await export_auto_worker.release_halted_run(database, run, _AUTH)
    assert getattr(caught.value, "status_code", None) == 409


# ===========================================================================
# The migration
# ===========================================================================


def test_the_migration_carries_every_structural_promise() -> None:
    root = Path(__file__).resolve().parents[2] / "apiome-db/scripts"
    text = (root / "V361__export_preset_delivery_profiles_4382.sql").read_text()
    for fragment in (
        "CREATE TABLE IF NOT EXISTS export_preset_delivery_profiles (",
        "preset_id UUID NOT NULL REFERENCES export_presets(id) ON DELETE CASCADE",
        "delivery_profile_id UUID NOT NULL REFERENCES export_delivery_profiles(id) ON DELETE CASCADE",
        "CHECK (position BETWEEN 0 AND 4)",
        "PRIMARY KEY (preset_id, delivery_profile_id)",
        "UNIQUE (preset_id, position)",
        "SELECT id, delivery_profile_id, 0",
        "-- Rollback notes",
    ):
        assert fragment in text
