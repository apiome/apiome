"""The unified refresh ledger's SQL against a real Postgres (CDG-1.7, #5958).

Seeds a connector with one run and reads ``list_refresh_runs`` / ``count_refresh_runs`` with and
without filters. Skips itself without a database (or a tenant member); deletes what it creates.
"""

from __future__ import annotations

import uuid

import pytest

from app import catalog_connector_store as store
from app.database import db


def test_ledger_sql_lists_and_filters_connector_runs():
    try:
        member = db.execute_query("SELECT tenant_id, user_id FROM apiome.tenant_users LIMIT 1")
    except Exception as exc:  # noqa: BLE001 - no database at all
        pytest.skip(f"no live Postgres: {exc}")
    if not member:
        pytest.skip("no tenant member in the local database")
    tenant_id, user_id = str(member[0]["tenant_id"]), str(member[0]["user_id"])
    connector = store.create_connector(
        db,
        tenant_id,
        kind="kong-admin",
        name=f"live-ledger-{uuid.uuid4().hex[:8]}",
        base_url=None,
        scope={},
        refresh_interval_seconds=None,
        conflict_policy="hold-for-review",
        status="active",
        created_by=user_id,
    )
    connector_id = str(connector["id"])
    try:
        run = store.start_run(db, tenant_id, connector_id, trigger="manual", created_by=user_id)
        store.finish_run(db, str(run["id"]), status="succeeded", pull_count=2, summary={"trigger": "manual"})
        only = store.list_refresh_runs(db, tenant_id, connector_id=connector_id, source=None, limit=10, offset=0)
        assert [str(r["id"]) for r in only] == [str(run["id"])]
        assert only[0]["connector_name"] == connector["name"] and only[0]["refresh_source"] == "connector"
        assert store.count_refresh_runs(db, tenant_id, connector_id=connector_id, source=None) == 1
        assert store.count_refresh_runs(db, tenant_id, connector_id=connector_id, source="git") == 0
        everything = store.list_refresh_runs(db, tenant_id, connector_id=None, source=None, limit=200, offset=0)
        assert str(run["id"]) in {str(r["id"]) for r in everything}
    finally:
        db._execute_write("DELETE FROM apiome.catalog_connectors WHERE id = %s::uuid", (connector_id,))
