"""The schema-registry discovery connector (MFI-12.3, #3784).

A fake upstream registry (:mod:`tests.schema_registry_upstream_fake`, an ``httpx.MockTransport`` in
Confluent, Karapace and Apicurio flavours) is crawled by the real
:class:`app.schema_registry_connector_source.SchemaRegistrySource` through
:func:`app.catalog_connector_sync.run_connector_sync`, over the in-memory connector store, the
in-memory subject store and a stand-in import pipeline (:mod:`tests.schema_registry_fakes`). Schemas
are parsed and fingerprinted by the real Avro and JSON Schema import sources; no network is used.

Covers the acceptance criteria: a registry is crawled; each subject becomes a mirrored subject backed
by a catalog item with one revision per version; the compatibility level is copied; schemas are
deduplicated by upstream schema id; the naming strategy is recorded.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List, Optional

import pytest
from catalog_connector_fakes import FakeConnectorStore, FakeDb, restore_builtin_sources

from app import catalog_connector_sync as sync
from app import schema_registry_connector_source as src
from app.catalog_connector_routes import _item_out
from app.catalog_connector_sync import (
    dry_run_connector,
    register_connector_source,
    run_connector_sync,
    source_factory_for,
    syncable_kinds,
    validate_connector_scope,
)
from app.catalog_connectors import ConnectorError
from app.config import settings
from app.mcp_credential_crypto import seal_credential_payload
from app.schema_registry import SchemaRegistryError
from tests.schema_registry_fakes import FakeCatalog, FakeStore
from tests.schema_registry_upstream_fake import APICURIO, KARAPACE, FakeUpstreamRegistry

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = "33333333-3333-4333-8333-333333333333"


def _avro(name: str, namespace: Optional[str] = "acme", extra: Optional[List[Dict[str, Any]]] = None) -> str:
    fields = [{"name": "id", "type": "string"}] + list(extra or [])
    doc: Dict[str, Any] = {"type": "record", "name": name, "fields": fields}
    if namespace:
        doc["namespace"] = namespace
    return json.dumps(doc)


ORDER_V1 = _avro("Order")
ORDER_V2 = _avro("Order", extra=[{"name": "total", "type": ["null", "double"], "default": None}])
CUSTOMER = _avro("Customer")
PAYMENT = _avro("Payment")
PERSON = json.dumps(
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Person",
        "type": "object",
        "properties": {"name": {"type": "string"}},
    }
)


def _registry_subjects() -> Dict[str, Dict[int, Dict[str, Any]]]:
    """Four subjects, one per naming strategy, and one schema id shared by two subjects."""
    return {
        "orders-value": {1: {"id": 10, "schema": ORDER_V1}, 2: {"id": 11, "schema": ORDER_V2}},
        "orders-archive-value": {1: {"id": 10, "schema": ORDER_V1}},
        "acme.Customer": {1: {"id": 20, "schema": CUSTOMER}},
        "payments-acme.Payment": {1: {"id": 30, "schema": PAYMENT}},
    }


class MirrorDb(FakeCatalog, FakeDb):
    """The catalog (items, revisions, import pipeline) plus the engine's audit and quota calls."""

    def __init__(self) -> None:
        FakeCatalog.__init__(self)
        FakeDb.__init__(self)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "ssrf_allow_private", True)
    monkeypatch.setattr(sync, "owner_recorder", lambda *a, **k: [])
    monkeypatch.setattr("app.gateway_config_store.refresh_gateway_configs", lambda *a, **k: 0)
    yield
    restore_builtin_sources()


@pytest.fixture
def store(monkeypatch):
    return FakeConnectorStore().install(monkeypatch)


@pytest.fixture
def db(monkeypatch):
    catalog = MirrorDb()
    monkeypatch.setattr("app.import_source_pipeline.run_adapter_import_job", catalog.run_import)
    return catalog


@pytest.fixture
def subjects(monkeypatch, db):
    return FakeStore(db).install(monkeypatch)


def _use(fake: FakeUpstreamRegistry) -> None:
    register_connector_source(
        src.KIND,
        lambda c, creds: src.SchemaRegistrySource(c, creds, transport=fake.transport()),
        scope_validator=src.validate_schema_registry_scope,
    )


