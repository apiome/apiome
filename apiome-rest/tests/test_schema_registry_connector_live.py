"""The schema-registry connector end to end against a real Postgres and the real import pipeline (MFI-12.3).

The fake upstream registry (``tests/schema_registry_upstream_fake.py``) stands in for Confluent;
everything after the network is real: the V281/V296 connector store, the V294/V300 subject store, the
in-process Avro import and the catalog item revisions. Covers the acceptance criteria as a tenant sees
them: subjects become mirrored subjects whose versions are catalog item revisions with the upstream
level copied; a schema id shared by two subjects is imported once; an unchanged re-sync pulls
nothing; a new upstream version adds one revision. Skips itself when no database with V300 applied
(and at least one tenant member) is reachable.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Iterator

import pytest
from catalog_connector_fakes import restore_builtin_sources

from app import catalog_connector_store as store
from app import catalog_connector_sync as sync
from app import schema_registry_connector_source as src
from app import schema_registry_store as subjects
from app.catalog_connector_sync import register_connector_source, run_connector_sync
from app.config import settings
from app.database import db
from tests.schema_registry_upstream_fake import FakeUpstreamRegistry


def _avro(name: str, *extra: str) -> str:
    fields = [{"name": "id", "type": "string"}] + [
        {"name": f, "type": ["null", "string"], "default": None} for f in extra
    ]
    return json.dumps({"type": "record", "name": name, "namespace": "live.mirror", "fields": fields})


@pytest.fixture
def live(monkeypatch) -> Iterator[tuple]:
    """``(tenant_id, fake, connector, prefix)``; deletes everything it created."""
    try:
        ready = db.execute_query(
            "SELECT 1 AS ok FROM information_schema.columns WHERE table_schema = 'apiome' "
            "AND table_name = 'schema_subject_versions' AND column_name = 'upstream_version'"
        )
        member = db.execute_query("SELECT tenant_id, user_id FROM apiome.tenant_users LIMIT 1")
    except Exception as exc:  # noqa: BLE001 - no database at all
        pytest.skip(f"no live Postgres: {exc}")
    if not ready or not member:
        pytest.skip("V300 not applied or no tenant member in the local database")
    tenant_id, user_id = str(member[0]["tenant_id"]), str(member[0]["user_id"])
    monkeypatch.setattr(settings, "ssrf_allow_private", True)
    monkeypatch.setattr(
        settings, "mcp_credential_encryption_keys", json.dumps({"1": base64.b64encode(os.urandom(32)).decode()})
    )
    monkeypatch.setattr(sync, "owner_recorder", lambda *a, **k: [])
    tag = uuid.uuid4().hex[:8]
    record = f"Order{tag}"
    fake = FakeUpstreamRegistry(
        {
            f"live-{tag}-orders-value": {
                1: {"id": 10, "schema": _avro(record)},
                2: {"id": 11, "schema": _avro(record, "note")},
            },
            f"live-{tag}-orders-copy-value": {1: {"id": 10, "schema": _avro(record)}},
        },
        subject_levels={f"live-{tag}-orders-value": "FULL"},
    )
    register_connector_source(src.KIND, lambda c, cr: src.SchemaRegistrySource(c, cr, transport=fake.transport()))
    created = store.create_connector(
        db,
        tenant_id,
        kind=src.KIND,
        name=f"live-registry-{tag}",
        base_url=fake.base_url,
        scope={},
        refresh_interval_seconds=None,
        conflict_policy="hold-for-review",
        status="active",
        created_by=user_id,
    )
    connector_id = str(created["id"])
    try:
        yield tenant_id, fake, store.get_connector(db, tenant_id, connector_id), f"live-{tag}"
    finally:
        projects = db.execute_query(
            "SELECT DISTINCT v.project_id::text AS id FROM apiome.schema_subject_versions v "
            "JOIN apiome.schema_subjects s ON s.id = v.subject_id WHERE s.source_connector_id = %s::uuid",
            (connector_id,),
        )
        db._execute_write("DELETE FROM apiome.schema_subjects WHERE source_connector_id = %s::uuid", (connector_id,))
        for row in projects or []:
            db._execute_write("DELETE FROM apiome.projects WHERE id = %s::uuid", (row["id"],))
        db._execute_write("DELETE FROM apiome.catalog_connectors WHERE id = %s::uuid", (connector_id,))
        restore_builtin_sources()


def test_a_registry_is_mirrored_into_subjects_and_catalog_revisions(live):
    tenant_id, fake, connector, prefix = live
    first = run_connector_sync(db, connector)
    assert first.status == "succeeded", first.error_message
    assert (first.summary["candidates"], first.summary["imported"], first.pull_count) == (2, 2, 3)

    orders = subjects.get_subject(db, tenant_id, f"{prefix}-orders-value")
    copy = subjects.get_subject(db, tenant_id, f"{prefix}-orders-copy-value")
    assert orders["source_ref"] == "registry:https://sr.example.test"
    assert str(orders["source_connector_id"]) == str(connector["id"])
    assert orders["compatibility_level"] == "FULL" and orders["strategy"] == "topic"
    assert copy["compatibility_level"] == "BACKWARD"

    orders_versions = subjects.list_versions(db, str(orders["id"]))
    copy_versions = subjects.list_versions(db, str(copy["id"]))
    assert [(v["upstream_version"], v["upstream_schema_id"]) for v in orders_versions] == [(1, 10), (2, 11)]
    # Upstream id 10 is held by both subjects: one schema id, one revision.
    assert copy_versions[0]["schema_id"] == orders_versions[0]["schema_id"]
    assert copy_versions[0]["version_record_id"] == orders_versions[0]["version_record_id"]

    # Every mirrored version is a revision of a catalog item that records the connector provenance.
    for version in orders_versions:
        revision = db.execute_query(
            "SELECT v.version_id, v.format_metadata, p.publishable FROM apiome.versions v "
            "JOIN apiome.projects p ON p.id = v.project_id WHERE v.id = %s::uuid",
            (str(version["version_record_id"]),),
        )[0]
        assert revision["publishable"] is False
        assert revision["format_metadata"]["connectorId"] == str(connector["id"])
        assert revision["format_metadata"]["remoteId"] in (f"{prefix}-orders-value", f"{prefix}-orders-copy-value")

    # An unchanged registry pulls nothing.
    again = run_connector_sync(db, connector)
    assert again.status == "succeeded" and again.pull_count == 0 and again.summary["unchanged"] == 2

    # A new upstream version adds exactly one revision.
    fake.subjects[f"{prefix}-orders-value"][3] = {"id": 12, "schema": _avro(f"Order{prefix[5:]}", "note", "total")}
    third = run_connector_sync(db, connector)
    assert third.status == "succeeded" and third.summary["imported"] == 1 and third.pull_count == 1
    latest = subjects.list_versions(db, str(orders["id"]))
    assert [v["upstream_version"] for v in latest] == [1, 2, 3]
    items = {row["remote_id"]: row for row in store.list_item_rows(db, str(connector["id"]))}
    assert items[f"{prefix}-orders-value"]["status"] == "imported"
    assert items[f"{prefix}-orders-value"]["project_id"] is not None
