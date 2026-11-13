"""API tests for deprecating and restoring a type (#3482, 7.5).

``POST`` / ``DELETE /v1/primitives/{tenant_slug}/{primitive_id}/deprecate`` with the DB mocked:
the happy paths, changing a deprecated type's details, the refusals (system type, unknown type,
past sunset date, bad replacement), the audit rows, and the deprecation record on the
single-primitive GET.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.registry_audit import ACTION_DEPRECATE, ACTION_RESTORE, REGISTRY_AUDIT_ACTIONS

client = TestClient(app)

_JWT = {"tenant_id": "t1", "user_id": "u1", "auth_method": "jwt"}
_NOW = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
_FUTURE = (datetime.now(timezone.utc).date() + timedelta(days=90))
_PAST = (datetime.now(timezone.utc).date() - timedelta(days=1))
_URL = "/v1/primitives/acme/p1/deprecate"


def _row(**overrides):
    """A representative apiome.primitives row as returned by the DB layer."""
    row = {
        "id": "p1",
        "tenant_id": "t1",
        "name": "money",
        "description": None,
        "category": "object",
        "schema": {"type": "object"},
        "tags": [],
        "created_by": "u1",
        "is_system": False,
        "is_public": False,
        "usage_count": 0,
        "source": "human",
        "schema_id": "https://api.apiome.dev/types/tenant/acme/v1/types/money",
        "draft": "2020-12",
        "namespace": "tenant/acme/v1/types",
        "base_uri": "https://api.apiome.dev/types/tenant/acme/v1/types/",
        "refs": [],
        "deprecated_at": None,
        "sunset_date": None,
        "deprecation_message": None,
        "replacement_id": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    row.update(overrides)
    return row


_REPLACEMENT = _row(
    id="p2",
    name="money-v2",
    schema_id="https://api.apiome.dev/types/tenant/acme/v2/types/money-v2",
)


def _by_id(*rows):
    """A ``get_primitive_by_id`` stand-in over the given rows."""
    index = {r["id"]: r for r in rows}
    return lambda primitive_id, tenant_id: index.get(primitive_id)


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@pytest.fixture
def mdb():
    """Patch the lifecycle routes' db and let permission checks pass."""
    with patch("app.primitives_lifecycle_routes.db") as mock_db, patch(
        "app.primitives_lifecycle_routes.enforce_permission"
    ):
        yield mock_db


# ===========================================================================
# DEPRECATE
# ===========================================================================


def test_deprecate_with_sunset_date_message_and_replacement(mdb):
    mdb.get_primitive_by_id.side_effect = _by_id(_row(), _REPLACEMENT)
    mdb.deprecate_primitive.return_value = _row(
        deprecated_at=_NOW,
        sunset_date=_FUTURE,
        deprecation_message="Use money-v2.",
        replacement_id="p2",
    )

    r = client.post(
        _URL,
        json={
            "sunset_date": _FUTURE.isoformat(),
            "message": "  Use money-v2.  ",
            "replacement_id": "p2",
        },
    )

    assert r.status_code == 200
    body = r.json()
    assert body["deprecated"] is True
    assert body["sunset_date"] == _FUTURE.isoformat()
    assert body["deprecation_message"] == "Use money-v2."
    assert body["replacement_id"] == "p2"
    assert body["replacement"] == {
        "id": "p2",
        "name": "money-v2",
        "schema_id": "https://api.apiome.dev/types/tenant/acme/v2/types/money-v2",
    }
    # The write is tenant-scoped and the message is trimmed before it is stored.
    args, kwargs = mdb.deprecate_primitive.call_args
    assert args == ("p1", "t1")
    assert kwargs == {
        "sunset_date": _FUTURE,
        "message": "Use money-v2.",
        "replacement_id": "p2",
    }


def test_deprecate_needs_no_details(mdb):
    """A type can be deprecated before its retirement date is decided."""
    mdb.get_primitive_by_id.side_effect = _by_id(_row())
    mdb.deprecate_primitive.return_value = _row(deprecated_at=_NOW)

    r = client.post(_URL, json={})

    assert r.status_code == 200
    body = r.json()
    assert body["deprecated"] is True
    assert body["sunset_date"] is None
    assert body["replacement"] is None
    assert mdb.deprecate_primitive.call_args.kwargs == {
        "sunset_date": None,
        "message": None,
        "replacement_id": None,
    }