def _connector(store, fake: FakeUpstreamRegistry, *, credentials: Optional[Dict[str, str]] = None):
    connector = store.add_connector(
        TENANT, kind=src.KIND, name="Prod registry", base_url=fake.base_url + "/", scope={}, created_by=ACTOR
    )
    if credentials:
        sealed, version = seal_credential_payload(credentials)
        store.credentials[connector["id"]] = {"encrypted_payload": sealed, "key_version": version}
    return connector


def _sync(store, db, connector, actor_id: Optional[str] = ACTOR):
    return run_connector_sync(db, store.connectors[connector["id"]], actor_id=actor_id)


def _items(store) -> Dict[str, Dict[str, Any]]:
    return {i["remote_id"]: i for i in store.items.values()}


def _subject(subjects: FakeStore, name: str) -> Dict[str, Any]:
    return next(s for s in subjects.subjects if s["name"] == name and not s["deleted_at"])


def _versions(subjects: FakeStore, name: str, *, live: bool = True) -> List[Dict[str, Any]]:
    sid = _subject(subjects, name)["id"]
    return sorted(
        (v for v in subjects.versions if v["subject_id"] == sid and (not live or not v["deleted_at"])),
        key=lambda v: v["version"],
    )


# --- the acceptance criteria -------------------------------------------------------------


def test_sync_mirrors_every_subject_with_its_versions_level_and_strategy(store, db, subjects):
    upstream = _registry_subjects()
    del upstream["orders-archive-value"]  # the shared schema id has its own test
    fake = FakeUpstreamRegistry(upstream, subject_levels={"orders-value": "FULL"})
    _use(fake)
    connector = _connector(store, fake)
    result = _sync(store, db, connector)

    assert result.status == "succeeded" and result.connector_status == "active"
    summary = result.summary
    assert (summary["candidates"], summary["imported"], summary["failed"]) == (3, 3, 0)
    # One pull per upstream version read: 2 + 1 + 1.
    assert result.pull_count == 4 and summary["fetched"] == 4

    orders = _subject(subjects, "orders-value")
    assert orders["source_ref"] == "registry:https://sr.example.test"
    assert orders["source_connector_id"] == connector["id"]
    assert orders["compatibility_level"] == "FULL" and orders["strategy"] == "topic"
    versions = _versions(subjects, "orders-value")
    coordinates = [(v["version"], v["upstream_version"], v["upstream_schema_id"]) for v in versions]
    assert coordinates == [(1, 1, 10), (2, 2, 11)]
    # Both versions are revisions of the subject's one catalog item, labelled by upstream version.
    item = orders["project_id"]
    assert {v["project_id"] for v in versions} == {item}
    assert [r["version_id"] for r in db.item_revisions(item)] == ["1", "2"]
    assert db.projects[item]["name"] == "orders-value"

    assert _subject(subjects, "acme.Customer")["strategy"] == "record"
    assert _subject(subjects, "payments-acme.Payment")["strategy"] == "topic_record"
    assert _subject(subjects, "acme.Customer")["compatibility_level"] == "BACKWARD"  # the registry default

    items = _items(store)
    assert all(i["status"] == "imported" for i in items.values())
    assert items["orders-value"]["project_id"] == item
    assert items["orders-value"]["deployment"]["compatibilityLevel"] == "FULL"
    assert items["orders-value"]["deployment"]["versions"] == [1, 2]


def test_a_schema_id_shared_by_two_subjects_is_parsed_and_imported_once(store, db, subjects, monkeypatch):
    parsed: List[str] = []
    real = src.fingerprint_schema
    monkeypatch.setattr(src, "fingerprint_schema", lambda t, s, n: (parsed.append(n), real(t, s, n))[1])
    fake = FakeUpstreamRegistry(_registry_subjects())
    _use(fake)
    _sync(store, db, _connector(store, fake))

    # Four distinct schema ids → four parses and four imports (id 10 is held by two subjects).
    assert len(parsed) == 4 and len(db.imports) == 4
    orders_v1 = _versions(subjects, "orders-value")[0]
    archive_v1 = _versions(subjects, "orders-archive-value")[0]
    assert archive_v1["schema_id"] == orders_v1["schema_id"]
    assert archive_v1["version_record_id"] == orders_v1["version_record_id"]
    assert archive_v1["upstream_schema_id"] == 10
    # Subjects are crawled by name, so orders-archive-value imported id 10 and backs that item;
    # orders-value shares its revision for version 1 and gets an item of its own for version 2.
    assert _items(store)["orders-archive-value"]["project_id"] == orders_v1["project_id"]
    assert _subject(subjects, "orders-value")["project_id"] == _versions(subjects, "orders-value")[1]["project_id"]


