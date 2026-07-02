"""API tests for the type-registry Settings endpoints (#3472).

Covers GET / PUT for ``/v1/types/{tenant_slug}/settings``: auth requirements, tenant scoping,
the defaults-when-unsaved contract, tenant-admin write rule, partial updates, enum/range
validation, and base-URL validation.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import db
from app.main import app

client = TestClient(app)

_JWT_ADMIN = {"tenant_id": "t1", "user_id": "admin-user", "auth_method": "jwt"}
_JWT_NON_ADMIN = {"tenant_id": "t1", "user_id": "plain-user", "auth_method": "jwt"}

_NOW = datetime(2026, 6, 23, 12, 0, 0, tzinfo=timezone.utc)

# A fully-populated persisted row, as the DB layer would return it.
_SETTINGS_ROW = {
    "default_draft": "2019-09",
    "strict_validation": False,
    "allow_annotation_keywords": True,
    "coerce_imported_drafts": False,
    "resolution_base_url": "https://types.acme.example/",
    "ref_style": "absolute",
    "allow_remote_refs": True,
    "remote_host_allowlist": ["json-schema.org", "acme.example"],
    "max_resolution_depth": 24,
    "circular_ref_policy": "warn",
    "default_import_scope": "tenant",
    "default_target_namespace": "tenant/acme/v1/types",
    "rewrite_refs_on_import": False,
    "accepted_formats": ["json-schema-2020-12"],
    "dedupe_identical_types": False,
    "validate_on_save": False,
    "block_publish_on_errors": False,
    "core_publish_role": "tenant_admin",
    "updated_by": "admin-user",
    "created_at": _NOW,
    "updated_at": _NOW,
}


@pytest.fixture(autouse=True)
def _default_auth():
    """Default to JWT admin; individual tests may override."""
    app.dependency_overrides[validate_authentication] = lambda: _JWT_ADMIN
    yield
    app.dependency_overrides.pop(validate_authentication, None)


# ===========================================================================
# GET
# ===========================================================================


def test_get_settings_returns_defaults_when_unsaved():
    """A tenant with no saved row gets the model defaults flagged is_default=true."""
    with patch("app.type_namespaces_routes.db") as mdb:
        mdb.get_type_registry_settings.return_value = None
        r = client.get("/v1/types/acme/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["is_default"] is True
    assert body["default_draft"] == "2020-12"
    assert body["ref_style"] == "relative"
    assert body["max_resolution_depth"] == 12
    assert body["remote_host_allowlist"] == ["json-schema.org", "spec.openapis.org"]
    assert body["validate_on_save"] is True


def test_get_settings_returns_saved_row():
    with patch("app.type_namespaces_routes.db") as mdb:
        mdb.get_type_registry_settings.return_value = _SETTINGS_ROW
        r = client.get("/v1/types/acme/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["is_default"] is False
    assert body["default_draft"] == "2019-09"
    assert body["ref_style"] == "absolute"
    assert body["max_resolution_depth"] == 24
    assert body["circular_ref_policy"] == "warn"
    assert body["updated_by"] == "admin-user"


def test_get_settings_scoped_to_caller_tenant():
    """The DB layer is queried with the token tenant_id, not the URL slug."""
    with patch("app.type_namespaces_routes.db") as mdb:
        mdb.get_type_registry_settings.return_value = None
        client.get("/v1/types/some-other-slug/settings")
        mdb.get_type_registry_settings.assert_called_once_with("t1")


def test_get_settings_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    r = client.get("/v1/types/acme/settings")
    assert r.status_code == 401


# ===========================================================================
# PUT
# ===========================================================================


def test_put_settings_ok_partial_update():
    with patch("app.type_namespaces_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        mdb.upsert_type_registry_settings.return_value = {**_SETTINGS_ROW, "default_draft": "draft-07"}
        r = client.put("/v1/types/acme/settings", json={"default_draft": "draft-07"})
    assert r.status_code == 200
    assert r.json()["default_draft"] == "draft-07"
    # Only the supplied field is forwarded to the DB layer.
    args = mdb.upsert_type_registry_settings.call_args
    assert args.args[0] == "t1"
    assert args.args[1] == {"default_draft": "draft-07"}
    assert args.kwargs["updated_by"] == "admin-user"


def test_put_settings_requires_admin():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_NON_ADMIN
    with patch("app.type_namespaces_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = False
        r = client.put("/v1/types/acme/settings", json={"default_draft": "2020-12"})
    assert r.status_code == 403
    mdb.upsert_type_registry_settings.assert_not_called()


def test_put_settings_invalid_draft_422():
    with patch("app.type_namespaces_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        r = client.put("/v1/types/acme/settings", json={"default_draft": "draft-99"})
    assert r.status_code == 422
    mdb.upsert_type_registry_settings.assert_not_called()


def test_put_settings_depth_out_of_range_422():
    with patch("app.type_namespaces_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        r = client.put("/v1/types/acme/settings", json={"max_resolution_depth": 999})
    assert r.status_code == 422
    mdb.upsert_type_registry_settings.assert_not_called()


def test_put_settings_invalid_ref_style_422():
    with patch("app.type_namespaces_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        r = client.put("/v1/types/acme/settings", json={"ref_style": "sideways"})
    assert r.status_code == 422
    mdb.upsert_type_registry_settings.assert_not_called()


def test_put_settings_empty_base_url_400():
    with patch("app.type_namespaces_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        r = client.put("/v1/types/acme/settings", json={"resolution_base_url": "   "})
    assert r.status_code == 400
    mdb.upsert_type_registry_settings.assert_not_called()


def test_put_settings_trims_base_url():
    with patch("app.type_namespaces_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        mdb.upsert_type_registry_settings.return_value = _SETTINGS_ROW
        r = client.put(
            "/v1/types/acme/settings",
            json={"resolution_base_url": "  https://types.acme.example/  "},
        )
    assert r.status_code == 200
    assert mdb.upsert_type_registry_settings.call_args.args[1]["resolution_base_url"] == (
        "https://types.acme.example/"
    )


def test_put_settings_full_payload_roundtrips_all_fields():
    """A full save forwards every field and echoes the persisted row back."""
    payload = {
        "default_draft": "2019-09",
        "strict_validation": False,
        "allow_annotation_keywords": True,
        "coerce_imported_drafts": False,
        "resolution_base_url": "https://types.acme.example/",
        "ref_style": "absolute",
        "allow_remote_refs": True,
        "remote_host_allowlist": ["json-schema.org", "acme.example"],
        "max_resolution_depth": 24,
        "circular_ref_policy": "warn",
        "default_import_scope": "tenant",
        "default_target_namespace": "tenant/acme/v1/types",
        "rewrite_refs_on_import": False,
        "accepted_formats": ["json-schema-2020-12"],
        "dedupe_identical_types": False,
        "validate_on_save": False,
        "block_publish_on_errors": False,
        "core_publish_role": "tenant_admin",
    }
    with patch("app.type_namespaces_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        mdb.upsert_type_registry_settings.return_value = _SETTINGS_ROW
        r = client.put("/v1/types/acme/settings", json=payload)
    assert r.status_code == 200
    assert mdb.upsert_type_registry_settings.call_args.args[1] == payload
    body = r.json()
    assert body["is_default"] is False
    assert body["allow_remote_refs"] is True
    assert body["accepted_formats"] == ["json-schema-2020-12"]


# ===========================================================================
# DB layer: upsert SQL construction (partial-update preservation)
# ===========================================================================


def _mock_cursor_conn(returned_row):
    """A (conn, cursor) pair where the cursor records the last execute() and returns a row."""
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    cursor.fetchone.return_value = returned_row
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, cursor


def test_upsert_partial_update_only_writes_supplied_columns():
    """A partial save must touch only the supplied columns; omitted ones are left as stored.

    Guards the ON CONFLICT path: EXCLUDED.<col> for a column absent from the INSERT list is that
    column's DEFAULT (not NULL), so a COALESCE-everything update would silently reset untouched
    columns. The SET clause must therefore name only the supplied columns.
    """
    conn, cursor = _mock_cursor_conn({**_SETTINGS_ROW})
    with patch.object(db, "connect", return_value=conn):
        db.upsert_type_registry_settings("t1", {"default_draft": "draft-07"}, updated_by="u1")

    sql, params = cursor.execute.call_args.args
    # Only the supplied column appears in the INSERT column list and the SET clause...
    assert "default_draft" in sql
    assert "default_draft = EXCLUDED.default_draft" in sql
    # ...no untouched column is written back on conflict.
    assert "strict_validation = EXCLUDED" not in sql
    assert "ref_style = EXCLUDED" not in sql
    # updated_by / updated_at are always refreshed.
    assert "updated_by = EXCLUDED.updated_by" in sql
    assert "updated_at = CURRENT_TIMESTAMP" in sql
    # Params: tenant_id, updated_by, then the single supplied value.
    assert params == ("t1", "u1", "draft-07")
    conn.commit.assert_called_once()


def test_upsert_empty_update_still_upserts_provenance():
    """An empty save inserts a defaults row (or refreshes provenance) without naming data columns."""
    conn, cursor = _mock_cursor_conn({**_SETTINGS_ROW})
    with patch.object(db, "connect", return_value=conn):
        db.upsert_type_registry_settings("t1", {}, updated_by="u1")

    sql, params = cursor.execute.call_args.args
    assert "EXCLUDED.default_draft" not in sql
    assert "updated_by = EXCLUDED.updated_by" in sql
    assert params == ("t1", "u1")
