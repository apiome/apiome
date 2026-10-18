"""The catalog connector sync engine (CDG-1.1, #5952).

A fake connector source drives :func:`app.catalog_connector_sync.run_connector_sync` over the
in-memory store, covering the acceptance criteria: catalog items carry the connector source
descriptor, an API that leaves the inventory is ``missing`` and never deleted, an auth failure is
a failed run with the provider's class and status (not a success with zero changes), and no
credential reaches a run, an audit row or a log line.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest
from catalog_connector_fakes import FakeConnectorStore, FakeDb, restore_builtin_sources

from app import catalog_connector_sync as sync
from app.catalog_connector_sync import (
    AUDIT_SYNC_ACTION,
    ConnectorImportError,
    ConnectorRefreshSource,
    import_document_as_catalog_item,
    process_connector_refresh_sweep,
    register_connector_source,
    run_connector_sync,
    syncable_kinds,
)
from app.catalog_connectors import CODE_KIND_UNSUPPORTED, CODE_SYNC_RUNNING, ConnectorError
from app.config import settings
from app.mcp_credential_crypto import seal_credential_payload
from app.models import SpecImportJobError, SpecImportJobResult, SpecImportJobStatus
from app.refresh_source import FetchedDocument, RefreshCandidate, RefreshSourceError
from app.repository_quota_window import METRIC_FILES_DEFERRED, METRIC_POLLS

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = "33333333-3333-4333-8333-333333333333"
SECRET = "kpat_TOPSECRET_9f8e7d6c"

_T1 = datetime(2026, 9, 1, tzinfo=timezone.utc)
_T2 = datetime(2026, 10, 1, tzinfo=timezone.utc)


class FakeGatewaySource(ConnectorRefreshSource):
    """A gateway with a settable inventory, per-API documents and failure switches."""

    inventory: List[RefreshCandidate] = []
    list_error: Optional[RefreshSourceError] = None
    fetch_errors: Dict[str, RefreshSourceError] = {}
    documents: Dict[str, bytes] = {}
    seen_credentials: List[Optional[Dict[str, str]]] = []
    fetched: List[str] = []

    def list_candidates(self):
        FakeGatewaySource.seen_credentials.append(self.credentials)
        if FakeGatewaySource.list_error is not None:
            raise FakeGatewaySource.list_error
        return list(FakeGatewaySource.inventory)

    def fetch(self, candidate):
        FakeGatewaySource.fetched.append(candidate.remote_id)
        error = FakeGatewaySource.fetch_errors.get(candidate.remote_id)
        if error is not None:
            raise error
        body = FakeGatewaySource.documents.get(candidate.remote_id, b'{"openapi": "3.0.3"}')
        return FetchedDocument(content=body, filename=f"{candidate.remote_id}.json", revision=candidate.revision)


def _api(
    remote_id: str, revision: Optional[str] = "r1", updated_at=None, name: Optional[str] = None
) -> RefreshCandidate:
    return RefreshCandidate(
        remote_id=remote_id,
        name=name or remote_id.title(),
        revision=revision,
        updated_at=updated_at,
        environment="prod",
        hosts=(f"{remote_id}.example.com",),
        base_path=f"/{remote_id}",
    )


class _Importer:
    """Records imports and returns one catalog item per remote id."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.fail_for: Dict[str, str] = {}

    def __call__(self, connector, candidate, document, item_row, actor_id):
        if candidate.remote_id in self.fail_for:
            raise ConnectorImportError(self.fail_for[candidate.remote_id])
        self.calls.append(
            {"remote_id": candidate.remote_id, "revision": document.revision, "prior": item_row.get("project_id")}
        )
        return item_row.get("project_id") or f"proj-{candidate.remote_id}"


@pytest.fixture(autouse=True)
def _source():
    FakeGatewaySource.inventory = []
    FakeGatewaySource.list_error = None
    FakeGatewaySource.fetch_errors = {}
    FakeGatewaySource.documents = {}
    FakeGatewaySource.seen_credentials = []
    FakeGatewaySource.fetched = []
    register_connector_source("kong-admin", FakeGatewaySource)
    yield
    restore_builtin_sources()


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)


@pytest.fixture
def store(monkeypatch) -> FakeConnectorStore:
    return FakeConnectorStore().install(monkeypatch)


@pytest.fixture
def db() -> FakeDb:
    return FakeDb()


@pytest.fixture
def importer() -> _Importer:
    return _Importer()


@pytest.fixture
def connector(store):
    return store.add_connector(TENANT, name="Prod gateway", created_by=ACTOR)