def test_imported_revisions_carry_the_connector_provenance(store, db, subjects):
    fake = FakeUpstreamRegistry({"orders-value": {1: {"id": 10, "schema": ORDER_V1}}})
    _use(fake)
    connector = _connector(store, fake)
    _sync(store, db, connector)

    (payload,) = db.imports
    provenance = payload["connector_source"]
    assert provenance["inputKind"] == "connector" and provenance["connectorId"] == connector["id"]
    assert provenance["connectorKind"] == "schema-registry" and provenance["remoteId"] == "orders-value"
    assert provenance["remoteRevision"] == "1"
    assert provenance["sourceUri"] == "https://sr.example.test/subjects/orders-value/versions/1"
    assert payload["metadata"]["source_kind"] == "avro" and payload["filename"] == "orders-value.avsc"


def test_crawl_reads_subjects_versions_and_config(store, db, subjects):
    fake = FakeUpstreamRegistry({"orders-value": {1: {"id": 10, "schema": ORDER_V1}}})
    _use(fake)
    _sync(store, db, _connector(store, fake))
    assert fake.paths() == [
        "/subjects",
        "/subjects/orders-value/versions",
        "/config/orders-value?defaultToGlobal=true",
        "/subjects/orders-value/versions/1",
    ]
    assert "vnd.schemaregistry.v1+json" in fake.requests[0].headers["accept"]


# --- re-syncs -----------------------------------------------------------------------------


def test_an_unchanged_registry_is_not_fetched_again(store, db, subjects):
    fake = FakeUpstreamRegistry(_registry_subjects())
    _use(fake)
    connector = _connector(store, fake)
    _sync(store, db, connector)
    fake.requests.clear()
    result = _sync(store, db, connector)
    assert result.summary["unchanged"] == 4 and result.summary["imported"] == 0 and result.pull_count == 0
    assert not any("/versions/" in p for p in fake.paths())
    reasons = {u["remoteId"]: u["reason"] for u in result.summary["unchangedItems"]}
    assert "latest version 2" in reasons["orders-value"]


def test_a_new_version_a_deleted_version_and_a_new_level_are_mirrored(store, db, subjects):
    upstream = _registry_subjects()
    del upstream["orders-archive-value"]
    fake = FakeUpstreamRegistry(upstream)
    _use(fake)
    connector = _connector(store, fake)
    _sync(store, db, connector)
    item = _subject(subjects, "orders-value")["project_id"]

    order_v3 = _avro("Order", extra=[{"name": "note", "type": ["null", "string"], "default": None}])
    upstream["orders-value"][3] = {"id": 12, "schema": order_v3}
    del upstream["orders-value"][1]
    fake.subject_levels["orders-value"] = "NONE"
    fake.requests.clear()
    result = _sync(store, db, connector)

    assert result.summary["imported"] == 1 and result.summary["unchanged"] == 2
    assert [p for p in fake.paths() if "/versions/" in p] == ["/subjects/orders-value/versions/3"]
    live = _versions(subjects, "orders-value")
    assert [(v["version"], v["upstream_version"]) for v in live] == [(2, 2), (3, 3)]
    retired = [v for v in _versions(subjects, "orders-value", live=False) if v["deleted_at"]]
    assert [v["upstream_version"] for v in retired] == [1]
    # The catalog keeps every revision; the new one lands on the same item.
    assert [r["version_id"] for r in db.item_revisions(item)] == ["1", "2", "3"]
    assert _subject(subjects, "orders-value")["compatibility_level"] == "NONE"


def test_a_schema_id_mirrored_in_an_earlier_sync_is_reused_without_parsing(store, db, subjects, monkeypatch):
    upstream = {"orders-value": {1: {"id": 10, "schema": ORDER_V1}}}
    fake = FakeUpstreamRegistry(upstream)
    _use(fake)
    connector = _connector(store, fake)
    _sync(store, db, connector)

    upstream["orders-copy-value"] = {1: {"id": 10, "schema": ORDER_V1}}

    def _no_parse(*_a):
        raise AssertionError("a schema id this connector already holds must not be parsed again")

    monkeypatch.setattr(src, "fingerprint_schema", _no_parse)
    result = _sync(store, db, connector)
    assert result.summary["imported"] == 1 and len(db.imports) == 1
    assert _versions(subjects, "orders-copy-value")[0]["upstream_schema_id"] == 10


