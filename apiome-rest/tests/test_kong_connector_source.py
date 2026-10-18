"""The Kong connector sources (CDG-1.2, #5953).

A fake Kong (``tests/kong_fake.py``) serves the fixture control plane — 3 services, 7 routes,
4 plugins, 1 consumer — in small pages, and the real sources run through
:func:`app.catalog_connector_sync.run_connector_sync` over the in-memory store. Covers the
acceptance criteria: 3 catalog items byte-identical to the equivalent declarative files, a
re-sync with one route changed importing exactly one new revision, an unmodeled plugin listed in
the loss ledger, and a revoked token producing a ``failing`` run with Kong's 401.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml
from catalog_connector_fakes import FakeConnectorStore, FakeDb
from kong_fake import ADMIN_TOKEN, FIXTURES, KONNECT_TOKEN, FakeKong

from app import kong_connector_source as kong
from app.catalog_connector_sync import (
    register_connector_source,
    run_connector_sync,
    source_factory_for,
    validate_connector_scope,
)
from app.catalog_connectors import ConnectorError
from app.config import settings
from app.import_preview_manifest import CoverageClass, build_import_preview_manifest, paginate_import_preview_manifest
from app.kong_import_source import KongImportSource
from app.mcp_credential_crypto import seal_credential_payload

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = "33333333-3333-4333-8333-333333333333"
DECLARATIVE = FIXTURES / "declarative"
SERVICE_NAMES = ("billing", "orders", "users")


class _Importer:
    """Records every document the engine imports and hands back one catalog item per service."""

    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, connector, candidate, document, item_row, actor_id):
        self.calls.append({"candidate": candidate, "document": document, "prior": item_row.get("project_id")})
        return item_row.get("project_id") or f"proj-{candidate.name}"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    # The fake Kong lives at a made-up host; the guard's address rule is covered separately.
    monkeypatch.setattr(settings, "ssrf_allow_private", True)
    yield
    register_connector_source(kong.KIND_KONNECT, kong.KongKonnectSource, scope_validator=kong.validate_konnect_scope)
    register_connector_source(kong.KIND_ADMIN, kong.KongAdminSource, scope_validator=kong.validate_admin_scope)


@pytest.fixture
def store(monkeypatch):
    return FakeConnectorStore().install(monkeypatch)


def _use_fake(fake: FakeKong) -> None:
    """Point both Kong kinds at the fake's transport (the real classes, a fake network)."""
    register_connector_source(
        kong.KIND_KONNECT,
        lambda c, creds: kong.KongKonnectSource(c, creds, transport=fake.transport()),
        scope_validator=kong.validate_konnect_scope,
    )
    register_connector_source(
        kong.KIND_ADMIN,
        lambda c, creds: kong.KongAdminSource(c, creds, transport=fake.transport()),
        scope_validator=kong.validate_admin_scope,
    )


def _konnect(store: FakeConnectorStore, fake: FakeKong, *, token: str = KONNECT_TOKEN, scope=None):
    connector = store.add_connector(
        TENANT,
        kind=kong.KIND_KONNECT,
        name="Konnect EU",
        base_url="https://konnect.example.test",
        scope=scope if scope is not None else {"region": "eu", "controlPlanes": [fake.control_plane["id"]]},
        created_by=ACTOR,
    )
    if token:
        sealed, version = seal_credential_payload({"token": token})
        store.credentials[connector["id"]] = {"encrypted_payload": sealed, "key_version": version}
    return connector


def _sync(store, connector, importer=None):
    db = FakeDb()
    importer = importer or _Importer()
    result = run_connector_sync(db, store.connectors[connector["id"]], actor_id=ACTOR, importer=importer)
    return result, importer, db


def _ledger(content: bytes):
    adapter = KongImportSource()
    model = adapter.normalize(adapter.parse(content.decode("utf-8"), source_label="svc.kong.yaml"))
    page = paginate_import_preview_manifest(build_import_preview_manifest(model, adapter_key="kong", options={}))
    return model, {row.source_construct: row for row in page.coverage}


# --- the acceptance criteria -------------------------------------------------------------


