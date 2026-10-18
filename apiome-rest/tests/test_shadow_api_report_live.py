"""The shadow-API report's SQL against a real Postgres (CDG-1.6, #5957).

Seeds one connector with five inventory rows (two linked, one served on a published Project's
server, two unknown), runs the real loaders and :func:`build_shadow_report`, then exercises the item
writes, the first-sight flag and the notification throttle. Skips itself when no database with V283
(and a tenant member) exists. Everything it creates is deleted.
"""

from __future__ import annotations

import uuid
from typing import Iterator

import pytest

from app import catalog_connector_store as connector_store
from app import shadow_api_store as store
from app.database import db
from app.refresh_source import RefreshCandidate
from app.shadow_api_report import build_shadow_report


@pytest.fixture
def live() -> Iterator[dict]:
    try:
        ready = db.execute_query(
            "SELECT 1 AS ok FROM information_schema.tables WHERE table_schema = 'apiome' "
            "AND table_name = 'catalog_connector_notification_throttle'"
        )
        member = db.execute_query("SELECT tenant_id, user_id FROM apiome.tenant_users LIMIT 1")
    except Exception as exc:  # noqa: BLE001 - no database at all
        pytest.skip(f"no live Postgres: {exc}")
    if not ready or not member:
        pytest.skip("V283 not applied or no tenant member in the local database")
    tenant_id, user_id = str(member[0]["tenant_id"]), str(member[0]["user_id"])
    tag = uuid.uuid4().hex[:8]
    connector = connector_store.create_connector(
        db,
        tenant_id,
        kind="kong-admin",
        name=f"live-shadow-{tag}",
        base_url=None,
        scope={},
        refresh_interval_seconds=None,
        conflict_policy="hold-for-review",
        status="active",
        created_by=user_id,
    )
    projects = []

    def project(name: str, *, publishable: bool, servers=(), remote_id=None) -> str:
        project_id = str(uuid.uuid4())
        db._execute_write(
            "INSERT INTO apiome.projects (id, tenant_id, creator_id, name, slug, publishable) "
            "VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s)",
            (project_id, tenant_id, user_id, name, f"{name.lower().replace(' ', '-')}-{tag}", publishable),
        )
        projects.append(project_id)
        version = db.execute_query(
            "INSERT INTO apiome.versions "
            "(project_id, creator_id, version_id, published, published_at, format_metadata) "
            "VALUES (%s::uuid, %s::uuid, '1.0.0', %s, CASE WHEN %s THEN now() END, %s::jsonb) RETURNING id",
            (project_id, user_id, publishable, publishable, '{"remoteId": "%s"}' % remote_id if remote_id else "{}"),
        )[0]["id"]
        for n, url in enumerate(servers):
            db._execute_write(
                "INSERT INTO apiome.version_server (version_id, url, sort_order) VALUES (%s::uuid, %s, %s)",
                (str(version), url, n),
            )
        return project_id

    try:
        yield {"tenant_id": tenant_id, "user_id": user_id, "connector": connector, "project": project, "tag": tag}
    finally:
        db._execute_write("DELETE FROM apiome.catalog_connectors WHERE id = %s::uuid", (str(connector["id"]),))
        for project_id in projects:
            db._execute_write("DELETE FROM apiome.projects WHERE id = %s::uuid", (project_id,))


def test_shadow_report_sql_end_to_end(live):
    tenant_id, user_id, connector = live["tenant_id"], live["user_id"], live["connector"]
    tag = live["tag"]
    linked_a = live["project"]("Linked A", publishable=False)
    linked_b = live["project"]("Linked B", publishable=True, servers=[f"https://b-{tag}.example.com"])
    orders = live["project"]("Orders", publishable=True, servers=[f"https://orders-{tag}.example.com/v2"])
    connector_id = str(connector["id"])

    rows = {}
    for remote_id, host, base in (
        ("a", f"a-{tag}.example.com", None),
        ("b", f"b-{tag}.example.com", None),
        ("orders", f"orders-{tag}.example.com", "/v2"),
        ("x", f"x-{tag}.example.com", None),
        ("y", f"y-{tag}.example.com", None),
    ):
        row = connector_store.upsert_seen_item(
            db,
            connector_id,
            RefreshCandidate(remote_id=remote_id, name=f"svc {remote_id}", hosts=(host,), base_path=base),
        )
        assert row["inserted"] is True
        rows[remote_id] = row
    assert connector_store.upsert_seen_item(db, connector_id, RefreshCandidate(remote_id="a"))["inserted"] is False
    store.link_item(db, str(rows["a"]["id"]), project_id=linked_a, actor_id=user_id)
    store.link_item(db, str(rows["b"]["id"]), project_id=linked_b, actor_id=user_id)

    connectors = store.load_report_connectors(db, tenant_id, connector_id)
    items = store.load_report_items(db, [connector_id])
    entries = store.load_catalog_entries(db, tenant_id)
    assert {e["project_id"] for e in entries} >= {linked_a, linked_b, orders}
    report = build_shadow_report(connectors=connectors, items=items, entries=entries)
    assert sorted(r["remoteId"] for r in report["shadow"]) == ["x", "y"]
    (possible,) = report["possibleMatches"]
    assert possible["remoteId"] == "orders" and possible["match"]["target"]["projectId"] == orders
    assert possible["match"]["tier"] == "host"

    linked = store.get_item(db, tenant_id, connector_id, str(rows["a"]["id"]))
    assert linked["status"] == "imported" and str(linked["linked_by"]) == user_id

    store.ignore_item(db, str(rows["x"]["id"]), reason="Health check", actor_id=user_id)
    ignored = store.get_item(db, tenant_id, connector_id, str(rows["x"]["id"]))
    assert ignored["status"] == "ignored" and ignored["ignored_hosts"] == [f"x-{tag}.example.com"]
    store.unignore_item(db, str(rows["x"]["id"]))
    assert store.get_item(db, tenant_id, connector_id, str(rows["x"]["id"]))["ignored_reason"] is None

    assert store.load_report_items(db, [connector_id], "nowhere") == []
    assert store.get_item(db, str(uuid.uuid4()), connector_id, str(rows["x"]["id"])) is None

    assert store.claim_connector_notification_slot(db, tenant_id, connector_id) is True
    assert store.claim_connector_notification_slot(db, tenant_id, connector_id) is False
    assert store.claim_connector_notification_slot(db, tenant_id, connector_id, window_seconds=0) is True