# --- flavours and credentials --------------------------------------------------------------


def test_apicurio_falls_back_to_the_global_level_and_reads_schemas_by_id(store, db, subjects):
    upstream = _registry_subjects()
    fake = FakeUpstreamRegistry(
        upstream, flavor=APICURIO, global_level="FORWARD", subject_levels={"acme.Customer": "FULL"},
        omit_schema_text=True,
    )
    _use(fake)
    result = _sync(store, db, _connector(store, fake))

    assert result.status == "succeeded" and result.summary["imported"] == 4
    assert _subject(subjects, "orders-value")["compatibility_level"] == "FORWARD"
    assert _subject(subjects, "acme.Customer")["compatibility_level"] == "FULL"
    paths = fake.paths()
    assert paths.count("/config") == 1  # the global level is read once per sync
    # Dedup by schema id: id 10 is fetched by id once, though two subjects hold it.
    assert sorted(p for p in paths if p.startswith("/schemas/ids/")) == [
        "/schemas/ids/10", "/schemas/ids/11", "/schemas/ids/20", "/schemas/ids/30"
    ]
    assert _subject(subjects, "orders-value")["source_ref"] == "registry:https://sr.example.test/apis/ccompat/v7"
    # Each /schemas/ids call counts as a pull: 5 version reads + 4 schema reads.
    assert result.pull_count == 9


def test_karapace_with_basic_auth_and_a_json_schema_subject(store, db, subjects):
    fake = FakeUpstreamRegistry(
        {
            "Person": {1: {"id": 5, "schema": PERSON, "schemaType": "JSON"}},
            "orders-value": {1: {"id": 6, "schema": ORDER_V1}},
        },
        flavor=KARAPACE,
        basic=("sr-key", "sr-secret"),
    )
    _use(fake)
    result = _sync(store, db, _connector(store, fake, credentials={"username": "sr-key", "password": "sr-secret"}))
    assert result.status == "succeeded" and result.summary["imported"] == 2
    person = _versions(subjects, "Person")[0]
    assert person["schema_type"] == "JSON" and _subject(subjects, "Person")["strategy"] == "record"
    assert db.imports[0]["metadata"]["source_kind"] in ("json-schema", "avro")


def test_a_bearer_token_is_sent(store, db, subjects):
    fake = FakeUpstreamRegistry({"orders-value": {1: {"id": 10, "schema": ORDER_V1}}}, token="sr-token")
    _use(fake)
    result = _sync(store, db, _connector(store, fake, credentials={"token": "sr-token"}))
    assert result.status == "succeeded"
    assert all(r.headers["authorization"] == "Bearer sr-token" for r in fake.requests)


def test_a_registry_refusal_fails_the_run_with_its_status(store, db, subjects):
    fake = FakeUpstreamRegistry(_registry_subjects(), basic=("sr-key", "sr-secret"))
    _use(fake)
    connector = _connector(store, fake, credentials={"username": "sr-key", "password": "wrong-secret"})
    result = _sync(store, db, connector)
    assert (result.status, result.error_class, result.http_status) == ("failed", "auth", 401)
    assert "error_code 40101" in result.error_message and "wrong-secret" not in result.error_message
    assert store.connectors[connector["id"]]["status"] == "failing"
    assert subjects.subjects == [] and db.imports == []


# --- subjects that stay discovered ------------------------------------------------------------


def test_a_subject_already_in_the_workspace_is_never_taken_over(store, db, subjects):
    subjects.record_version(
        db, tenant_id=TENANT, subject="orders-value", schema_type="AVRO", fingerprint="sha256:local",
        references=[], project_id="item-x", version_record_id="rev-x", actor_id=ACTOR,
    )
    fake = FakeUpstreamRegistry({"orders-value": {1: {"id": 10, "schema": ORDER_V1}}})
    _use(fake)
    result = _sync(store, db, _connector(store, fake))

    item = _items(store)["orders-value"]
    assert item["status"] == "discovered" and item["discovered_reason"].startswith("subject-name-taken:")
    assert result.summary["discovered"] == 1 and result.summary["failed"] == 0 and result.pull_count == 0
    assert db.imports == [] and _subject(subjects, "orders-value")["source_ref"] is None
    assert len(_versions(subjects, "orders-value")) == 1