def _run(db, connector, importer, **kwargs):
    return run_connector_sync(db, connector, actor_id=ACTOR, importer=importer, **kwargs)


def test_first_sync_imports_every_api_as_a_catalog_item(store, db, importer, connector):
    FakeGatewaySource.inventory = [_api("orders"), _api("billing")]
    result = _run(db, connector, importer)
    assert result.status == "succeeded"
    assert result.summary["imported"] == 2 and result.pull_count == 2
    assert {c["remote_id"] for c in importer.calls} == {"orders", "billing"}
    orders = store.item(connector["id"], "orders")
    assert orders["status"] == "imported" and orders["project_id"] == "proj-orders"
    assert orders["hosts"] == ["orders.example.com"] and orders["environment"] == "prod"
    assert store.connectors[connector["id"]]["status"] == "active"


def test_an_unchanged_inventory_imports_nothing(store, db, importer, connector):
    FakeGatewaySource.inventory = [_api("orders", "r1")]
    _run(db, connector, importer)
    FakeGatewaySource.fetched = []
    second = _run(db, connector, importer)
    assert second.summary["unchanged"] == 1 and second.summary["imported"] == 0
    assert FakeGatewaySource.fetched == []  # the freshness gate ran before any fetch
    assert second.pull_count == 0


def test_a_new_remote_revision_is_a_new_revision_of_the_same_item(store, db, importer, connector):
    FakeGatewaySource.inventory = [_api("orders", "r1", _T1)]
    _run(db, connector, importer)
    FakeGatewaySource.inventory = [_api("orders", "r2", _T2)]
    FakeGatewaySource.documents["orders"] = b'{"openapi": "3.0.3", "info": {"version": "2"}}'
    result = _run(db, connector, importer)
    assert result.summary["imported"] == 1
    assert importer.calls[-1] == {"remote_id": "orders", "revision": "r2", "prior": "proj-orders"}
    assert store.item(connector["id"], "orders")["imported_revision"] == "r2"


def test_a_moved_revision_with_identical_content_reanchors_without_importing(store, db, importer, connector):
    FakeGatewaySource.inventory = [_api("orders", "r1", _T1)]
    _run(db, connector, importer)
    FakeGatewaySource.inventory = [_api("orders", "r2", _T2)]
    result = _run(db, connector, importer)
    assert result.summary == {**result.summary, "fetched": 1, "imported": 0, "unchanged": 1}
    assert len(importer.calls) == 1
    assert store.item(connector["id"], "orders")["imported_revision"] == "r2"


def test_an_api_that_leaves_the_inventory_is_missing_and_never_deleted(store, db, importer, connector):
    FakeGatewaySource.inventory = [_api("orders"), _api("billing")]
    _run(db, connector, importer)
    FakeGatewaySource.inventory = [_api("orders")]
    result = _run(db, connector, importer)
    assert result.summary["missing"] == 1
    billing = store.item(connector["id"], "billing")
    assert billing["status"] == "missing"
    assert billing["project_id"] == "proj-billing"  # the catalog item is kept
    assert len(store.list_item_rows(None, connector["id"])) == 2


def test_a_missing_api_that_returns_is_imported_again(store, db, importer, connector):
    FakeGatewaySource.inventory = [_api("orders")]
    _run(db, connector, importer)
    FakeGatewaySource.inventory = []
    _run(db, connector, importer)
    FakeGatewaySource.inventory = [_api("orders")]
    _run(db, connector, importer)
    assert store.item(connector["id"], "orders")["status"] == "imported"


def test_ignored_apis_are_never_fetched(store, db, importer, connector):
    FakeGatewaySource.inventory = [_api("orders")]
    _run(db, connector, importer)
    store.item(connector["id"], "orders")["status"] = "ignored"
    FakeGatewaySource.inventory = [_api("orders", "r9")]
    FakeGatewaySource.fetched = []
    result = _run(db, connector, importer)
    assert result.summary["ignored"] == 1 and FakeGatewaySource.fetched == []
    FakeGatewaySource.inventory = []
    _run(db, connector, importer)
    assert store.item(connector["id"], "orders")["status"] == "ignored"


def test_auth_failure_listing_is_a_failed_run_with_the_provider_class_and_status(store, db, importer, connector):
    FakeGatewaySource.list_error = RefreshSourceError("401 Unauthorized from Konnect", http_status=401)
    result = _run(db, connector, importer)
    assert result.status == "failed"
    assert (result.error_class, result.http_status) == ("auth", 401)
    run = store.runs[result.run_id]
    assert run["status"] == "failed" and run["error_class"] == "auth" and run["http_status"] == 401
    assert store.connectors[connector["id"]]["status"] == "failing"
    assert db.audits[-1]["outcome"] == "failure"