def test_konnect_sync_yields_three_items_byte_identical_to_the_declarative_files(store):
    fake = FakeKong()
    _use_fake(fake)
    connector = _konnect(store, fake)
    result, importer, _ = _sync(store, connector)

    assert result.status == "succeeded" and result.summary["imported"] == 3
    assert len(importer.calls) == 3
    by_name = {call["candidate"].name: call["document"] for call in importer.calls}
    assert sorted(by_name) == list(SERVICE_NAMES)
    for name in SERVICE_NAMES:
        document = by_name[name]
        expected = (DECLARATIVE / f"{name}.kong.yaml").read_bytes()
        assert document.content == expected, f"{name}: synced document differs from the declarative file"
        assert document.import_kind == "kong" and document.filename == f"{name}.kong.yaml"
        # Same bytes, same import: the canonical models are identical.
        synced_model, _ = _ledger(document.content)
        file_model, _ = _ledger(expected)
        assert synced_model.model_dump() == file_model.model_dump()

    # Every collection was paged through Kong's offset token, never fetched in one go.
    offsets = [params.get("offset") for _, path, params in fake.requests if path.endswith("/routes")]
    assert offsets == [None, "2", "4", "6"]
    assert all(header == f"Bearer {KONNECT_TOKEN}" for header in fake.auth_headers)


def test_each_service_records_deployment_metadata_and_suggested_owners(store):
    fake = FakeKong()
    _use_fake(fake)
    connector = _konnect(store, fake)
    _sync(store, connector)
    rows = {row["remote_name"]: row for row in store.items.values()}
    billing = rows["billing"]
    plane = fake.control_plane
    assert billing["remote_id"] == f"{plane['id']}:a1000000-0000-4000-8000-000000000001"
    assert billing["environment"] == "prod-eu"
    assert billing["hosts"] == ["api.example.com"] and billing["base_path"] == "/billing/invoices"
    deployment = billing["deployment"]
    assert deployment["controlPlaneId"] == plane["id"] and deployment["controlPlaneName"] == "prod-eu"
    assert deployment["tags"] == ["owner:payments", "tier:gold"] and deployment["enabled"] is True
    assert deployment["protocols"] == ["https"] and deployment["routeCount"] == 2
    assert deployment["paths"] == ["/billing/invoices", "~/billing/invoices/(?<invoice_id>[^/]+)$"]
    assert deployment["suggestedOwners"] == [
        {"team": "payments", "source": "gateway_tag", "sourceRef": "owner:payments"}
    ]
    assert rows["orders"]["deployment"]["suggestedOwners"][0]["team"] == "commerce"
    assert rows["users"]["deployment"]["suggestedOwners"] == []


def test_resync_with_one_route_changed_imports_exactly_one_new_revision(store):
    fake = FakeKong()
    _use_fake(fake)
    connector = _konnect(store, fake)
    first, _, _ = _sync(store, connector)
    assert first.summary["imported"] == 3

    unchanged, importer, _ = _sync(store, connector)
    assert unchanged.summary["imported"] == 0 and unchanged.summary["unchanged"] == 3
    assert importer.calls == []

    route = next(r for r in fake.entities["routes"] if r["name"] == "orders-list")
    route["paths"] = ["/orders/all"]
    route["updated_at"] += 60
    changed, importer, _ = _sync(store, connector)
    assert changed.status == "succeeded"
    assert changed.summary["imported"] == 1 and changed.summary["unchanged"] == 2
    [call] = importer.calls
    assert call["candidate"].name == "orders" and call["prior"] == "proj-orders"
    assert b"/orders/all" in call["document"].content
    orders_row = next(r for r in store.items.values() if r["remote_name"] == "orders")
    assert orders_row["imported_revision"] == call["candidate"].revision


