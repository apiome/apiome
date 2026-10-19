"""Tests for the schema subject model (CDG-4.2, #5974).

Four layers:

* **Pure rules** (:mod:`app.schema_registry`) — subject names, enumerations, the strategy
  vocabulary shared with the Avro emitter (MFX-19.3), format → schema type, and the canonical-model
  fingerprint computed through the real Avro and JSON Schema import sources.
* **Service** (:mod:`app.schema_registry_service`) against an in-memory store that keeps the same
  contract as :mod:`app.schema_registry_store` and a stand-in import pipeline that records every
  revision it creates — so the acceptance criteria are checked end to end: one id and one revision
  for a schema registered twice, a shared id across subjects, deleted subjects hidden but resolvable,
  and attach making an item's latest revision version 1 without touching its history.
* **Store transactions** (:func:`app.schema_registry_store.record_version` /
  :func:`~app.schema_registry_store.soft_delete_subject`) over a scripted connection: which
  statements run, in one transaction, and a refusal rolls everything back. The SQL itself was run
  against a scratch database built from V294.
* **Routes** — status codes, permissions, camelCase bodies.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import schema_registry_service as service
from app import schema_registry_store as store
from app.avro_emitter import AvroEmitOptions, AvroSubjectNamingStrategy
from app.main import app
from app.schema_registry import (
    FINGERPRINT_KIND,
    STRATEGIES,
    SchemaRegistryError,
    effective_mode,
    fingerprint_schema,
    intake_for,
    normalize_choice,
    schema_type_for_format,
    strategy_from_avro,
    strategy_to_avro,
    validate_subject_name,
)
from tests.schema_registry_fakes import NOW, FakeCatalog, FakeStore
from tests.scripted_connection import ScriptedConnection, database_with

T = "11111111-1111-1111-1111-111111111111"

ORDER = json.dumps(
    {"type": "record", "name": "Order", "namespace": "acme", "fields": [{"name": "id", "type": "string"}]}
)
ORDER_REORDERED = json.dumps(
    {"fields": [{"type": "string", "name": "id"}], "namespace": "acme", "name": "Order", "type": "record"}
)
ORDER_V2 = json.dumps(
    {
        "type": "record",
        "name": "Order",
        "namespace": "acme",
        "fields": [{"name": "id", "type": "string"}, {"name": "total", "type": ["null", "double"], "default": None}],
    }
)
PERSON = json.dumps(
    {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Person",
        "type": "object",
        "properties": {"name": {"type": "string"}},
    }
)


# --------------------------------------------------------------------------- pure rules


def test_validate_subject_name():
    assert validate_subject_name("orders-value") == "orders-value"
    assert validate_subject_name("acme.Order-value") == "acme.Order-value"
    for bad in ("", "   ", None, "a" * 256, "bad\nname", "tab\tname"):
        with pytest.raises(SchemaRegistryError) as exc:
            validate_subject_name(bad)
        assert exc.value.code == "subject-invalid"


def test_normalize_choice():
    assert normalize_choice(None, STRATEGIES, field="strategy") is None
    assert normalize_choice("record", STRATEGIES, field="strategy") == "record"
    with pytest.raises(SchemaRegistryError) as exc:
        normalize_choice("record_name", STRATEGIES, field="strategy")
    assert exc.value.code == "strategy-invalid" and exc.value.status_code == 422


def test_strategy_vocabulary_matches_the_avro_emitter():
    assert strategy_to_avro("topic") is AvroSubjectNamingStrategy.TOPIC_NAME
    assert strategy_to_avro("record") is AvroSubjectNamingStrategy.RECORD_NAME
    assert strategy_to_avro("topic_record") is AvroSubjectNamingStrategy.TOPIC_RECORD_NAME
    assert strategy_to_avro(None) is None
    for member in AvroSubjectNamingStrategy:
        assert strategy_to_avro(strategy_from_avro(member)) is member
    # Every emitter strategy can be stored: the V294 CHECK and the emitter agree.
    assert {strategy_from_avro(m) for m in AvroSubjectNamingStrategy} == set(STRATEGIES)
    AvroEmitOptions(subject_naming=strategy_to_avro("topic"), topic="orders")


@pytest.mark.parametrize(
    "fmt, expected",
    [
        ("avro", "AVRO"),
        ("avsc", "AVRO"),
        ("avro-idl", "AVRO"),
        ("json-schema", "JSON"),
        ("jsonschema", "JSON"),
        ("protobuf", "PROTOBUF"),
        ("protobuf-editions", "PROTOBUF"),
        ("openapi-3.1", None),
        ("asyncapi-3", None),
        (None, None),
    ],
)
def test_schema_type_for_format(fmt, expected):
    assert schema_type_for_format(fmt) == expected


def test_intake_for_labels_the_upload():
    assert intake_for("AVRO", "orders-value") == ("avro", "orders-value.avsc")
    assert intake_for("JSON", "people") == ("json-schema", "people.json")
    assert intake_for("PROTOBUF", "a/b c") == ("grpc", "a-b-c.proto")
    assert intake_for("AVRO", "///") == ("avro", "schema.avsc")


def test_effective_mode():
    assert effective_mode(None, "READWRITE") == "READWRITE"
    assert effective_mode("READONLY", "READWRITE") == "READONLY"
    assert effective_mode("READWRITE", "READONLY") == "READONLY"


def test_avro_fingerprint_is_canonical_and_key_order_independent():
    first = fingerprint_schema("AVRO", ORDER, "orders-value")
    assert first.fingerprint.startswith("sha256:")
    assert first.adapter_key == "avro" and first.filename == "orders-value.avsc"
    assert fingerprint_schema("AVRO", ORDER_REORDERED, "other").fingerprint == first.fingerprint
    assert fingerprint_schema("AVRO", ORDER_V2, "orders-value").fingerprint != first.fingerprint


def test_json_schema_fingerprint():
    parsed = fingerprint_schema("JSON", PERSON, "people")
    assert parsed.schema_type == "JSON" and parsed.adapter_key == "json-schema"


def test_invalid_and_empty_schemas_are_refused():
    for text in ("", "   ", "{not json"):
        with pytest.raises(SchemaRegistryError) as exc:
            fingerprint_schema("AVRO", text, "s")
        assert exc.value.code == "schema-invalid"


def test_protobuf_goes_through_the_grpc_intake():
    model = object()
    adapter = SimpleNamespace(
        key="grpc",
        parse=lambda raw, source_label=None: ("ast", raw, source_label),
        normalize=lambda ast: model,
        fingerprint=lambda m: "sha256:" + "f" * 64,
    )
    with patch("app.import_source.get_import_source", return_value=adapter) as lookup:
        parsed = fingerprint_schema("PROTOBUF", 'syntax = "proto3";', "orders")
    lookup.assert_called_with("grpc")
    assert parsed.fingerprint == "sha256:" + "f" * 64 and parsed.filename == "orders.proto"


# --------------------------------------------------------------------------- in-memory doubles


@pytest.fixture
def registry():
    """The service wired to the in-memory catalog, store and import pipeline."""
    catalog = FakeCatalog()
    fake = FakeStore(catalog)
    with patch.object(service, "store", fake), patch(
        "app.import_source_pipeline.run_adapter_import_job", catalog.run_import
    ):
        yield SimpleNamespace(db=catalog, store=fake, catalog=catalog)


def _register(reg, subject: str, schema: str = ORDER, schema_type: str = "AVRO", **kw) -> Dict[str, Any]:
    return service.register_schema(
        reg.db, tenant_id=T, actor_id="u1", subject=subject, schema=schema, schema_type=schema_type, **kw
    )


# --------------------------------------------------------------------------- service: register


def test_registering_the_same_avro_schema_twice_returns_one_id_and_one_revision(registry):
    first = _register(registry, "orders-value", strategy="topic")
    second = _register(registry, "orders-value", ORDER_REORDERED)
    assert first["created"] is True and second["created"] is False
    assert (first["schema_id"], first["version"]) == (second["schema_id"], second["version"]) == (1, 1)
    assert len(registry.catalog.imports) == 1
    assert len(registry.catalog.revisions) == 1
    subject = registry.store.get_subject(None, T, "orders-value")
    assert subject["project_id"] == first["project_id"] and subject["strategy"] == "topic"


def test_first_registration_creates_a_catalog_item_named_after_the_subject(registry):
    _register(registry, "orders-value")
    payload = registry.catalog.imports[0]
    meta = payload["metadata"]
    assert meta["source_kind"] == "avro"
    assert meta["project"] == {"name": "orders-value", "slug": "orders-value"}
    assert meta["existing_project_id"] is None
    assert meta["version"]["version_id"] == "1"
    assert payload["filename"] == "orders-value.avsc"
    assert payload["tenant_id"] == T and payload["user_id"] == "u1"


def test_two_subjects_share_an_id_for_the_same_schema_without_a_new_revision(registry):
    orders = _register(registry, "orders-value")
    audit = _register(registry, "audit-value", ORDER_REORDERED)
    assert audit["created"] is True
    assert audit["schema_id"] == orders["schema_id"]
    assert audit["version_record_id"] == orders["version_record_id"]
    assert len(registry.catalog.revisions) == 1
    # The second subject is not backed by the first subject's item.
    assert registry.store.get_subject(None, T, "audit-value")["project_id"] is None


def test_a_new_schema_adds_a_revision_to_the_subjects_item(registry):
    registry.store.config["compatibility_level"] = "NONE"  # no XPC-4.x verdicts yet (CDG-4.3)
    v1 = _register(registry, "orders-value")
    v2 = _register(registry, "orders-value", ORDER_V2)
    assert (v2["schema_id"], v2["version"]) == (2, 2)
    assert v2["project_id"] == v1["project_id"]
    assert [r["version_id"] for r in registry.catalog.item_revisions(v1["project_id"])] == ["1", "2"]
    assert registry.catalog.imports[1]["metadata"]["existing_project_id"] == v1["project_id"]


def test_json_schema_and_references_are_stored(registry):
    row = _register(registry, "people", PERSON, "JSON", references=[{"name": "Address", "subject": "addr", "version": 1}])
    assert row["schema_type"] == "JSON"
    assert row["references"] == [{"name": "Address", "subject": "addr", "version": 1}]
    assert registry.catalog.imports[0]["metadata"]["source_kind"] == "json-schema"


def test_a_soft_deleted_subjects_versions_are_hidden_but_resolvable_by_id(registry):
    v1 = _register(registry, "orders-value")
    assert registry.store.soft_delete_subject(None, T, "orders-value") == [1]
    assert registry.store.get_subject(None, T, "orders-value") is None
    resolved = registry.store.get_schema_by_id(None, T, v1["schema_id"])
    assert resolved["schema_id"] == 1 and resolved["subjects"] == []
    # Registering the name again starts a new subject at version 1 that reuses the id.
    again = _register(registry, "orders-value")
    assert (again["schema_id"], again["version"], again["created"]) == (1, 1, True)
    assert len(registry.catalog.revisions) == 1


def test_a_second_version_under_a_checked_level_is_refused_not_accepted_unchecked(registry):
    """CDG-4.3: no XPC-4.x rules yet, so BACKWARD (the default) cannot judge a second version."""
    _register(registry, "orders-value")
    with pytest.raises(SchemaRegistryError) as exc:
        _register(registry, "orders-value", ORDER_V2)
    assert exc.value.code == "compatibility-rules-unavailable" and exc.value.status_code == 422
    assert len(registry.catalog.imports) == 1
    # Re-registering what the subject already holds needs no verdict.
    assert _register(registry, "orders-value", ORDER_REORDERED)["created"] is False
    # A subject-level NONE beats the tenant default.
    registry.store.get_subject(None, T, "orders-value")["compatibility_level"] = "NONE"
    assert _register(registry, "orders-value", ORDER_V2)["version"] == 2


@pytest.mark.parametrize("where", ["tenant", "subject"])
def test_readonly_mode_refuses_registration(registry, where):
    registry.store.config["compatibility_level"] = "NONE"
    _register(registry, "orders-value")
    if where == "tenant":
        registry.store.config["mode"] = "READONLY"
    else:
        registry.store.get_subject(None, T, "orders-value")["mode"] = "READONLY"
    with pytest.raises(SchemaRegistryError) as exc:
        _register(registry, "orders-value", ORDER_V2)
    assert exc.value.code == "subject-read-only" and exc.value.status_code == 409


def test_invalid_input_is_refused_before_anything_is_imported(registry):
    cases = [
        ({"subject": ""}, "subject-invalid"),
        ({"schema_type": "XML"}, "schemaType-invalid"),
        ({"strategy": "record_name"}, "strategy-invalid"),
        ({"schema": "{oops"}, "schema-invalid"),
        ({"references": {"not": "a list"}}, "references-invalid"),
    ]
    for overrides, code in cases:
        args = {"subject": "s", "schema": ORDER, "schema_type": "AVRO", **overrides}
        with pytest.raises(SchemaRegistryError) as exc:
            service.register_schema(registry.db, tenant_id=T, actor_id=None, **args)
        assert exc.value.code == code
    assert registry.catalog.imports == []


def test_a_failed_import_is_a_clean_refusal(registry):
    async def failing(adapter, payload):
        return SimpleNamespace(state="failed", result=None, error=SimpleNamespace(message="parse exploded"))

    with patch("app.import_source_pipeline.run_adapter_import_job", failing):
        with pytest.raises(SchemaRegistryError) as exc:
            _register(registry, "orders-value")
    assert exc.value.code == "schema-import-failed" and "parse exploded" in str(exc.value)
    assert registry.store.versions == []


def test_a_deleted_backing_item_gets_a_fresh_one(registry):
    registry.store.config["compatibility_level"] = "NONE"  # no XPC-4.x verdicts yet (CDG-4.3)
    v1 = _register(registry, "orders-value")
    registry.catalog.projects[v1["project_id"]]["deleted"] = True
    v2 = _register(registry, "orders-value", ORDER_V2)
    assert v2["project_id"] != v1["project_id"]
    assert registry.catalog.imports[1]["metadata"]["existing_project_id"] is None


# --------------------------------------------------------------------------- service: attach


def _avro_item(reg, revisions: int = 3) -> str:
    fp = fingerprint_schema("AVRO", ORDER, "x").fingerprint
    return reg.catalog.add_item(
        "orders",
        [
            {"label": f"1.{n}.0", "source_format": "avro", "format_metadata": {"fingerprint": fp if n == revisions - 1 else "sha256:old"}}
            for n in range(revisions)
        ],
    )


def test_attach_makes_the_latest_revision_version_1_and_keeps_history(registry):
    item = _avro_item(registry)
    before = [dict(r) for r in registry.catalog.item_revisions(item)]
    row = service.attach_catalog_item(registry.db, tenant_id=T, actor_id="u1", subject="orders-value", project_id=item)
    assert (row["version"], row["schema_id"], row["created"]) == (1, 1, True)
    assert row["version_record_id"] == before[-1]["id"]
    assert registry.catalog.item_revisions(item) == before  # nothing created, moved or deleted
    assert registry.catalog.imports == []
    assert registry.store.get_subject(None, T, "orders-value")["project_id"] == item


def test_after_attach_registration_is_idempotent_and_adds_revisions_to_the_item(registry):
    registry.store.config["compatibility_level"] = "NONE"  # no XPC-4.x verdicts yet (CDG-4.3)
    item = _avro_item(registry)
    service.attach_catalog_item(registry.db, tenant_id=T, actor_id=None, subject="orders-value", project_id=item)
    same = _register(registry, "orders-value", ORDER_REORDERED)
    assert (same["version"], same["created"]) == (1, False)
    v2 = _register(registry, "orders-value", ORDER_V2)
    assert v2["version"] == 2 and v2["project_id"] == item
    assert registry.catalog.imports[0]["metadata"]["existing_project_id"] == item


def test_attach_recomputes_a_missing_fingerprint_from_the_captured_source(registry):
    item = registry.catalog.add_item(
        "orders", [{"label": "1", "source_format": "avro", "format_metadata": {"sourceContent": ORDER}}]
    )
    row = service.attach_catalog_item(registry.db, tenant_id=T, actor_id=None, subject="s", project_id=item)
    assert row["fingerprint"] == fingerprint_schema("AVRO", ORDER, "s").fingerprint


def test_attach_refusals(registry):
    openapi = registry.catalog.add_item("api", [{"label": "1", "source_format": "openapi-3.1", "format_metadata": {}}])
    no_source = registry.catalog.add_item("bare", [{"label": "1", "source_format": "avro", "format_metadata": {}}])
    project = registry.catalog.add_item("proj", [{"label": "1", "source_format": "avro", "format_metadata": {}}], publishable=True)
    cases = [
        ("missing", "item-not-found", 404),
        (openapi, "item-not-a-schema", 422),
        (no_source, "item-has-no-source", 422),
        (project, "item-not-found", 404),
    ]
    for project_id, code, status in cases:
        with pytest.raises(SchemaRegistryError) as exc:
            service.attach_catalog_item(registry.db, tenant_id=T, actor_id=None, subject="s", project_id=project_id)
        assert (exc.value.code, exc.value.status_code) == (code, status)


def test_attach_needs_an_empty_subject(registry):
    _register(registry, "orders-value")
    item = _avro_item(registry)
    with pytest.raises(SchemaRegistryError) as exc:
        service.attach_catalog_item(registry.db, tenant_id=T, actor_id=None, subject="orders-value", project_id=item)
    assert exc.value.code in {"subject-has-versions", "subject-attached-elsewhere"}
    assert exc.value.status_code == 409


def test_schema_text_reads_the_revision_source():
    with patch.object(service.store, "get_revision_source", return_value={"source_format": "avro", "format_metadata": {"sourceContent": ORDER}}):
        assert service.schema_text(None, "rev-1") == ORDER
    with patch.object(service.store, "get_revision_source", return_value=None):
        assert service.schema_text(None, "rev-1") is None


# --------------------------------------------------------------------------- store transactions


def _subject_row(**kw: Any) -> Dict[str, Any]:
    row = {"id": "s1", "tenant_id": T, "name": "orders-value", "strategy": None, "compatibility_level": None,
           "mode": "READWRITE", "project_id": None, "created_by": None, "created_at": NOW, "updated_at": NOW,
           "deleted_at": None}
    row.update(kw)
    return row


def _record(database, **kw: Any) -> Dict[str, Any]:
    args = dict(tenant_id=T, subject="orders-value", schema_type="AVRO", fingerprint="sha256:a", references=[],
                project_id="p1", version_record_id="r1", actor_id="u1")
    args.update(kw)
    return store.record_version(database, **args)


def test_record_version_allocates_an_id_and_inserts_in_one_transaction(monkeypatch):
    conn = ScriptedConnection(
        [
            [],  # insert subject (on conflict do nothing)
            [_subject_row()],  # select … for update
            [],  # update subject.project_id
            [],  # find schema by fingerprint: none
            [],  # ensure config row
            [{"schema_id": 7}],  # allocate from the tenant counter
            [{"schema_id": 7}],  # insert schema
            [],  # subject already holds it? no
            [{"version": 1}],  # next version
            [{"id": "v1", "subject_id": "s1", "version": 1, "schema_id": 7}],  # insert version
        ]
    )
    row = _record(database_with(monkeypatch, conn), subject_project_id="p1")
    assert (row["schema_id"], row["version"], row["created"]) == (7, 1, True)
    sqls = [s for s, _ in conn.statements]
    assert "FOR UPDATE" in sqls[1]
    assert "UPDATE apiome.schema_subjects SET project_id" in sqls[2]
    assert "next_schema_id = next_schema_id + 1" in sqls[5]
    assert "INSERT INTO apiome.schema_registry_schemas" in sqls[6]
    assert conn.statements[6][1][4] == FINGERPRINT_KIND
    assert (conn.commits, conn.rollbacks) == (1, 0)


def test_record_version_reuses_a_known_schema_id_and_is_idempotent(monkeypatch):
    conn = ScriptedConnection(
        [
            [],
            [_subject_row(project_id="p1")],
            [{"schema_id": 3}],  # known fingerprint
            [{"id": "v9", "subject_id": "s1", "version": 2, "schema_id": 3, "deleted_at": None}],
        ]
    )
    row = _record(database_with(monkeypatch, conn), subject_project_id="p1")
    assert (row["schema_id"], row["version"], row["created"]) == (3, 2, False)
    assert not any("next_schema_id" in s for s, _ in conn.statements)
    assert not any("INSERT INTO apiome.schema_subject_versions" in s for s, _ in conn.statements)
    assert conn.commits == 1


def test_record_version_attach_refusal_rolls_back(monkeypatch):
    conn = ScriptedConnection([[], [_subject_row()], [{"taken": 1}]])
    with pytest.raises(SchemaRegistryError) as exc:
        _record(database_with(monkeypatch, conn), subject_project_id="p1", require_empty_subject=True)
    assert exc.value.code == "subject-has-versions"
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_record_version_attach_to_a_subject_backed_elsewhere(monkeypatch):
    conn = ScriptedConnection([[], [_subject_row(project_id="other")]])
    with pytest.raises(SchemaRegistryError) as exc:
        _record(database_with(monkeypatch, conn), subject_project_id="p1", require_empty_subject=True)
    assert exc.value.code == "subject-attached-elsewhere"
    assert conn.rollbacks == 1


def test_soft_delete_subject_marks_subject_and_versions(monkeypatch):
    conn = ScriptedConnection([[{"id": "s1"}], [{"version": 2}, {"version": 1}]])
    assert store.soft_delete_subject(database_with(monkeypatch, conn), T, "orders-value") == [1, 2]
    assert "UPDATE apiome.schema_subjects SET deleted_at" in conn.statements[0][0]
    assert "UPDATE apiome.schema_subject_versions SET deleted_at" in conn.statements[1][0]
    assert conn.commits == 1


def test_soft_delete_unknown_subject_rolls_back(monkeypatch):
    conn = ScriptedConnection([[]])
    assert store.soft_delete_subject(database_with(monkeypatch, conn), T, "nope") is None
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_reads_hide_deleted_rows_and_get_config_defaults(monkeypatch):
    conn = ScriptedConnection([[], [], [], []])
    database = database_with(monkeypatch, conn)
    assert store.get_config(database, T) == {"compatibility_level": "BACKWARD", "mode": "READWRITE"}
    store.list_subjects(database, T)
    store.get_subject(database, T, "x")
    store.list_versions(database, "s1")
    sqls = [s for s, _ in conn.statements]
    assert "s.deleted_at IS NULL" in sqls[1] and "v.deleted_at IS NULL" in sqls[1]
    assert "s.deleted_at IS NULL" in sqls[2]
    assert "v.deleted_at IS NULL" in sqls[3]


def test_get_schema_by_id_does_not_filter_on_subject_deletion(monkeypatch):
    conn = ScriptedConnection(
        [
            [{"schema_id": 4, "schema_type": "AVRO", "fingerprint": "f", "fingerprint_kind": FINGERPRINT_KIND,
              "project_id": "p", "version_record_id": "r", "references": [], "created_at": NOW,
              "source_format": "avro", "format_metadata": {}}],
            [],
        ]
    )
    row = store.get_schema_by_id(database_with(monkeypatch, conn), T, 4)
    assert row["schema_id"] == 4 and row["subjects"] == []
    assert "deleted_at" not in conn.statements[0][0]


# --------------------------------------------------------------------------- routes

client = TestClient(app)
_BASE = "/v1/tenants/acme/schema-registry"


@pytest.fixture
def routes():
    """Authenticate as a tenant member and record the permission each route enforces."""
    from app.auth import validate_authentication

    seen: List[str] = []

    def _enforce(db, auth_data, resource, action, target=None):
        seen.append(f"{resource}:{action}")
        return "u1"

    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": T, "user_id": "u1"}
    with patch("app.schema_registry_routes.enforce_permission", _enforce):
        yield seen
    app.dependency_overrides.pop(validate_authentication, None)


def _version_row(**kw: Any) -> Dict[str, Any]:
    row = {"subject_id": "s1", "version": 1, "schema_id": 1, "schema_type": "AVRO", "fingerprint": "sha256:a",
           "references": [], "project_id": "p1", "version_record_id": "r1", "created_at": NOW}
    row.update(kw)
    return row


def test_register_route(routes):
    with patch("app.schema_registry_routes.register_schema", return_value={**_version_row(), "created": True}) as reg:
        resp = client.post(f"{_BASE}/subjects/orders-value/versions", json={"schema": ORDER, "schemaType": "AVRO", "strategy": "topic"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 1 and body["version"] == 1 and body["created"] is True
    assert body["schemaType"] == "AVRO" and body["versionRecordId"] == "r1"
    assert reg.call_args.kwargs["schema"] == ORDER and reg.call_args.kwargs["strategy"] == "topic"
    assert routes == ["imports:create"]


def test_register_route_maps_refusals(routes):
    err = SchemaRegistryError("subject-read-only", "read only", status_code=409)
    with patch("app.schema_registry_routes.register_schema", side_effect=err):
        resp = client.post(f"{_BASE}/subjects/s/versions", json={"schema": ORDER})
    assert resp.status_code == 409
    assert resp.json()["detail"] == {"code": "subject-read-only", "message": "read only"}


def test_attach_route(routes):
    with patch("app.schema_registry_routes.attach_catalog_item", return_value={**_version_row(), "created": True}) as att:
        resp = client.post(f"{_BASE}/subjects/orders-value/attach", json={"projectId": "item-1"})
    assert resp.status_code == 200
    assert att.call_args.kwargs["project_id"] == "item-1"
    assert routes == ["imports:edit"]


def test_subject_reads(routes):
    subject = _subject_row(version_count=1, latest_version=1)
    with patch.object(store, "list_subjects", return_value=[subject]), patch.object(
        store, "get_config", return_value={"compatibility_level": "FULL", "mode": "READWRITE"}
    ):
        body = client.get(f"{_BASE}/subjects").json()
    assert body["subjects"][0]["name"] == "orders-value"
    assert body["subjects"][0]["compatibilityLevel"] is None
    assert body["subjects"][0]["effectiveCompatibilityLevel"] == "FULL"

    with patch.object(store, "get_subject", return_value=None):
        resp = client.get(f"{_BASE}/subjects/nope")
    assert resp.status_code == 404 and resp.json()["detail"]["code"] == "subject-not-found"


def test_version_routes(routes):
    with patch.object(store, "get_subject", return_value=_subject_row()), patch.object(
        store, "list_versions", return_value=[_version_row(), _version_row(version=2, schema_id=5, version_record_id="r2")]
    ), patch.object(store, "get_version", return_value=_version_row()), patch(
        "app.schema_registry_routes.schema_text", return_value=ORDER
    ):
        listed = client.get(f"{_BASE}/subjects/orders-value/versions").json()
        latest = client.get(f"{_BASE}/subjects/orders-value/versions/latest").json()
        one = client.get(f"{_BASE}/subjects/orders-value/versions/1").json()
        bad = client.get(f"{_BASE}/subjects/orders-value/versions/zero")
    assert [v["version"] for v in listed["versions"]] == [1, 2]
    assert "schema" not in listed["versions"][0] or listed["versions"][0]["schema"] is None
    assert latest["version"] == 2 and latest["id"] == 5 and latest["schema"] == ORDER
    assert one["version"] == 1
    assert bad.status_code == 422


def test_delete_and_by_id_routes(routes):
    with patch.object(store, "soft_delete_subject", return_value=[1, 2]):
        assert client.delete(f"{_BASE}/subjects/orders-value").json() == [1, 2]
    with patch.object(store, "soft_delete_subject", return_value=None):
        assert client.delete(f"{_BASE}/subjects/orders-value").status_code == 404
    resolved = {"schema_id": 3, "schema_type": "AVRO", "fingerprint": "f", "fingerprint_kind": FINGERPRINT_KIND,
                "references": [], "project_id": "p", "version_record_id": "r", "subjects": []}
    with patch.object(store, "get_schema_by_id", return_value=resolved), patch(
        "app.schema_registry_routes.schema_text", return_value=ORDER
    ):
        body = client.get(f"{_BASE}/schemas/ids/3").json()
    assert body["id"] == 3 and body["subjects"] == [] and body["schema"] == ORDER
    assert body["fingerprintKind"] == "canonical-model"
    with patch.object(store, "get_schema_by_id", return_value=None):
        assert client.get(f"{_BASE}/schemas/ids/99").status_code == 404
    assert "imports:delete" in routes and "imports:view" in routes


def test_config_and_subject_settings_routes(routes):
    with patch.object(store, "put_config", return_value={"compatibility_level": "FULL", "mode": "READONLY"}) as put:
        body = client.put(f"{_BASE}/config", json={"compatibilityLevel": "FULL", "mode": "READONLY"}).json()
    assert body == {"compatibilityLevel": "FULL", "mode": "READONLY"}
    assert put.call_args.kwargs == {"compatibility_level": "FULL", "mode": "READONLY"}
    assert client.put(f"{_BASE}/config", json={"mode": "WRITEONLY"}).status_code == 422

    with patch.object(store, "upsert_subject", return_value=_subject_row(strategy="record")) as up, patch.object(
        store, "list_versions", return_value=[]
    ), patch.object(store, "get_config", return_value={"compatibility_level": "BACKWARD", "mode": "READWRITE"}):
        body = client.put(f"{_BASE}/subjects/orders-value", json={"strategy": "record"}).json()
    assert body["strategy"] == "record" and body["versionCount"] == 0
    assert up.call_args.kwargs["strategy"] == "record"
    assert client.put(f"{_BASE}/subjects/orders-value", json={"strategy": "record_name"}).status_code == 422