def test_zero_of_twelve_fetched_because_of_auth_is_a_failed_run_not_an_empty_success(store, db, importer, connector):
    FakeGatewaySource.inventory = [_api(f"api{i}") for i in range(12)]
    FakeGatewaySource.fetch_errors = {
        f"api{i}": RefreshSourceError("forbidden", http_status=403) for i in range(12)
    }
    result = _run(db, connector, importer)
    assert result.status == "failed"
    assert (result.error_class, result.http_status) == ("auth", 403)
    assert result.summary["candidates"] == 12 and result.summary["failed"] == 12
    assert "Fetched 0 of 12" in result.error_message
    assert store.connectors[connector["id"]]["status"] == "failing"


def test_a_partial_failure_is_a_success_that_counts_the_failures(store, db, importer, connector):
    FakeGatewaySource.inventory = [_api("orders"), _api("billing")]
    FakeGatewaySource.fetch_errors = {"billing": RefreshSourceError("rate limited", http_status=429)}
    result = _run(db, connector, importer)
    assert result.status == "succeeded"
    assert result.summary["imported"] == 1 and result.summary["failed"] == 1
    assert (result.error_class, result.http_status) == ("rate-limited", 429)


def test_every_import_refused_is_a_failed_run(store, db, importer, connector):
    FakeGatewaySource.inventory = [_api("orders")]
    importer.fail_for = {"orders": "document is not valid OpenAPI"}
    result = _run(db, connector, importer)
    assert result.status == "failed" and result.error_class == "import-failed"
    assert store.item(connector["id"], "orders")["status"] == "discovered"


def test_a_source_that_crashes_closes_the_run_as_failed(store, db, importer, connector):
    FakeGatewaySource.list_error = None

    class _Boom(FakeGatewaySource):
        def list_candidates(self):
            raise KeyError("unexpected shape")

    register_connector_source("kong-admin", _Boom)
    result = _run(db, connector, importer)
    assert result.status == "failed" and result.error_class == "unexpected"
    assert store.runs[result.run_id]["finished_at"] is not None


def test_credentials_reach_the_source_and_nothing_else(store, db, importer, connector, caplog):
    sealed, version = seal_credential_payload({"token": SECRET})
    store.put_credentials(None, connector["id"], encrypted_payload=sealed, key_version=version, created_by=ACTOR)
    FakeGatewaySource.list_error = RefreshSourceError(f"bad token {SECRET}", http_status=401)
    with caplog.at_level(logging.DEBUG):
        result = _run(db, connector, importer)
    assert FakeGatewaySource.seen_credentials == [{"token": SECRET}]
    assert SECRET not in (result.error_message or "")
    assert "[redacted]" in result.error_message
    assert SECRET not in json.dumps(store.runs, default=str)
    assert SECRET not in json.dumps(db.audits, default=str)
    assert SECRET not in caplog.text


def test_a_crashing_source_never_logs_the_credential(store, db, importer, connector, caplog):
    sealed, version = seal_credential_payload({"token": SECRET})
    store.put_credentials(None, connector["id"], encrypted_payload=sealed, key_version=version, created_by=ACTOR)

    class _Leaky(FakeGatewaySource):
        def list_candidates(self):
            raise ValueError(f"could not parse response for Authorization: Bearer {SECRET}")

    register_connector_source("kong-admin", _Leaky)
    with caplog.at_level(logging.DEBUG):
        result = _run(db, connector, importer)
    assert result.error_class == "unexpected"
    assert SECRET not in caplog.text and SECRET not in (result.error_message or "")
    assert "[redacted]" in caplog.text


def test_an_unreadable_credential_fails_the_run_without_calling_the_source(store, db, importer, connector):
    store.credentials[connector["id"]] = {"encrypted_payload": b"garbage", "key_version": 1, "replaced_at": None}
    result = _run(db, connector, importer)
    assert result.status == "failed" and result.error_class == "credentials-unreadable"
    assert FakeGatewaySource.seen_credentials == []


