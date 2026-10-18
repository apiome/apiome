"""The Kong connector end to end against a real Postgres and the real import pipeline (CDG-1.2).

The fake Kong (``tests/kong_fake.py``) stands in for Konnect; everything after the network is
real: the V281/V282 store, the in-process catalog import, the change report. Covers the
acceptance criteria as a tenant sees them: 3 catalog items, an unchanged re-sync that imports
nothing, one changed route that creates exactly one new revision and one change report, and a
revoked token that leaves a failed run with Kong's 401. Skips itself when no database with V282
applied (and at least one tenant member) is reachable.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Iterator, List

import pytest
from catalog_connector_fakes import restore_builtin_sources
from kong_fake import KONNECT_TOKEN, FakeKong

from app import catalog_connector_store as store
from app import kong_connector_source as kong
from app.catalog_connector_sync import register_connector_source, run_connector_sync
from app.config import settings
from app.database import db
from app.mcp_credential_crypto import seal_credential_payload


@pytest.fixture
def live(monkeypatch) -> Iterator[tuple]:
    """``(tenant_id, user_id, fake, connector)``; deletes everything it created."""
    try:
        ready = db.execute_query(
            "SELECT 1 AS ok FROM information_schema.columns WHERE table_schema = 'apiome' "
            "AND table_name = 'catalog_connector_items' AND column_name = 'deployment'"
        )
        member = db.execute_query("SELECT tenant_id, user_id FROM apiome.tenant_users LIMIT 1")
    except Exception as exc:  # noqa: BLE001 - no database at all
        pytest.skip(f"no live Postgres: {exc}")
    if not ready or not member:
        pytest.skip("V282 not applied or no tenant member in the local database")
    tenant_id, user_id = str(member[0]["tenant_id"]), str(member[0]["user_id"])
    monkeypatch.setattr(settings, "ssrf_allow_private", True)
    monkeypatch.setattr(
        settings, "mcp_credential_encryption_keys", json.dumps({"1": base64.b64encode(os.urandom(32)).decode()})
    )
    fake = FakeKong()
    register_connector_source(
        kong.KIND_KONNECT, lambda c, cr: kong.KongKonnectSource(c, cr, transport=fake.transport())
    )
    created = store.create_connector(
        db,
        tenant_id,
        kind=kong.KIND_KONNECT,
        name=f"live-kong-{uuid.uuid4().hex[:8]}",
        base_url="https://konnect.example.test",
        scope={"region": "eu", "controlPlanes": [fake.control_plane["id"]]},
        refresh_interval_seconds=None,
        conflict_policy="hold-for-review",
        status="active",
        created_by=user_id,
    )
    connector_id = str(created["id"])
    try:
        sealed, version = seal_credential_payload({"token": KONNECT_TOKEN})
        store.put_credentials(db, connector_id, encrypted_payload=sealed, key_version=version, created_by=user_id)
        yield tenant_id, user_id, fake, store.get_connector(db, tenant_id, connector_id)
    finally:
        for row in store.list_item_rows(db, connector_id):
            if row.get("project_id"):
                db._execute_write("DELETE FROM apiome.projects WHERE id = %s::uuid", (str(row["project_id"]),))
        db._execute_write("DELETE FROM apiome.catalog_connectors WHERE id = %s::uuid", (connector_id,))
        restore_builtin_sources()


def _count(sql: str, project_ids: List[str]) -> int:
    return int(db.execute_query(sql, (project_ids,))[0]["n"])


def test_konnect_sync_end_to_end(live):
    tenant_id, user_id, fake, connector = live

    first = run_connector_sync(db, connector, actor_id=user_id)
    assert first.status == "succeeded" and first.summary["imported"] == 3
    rows = {r["remote_name"]: r for r in store.list_item_rows(db, str(connector["id"]))}
    assert sorted(rows) == ["billing", "orders", "users"]
    assert all(r["status"] == "imported" and r["environment"] == "prod-eu" for r in rows.values())
    assert rows["billing"]["deployment"]["suggestedOwners"][0]["team"] == "payments"
    project_ids = [str(r["project_id"]) for r in rows.values()]
    item = db.get_catalog_item_by_id(str(rows["orders"]["project_id"]), tenant_id)
    assert item["source_format"] == "kong" and item["publishable"] is False
    assert item["format_metadata"]["inputKind"] == "connector"

    versions_sql = "SELECT count(*) AS n FROM apiome.versions WHERE project_id = ANY(%s::uuid[])"
    reports_sql = "SELECT count(*) AS n FROM apiome.change_reports WHERE project_id = ANY(%s::uuid[])"
    assert (_count(versions_sql, project_ids), _count(reports_sql, project_ids)) == (3, 0)

    again = run_connector_sync(db, connector, actor_id=user_id)
    assert again.summary["imported"] == 0 and again.summary["unchanged"] == 3

    next(r for r in fake.entities["routes"] if r["name"] == "orders-list")["paths"] = ["/orders/all"]
    changed = run_connector_sync(db, connector, actor_id=user_id)
    assert changed.summary["imported"] == 1
    assert (_count(versions_sql, project_ids), _count(reports_sql, project_ids)) == (4, 1)
    [report] = db.execute_query(
        "SELECT change_model_json FROM apiome.change_reports WHERE project_id = %s::uuid",
        (str(rows["orders"]["project_id"]),),
    )
    model = report["change_model_json"]
    assert model["noChanges"] is False and model["classifiedChanges"]["counts"]["total"] == 2

    fake.token = "kpat_revoked"
    revoked = run_connector_sync(db, connector, actor_id=user_id)
    assert revoked.status == "failed" and revoked.error_class == "auth" and revoked.http_status == 401
    assert store.get_connector(db, tenant_id, str(connector["id"]))["status"] == "failing"