SHIPMENT = json.dumps(
    {"type": "record", "name": "Shipment", "namespace": "acme", "fields": [{"name": "to", "type": "acme.Address"}]}
)
ADDRESS_REF = [{"name": "acme.Address", "subject": "address-value", "version": 1}]


def test_a_schema_with_references_is_mirrored_with_them_when_it_can_be_read(store, db, subjects):
    fake = FakeUpstreamRegistry({"shipments-value": {1: {"id": 40, "schema": SHIPMENT, "references": ADDRESS_REF}}})
    _use(fake)
    result = _sync(store, db, _connector(store, fake))
    assert result.summary["imported"] == 1
    assert _versions(subjects, "shipments-value")[0]["references"] == ADDRESS_REF


def test_a_schema_with_references_that_cannot_be_read_alone_stays_discovered(store, db, subjects, monkeypatch):
    def _refused(schema_type, schema, subject):
        raise SchemaRegistryError("schema-invalid", "Invalid AVRO schema: unknown type acme.Address")

    monkeypatch.setattr(src, "fingerprint_schema", _refused)
    fake = FakeUpstreamRegistry({"shipments-value": {1: {"id": 40, "schema": SHIPMENT, "references": ADDRESS_REF}}})
    _use(fake)
    result = _sync(store, db, _connector(store, fake))
    item = _items(store)["shipments-value"]
    assert item["status"] == "discovered" and item["discovered_reason"].startswith("references-unsupported:")
    assert "address-value" in item["discovered_reason"]
    assert result.status == "succeeded" and result.summary["discovered"] == 1


def test_an_unreadable_schema_type_stays_discovered(store, db, subjects, monkeypatch):
    def _unavailable(schema_type, schema, subject):
        raise SchemaRegistryError("schema-type-unavailable", "PROTOBUF schemas cannot be read in this deployment.")

    monkeypatch.setattr(src, "fingerprint_schema", _unavailable)
    proto = {"id": 1, "schema": 'syntax = "proto3";', "schemaType": "PROTOBUF"}
    fake = FakeUpstreamRegistry({"events-value": {1: proto}})
    _use(fake)
    _sync(store, db, _connector(store, fake))
    assert _items(store)["events-value"]["discovered_reason"].startswith("schema-type-unavailable:")


def test_an_invalid_schema_fails_that_subject_only(store, db, subjects):
    upstream = _registry_subjects()
    upstream["broken-value"] = {1: {"id": 99, "schema": "{not json"}}
    fake = FakeUpstreamRegistry(upstream)
    _use(fake)
    result = _sync(store, db, _connector(store, fake))
    assert result.status == "succeeded" and result.summary["failed"] == 1 and result.summary["imported"] == 4
    assert result.error_class == "import-failed"


# --- dry run, registration, item projection -----------------------------------------------------


def test_dry_run_lists_subjects_without_storing_anything(store, db, subjects):
    fake = FakeUpstreamRegistry(_registry_subjects(), flavor=APICURIO)
    _use(fake)
    out = dry_run_connector(
        {"id": "dry", "tenant_id": TENANT, "kind": src.KIND, "base_url": fake.base_url, "scope": {}}, None
    )
    assert out["itemCount"] == 4 and {i["remoteId"] for i in out["items"]} == set(_registry_subjects())
    assert subjects.subjects == [] and db.imports == []


def test_the_kind_is_syncable_and_validates_its_scope():
    restore_builtin_sources()
    assert "schema-registry" in syncable_kinds() and source_factory_for(src.KIND) is not None
    validate_connector_scope(src.KIND, {}, "https://sr.example.test")
    with pytest.raises(ConnectorError) as missing:
        validate_connector_scope(src.KIND, {}, None)
    assert missing.value.code == "connector-invalid" and "base URL" in str(missing.value)
    with pytest.raises(ConnectorError) as scoped:
        validate_connector_scope(src.KIND, {"subjects": ["a"]}, "https://sr.example.test")
    assert "takes no scope" in str(scoped.value)


