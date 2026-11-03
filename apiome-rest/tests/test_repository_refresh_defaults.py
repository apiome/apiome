"""Workspace refresh defaults for repositories (RAR-6.5, #3542).

Acceptance criteria, as tested here:

* **Org admins define a default refresh preset** — ``GET/PUT …/repository-refresh-defaults``: anyone
  who can view imports reads it (``canEdit`` says whether they may change it); only a tenant
  administrator writes it (403 otherwise, API keys included); bad policies and sub-floor cadences
  are 400s; an unset workspace reports the built-in values with ``configured: false``.
* **New repos inherit the preset; per-repo override supported** — the insert reads the defaults
  (checked against Postgres in the PR); ``PATCH …/repositories/{id}`` takes a cadence override
  (floor-checked) and ``useWorkspaceDefaults`` to follow a default again; the record reports
  each setting's inheritance.
* **Changing a preset optionally re-applies to inheriting repos** — ``applyToInheriting`` is
  passed through and the per-setting change counts are returned.

Plus the pure resolution of the defaults and the migration's shape.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.repository_refresh_defaults import BUILT_IN_REFRESH_DEFAULTS, resolve_refresh_defaults

client = TestClient(app)

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_USER_ID = "660e8400-e29b-41d4-a716-446655440001"
_REPO_ID = "770e8400-e29b-41d4-a716-446655440002"
_JWT = {"tenant_id": _TENANT_ID, "tenant_slug": "acme", "user_id": _USER_ID, "auth_method": "jwt"}
_API_KEY = {**_JWT, "auth_method": "api_key"}
_URL = "/v1/tenants/acme/repository-refresh-defaults"
_REPO_URL = f"/v1/tenants/acme/repositories/{_REPO_ID}"

_COUNTS = {"repositories": 5, "refresh_interval": 4, "conflict_policy": 3, "auto_refresh": 5}
_STORED = {
    "tenant_id": _TENANT_ID,
    "refresh_interval_seconds": 900,
    "refresh_conflict_policy": "overwrite",
    "auto_refresh_enabled": True,
    "updated_by": _USER_ID,
    "created_at": None,
    "updated_at": None,
}


@pytest.fixture
def as_user():
    def _set(principal):
        app.dependency_overrides[validate_authentication] = lambda: principal

    yield _set
    app.dependency_overrides.pop(validate_authentication, None)


def _mock_defaults(mdb, *, stored=None, admin=True):
    mdb.get_repository_refresh_defaults.return_value = stored
    mdb.count_repository_refresh_inheritance.return_value = dict(_COUNTS)
    mdb.is_user_tenant_admin.return_value = admin


# ===========================================================================
# Pure resolution
# ===========================================================================


def test_no_stored_defaults_means_the_built_in_values() -> None:
    assert resolve_refresh_defaults(None) == BUILT_IN_REFRESH_DEFAULTS
    assert (BUILT_IN_REFRESH_DEFAULTS.refresh_interval_seconds, BUILT_IN_REFRESH_DEFAULTS.conflict_policy,
            BUILT_IN_REFRESH_DEFAULTS.auto_refresh_enabled) == (300, "hold-for-review", True)


def test_stored_defaults_are_read_and_bad_fields_fall_back() -> None:
    assert resolve_refresh_defaults(_STORED).refresh_interval_seconds == 900
    assert resolve_refresh_defaults(_STORED).conflict_policy == "overwrite"
    odd = resolve_refresh_defaults({"refresh_interval_seconds": 0, "refresh_conflict_policy": "nope",
                                    "auto_refresh_enabled": None})
    assert odd == BUILT_IN_REFRESH_DEFAULTS


# ===========================================================================
# GET / PUT the workspace defaults
# ===========================================================================


def test_the_read_reports_built_ins_when_unset(as_user) -> None:
    as_user(_JWT)
    with patch("app.tenant_repositories_routes.db") as mdb:
        _mock_defaults(mdb, stored=None, admin=False)
        r = client.get(_URL)
    assert r.status_code == 200
    body = r.json()["refreshDefaults"]
    assert body["configured"] is False
    assert (body["refreshIntervalSeconds"], body["conflictPolicy"], body["autoRefreshEnabled"]) == (
        300, "hold-for-review", True
    )
    assert body["canEdit"] is False
    assert body["inheriting"] == {"repositories": 5, "refreshInterval": 4, "conflictPolicy": 3, "autoRefresh": 5}
    assert set(body["availableConflictPolicies"]) == {"overwrite", "hold-for-review", "new-branch"}
    assert body["applied"] is None


def test_the_read_reports_stored_defaults_and_admin_can_edit(as_user) -> None:
    as_user(_JWT)
    with patch("app.tenant_repositories_routes.db") as mdb:
        _mock_defaults(mdb, stored=_STORED, admin=True)
        body = client.get(_URL).json()["refreshDefaults"]
    assert body["configured"] is True
    assert (body["refreshIntervalSeconds"], body["conflictPolicy"], body["updatedBy"]) == (900, "overwrite", _USER_ID)
    assert body["canEdit"] is True


def test_an_admin_saves_and_re_applies(as_user) -> None:
    as_user(_JWT)
    with patch("app.tenant_repositories_routes.db") as mdb:
        _mock_defaults(mdb, stored=_STORED, admin=True)
        mdb.save_repository_refresh_defaults.return_value = {
            "refresh_interval": 4, "conflict_policy": 3, "auto_refresh": 0
        }
        r = client.put(_URL, json={
            "refreshIntervalSeconds": 900, "conflictPolicy": "overwrite",
            "autoRefreshEnabled": True, "applyToInheriting": True,
        })
    assert r.status_code == 200
    kwargs = mdb.save_repository_refresh_defaults.call_args.kwargs
    assert mdb.save_repository_refresh_defaults.call_args.args == (_TENANT_ID,)
    assert kwargs == {
        "refresh_interval_seconds": 900, "refresh_conflict_policy": "overwrite",
        "auto_refresh_enabled": True, "updated_by": _USER_ID, "apply_to_inheriting": True,
    }
    assert r.json()["refreshDefaults"]["applied"] == {"refreshInterval": 4, "conflictPolicy": 3, "autoRefresh": 0}


def test_saving_without_re_apply_reports_no_applied_counts(as_user) -> None:
    as_user(_JWT)
    with patch("app.tenant_repositories_routes.db") as mdb:
        _mock_defaults(mdb, stored=_STORED, admin=True)
        mdb.save_repository_refresh_defaults.return_value = {
            "refresh_interval": 0, "conflict_policy": 0, "auto_refresh": 0
        }
        r = client.put(_URL, json={"refreshIntervalSeconds": 900, "conflictPolicy": "overwrite",
                                   "autoRefreshEnabled": False})
    assert r.status_code == 200
    assert mdb.save_repository_refresh_defaults.call_args.kwargs["apply_to_inheriting"] is False
    assert r.json()["refreshDefaults"]["applied"] is None


def test_a_non_admin_cannot_save(as_user) -> None:
    as_user(_JWT)
    with patch("app.tenant_repositories_routes.db") as mdb:
        _mock_defaults(mdb, admin=False)
        r = client.put(_URL, json={"refreshIntervalSeconds": 900, "conflictPolicy": "overwrite",
                                   "autoRefreshEnabled": True})
    assert r.status_code == 403
    mdb.save_repository_refresh_defaults.assert_not_called()


def test_an_api_key_cannot_save(as_user) -> None:
    as_user(_API_KEY)
    with patch("app.tenant_repositories_routes.db") as mdb:
        _mock_defaults(mdb, admin=True)
        r = client.put(_URL, json={"refreshIntervalSeconds": 900, "conflictPolicy": "overwrite",
                                   "autoRefreshEnabled": True})
    assert r.status_code == 403
    mdb.save_repository_refresh_defaults.assert_not_called()


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({"refreshIntervalSeconds": 900, "conflictPolicy": "explode", "autoRefreshEnabled": True}, "conflict policy"),
        ({"refreshIntervalSeconds": 5, "conflictPolicy": "overwrite", "autoRefreshEnabled": True}, "at least"),
    ],
)
def test_invalid_defaults_are_refused(as_user, body, fragment) -> None:
    as_user(_JWT)
    with patch("app.tenant_repositories_routes.db") as mdb:
        _mock_defaults(mdb, admin=True)
        r = client.put(_URL, json=body)
    assert r.status_code == 400
    assert fragment in r.json()["detail"]
    mdb.save_repository_refresh_defaults.assert_not_called()


# ===========================================================================
# Per-repository override and "use workspace default"
# ===========================================================================


def _repo_row(**extra) -> dict:
    row = {
        "id": _REPO_ID, "tenant_id": _TENANT_ID, "provider": "github", "default_branch": "main",
        "status": "ready", "repository_full_name": "acme/specs", "auto_refresh_enabled": True,
        "refresh_conflict_policy": "hold-for-review", "refresh_interval_seconds": 300,
        "inherits_refresh_interval": True, "inherits_conflict_policy": True, "inherits_auto_refresh": True,
    }
    row.update(extra)
    return row


def test_a_repository_overrides_the_cadence(as_user) -> None:
    as_user(_JWT)
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.set_repository_refresh_interval.return_value = 3600
        mdb.get_tenant_repository.return_value = _repo_row(
            refresh_interval_seconds=3600, inherits_refresh_interval=False
        )
        mdb.get_repository_health_signals.return_value = []
        r = client.patch(_REPO_URL, json={"refreshIntervalSeconds": 3600})
    assert r.status_code == 200
    mdb.set_repository_refresh_interval.assert_called_once_with(_TENANT_ID, _REPO_ID, 3600)
    repo = r.json()["repository"]
    assert (repo["refresh_interval_seconds"], repo["inherits_refresh_interval"]) == (3600, False)
    assert repo["inherits_conflict_policy"] is True


def test_a_cadence_below_the_floor_is_refused(as_user) -> None:
    as_user(_JWT)
    with patch("app.tenant_repositories_routes.db") as mdb:
        r = client.patch(_REPO_URL, json={"refreshIntervalSeconds": 5})
    assert r.status_code == 400
    mdb.set_repository_refresh_interval.assert_not_called()


def test_a_repository_follows_the_workspace_defaults_again(as_user) -> None:
    as_user(_JWT)
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.restore_repository_refresh_defaults.return_value = True
        mdb.get_tenant_repository.return_value = _repo_row()
        mdb.get_repository_health_signals.return_value = []
        r = client.patch(_REPO_URL, json={"useWorkspaceDefaults": ["refresh_interval", "auto_refresh"]})
    assert r.status_code == 200
    mdb.restore_repository_refresh_defaults.assert_called_once_with(
        _TENANT_ID, _REPO_ID, ["refresh_interval", "auto_refresh"]
    )


def test_an_unknown_setting_is_a_validation_error(as_user) -> None:
    as_user(_JWT)
    with patch("app.tenant_repositories_routes.db") as mdb:
        r = client.patch(_REPO_URL, json={"useWorkspaceDefaults": ["schedule"]})
    assert r.status_code == 422
    mdb.restore_repository_refresh_defaults.assert_not_called()


def test_restoring_on_an_unknown_repository_is_404(as_user) -> None:
    as_user(_JWT)
    with patch("app.tenant_repositories_routes.db") as mdb:
        mdb.restore_repository_refresh_defaults.return_value = False
        r = client.patch(_REPO_URL, json={"useWorkspaceDefaults": ["conflict_policy"]})
    assert r.status_code == 404


# ===========================================================================
# Migration
# ===========================================================================

_MIGRATION = "apiome-db/scripts/V351__repository_refresh_defaults_3542.sql"


def test_migration_defines_the_preset_and_the_inheritance_flags(repo_root: Path) -> None:
    text = (repo_root / _MIGRATION).read_text()
    for fragment in (
        "CREATE TABLE IF NOT EXISTS apiome.tenant_repository_refresh_defaults",
        "tenant_id                UUID PRIMARY KEY",
        "CHECK (refresh_conflict_policy IN ('overwrite', 'hold-for-review', 'new-branch'))",
        "ADD COLUMN IF NOT EXISTS inherits_refresh_interval BOOLEAN NOT NULL DEFAULT TRUE",
        "ADD COLUMN IF NOT EXISTS inherits_conflict_policy  BOOLEAN NOT NULL DEFAULT TRUE",
        "ADD COLUMN IF NOT EXISTS inherits_auto_refresh     BOOLEAN NOT NULL DEFAULT TRUE",
        # Backfill: only settings still at their built-in value follow the defaults.
        "SET inherits_refresh_interval = (refresh_interval_seconds = 300)",
    ):
        assert fragment in text, fragment
