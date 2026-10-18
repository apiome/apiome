"""The Azure API Management connector end to end against a real Postgres and import pipeline (CDG-1.4).

The fake Azure (``tests/azure_apim_fake.py``) stands in for Entra ID, ARM and the export links;
everything after it is real: the V281/V282 store, the in-process FMT-7.2 catalog import of the
fetched archive, the captured source and the project tags. Covers the acceptance criteria as a tenant
sees them: the two HTTP APIs become two catalog items whose canonical model (rebuilt from the captured
source, as the catalog does) equals a direct FMT-7.2 import of the same archive, the non-current
revision stays ``discovered``, products become tags, and a re-sync of unchanged APIs imports nothing.
Skips itself when no database with V282 (and a tenant member) exists.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Iterator

import pytest
from azure_apim_fake import CLIENT_SECRET, SCOPE, FakeAzure
from catalog_connector_fakes import restore_builtin_sources

from app import azure_apim_connector_source as azure
from app import catalog_connector_store as store
from app import import_source_pipeline
from app.azure_apim_import_source import AzureApimImportSource
from app.catalog_connector_sync import register_connector_source, run_connector_sync
from app.catalog_parsed_model import reconstruct_catalog_api
from app.config import settings
from app.database import db
from app.import_source import canonical_fingerprint
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
    if not settings.mcp_credential_encryption_keys:
        key = base64.b64encode(os.urandom(32)).decode()
        monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "ssrf_allow_private", True)
    tenant_id, user_id = str(member[0]["tenant_id"]), str(member[0]["user_id"])
    fake = FakeAzure()
    register_connector_source(
        azure.KIND,
        lambda c, creds: azure.AzureApimSource(c, creds, transport=fake.transport()),
        scope_validator=azure.validate_azure_scope,
    )
    created = store.create_connector(
        db,
        tenant_id,
        kind=azure.KIND,
        name=f"live-azure-{uuid.uuid4().hex[:8]}",
        base_url=None,
        scope=dict(SCOPE),
        refresh_interval_seconds=None,
        conflict_policy="hold-for-review",
        status="active",
        created_by=user_id,
    )
    connector_id = str(created["id"])
    sealed, version = seal_credential_payload({"clientSecret": CLIENT_SECRET})
    store.put_credentials(db, connector_id, encrypted_payload=sealed, key_version=version, created_by=user_id)
    try:
        yield tenant_id, user_id, fake, store.get_connector(db, tenant_id, connector_id)
    finally:
        for row in store.list_item_rows(db, connector_id):
            if row.get("project_id"):
                db._execute_write("DELETE FROM apiome.projects WHERE id = %s::uuid", (str(row["project_id"]),))
        db._execute_write("DELETE FROM apiome.catalog_connectors WHERE id = %s::uuid", (connector_id,))
        restore_builtin_sources()


def test_azure_sync_end_to_end(live):
    tenant_id, user_id, fake, connector = live
    first = run_connector_sync(db, connector, actor_id=user_id)
    assert first.status == "succeeded", first.error_message
    assert first.summary["imported"] == 2 and first.summary["discovered"] == 1

    adapter = AzureApimImportSource()
    rows = {r["remote_id"]: r for r in store.list_item_rows(db, str(connector["id"]))}
    assert rows["contoso-apim/orders-api;rev=1"]["status"] == "discovered"
    source = azure.AzureApimSource(connector, {"clientSecret": CLIENT_SECRET}, transport=fake.transport())
    candidates = {c.remote_id: c for c in source.list_candidates()}
    for remote_id in ("contoso-apim/orders-api", "contoso-apim/billing-api"):
        row = rows[remote_id]
        item = db.get_catalog_item_by_id(str(row["project_id"]), tenant_id)
        assert item["source_format"] == "azure-apim" and item["publishable"] is False
        assert item["format_metadata"]["inputKind"] == "connector"
        document = source.fetch(candidates[remote_id])
        intake = import_source_pipeline._resolve_intake(
            {"document_base64": base64.standard_b64encode(document.content).decode(), "filename": document.filename}, {}
        )
        direct = adapter.normalize(adapter.parse_fileset(intake.fileset, source_label=document.filename))
        rebuilt = reconstruct_catalog_api(item)
        assert rebuilt is not None
        assert canonical_fingerprint(rebuilt) == canonical_fingerprint(direct)

    tags = {t["name"] for t in db.get_tags_for_project(str(rows["contoso-apim/orders-api"]["project_id"]))}
    assert tags == {"Starter", "Unlimited"}

    again = run_connector_sync(db, connector, actor_id=user_id)
    assert again.summary["imported"] == 0 and again.summary["unchanged"] == 2
