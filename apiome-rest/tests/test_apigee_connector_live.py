"""The Apigee connector end to end against a real Postgres and import pipeline (CDG-1.5).

The fake Google (``tests/apigee_fake.py``) stands in for the token endpoint and the Apigee
Management API; everything after it is real: the store, the in-process FMT-7.3 import of each bundle
through archive intake, the captured source and the shared catalog item. Covers the acceptance
criteria as a tenant sees them: ``orders-v2`` deployed to ``test`` and ``prod`` at revisions 5 and 3
is **one** catalog item holding both revisions, ``store-v1``'s target-less route rule is a declared
condition on its item (rebuilt from the captured bundle), and a re-sync imports nothing. Skips
itself when no database with V283 (and a tenant member) exists.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Iterator

import pytest
from apigee_fake import ORG, FakeGoogle
from catalog_connector_fakes import restore_builtin_sources
from test_apigee_connector_source import SA_JSON

from app import apigee_connector_source as apigee
from app import catalog_connector_store as store
from app.catalog_connector_sync import register_connector_source, run_connector_sync
from app.catalog_parsed_model import reconstruct_catalog_api
from app.config import settings
from app.database import db
from app.mcp_credential_crypto import seal_credential_payload


@pytest.fixture
def live(monkeypatch) -> Iterator[tuple]:
    """``(tenant_id, user_id, connector)``; deletes everything it created."""
    try:
        ready = db.execute_query(
            "SELECT 1 AS ok FROM information_schema.columns WHERE table_schema = 'apiome' "
            "AND table_name = 'catalog_connector_items' AND column_name = 'ignored_reason'"
        )
        member = db.execute_query("SELECT tenant_id, user_id FROM apiome.tenant_users LIMIT 1")
    except Exception as exc:  # noqa: BLE001 - no database at all
        pytest.skip(f"no live Postgres: {exc}")
    if not ready or not member:
        pytest.skip("V283 not applied or no tenant member in the local database")
    if not settings.mcp_credential_encryption_keys:
        monkeypatch.setattr(
            settings, "mcp_credential_encryption_keys", json.dumps({"1": base64.b64encode(os.urandom(32)).decode()})
        )
    monkeypatch.setattr(settings, "ssrf_allow_private", True)
    tenant_id, user_id = str(member[0]["tenant_id"]), str(member[0]["user_id"])
    fake = FakeGoogle()
    register_connector_source(
        apigee.KIND,
        lambda c, creds: apigee.ApigeeSource(c, creds, transport=fake.transport()),
        scope_validator=apigee.validate_apigee_scope,
    )
    created = store.create_connector(
        db,
        tenant_id,
        kind=apigee.KIND,
        name=f"live-apigee-{uuid.uuid4().hex[:8]}",
        base_url=None,
        scope={"organization": ORG},
        refresh_interval_seconds=None,
        conflict_policy="hold-for-review",
        status="active",
        created_by=user_id,
    )
    connector_id = str(created["id"])
    sealed, version = seal_credential_payload({"credentialJson": SA_JSON})
    store.put_credentials(db, connector_id, encrypted_payload=sealed, key_version=version, created_by=user_id)
    try:
        yield tenant_id, user_id, store.get_connector(db, tenant_id, connector_id)
    finally:
        for project_id in {str(r["project_id"]) for r in store.list_item_rows(db, connector_id) if r.get("project_id")}:
            db._execute_write("DELETE FROM apiome.projects WHERE id = %s::uuid", (project_id,))
        db._execute_write("DELETE FROM apiome.catalog_connectors WHERE id = %s::uuid", (connector_id,))
        restore_builtin_sources()


def test_apigee_sync_end_to_end(live):
    tenant_id, user_id, connector = live
    first = run_connector_sync(db, connector, actor_id=user_id)
    assert first.status == "succeeded", first.error_message
    assert first.summary["imported"] == 3 and first.summary["discovered"] == 1

    rows = {r["remote_id"]: r for r in store.list_item_rows(db, str(connector["id"]))}
    prod, test = rows[f"{ORG}/orders-v2/prod"], rows[f"{ORG}/orders-v2/test"]
    assert prod["project_id"] == test["project_id"]
    versions = db.execute_query(
        "SELECT version_id FROM apiome.versions WHERE project_id = %s::uuid AND deleted_at IS NULL ORDER BY version_id",
        (str(prod["project_id"]),),
    )
    assert [v["version_id"] for v in versions] == ["3", "5"]
    assert (prod["environment"], prod["remote_revision"], test["environment"], test["remote_revision"]) == (
        "prod",
        "3",
        "test",
        "5",
    )

    item = db.get_catalog_item_by_id(str(rows[f"{ORG}/store-v1/test"]["project_id"]), tenant_id)
    assert item["source_format"] == "apigee"
    rebuilt = reconstruct_catalog_api(item)
    assert rebuilt is not None
    declared = rebuilt.extras["apigee"]["declaredConditions"]
    assert any(c["kind"] == "route-without-target" for c in declared)

    again = run_connector_sync(db, connector, actor_id=user_id)
    assert again.summary["imported"] == 0 and again.summary["unchanged"] == 3
