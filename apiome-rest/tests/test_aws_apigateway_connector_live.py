"""The AWS API Gateway connector end to end against a real Postgres and import pipeline (CDG-1.3).

moto and the fixture exports stand in for AWS (``tests/aws_apigateway_fake.py``); everything
after them is real: the V281/V282 store, the in-process FMT-7.1 catalog import and the captured
source. Covers the acceptance criteria as a tenant sees them: one REST API with two stages and one
HTTP API become three catalog items, each item's canonical model (rebuilt from its captured source,
as the catalog does) equals a direct FMT-7.1 import of the same export, and a re-sync of unchanged
deployments imports nothing. Skips itself when no database with V282 (and a tenant member) exists.
"""

from __future__ import annotations

import uuid
from typing import Iterator

import pytest
from aws_apigateway_fake import EXTERNAL_ID, REGION, ROLE_ARN, moto_estate, session_factory_with
from catalog_connector_fakes import restore_builtin_sources

from app import aws_apigateway_connector_source as aws
from app import catalog_connector_store as store
from app.aws_apigateway_import_source import AwsApiGatewayImportSource
from app.catalog_connector_sync import run_connector_sync
from app.catalog_parsed_model import reconstruct_catalog_api
from app.database import db
from app.import_source import canonical_fingerprint


@pytest.fixture
def live(monkeypatch) -> Iterator[tuple]:
    """``(tenant_id, user_id, estate, connector)``; deletes everything it created."""
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
    with moto_estate(monkeypatch) as estate:
        monkeypatch.setattr(
            aws, "session_factory", session_factory_with(estate["exports"], http_deployments=estate["http_deployments"])
        )
        created = store.create_connector(
            db,
            tenant_id,
            kind=aws.KIND,
            name=f"live-aws-{uuid.uuid4().hex[:8]}",
            base_url=None,
            scope={"roleArn": ROLE_ARN, "externalId": EXTERNAL_ID, "regions": [REGION]},
            refresh_interval_seconds=None,
            conflict_policy="hold-for-review",
            status="active",
            created_by=user_id,
        )
        connector_id = str(created["id"])
        try:
            yield tenant_id, user_id, estate, store.get_connector(db, tenant_id, connector_id)
        finally:
            for row in store.list_item_rows(db, connector_id):
                if row.get("project_id"):
                    db._execute_write("DELETE FROM apiome.projects WHERE id = %s::uuid", (str(row["project_id"]),))
            db._execute_write("DELETE FROM apiome.catalog_connectors WHERE id = %s::uuid", (connector_id,))
            restore_builtin_sources()


def test_aws_sync_end_to_end(live):
    tenant_id, user_id, estate, connector = live
    first = run_connector_sync(db, connector, actor_id=user_id)
    assert first.status == "succeeded" and first.summary["imported"] == 3

    adapter = AwsApiGatewayImportSource()
    rows = store.list_item_rows(db, str(connector["id"]))
    assert sorted(r["environment"] for r in rows) == ["$default", "dev", "prod"]
    for row in rows:
        item = db.get_catalog_item_by_id(str(row["project_id"]), tenant_id)
        assert item["source_format"] == "aws-apigateway" and item["publishable"] is False
        assert item["format_metadata"]["inputKind"] == "connector"
        assert item["format_metadata"]["remoteRevision"] == row["remote_revision"]
        deployment = row["deployment"]
        exported = estate["exports"][(deployment["apiId"], deployment["stage"])]
        direct = adapter.normalize(adapter.parse(exported.decode("utf-8")))
        rebuilt = reconstruct_catalog_api(item)
        assert rebuilt is not None
        assert canonical_fingerprint(rebuilt) == canonical_fingerprint(direct)

    again = run_connector_sync(db, connector, actor_id=user_id)
    assert again.summary["imported"] == 0 and again.summary["unchanged"] == 3
    assert len(again.summary["unchangedItems"]) == 3
