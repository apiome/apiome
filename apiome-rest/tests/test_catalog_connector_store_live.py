"""Catalog connector SQL against a real Postgres (CDG-1.1, #5952).

The engine and route tests run over an in-memory fake; this module runs the real store
functions against the local database so the V281 SQL itself is exercised: tenant scoping, the
live-name index, the single-flight run index, missing-marking that never deletes, the shared
quota count and the ledger's shape check. It skips itself when no database with V281 applied
(and at least one tenant) is reachable, so it never fails a machine without Postgres.
"""

from __future__ import annotations

import uuid
from typing import Iterator

import psycopg2
import pytest

from app import catalog_connector_store as store
from app.catalog_connectors import CODE_NAME_TAKEN, ConnectorError
from app.database import Database
from app.refresh_source import RefreshCandidate


@pytest.fixture
def live() -> Iterator[tuple]:
    """A real Database, a tenant id and a cleanup list; skips when unavailable."""
    database = Database()
    try:
        ready = database.execute_query("SELECT to_regclass('apiome.catalog_connectors') AS t")
        tenants = database.execute_query("SELECT id FROM apiome.tenants ORDER BY created_at LIMIT 1")
    except Exception as exc:  # noqa: BLE001 - no database at all
        pytest.skip(f"no live Postgres: {exc}")
    if not ready or ready[0]["t"] is None or not tenants:
        pytest.skip("V281 not applied or no tenant in the local database")
    created: list = []
    try:
        yield database, str(tenants[0]["id"]), created
    finally:
        for connector_id in created:
            database._execute_write("DELETE FROM apiome.catalog_connectors WHERE id = %s::uuid", (connector_id,))
        database.close()


def _connector(database, tenant_id, created, **overrides):
    fields = dict(
        kind="kong-admin",
        name=f"live-test-{uuid.uuid4().hex[:8]}",
        base_url=None,
        scope={"workspace": "default"},
        refresh_interval_seconds=None,
        conflict_policy="hold-for-review",
        status="active",
        created_by=None,
    )
    fields.update(overrides)
    row = store.create_connector(database, tenant_id, **fields)
    created.append(str(row["id"]))
    return row


def test_connector_crud_is_tenant_scoped(live):
    database, tenant_id, created = live
    row = _connector(database, tenant_id, created)
    assert row["scope"] == {"workspace": "default"} and row["has_credentials"] is False
    assert store.get_connector(database, str(uuid.uuid4()), str(row["id"])) is None
    updated = store.update_connector(database, tenant_id, str(row["id"]), {"status": "paused", "scope": {"a": 1}})
    assert updated["status"] == "paused" and updated["scope"] == {"a": 1}
    assert any(str(c["id"]) == str(row["id"]) for c in store.list_connectors(database, tenant_id))
    assert store.soft_delete_connector(database, tenant_id, str(row["id"]))["name"] == row["name"]
    assert store.get_connector(database, tenant_id, str(row["id"])) is None


def test_live_names_are_unique_and_deleted_ones_free_theirs(live):
    database, tenant_id, created = live
    row = _connector(database, tenant_id, created)
    with pytest.raises(ConnectorError) as info:
        _connector(database, tenant_id, created, name=row["name"].upper())
    assert info.value.code == CODE_NAME_TAKEN
    store.soft_delete_connector(database, tenant_id, str(row["id"]))
    _connector(database, tenant_id, created, name=row["name"])


def test_credentials_are_stored_sealed_and_replaced(live):
    database, tenant_id, created = live
    row = _connector(database, tenant_id, created)
    store.put_credentials(database, str(row["id"]), encrypted_payload=b"sealed-1", key_version=1, created_by=None)
    store.put_credentials(database, str(row["id"]), encrypted_payload=b"sealed-2", key_version=2, created_by=None)
    sealed = store.get_sealed_credentials(database, str(row["id"]))
    assert bytes(sealed["encrypted_payload"]) == b"sealed-2" and sealed["key_version"] == 2
    assert store.get_connector(database, tenant_id, str(row["id"]))["has_credentials"] is True
    store.soft_delete_connector(database, tenant_id, str(row["id"]))
    assert store.get_sealed_credentials(database, str(row["id"])) is None


