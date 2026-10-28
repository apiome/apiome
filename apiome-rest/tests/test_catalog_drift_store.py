"""Catalog drift storage SQL and the V334 migration (MFI-31.3, #4400).

A recording fake stands in for :class:`~app.database.Database`; the tests pin tenant scoping, the
one-event-per-version rule, dismissal, digest selection and the migration's shape.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app import catalog_drift_store as store
from app.catalog_drift import DriftClassification, DriftSettings

_TENANT = "11111111-1111-4111-8111-111111111111"
_ITEM = "22222222-2222-4222-8222-222222222222"
_EVENT = "33333333-3333-4333-8333-333333333333"
_MIGRATION = "apiome-db/scripts/V334__catalog_drift_notifications_4400.sql"


class _RecordingDb:
    def __init__(self, rows: List[Dict[str, Any]] | None = None) -> None:
        self.calls: List[Tuple[str, Any]] = []
        self.rows = rows or []

    def execute_query(self, query: str, params: Any = None) -> List[Dict[str, Any]]:
        self.calls.append((" ".join(query.split()), params))
        return self.rows


def test_settings_read_is_tenant_scoped():
    db = _RecordingDb()
    assert store.get_settings_row(db, _TENANT) is None
    sql, params = db.calls[0]
    assert "FROM apiome.catalog_drift_settings WHERE tenant_id = %s::uuid" in sql
    assert params == (_TENANT,)


def test_settings_upsert_keeps_the_last_digest_time():
    db = _RecordingDb([{"tenant_id": _TENANT}])
    store.put_settings(db, _TENANT, DriftSettings(delivery="daily_digest"), actor_id="u-1")
    sql, params = db.calls[0]
    assert "ON CONFLICT (tenant_id) DO UPDATE" in sql
    assert "last_digest_at" not in sql.split("DO UPDATE SET")[1]
    assert params == (_TENANT, True, True, False, "daily_digest", True, False, "u-1")


def test_insert_event_is_once_per_version_and_stamps_sent():
    db = _RecordingDb([{"id": _EVENT}])
    classification = DriftClassification(
        severity="breaking", counts={"safe": 0, "dangerous": 0, "breaking": 1}, change_count=1, changes=[{"key": "A"}]
    )
    store.insert_event(
        db,
        tenant_id=_TENANT,
        project_id=_ITEM,
        version_id="v-2",
        parent_version_id="v-1",
        version_label="2026-10-27T12:00Z",
        parent_version_label="1.0.0",
        trigger="sweep",
        classification=classification,
        notification="sent",
    )
    sql, params = db.calls[0]
    assert "ON CONFLICT (version_id) DO NOTHING" in sql
    assert "CASE WHEN %s = 'sent' THEN CURRENT_TIMESTAMP END" in sql
    assert "WHERE e.version_id = %s::uuid AND NOT EXISTS (SELECT 1 FROM inserted)" in sql
    assert json.loads(params[8]) == classification.counts
    assert json.loads(params[10]) == [{"key": "A"}]
    assert params[11:] == ("sent", "sent", "v-2")


def test_badges_read_the_newest_open_event_per_item_and_skip_bad_ids():
    db = _RecordingDb([{"project_id": _ITEM, "id": _EVENT}])
    assert store.latest_open_events(db, _TENANT, [_ITEM, "not-a-uuid"]) == {_ITEM: {"project_id": _ITEM, "id": _EVENT}}
    sql, params = db.calls[0]
    assert "DISTINCT ON (e.project_id)" in sql and "e.dismissed_at IS NULL" in sql
    assert params == (_TENANT, [_ITEM])
    assert store.latest_open_events(db, "t1", [_ITEM]) == {}
    assert store.latest_open_events(db, _TENANT, []) == {}
    assert len(db.calls) == 1


def test_dismiss_is_scoped_and_keeps_the_first_dismissal():
    db = _RecordingDb()
    assert store.dismiss_event(db, _TENANT, _ITEM, _EVENT, actor_id="u-1") is None
    sql, params = db.calls[0]
    assert "dismissed_at = COALESCE(e.dismissed_at, CURRENT_TIMESTAMP)" in sql
    assert "e.id = %s::uuid AND e.project_id = %s::uuid AND e.tenant_id = %s::uuid" in sql
    assert params == ("u-1", _EVENT, _ITEM, _TENANT)


def test_digest_selection_waits_a_full_interval():
    db = _RecordingDb([{"tenant_id": _TENANT}])
    assert store.tenants_due_for_digest(db, interval_seconds=86400) == [_TENANT]
    sql, params = db.calls[0]
    assert "COALESCE(s.last_digest_at, MIN(e.created_at)) <= CURRENT_TIMESTAMP - make_interval(secs => %s)" in sql
    assert params == ("pending_digest", 86400)


def test_mark_digested_updates_events_and_the_tenant_clock():
    db = _RecordingDb()
    store.mark_digested(db, _TENANT, [_EVENT])
    sql, params = db.calls[0]
    assert "SET notification = %s, notified_at = CURRENT_TIMESTAMP" in sql
    assert "ON CONFLICT (tenant_id) DO UPDATE SET last_digest_at = CURRENT_TIMESTAMP" in sql
    assert params == ("digested", _TENANT, [_EVENT], _TENANT)


def test_the_migration_has_both_tables_and_their_checks():
    sql = (Path(__file__).resolve().parents[2] / _MIGRATION).read_text()
    assert "CREATE TABLE IF NOT EXISTS apiome.catalog_drift_events" in sql
    assert "CREATE TABLE IF NOT EXISTS apiome.catalog_drift_settings" in sql
    assert "CHECK (severity IN ('safe', 'dangerous', 'breaking'))" in sql
    assert "CHECK (notification IN ('none', 'sent', 'pending_digest', 'digested'))" in sql
    assert "CHECK (delivery IN ('immediate', 'daily_digest'))" in sql
    assert "CONSTRAINT uq_catalog_drift_events_version UNIQUE (version_id)" in sql
    assert "WHERE notification = 'pending_digest'" in sql
    assert "notify_safe          BOOLEAN NOT NULL DEFAULT FALSE" in sql