def test_runs_count_pulls_against_the_quota_window_and_are_audited(store, db, importer, connector):
    FakeGatewaySource.inventory = [_api("orders"), _api("billing"), _api("users")]
    result = _run(db, connector, importer, max_pulls=2)
    assert result.summary["deferred"] == 1 and result.pull_count == 2
    assert db.quota_total(METRIC_POLLS) == 2
    assert db.quota_total(METRIC_FILES_DEFERRED) == 1
    audit = db.audits[-1]
    assert audit["action"] == AUDIT_SYNC_ACTION and audit["action"].startswith("repository.")
    assert audit["detail"]["runId"] == result.run_id
    assert audit["detail"]["pullCount"] == 2


def test_a_kind_without_a_source_cannot_sync_and_opens_no_run(store, db, importer):
    other = store.add_connector(TENANT, kind="apigee")
    with pytest.raises(ConnectorError) as info:
        _run(db, other, importer)
    assert info.value.code == CODE_KIND_UNSUPPORTED
    assert store.runs == {}
    assert "apigee" not in syncable_kinds() and "kong-admin" in syncable_kinds()


def test_one_run_at_a_time(store, db, importer, connector):
    store.start_run(None, TENANT, connector["id"], trigger="manual", created_by=None)
    with pytest.raises(ConnectorError) as info:
        _run(db, connector, importer)
    assert info.value.code == CODE_SYNC_RUNNING


def test_a_paused_connector_syncs_by_hand_and_stays_paused(store, db, importer):
    paused = store.add_connector(TENANT, status="paused")
    FakeGatewaySource.inventory = [_api("orders")]
    assert _run(db, paused, importer).status == "succeeded"
    assert store.connectors[paused["id"]]["status"] == "paused"


def test_sweep_syncs_due_connectors_and_skips_paused_and_unsupported(store, db, monkeypatch):
    monkeypatch.setattr(settings, "refresh_enabled", True)
    monkeypatch.setattr(sync, "import_document_as_catalog_item", _Importer())
    monkeypatch.setattr("app.repository_refresh_quota.load_tenant_refresh_quota_tracker", lambda d: None)
    due = store.add_connector(TENANT, name="due")
    paused = store.add_connector(TENANT, name="paused", status="paused")
    other = store.add_connector(TENANT, name="apigee", kind="apigee")
    FakeGatewaySource.inventory = [_api("orders")]
    assert process_connector_refresh_sweep(db) == 1
    synced = {r["connector_id"] for r in store.runs.values()}
    assert synced == {due["id"]}
    assert paused["id"] not in synced and other["id"] not in synced
    assert next(iter(store.runs.values()))["run_summary"]["trigger"] == "scheduled"


def test_sweep_respects_the_kill_switch(store, db, monkeypatch):
    monkeypatch.setattr(settings, "refresh_enabled", False)
    store.add_connector(TENANT)
    assert process_connector_refresh_sweep(db) == 0
    assert store.runs == {}


def test_sweep_defers_a_tenant_out_of_quota(store, db, monkeypatch):
    monkeypatch.setattr(settings, "refresh_enabled", True)

    class _Spent:
        def is_exhausted(self, tenant_id):
            return True

    monkeypatch.setattr("app.repository_refresh_quota.load_tenant_refresh_quota_tracker", lambda d: _Spent())
    store.add_connector(TENANT)
    assert process_connector_refresh_sweep(db) == 0
    assert store.runs == {}
    assert db.quota_total("polls_deferred") == 1


# --- the default importer -----------------------------------------------------------


def _completed(project_id: str = "proj-9") -> SpecImportJobStatus:
    return SpecImportJobStatus(
        job_id="j",
        state="completed",
        percent=100,
        result=SpecImportJobResult(project_id=project_id, version_id="r1"),
    )


def test_default_importer_sends_a_catalog_import_with_the_connector_descriptor(monkeypatch):
    captured: Dict[str, Any] = {}

    async def _fake_run(adapter, payload, **kwargs):
        captured["adapter"] = adapter.key
        captured["payload"] = payload
        return _completed()

    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", _fake_run)
    connector = {"id": "c0ffee00-0000-4000-8000-000000000001", "tenant_id": TENANT, "kind": "kong-admin",
                 "name": "Prod", "created_by": ACTOR}
    document = FetchedDocument(content=b'{"openapi":"3.0.3"}', filename="orders.json", revision="r4")
    project_id = import_document_as_catalog_item(connector, _api("orders", "r4"), document, {}, None)
    assert project_id == "proj-9"
    payload = captured["payload"]
    assert captured["adapter"] == "openapi"
    assert payload["user_id"] == ACTOR  # a scheduled sync is attributed to the connector's creator
    assert payload["metadata"]["existing_project_id"] is None
    assert payload["metadata"]["version"] == {"version_id": "r4"}
    assert payload["metadata"]["project"]["slug"] == "orders-c0ffee00"
    assert payload["connector_source"] == {
        "inputKind": "connector",
        "connectorId": connector["id"],
        "connectorKind": "kong-admin",
        "connectorName": "Prod",
        "remoteId": "orders",
        "remoteRevision": "r4",
        "remoteName": "Orders",
    }
    assert base64.standard_b64decode(payload["document_base64"]) == b'{"openapi":"3.0.3"}'