def test_a_plugin_the_adapter_does_not_model_is_in_the_loss_ledger(store):
    fake = FakeKong()
    _use_fake(fake)
    connector = _konnect(store, fake)
    _, importer, _ = _sync(store, connector)
    documents = {call["candidate"].name: call["document"].content for call in importer.calls}

    _, users = _ledger(documents["users"])
    row = users["gateway#plugin.acme-audit-trail.service"]
    assert row.coverage is CoverageClass.PARTIALLY_MAPPED and "acme-audit-trail" in row.detail
    assert users["gateway#plugin.correlation-id.global"].coverage is CoverageClass.PARTIALLY_MAPPED

    _, orders = _ledger(documents["orders"])
    assert orders["gateway#plugin.rate-limiting.route"].coverage is CoverageClass.PARTIALLY_MAPPED

    _, billing = _ledger(documents["billing"])
    # An auth plugin is modeled (canonical security, inferred), so it is not a loss row.
    assert billing["gateway#auth.key-auth"].coverage is CoverageClass.INFERRED
    assert "gateway#plugin.key-auth.service" not in billing


def test_a_revoked_token_fails_the_run_with_kongs_401(store, caplog):
    fake = FakeKong()
    _use_fake(fake)
    connector = _konnect(store, fake)
    _sync(store, connector)
    fake.token = "kpat_ROTATED_new_token_value"

    result, importer, db = _sync(store, connector)
    assert result.status == "failed" and result.connector_status == "failing"
    assert result.error_class == "auth" and result.http_status == 401
    assert "Unauthorized: Invalid credentials" in (result.error_message or "")
    assert KONNECT_TOKEN not in (result.error_message or "")
    assert importer.calls == [] and result.summary["candidates"] == 0
    assert store.connectors[connector["id"]]["status"] == "failing"
    run = store.runs[result.run_id]
    assert run["status"] == "failed" and run["error_class"] == "auth" and run["http_status"] == 401
    assert KONNECT_TOKEN not in json.dumps(db.audits, default=str)
    assert KONNECT_TOKEN not in caplog.text
    # Nothing was marked missing: a failed listing is not an empty inventory.
    assert all(row["status"] == "imported" for row in store.items.values())


# --- findings ----------------------------------------------------------------------------


def test_a_route_without_a_service_is_a_connector_level_finding(store):
    fake = FakeKong()
    fake.entities["routes"].append(
        {
            "id": "b2000000-0000-4000-8000-0000000000ff",
            "name": "orphan-health",
            "protocols": ["https"],
            "methods": ["GET"],
            "paths": ["/health"],
            "service": None,
            "created_at": 1780002000,
            "updated_at": 1790002000,
        }
    )
    _use_fake(fake)
    connector = _konnect(store, fake)
    result, importer, _ = _sync(store, connector)
    assert result.status == "succeeded" and len(importer.calls) == 3
    findings = [f for f in result.summary["findings"] if f["code"] == "route-without-service"]
    assert findings == [
        {
            "code": "route-without-service",
            "severity": "warning",
            "controlPlaneId": fake.control_plane["id"],
            "controlPlaneName": "prod-eu",
            "routeId": "b2000000-0000-4000-8000-0000000000ff",
            "routeName": "orphan-health",
            "paths": ["/health"],
            "message": findings[0]["message"],
        }
    ]
    assert all(b"/health" not in call["document"].content for call in importer.calls)
    assert result.summary["findingsTotal"] == len(result.summary["findings"])


def test_malformed_owner_tags_and_consumer_plugins_are_findings():
    entities = kong.KongEntities(
        services=[{"id": "s1", "name": "svc", "tags": ["owner:Payments", "owner:not a slug!", "owner:payments"]}],
        routes=[{"id": "r1", "name": "r", "paths": ["/a"], "service": {"id": "s1"}}],
        plugins=[{"id": "p1", "name": "rate-limiting", "consumer": {"id": "c1"}, "config": {}}],
        consumers=[{"id": "c1", "username": "app"}],
    )
    inventory, findings = kong.build_service_inventory(
        entities, remote_prefix=None, environment=None, location={"workspace": "ws"}
    )
    [entry] = inventory
    # Case folds to one slug; the malformed tag is a finding, never a suggestion.
    assert entry.candidate.deployment["suggestedOwners"] == [
        {"team": "payments", "source": "gateway_tag", "sourceRef": "owner:Payments"}
    ]
    codes = sorted(f["code"] for f in findings)
    assert codes == ["consumer-plugins-not-imported", "consumers-not-imported", "owner-tag-invalid"]
    assert next(f for f in findings if f["code"] == "owner-tag-invalid")["tag"] == "owner:not a slug!"
    # A consumer-scoped plugin configures a caller and is not part of the service document.
    assert b"rate-limiting" not in entry.document