def test_inventory_marks_missing_and_never_deletes(live):
    database, tenant_id, created = live
    connector_id = str(_connector(database, tenant_id, created)["id"])
    a = store.upsert_seen_item(database, connector_id, RefreshCandidate(remote_id="a", hosts=("a.example",)))
    store.upsert_seen_item(database, connector_id, RefreshCandidate(remote_id="b"))
    assert a["status"] == "discovered" and a["hosts"] == ["a.example"]
    assert store.mark_missing_items(database, connector_id, ["a"]) == 1
    assert store.mark_missing_items(database, connector_id, ["a"]) == 0
    statuses = {r["remote_id"]: r["status"] for r in store.list_item_rows(database, connector_id)}
    assert statuses == {"a": "discovered", "b": "missing"}
    back = store.upsert_seen_item(database, connector_id, RefreshCandidate(remote_id="b", revision="r2"))
    assert back["status"] == "discovered" and back["remote_revision"] == "r2"
    assert store.count_items(database, connector_id, status=None) == 2
    page = store.list_items(database, connector_id, status="discovered", limit=1, offset=1)
    assert [r["remote_id"] for r in page] == ["b"]


def test_runs_are_single_flight_and_count_their_pulls_against_the_quota(live):
    database, tenant_id, created = live
    connector_id = str(_connector(database, tenant_id, created)["id"])
    before = database.count_recent_repository_refresh_jobs_by_tenant(3600).get(tenant_id, 0)
    run = store.start_run(database, tenant_id, connector_id, trigger="manual", created_by=None)
    assert run["status"] == "running" and run["refresh_source"] == "connector"
    assert store.start_run(database, tenant_id, connector_id, trigger="manual", created_by=None) is None
    store.finish_run(database, str(run["id"]), status="failed", pull_count=5, summary={"trigger": "manual"},
                     error_class="auth", http_status=401, error_message="denied")
    after = database.count_recent_repository_refresh_jobs_by_tenant(3600).get(tenant_id, 0)
    assert after - before == 5
    (row,) = store.list_runs(database, tenant_id, connector_id, limit=5, offset=0)
    assert (row["status"], row["error_class"], row["http_status"]) == ("failed", "auth", 401)
    assert store.count_runs(database, tenant_id, connector_id) == 1
    assert store.start_run(database, tenant_id, connector_id, trigger="scheduled", created_by=None) is not None


def test_the_ledger_refuses_a_connector_row_shaped_like_a_git_job(live):
    database, tenant_id, created = live
    connector_id = str(_connector(database, tenant_id, created)["id"])
    with pytest.raises(psycopg2.errors.CheckViolation):
        database.execute_query(
            """
            INSERT INTO apiome.tenant_repository_refresh_jobs (tenant_id, connector_id, refresh_source)
            VALUES (%s::uuid, %s::uuid, 'git') RETURNING id
            """,
            (tenant_id, connector_id),
        )


def test_due_selection_skips_paused_connectors_and_honours_the_cadence(live):
    database, tenant_id, created = live
    due = _connector(database, tenant_id, created)
    paused = _connector(database, tenant_id, created, status="paused")
    ids = {str(r["id"]) for r in store.list_due_connectors(database, default_interval_seconds=300, floor_seconds=60)}
    assert str(due["id"]) in ids and str(paused["id"]) not in ids
    store.record_connector_outcome(database, str(due["id"]), status="failing")
    ids = {str(r["id"]) for r in store.list_due_connectors(database, default_interval_seconds=300, floor_seconds=60)}
    assert str(due["id"]) not in ids  # just ran: not due until its cadence passes
    store.record_connector_outcome(database, str(paused["id"]), status="active")
    assert store.get_connector(database, tenant_id, str(paused["id"]))["status"] == "paused"