def test_default_importer_adds_a_revision_to_a_live_catalog_item_only(monkeypatch):
    captured: Dict[str, Any] = {}

    async def _fake_run(adapter, payload, **kwargs):
        captured["payload"] = payload
        return _completed("proj-1")

    projects = {
        "proj-1": {"id": "proj-1", "publishable": False, "deleted_at": None},
        "proj-converted": {"id": "proj-converted", "publishable": True, "deleted_at": None},
    }
    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", _fake_run)
    monkeypatch.setattr("app.database.db.get_project_by_id", lambda pid, tid: projects.get(pid))
    connector = {"id": "c1", "tenant_id": TENANT, "kind": "kong-admin", "name": "P", "created_by": ACTOR}
    document = FetchedDocument(content=b"{}", filename="o.json")
    import_document_as_catalog_item(connector, _api("o"), document, {"project_id": "proj-1"}, ACTOR)
    assert captured["payload"]["metadata"]["existing_project_id"] == "proj-1"
    import_document_as_catalog_item(connector, _api("o"), document, {"project_id": "proj-converted"}, ACTOR)
    assert captured["payload"]["metadata"]["existing_project_id"] is None


def test_default_importer_surfaces_a_failed_import(monkeypatch):
    async def _fake_run(adapter, payload, **kwargs):
        return SpecImportJobStatus(
            job_id="j",
            state="failed",
            percent=10,
            error=SpecImportJobError(
                code="PARSE_ERROR", category="input", message="bad document", remediation="Fix it.", retriable=False
            ),
        )

    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", _fake_run)
    connector = {"id": "c1", "tenant_id": TENANT, "kind": "kong-admin", "name": "P", "created_by": ACTOR}
    with pytest.raises(ConnectorImportError, match="bad document"):
        import_document_as_catalog_item(connector, _api("o"), FetchedDocument(content=b"x", filename="o"), {}, ACTOR)
    with pytest.raises(ConnectorImportError, match="No importer"):
        import_document_as_catalog_item(
            connector, _api("o"), FetchedDocument(content=b"x", filename="o", import_kind="nope-format"), {}, ACTOR
        )


def test_default_importer_writes_a_change_report_when_it_adds_a_revision(monkeypatch):
    async def _fake_run(adapter, payload, **kwargs):
        return SpecImportJobStatus(
            job_id="j",
            state="completed",
            percent=100,
            result=SpecImportJobResult(project_id="proj-1", version_id="r2", version_record_id="ver-2"),
        )

    reports: List[Dict[str, Any]] = []
    looked_up: List[tuple] = []

    def _version_by_label(project_id, label, tenant_id):
        looked_up.append((project_id, label, tenant_id))
        return {"id": "ver-1"} if label == "r1" else None

    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", _fake_run)
    monkeypatch.setattr(
        "app.database.db.get_project_by_id", lambda pid, tid: {"id": pid, "publishable": False, "deleted_at": None}
    )
    monkeypatch.setattr("app.database.db.get_version_by_version_id", _version_by_label)
    monkeypatch.setattr(
        "app.catalog_revision_change_report.generate_catalog_revision_change_report",
        lambda **kwargs: reports.append(kwargs),
    )
    connector = {"id": "c1", "tenant_id": TENANT, "kind": "kong-admin", "name": "P", "created_by": ACTOR}
    document = FetchedDocument(content=b"{}", filename="o.json", revision="r2")
    row = {"project_id": "proj-1", "imported_revision": "r1"}
    assert import_document_as_catalog_item(connector, _api("o", "r2"), document, row, None) == "proj-1"
    assert looked_up == [("proj-1", "r1", TENANT)]
    assert reports == [
        {
            "tenant_id": TENANT,
            "project_id": "proj-1",
            "revision_version_id": "ver-2",
            "parent_version_id": "ver-1",
            "actor_id": ACTOR,
        }
    ]

    # A first import (no prior revision) writes no report.
    reports.clear()
    import_document_as_catalog_item(connector, _api("o", "r2"), document, {}, ACTOR)
    assert reports == []