def test_secret_plugin_config_is_redacted_before_the_document_is_built():
    entities = kong.KongEntities(
        services=[{"id": "s1", "name": "svc"}],
        routes=[{"id": "r1", "name": "r", "paths": ["/a"], "service": {"id": "s1"}}],
        plugins=[
            {
                "id": "p1",
                "name": "openid-connect",
                "service": {"id": "s1"},
                "config": {"client_id": ["app"], "client_secret": ["s3cr3t-value"], "issuer": "https://idp"},
            }
        ],
    )
    [entry], _ = kong.build_service_inventory(entities, remote_prefix=None, environment=None, location={})
    assert b"s3cr3t-value" not in entry.document
    assert yaml.safe_load(entry.document)["services"][0]["plugins"][0]["config"]["client_secret"] == ["***"]


def test_the_document_digest_ignores_entity_order():
    entities = kong.KongEntities(
        services=[{"id": "s1", "name": "svc"}],
        routes=[
            {"id": "r1", "name": "a", "paths": ["/a"], "service": {"id": "s1"}},
            {"id": "r2", "name": "b", "paths": ["/b"], "service": {"id": "s1"}},
        ],
    )
    [first], _ = kong.build_service_inventory(entities, remote_prefix=None, environment=None, location={})
    entities.routes.reverse()
    [second], _ = kong.build_service_inventory(entities, remote_prefix=None, environment=None, location={})
    assert first.document == second.document and first.candidate.revision == second.candidate.revision


# --- Konnect specifics -------------------------------------------------------------------


def test_konnect_without_control_planes_syncs_every_control_plane_the_token_reads(store):
    fake = FakeKong()
    _use_fake(fake)
    connector = _konnect(store, fake, scope={"region": "eu"})
    result, importer, _ = _sync(store, connector)
    assert result.status == "succeeded" and len(importer.calls) == 3
    assert ("GET", "/v2/control-planes", {"page[size]": "100", "page[number]": "1"}) in fake.requests


def test_konnect_without_a_token_fails_as_misconfigured(store):
    fake = FakeKong()
    _use_fake(fake)
    connector = _konnect(store, fake, token="")
    result, _, _ = _sync(store, connector)
    assert result.status == "failed" and result.error_class == "invalid-configuration"
    assert fake.requests == []


def test_an_unknown_control_plane_fails_with_kongs_404(store):
    fake = FakeKong()
    _use_fake(fake)
    connector = _konnect(store, fake, scope={"controlPlanes": ["no-such-plane"]})
    result, _, _ = _sync(store, connector)
    assert result.status == "failed" and result.error_class == "not-found" and result.http_status == 404
    assert "control plane not found" in result.error_message


def test_konnect_defaults_to_the_regions_host():
    source = kong.KongKonnectSource(
        {"id": "c", "kind": kong.KIND_KONNECT, "scope": {"region": "au"}}, {"token": KONNECT_TOKEN}
    )
    http = source._http()
    try:
        assert http._base == "https://au.api.konghq.com"
    finally:
        http.close()
    assert source.describe() == {"kind": kong.KIND_KONNECT, "connectorId": "c", "region": "au", "controlPlanes": []}


# --- Admin API ---------------------------------------------------------------------------


