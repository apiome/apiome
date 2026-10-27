"""Catalog item refresh storage SQL and the V333 migration (MFI-31.1, #4398).

A recording fake stands in for :class:`~app.database.Database`; the tests pin the parts of each
statement the feature depends on (tenant scoping, due-selection, backoff, credential keep /
replace, the sealed blob never in API reads) and the migration's shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple

from app import catalog_refresh_store as store

_TENANT = "11111111-1111-4111-8111-111111111111"
_ITEM = "22222222-2222-4222-8222-222222222222"
_MIGRATION = "apiome-db/scripts/V333__catalog_item_refresh_4398.sql"


class _RecordingDb:
    def __init__(self, rows: List[Dict[str, Any]] | None = None, affected: int = 1) -> None:
        self.calls: List[Tuple[str, Any]] = []
        self.rows = rows or []
        self.affected = affected

    def execute_query(self, query: str, params: Any = None) -> List[Dict[str, Any]]:
        self.calls.append((" ".join(query.split()), params))
        return self.rows

    def _execute_write(self, query: str, params: Any = None) -> int:
        self.calls.append((" ".join(query.split()), params))
        return self.affected


def test_the_api_read_is_tenant_scoped_and_hides_the_blob():
    db = _RecordingDb()
    assert store.get_refresh(db, _ITEM, _TENANT) is None
    sql, params = db.calls[0]
    assert "r.project_id = %s::uuid AND r.tenant_id = %s::uuid" in sql
    assert "encrypted_payload IS NOT NULL) AS has_credential" in sql
    assert "r.encrypted_payload," not in sql
    assert params == (_ITEM, _TENANT)


def test_the_check_read_carries_the_sealed_blob():
    db = _RecordingDb([{"project_id": _ITEM}])
    store.get_refresh_for_check(db, _ITEM)
    assert "r.encrypted_payload, r.key_version" in db.calls[0][0]


def test_due_selection_applies_every_gate():
    db = _RecordingDb()
    store.list_due(db, limit=50)
    sql, params = db.calls[0]
    assert "p.deleted_at IS NULL" in sql and "p.publishable = false" in sql
    assert "t.catalog_refresh_enabled" in sql
    assert "(r.next_check_after IS NULL OR r.next_check_after <= now())" in sql
    assert "CASE r.cadence WHEN 'hourly' THEN 3600 WHEN 'daily' THEN 86400 WHEN 'weekly' THEN 604800 END" in sql
    assert "ORDER BY r.last_checked_at NULLS FIRST" in sql
    assert params == ("hourly", "daily", "weekly", 50)


def test_upsert_keeps_the_credential_by_default():
    db = _RecordingDb([{"project_id": _ITEM}])
    store.upsert_refresh(
        db,
        project_id=_ITEM,
        tenant_id=_TENANT,
        cadence="daily",
        adapter_key="graphql",
        endpoint="https://x.example.com",
        options={},
    )
    sql, params = db.calls[0]
    assert "ON CONFLICT (project_id) DO UPDATE" in sql
    assert "IS DISTINCT FROM (EXCLUDED.adapter_key, EXCLUDED.endpoint)" in sql
    assert "next_check_after = NULL" in sql
    # keep flags (three CASEs) are True; the inserted credential is empty.
    assert params[11:14] == (True, True, True)
    assert params[6:9] == ("none", None, None)


def test_upsert_replaces_with_a_sealed_credential():
    db = _RecordingDb([{"project_id": _ITEM}])
    store.upsert_refresh(
        db,
        project_id=_ITEM,
        tenant_id=_TENANT,
        cadence="daily",
        adapter_key="graphql",
        endpoint="https://x.example.com",
        options={"a": 1},
        credential=("bearer", b"blob", 2),
    )
    params = db.calls[0][1]
    assert params[5] == '{"a": 1}'
    assert params[6] == "bearer" and bytes(params[7].adapted) == b"blob" and params[8] == 2
    assert params[11:14] == (False, False, False)


def test_upsert_clears_the_credential_with_none():
    db = _RecordingDb([{"project_id": _ITEM}])
    store.upsert_refresh(
        db,
        project_id=_ITEM,
        tenant_id=_TENANT,
        cadence="off",
        adapter_key="graphql",
        endpoint="https://x.example.com",
        options={},
        credential=None,
    )
    params = db.calls[0][1]
    assert params[6:9] == ("none", None, None) and params[11:14] == (False, False, False)


def test_failure_increments_and_backs_off_without_touching_the_fingerprint():
    db = _RecordingDb()
    store.record_failure(db, _ITEM, error="boom", backoff_seconds=600)
    sql, params = db.calls[0]
    assert "consecutive_failures = consecutive_failures + 1" in sql
    assert "next_check_after = now() + make_interval(secs => %s)" in sql
    assert "last_fingerprint" not in sql
    assert params == ("failed", "boom", 600.0, _ITEM)


def test_success_resets_failures_and_backoff():
    db = _RecordingDb()
    store.record_success(db, _ITEM, status="changed", fingerprint="fp")
    sql, params = db.calls[0]
    assert "consecutive_failures = 0" in sql and "next_check_after = NULL" in sql
    assert params == ("changed", "fp", _ITEM)


def test_delete_is_tenant_scoped():
    db = _RecordingDb(affected=0)
    assert store.delete_refresh(db, _ITEM, _TENANT) is False
    assert "project_id = %s::uuid AND tenant_id = %s::uuid" in db.calls[0][0]


def test_the_tenant_switch_defaults_on():
    assert store.get_tenant_refresh_enabled(_RecordingDb([]), _TENANT) is True
    assert store.get_tenant_refresh_enabled(_RecordingDb([{"catalog_refresh_enabled": False}]), _TENANT) is False


# --- migration -------------------------------------------------------------------------


def test_v333_creates_the_refresh_table_and_kill_switch(repo_root: Path):
    text = (repo_root / _MIGRATION).read_text()
    for fragment in (
        "CREATE TABLE IF NOT EXISTS apiome.catalog_item_refresh",
        "project_id           UUID PRIMARY KEY REFERENCES apiome.projects(id) ON DELETE CASCADE",
        "CHECK (cadence IN ('off', 'manual', 'hourly', 'daily', 'weekly'))",
        "CHECK (auth_type IN ('none', 'bearer', 'header', 'oauth2'))",
        "CHECK (status IN ('never', 'unchanged', 'changed', 'failed'))",
        "encrypted_payload    BYTEA",
        "ck_catalog_item_refresh_sealed_pair",
        "WHERE cadence IN ('hourly', 'daily', 'weekly')",
        "ADD COLUMN IF NOT EXISTS catalog_refresh_enabled BOOLEAN NOT NULL DEFAULT TRUE",
        "DROP TABLE IF EXISTS apiome.catalog_item_refresh",  # documented rollback
    ):
        assert fragment in text, fragment


def test_the_migration_vocabulary_matches_the_app(repo_root: Path):
    from app.catalog_refresh import AUTH_TYPES, CADENCES

    text = (repo_root / _MIGRATION).read_text()
    for value in (*CADENCES, *AUTH_TYPES):
        assert f"'{value}'" in text