def test_item_projection_carries_the_discovered_reason():
    out = _item_out(
        {
            "id": "i1",
            "connector_id": "c1",
            "remote_id": "orders-value",
            "remote_name": "orders-value",
            "status": "discovered",
            "discovered_reason": "subject-name-taken: x",
            "first_seen_at": None,
            "last_seen_at": None,
        }
    )
    assert out.discovered_reason == "subject-name-taken: x"


# --- pure rules ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, root",
    [
        ("https://sr.example.test/", "https://sr.example.test"),
        ("https://sr.example.test/subjects", "https://sr.example.test"),
        ("https://apicurio.test/apis/ccompat/v7/", "https://apicurio.test/apis/ccompat/v7"),
    ],
)
def test_normalize_registry_base(raw, root):
    assert src.normalize_registry_base(raw) == root


def test_parse_compatibility_level_reads_both_keys_and_flags_unknown_levels():
    assert src.parse_compatibility_level({"compatibilityLevel": "full_transitive"}) == ("FULL_TRANSITIVE", None)
    assert src.parse_compatibility_level({"compatibility": "NONE"}) == ("NONE", None)
    assert src.parse_compatibility_level({"compatibilityLevel": "SOMETIMES"}) == (None, "SOMETIMES")
    assert src.parse_compatibility_level(None) == (None, None)
    assert src.parse_compatibility_level({}) == (None, None)


def test_an_unknown_level_is_a_finding(store, db, subjects):
    fake = FakeUpstreamRegistry({"orders-value": {1: {"id": 10, "schema": ORDER_V1}}}, global_level="SOMETIMES")
    _use(fake)
    result = _sync(store, db, _connector(store, fake))
    (finding,) = result.summary["findings"]
    assert finding["code"] == "registry-level-unknown" and finding["level"] == "SOMETIMES"
    assert _subject(subjects, "orders-value")["compatibility_level"] is None  # left at the tenant default


def test_record_name():
    assert src.record_name("AVRO", _avro("Order")) == "acme.Order"
    assert src.record_name("AVRO", _avro("Order", namespace=None)) == "Order"
    dotted = json.dumps({"type": "record", "name": "x.y.Z", "namespace": "ignored", "fields": []})
    assert src.record_name("AVRO", dotted) == "x.y.Z"
    assert src.record_name("AVRO", '"string"') is None
    assert src.record_name("AVRO", "{not json") is None
    assert src.record_name("JSON", PERSON) == "Person"
    assert src.record_name("JSON", json.dumps({"type": "object"})) is None
    proto = 'syntax = "proto3";\npackage acme.v1;\n\nmessage Order {\n  string id = 1;\n}\nmessage Line {}\n'
    assert src.record_name("PROTOBUF", proto) == "acme.v1.Order"
    assert src.record_name("PROTOBUF", "message Bare {}") == "Bare"
    assert src.record_name("PROTOBUF", "enum Only { A = 0; }") is None


@pytest.mark.parametrize(
    "subject, record, strategy",
    [
        ("orders-value", "acme.Order", "topic"),
        ("orders-key", None, "topic"),
        ("acme.Order", "acme.Order", "record"),
        ("orders-acme.Order", "acme.Order", "topic_record"),
        ("orders", "acme.Order", None),
        ("-acme.Order", "acme.Order", None),
    ],
)
def test_infer_strategy(subject, record, strategy):
    assert src.infer_strategy(subject, record) == strategy


def test_subject_revision_tracks_versions_and_level():
    base = src.subject_revision([1, 2], "BACKWARD")
    assert base.startswith("v2+sha256.")
    assert src.subject_revision([2, 1], "BACKWARD") == base
    assert src.subject_revision([1, 2, 3], "BACKWARD") != base
    assert src.subject_revision([2], "BACKWARD") != base
    assert src.subject_revision([1, 2], "FULL") != base


def test_candidate_is_credential_free():
    state = src.SubjectState(name="orders-value", versions=(1, 2), compatibility_level="FULL")
    candidate = src.build_candidate(state, registry_url="https://sr.example.test")
    assert candidate.remote_id == candidate.name == "orders-value"
    assert candidate.deployment == {
        "registryUrl": "https://sr.example.test",
        "subject": "orders-value",
        "versions": [1, 2],
        "latestVersion": 2,
        "compatibilityLevel": "FULL",
    }