def test_deprecate_today_is_allowed(mdb):
    today = datetime.now(timezone.utc).date()
    mdb.get_primitive_by_id.side_effect = _by_id(_row())
    mdb.deprecate_primitive.return_value = _row(deprecated_at=_NOW, sunset_date=today)

    r = client.post(_URL, json={"sunset_date": today.isoformat()})

    assert r.status_code == 200


def test_deprecate_writes_an_audit_row(mdb):
    mdb.get_primitive_by_id.side_effect = _by_id(_row())
    mdb.deprecate_primitive.return_value = _row(deprecated_at=_NOW, sunset_date=_FUTURE)

    client.post(_URL, json={"sunset_date": _FUTURE.isoformat()})

    args, kwargs = mdb.insert_registry_audit.call_args
    assert args[:3] == ("t1", ACTION_DEPRECATE, "success")
    assert kwargs["primitive_id"] == "p1"
    assert kwargs["namespace"] == "tenant/acme/v1/types"
    assert kwargs["actor_id"] == "u1"
    assert kwargs["detail"]["sunset_date"] == _FUTURE.isoformat()
    assert kwargs["detail"]["updated_existing"] is False


def test_deprecate_again_changes_the_details_and_says_so_in_the_audit(mdb):
    already = _row(deprecated_at=_NOW, sunset_date=_FUTURE)
    later = _FUTURE + timedelta(days=30)
    mdb.get_primitive_by_id.side_effect = _by_id(already)
    mdb.deprecate_primitive.return_value = _row(deprecated_at=_NOW, sunset_date=later)

    r = client.post(_URL, json={"sunset_date": later.isoformat()})

    assert r.status_code == 200
    assert r.json()["sunset_date"] == later.isoformat()
    assert mdb.insert_registry_audit.call_args.kwargs["detail"]["updated_existing"] is True


def test_deprecate_survives_a_failed_audit_write(mdb):
    mdb.get_primitive_by_id.side_effect = _by_id(_row())
    mdb.deprecate_primitive.return_value = _row(deprecated_at=_NOW)
    mdb.insert_registry_audit.side_effect = RuntimeError("audit down")

    r = client.post(_URL, json={})

    assert r.status_code == 200


def test_deprecate_unknown_type_is_404(mdb):
    mdb.get_primitive_by_id.side_effect = _by_id()

    r = client.post(_URL, json={})

    assert r.status_code == 404
    mdb.deprecate_primitive.assert_not_called()


def test_deprecate_system_type_is_403(mdb):
    mdb.get_primitive_by_id.side_effect = _by_id(_row(is_system=True))

    r = client.post(_URL, json={})

    assert r.status_code == 403
    assert r.json()["detail"] == "Cannot deprecate system primitives"
    mdb.deprecate_primitive.assert_not_called()


def test_deprecate_with_a_past_sunset_date_is_422(mdb):
    mdb.get_primitive_by_id.side_effect = _by_id(_row())

    r = client.post(_URL, json={"sunset_date": _PAST.isoformat()})

    assert r.status_code == 422
    assert "in the past" in r.json()["detail"]
    mdb.deprecate_primitive.assert_not_called()
    mdb.insert_registry_audit.assert_not_called()


def test_deprecate_with_a_malformed_sunset_date_is_422(mdb):
    r = client.post(_URL, json={"sunset_date": "next spring"})

    assert r.status_code == 422
    mdb.deprecate_primitive.assert_not_called()


def test_deprecate_with_an_overlong_message_is_422(mdb):
    r = client.post(_URL, json={"message": "x" * 501})

    assert r.status_code == 422
    mdb.deprecate_primitive.assert_not_called()


@pytest.mark.parametrize(
    "replacement_id, rows, fragment",
    [
        ("p1", [], "its own replacement"),
        ("p9", [], "Replacement type not found: p9"),
        ("p2", [_row(id="p2", name="old-money", deprecated_at=_NOW)], "itself deprecated"),
    ],
)
def test_deprecate_with_a_bad_replacement_is_422(mdb, replacement_id, rows, fragment):
    mdb.get_primitive_by_id.side_effect = _by_id(_row(), *rows)

    r = client.post(_URL, json={"replacement_id": replacement_id})

    assert r.status_code == 422
    assert fragment in r.json()["detail"]
    mdb.deprecate_primitive.assert_not_called()


def test_deprecate_reports_every_problem_at_once(mdb):
    mdb.get_primitive_by_id.side_effect = _by_id(_row())

    r = client.post(_URL, json={"sunset_date": _PAST.isoformat(), "replacement_id": "p9"})

    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "in the past" in detail and "Replacement type not found" in detail