def test_admin_api_sync_reads_the_workspace_with_the_rbac_header(store):
    fake = FakeKong(token=ADMIN_TOKEN, workspace="team-a")
    _use_fake(fake)
    connector = store.add_connector(
        TENANT,
        kind=kong.KIND_ADMIN,
        name="Self-managed",
        base_url="https://kong-admin.example.test:8444",
        scope={"workspace": "team-a", "environment": "staging"},
        created_by=ACTOR,
    )
    sealed, version = seal_credential_payload({"token": ADMIN_TOKEN})
    store.credentials[connector["id"]] = {"encrypted_payload": sealed, "key_version": version}
    result, importer, _ = _sync(store, connector)
    assert result.status == "succeeded" and len(importer.calls) == 3
    assert {path for _, path, _ in fake.requests} == {
        "/team-a/services",
        "/team-a/routes",
        "/team-a/plugins",
        "/team-a/consumers",
    }
    assert set(fake.auth_headers) == {ADMIN_TOKEN}
    row = next(r for r in store.items.values() if r["remote_name"] == "billing")
    assert row["remote_id"] == "team-a:a1000000-0000-4000-8000-000000000001"
    assert row["environment"] == "staging" and row["deployment"]["workspace"] == "team-a"
    # The Admin API document is the same declarative file as the Konnect one.
    by_name = {call["candidate"].name: call["document"].content for call in importer.calls}
    assert by_name["billing"] == (DECLARATIVE / "billing.kong.yaml").read_bytes()


def test_admin_api_revoked_token_fails_with_the_admin_message(store):
    fake = FakeKong(token=ADMIN_TOKEN)
    _use_fake(fake)
    connector = store.add_connector(
        TENANT, kind=kong.KIND_ADMIN, name="Open admin", base_url="https://kong-admin.example.test", scope={}
    )
    result, _, _ = _sync(store, connector)
    assert result.status == "failed" and result.error_class == "auth" and result.http_status == 401
    assert "Invalid RBAC Token" in result.error_message
    assert set(fake.auth_headers) == {None}


def test_admin_api_without_a_base_url_fails_as_misconfigured(store):
    connector = store.add_connector(TENANT, kind=kong.KIND_ADMIN, name="No URL", base_url=None, scope={})
    result, _, _ = _sync(store, connector)
    assert result.status == "failed" and result.error_class == "invalid-configuration"


def test_a_private_address_is_refused_by_the_guard_on_every_request(store, monkeypatch):
    monkeypatch.setattr(settings, "ssrf_allow_private", False)
    fake = FakeKong(token=ADMIN_TOKEN)
    _use_fake(fake)
    connector = store.add_connector(
        TENANT, kind=kong.KIND_ADMIN, name="Private", base_url="http://10.0.0.5:8001", scope={}
    )
    result, _, _ = _sync(store, connector)
    assert result.status == "failed" and result.error_class == "address-refused"
    assert fake.requests == []


# --- scope validation --------------------------------------------------------------------


@pytest.mark.parametrize(
    "kind,scope",
    [
        ("kong-konnect", {}),
        ("kong-konnect", {"region": "eu", "controlPlanes": ["cp-1", "cp-2"]}),
        ("kong-admin", {}),
        ("kong-admin", {"workspace": "team-a", "environment": "prod"}),
    ],
)
def test_valid_kong_scopes_pass(kind, scope):
    validate_connector_scope(kind, scope, None)


@pytest.mark.parametrize(
    "kind,scope,fragment",
    [
        ("kong-konnect", {"region": "mars"}, "region"),
        ("kong-konnect", {"controlPlanes": "cp-1"}, "controlPlanes"),
        ("kong-konnect", {"controlPlanes": [""]}, "controlPlanes"),
        ("kong-konnect", {"workspace": "x"}, "Unknown"),
        ("kong-admin", {"workspace": "a/b"}, "workspace"),
        ("kong-admin", {"environment": 3}, "environment"),
        ("kong-admin", {"region": "us"}, "Unknown"),
    ],
)
def test_invalid_kong_scopes_are_refused(kind, scope, fragment):
    with pytest.raises(ConnectorError) as info:
        validate_connector_scope(kind, scope, None)
    assert info.value.code == "connector-invalid" and fragment in str(info.value)


def test_both_kong_kinds_are_syncable_out_of_the_box():
    assert source_factory_for("kong-konnect") is kong.KongKonnectSource
    assert source_factory_for("kong-admin") is kong.KongAdminSource


def test_the_fixture_matches_the_acceptance_shape():
    entities = json.loads(Path(FIXTURES / "konnect_entities.json").read_text())
    assert (len(entities["services"]), len(entities["routes"]), len(entities["plugins"])) == (3, 7, 4)