# --- store: the mirror half of record_version (scripted connection) ----------------------------

MIRROR = {
    "connector_id": "c-1",
    "source_ref": "registry:https://sr.example.test",
    "upstream_version": 4,
    "upstream_schema_id": 101,
}


def _mirror_subject(**kw: Any) -> Dict[str, Any]:
    row = {"id": "s1", "tenant_id": TENANT, "name": "orders-value", "strategy": None, "compatibility_level": None,
           "mode": "READWRITE", "project_id": None, "source_ref": MIRROR["source_ref"], "source_connector_id": "c-1",
           "deleted_at": None}
    row.update(kw)
    return row


def _record_mirror(database, **kw: Any) -> Dict[str, Any]:
    from app import schema_registry_store as real

    args = dict(tenant_id=TENANT, subject="orders-value", schema_type="AVRO", fingerprint="sha256:a", references=[],
                project_id="p1", version_record_id="r1", actor_id=ACTOR, mirror=MIRROR)
    args.update(kw)
    return real.record_version(database, **args)


def test_record_version_records_the_source_and_upstream_coordinates(monkeypatch):
    from tests.scripted_connection import ScriptedConnection, database_with

    conn = ScriptedConnection(
        [
            [],  # insert subject with its source
            [_mirror_subject()],  # select … for update
            [{"schema_id": 7}],  # schema known by fingerprint
            [],  # subject already holds it? no
            [{"version": 2}],  # next local version
            [{"id": "v2", "subject_id": "s1", "version": 2, "schema_id": 7, "upstream_version": 4}],
        ]
    )
    row = _record_mirror(database_with(monkeypatch, conn))
    assert row["created"] is True and row["upstream_version"] == 4
    insert_subject, _, _, _, _, insert_version = conn.statements
    assert "source_ref, source_connector_id" in insert_subject[0]
    assert insert_subject[1][-2:] == (MIRROR["source_ref"], "c-1")
    assert "upstream_version" in insert_version[0] and insert_version[1][-2:] == (4, 101)
    assert (conn.commits, conn.rollbacks) == (1, 0)


def test_record_version_refuses_a_subject_another_source_owns(monkeypatch):
    from tests.scripted_connection import ScriptedConnection, database_with

    conn = ScriptedConnection([[], [_mirror_subject(source_connector_id=None, source_ref=None)]])
    with pytest.raises(SchemaRegistryError) as exc:
        _record_mirror(database_with(monkeypatch, conn))
    assert exc.value.code == "subject-not-mirrored" and exc.value.status_code == 409
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_record_version_moves_a_held_schema_to_its_new_upstream_version(monkeypatch):
    from tests.scripted_connection import ScriptedConnection, database_with

    conn = ScriptedConnection(
        [
            [],
            [_mirror_subject()],
            [{"schema_id": 7}],
            [{"id": "v1", "subject_id": "s1", "version": 1, "schema_id": 7, "upstream_version": 1,
              "upstream_schema_id": 101, "deleted_at": None}],
            [],  # update upstream coordinates
        ]
    )
    row = _record_mirror(database_with(monkeypatch, conn))
    assert row["created"] is False and row["upstream_version"] == 4
    assert "SET upstream_version" in conn.statements[-1][0] and conn.statements[-1][1] == (4, 101, "v1")


def test_retire_and_find_mirrored_sql(monkeypatch):
    from app import schema_registry_store as real
    from tests.scripted_connection import ScriptedConnection, database_with

    conn = ScriptedConnection([[{"version": 3}, {"version": 1}], [{"schema_type": "AVRO", "fingerprint": "sha256:a",
                                                                    "project_id": "p", "version_record_id": "r",
                                                                    "references": []}]])
    database = database_with(monkeypatch, conn)
    assert real.retire_mirrored_versions(database, "s1", [2, 4]) == [1, 3]
    sql, params = conn.statements[0]
    assert "upstream_version IS NOT NULL" in sql and params == ("s1", [2, 4])
    assert real.find_mirrored_schema(database, TENANT, "c-1", 101)["fingerprint"] == "sha256:a"
    assert conn.statements[1][1] == (TENANT, "c-1", 101)