def test_deprecate_type_deleted_between_read_and_write_is_404(mdb):
    mdb.get_primitive_by_id.side_effect = _by_id(_row())
    mdb.deprecate_primitive.return_value = None

    r = client.post(_URL, json={})

    assert r.status_code == 404
    mdb.insert_registry_audit.assert_not_called()


def test_deprecate_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)

    r = client.post(_URL, json={})

    assert r.status_code == 401


def test_deprecate_requires_the_edit_permission():
    """Without the types:edit permission the request stops before any read or write."""
    from fastapi import HTTPException

    with patch("app.primitives_lifecycle_routes.db") as mock_db, patch(
        "app.primitives_lifecycle_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="Permission denied"),
    ):
        r = client.post(_URL, json={})

    assert r.status_code == 403
    mock_db.get_primitive_by_id.assert_not_called()
    mock_db.deprecate_primitive.assert_not_called()


# ===========================================================================
# RESTORE
# ===========================================================================


def test_restore_clears_the_deprecation_and_writes_an_audit_row(mdb):
    mdb.get_primitive_by_id.side_effect = _by_id(_row(deprecated_at=_NOW, sunset_date=_FUTURE))
    mdb.restore_primitive.return_value = _row()

    r = client.delete(_URL)

    assert r.status_code == 200
    body = r.json()
    assert body["deprecated"] is False
    assert body["sunset_date"] is None
    mdb.restore_primitive.assert_called_once_with("p1", "t1")
    args, kwargs = mdb.insert_registry_audit.call_args
    assert args[:3] == ("t1", ACTION_RESTORE, "success")
    assert kwargs["primitive_id"] == "p1"


def test_restore_of_an_active_type_changes_nothing(mdb):
    """Safe to repeat: no write and no audit row when the type is not deprecated."""
    mdb.get_primitive_by_id.side_effect = _by_id(_row())

    r = client.delete(_URL)

    assert r.status_code == 200
    assert r.json()["deprecated"] is False
    mdb.restore_primitive.assert_not_called()
    mdb.insert_registry_audit.assert_not_called()


def test_restore_unknown_type_is_404(mdb):
    mdb.get_primitive_by_id.side_effect = _by_id()

    assert client.delete(_URL).status_code == 404


def test_restore_system_type_is_403(mdb):
    mdb.get_primitive_by_id.side_effect = _by_id(_row(is_system=True, deprecated_at=_NOW))

    assert client.delete(_URL).status_code == 403
    mdb.restore_primitive.assert_not_called()


def test_restore_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)

    assert client.delete(_URL).status_code == 401


# ===========================================================================
# READ SIDE + VOCABULARY
# ===========================================================================


def test_get_primitive_carries_the_deprecation_record_and_its_replacement():
    deprecated = _row(
        deprecated_at=_NOW,
        sunset_date=date(2027, 1, 31),
        deprecation_message="Use money-v2.",
        replacement_id="p2",
    )
    with patch("app.primitives_routes.db") as mock_db:
        mock_db.get_primitive_by_id.side_effect = _by_id(deprecated, _REPLACEMENT)
        mock_db.get_dependent_primitives.return_value = []
        mock_db.get_property_bindings_for_primitive.return_value = []
        r = client.get("/v1/primitives/acme/p1")

    assert r.status_code == 200
    body = r.json()
    assert body["deprecated"] is True
    assert body["sunset_date"] == "2027-01-31"
    assert body["deprecation_message"] == "Use money-v2."
    assert body["replacement"]["name"] == "money-v2"


def test_get_primitive_of_an_active_type_is_not_deprecated():
    with patch("app.primitives_routes.db") as mock_db:
        mock_db.get_primitive_by_id.side_effect = _by_id(_row())
        mock_db.get_dependent_primitives.return_value = []
        mock_db.get_property_bindings_for_primitive.return_value = []
        r = client.get("/v1/primitives/acme/p1")

    assert r.status_code == 200
    body = r.json()
    assert body["deprecated"] is False
    assert body["deprecated_at"] is None
    assert body["replacement"] is None


def test_the_lifecycle_verbs_are_registered_audit_actions():
    assert ACTION_DEPRECATE == "primitive.deprecate"
    assert ACTION_RESTORE == "primitive.restore"
    assert {ACTION_DEPRECATE, ACTION_RESTORE} <= set(REGISTRY_AUDIT_ACTIONS)
