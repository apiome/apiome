"""Push JSON Schema and Protobuf subjects to a Confluent Schema Registry — MFX-19.6 (#4183).

Pinned here, against a fake registry speaking the Confluent API (and, when
``APIOME_TEST_SCHEMA_REGISTRY_URL`` names one, a live registry):

* subject naming: one strategy for Avro, JSON Schema and Protobuf, from each format's record name;
* the JSON Schema plan: one subject per type, ``$ref``\\ s to other files as references, dependencies
  first; the bundle as one subject; refusals for a shared subject, a cycle and a document that is not JSON;
* the Protobuf plan: one subject per ``.proto`` named by its first message, imports of other files as
  references, well-known imports left to the registry; a file with no message or enum is refused;
* the push: ``schemaType`` ``JSON`` / ``PROTOBUF`` on every call (left out for Avro), references, a
  second push writing nothing, and ``compatibility_level`` set before the check (never in a dry run);
* the route ``POST /v1/export/{tenant}/schema-registry/push``: each format, the request's subject
  naming, refused options, per-format audit actions.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Mapping, Optional
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.avro_registry_push import plan_avro_push, to_registry_units
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from app.config import settings
from app.emitter import EmitResult, EmittedFile, coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_source import ExportSource
from app.main import app
from app.schema_registry_connector_source import SchemaRegistrySource
from app.schema_registry_push import (
    RegistryPushError,
    RegistryPushUnit,
    order_by_dependencies,
    push_registry_subjects,
)
from app.schema_registry_push_plans import plan_jsonschema_push, plan_protobuf_push
from app.schema_registry_subjects import registry_subject
from tests.fake_push_registry import DEFAULT_BASIC, PushRegistry

_TENANT = "550e8400-e29b-41d4-a716-446655440000"
_ACTOR = "11111111-1111-4111-8111-111111111111"
_CONNECTOR = "22222222-2222-4222-8222-222222222222"
_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_URL = "https://sr.example.test"
_CREDS = {"username": DEFAULT_BASIC[0], "password": DEFAULT_BASIC[1]}
_ROUTE = "/v1/export/acme/schema-registry/push"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


@pytest.fixture(autouse=True)
def _ssrf(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ssrf_allow_private", True)


# ---------------------------------------------------------------------------
# Models and exports
# ---------------------------------------------------------------------------


def _widgets() -> CanonicalApi:
    """``Widget`` (its ``owner`` an ``Owner``, its ``colour`` a ``Colour``), ``Owner`` and ``Colour``."""
    owner = Type(key="Owner", name="Owner", kind=TypeKind.RECORD,
                 fields=[CanonicalField(key="Owner.team", name="team", type=TypeRef(name="string"))])
    colour = Type(key="Colour", name="Colour", kind=TypeKind.ENUM,
                  enum_values=[EnumValue(key=f"Colour.{v}", name=v) for v in ("RED", "GREEN")])
    widget = Type(key="Widget", name="Widget", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string", nullable=False)),
        CanonicalField(key="Widget.owner", name="owner", type=TypeRef(name="Owner")),
        CanonicalField(key="Widget.colour", name="colour", type=TypeRef(name="Colour", nullable=False)),
    ])
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema",
                        identity=ApiIdentity(name="Widgets", namespace="acme"), types=[widget, owner, colour])


def _packages() -> CanonicalApi:
    """``acme.Widget`` referencing ``acme.common.Owner`` (which uses a well-known ``Timestamp``)."""
    owner = Type(key="acme.common.Owner", name="Owner", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="acme.common.Owner.team", name="team", type=TypeRef(name="string")),
        CanonicalField(key="acme.common.Owner.since", name="since", type=TypeRef(name="google.protobuf.Timestamp")),
    ])
    widget = Type(key="acme.Widget", name="Widget", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="acme.Widget.id", name="id", type=TypeRef(name="string", nullable=False)),
        CanonicalField(key="acme.Widget.owner", name="owner", type=TypeRef(name="acme.common.Owner")),
    ])
    return CanonicalApi(paradigm=ApiParadigm.RPC, format="protobuf",
                        identity=ApiIdentity(name="Widgets", namespace="acme"), types=[widget, owner])


def _emit(key: str, api: Optional[CanonicalApi] = None, **options: Any) -> EmitResult:
    emitter = get_emitter(key)
    return emitter().emit(api or _widgets(), opts=coerce_emit_options(emitter, options))


def _json_units(**naming: Any) -> List[RegistryPushUnit]:
    return plan_jsonschema_push(_emit("json-schema", packaging="per-type"), **naming)


def _proto_units(api: Optional[CanonicalApi] = None, **naming: Any) -> List[RegistryPushUnit]:
    return plan_protobuf_push(_emit("proto3", api or _packages()), **naming)


def _client(fake: PushRegistry, credentials: Optional[Dict[str, str]] = _CREDS) -> httpx.Client:
    connector = {"id": _CONNECTOR, "kind": "schema-registry", "name": "Prod registry", "base_url": _URL,
                 "scope": {}, "status": "active"}
    return SchemaRegistrySource(connector, credentials, transport=fake.transport()).http_client()


def _push(fake: PushRegistry, units: List[RegistryPushUnit], **kwargs: Any):
    with _client(fake) as client:
        return push_registry_subjects(client, _URL, units, credentials=_CREDS, **kwargs)


def _file(path: str, content: str) -> EmittedFile:
    return EmittedFile(path=path, content=content, media_type="text/plain")


# ---------------------------------------------------------------------------
# Subject naming — one strategy for every format
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("naming", "topic", "role", "subject"), [
    ("record_name", None, "value", "acme.Widget-value"),
    ("record_name", None, "key", "acme.Widget-key"),
    ("topic_name", "orders", "value", "orders-value"),
    ("topic_record_name", "orders", "key", "orders-acme.Widget-key"),
    ("topic_record_name", "  orders ", "value", "orders-acme.Widget-value"),
])
def test_a_subject_is_built_from_the_record_name(naming: str, topic: Optional[str], role: str, subject: str) -> None:
    assert registry_subject("acme.Widget", naming, topic, role) == subject


@pytest.mark.parametrize(("naming", "topic"), [("topic_name", None), ("topic_record_name", " "), ("bogus", "t")])
def test_a_naming_without_its_topic_or_unknown_is_refused(naming: str, topic: Optional[str]) -> None:
    with pytest.raises(ValueError):
        registry_subject("acme.Widget", naming, topic, "value")


def test_the_three_formats_name_subjects_the_same_way() -> None:
    """The same strategy over each format's record name: Avro full name, JSON title, first proto message."""
    naming = {"naming": "topic_record_name", "topic": "widgets", "role": "key"}
    avro = plan_avro_push(_emit("avro", subject_naming="topic_record_name", topic="widgets", subject_role="key"))
    json_units = _json_units(**naming)
    proto = _proto_units(_widgets(), **naming)
    for units in (avro, json_units, proto):
        for unit in units:
            assert unit.subject == f"widgets-{unit.record}-key"
    assert {u.record for u in avro} == {"acme.Widget", "acme.Owner", "acme.Colour"}
    assert {u.record for u in json_units} == {"Widget", "Owner", "Colour"}
    assert [u.record for u in proto] == ["Widget"]


# ---------------------------------------------------------------------------
# JSON Schema plan
# ---------------------------------------------------------------------------


def test_the_jsonschema_plan_is_one_subject_per_type_referenced_first() -> None:
    units = _json_units()
    assert [u.subject for u in units] == ["Colour-value", "Owner-value", "Widget-value"]
    assert {u.schema_type for u in units} == {"JSON"}
    widget = units[-1]
    assert widget.file == "Widget.schema.json"
    assert list(widget.references) == [("Colour.schema.json", "Colour-value"), ("Owner.schema.json", "Owner-value")]
    assert units[0].references == () and units[1].references == ()
    assert '"$ref":"Owner.schema.json"' in widget.schema  # compact JSON, the reference kept as written


def test_the_jsonschema_bundle_is_one_subject_named_by_its_title() -> None:
    units = plan_jsonschema_push(_emit("json-schema"))
    assert [(u.subject, u.record, u.references) for u in units] == [("Widgets-value", "Widgets", ())]


def test_a_ref_with_a_fragment_references_its_file() -> None:
    emit = EmitResult(files=[
        _file("A.schema.json", '{"title":"A","properties":{"b":{"$ref":"B.schema.json#/$defs/x"}}}'),
        _file("B.schema.json", '{"title":"B","$defs":{"x":{"type":"string"}}}'),
    ])
    units = plan_jsonschema_push(emit)
    assert [u.subject for u in units] == ["B-value", "A-value"]
    assert list(units[1].references) == [("B.schema.json", "B-value")]


def test_a_document_without_a_title_is_named_by_its_file() -> None:
    units = plan_jsonschema_push(EmitResult(files=[_file("dir/Thing.schema.json", '{"type":"object"}')]))
    assert units[0].record == "Thing" and units[0].subject == "Thing-value"


def test_jsonschema_types_on_one_topic_subject_are_refused() -> None:
    with pytest.raises(RegistryPushError) as caught:
        _json_units(naming="topic_name", topic="widgets")
    assert caught.value.code == "REGISTRY_PUSH_DUPLICATE_SUBJECT"
    assert "widgets-value" in caught.value.message


def test_jsonschema_refs_in_a_cycle_are_refused() -> None:
    emit = EmitResult(files=[
        _file("A.schema.json", '{"title":"A","properties":{"b":{"$ref":"B.schema.json"}}}'),
        _file("B.schema.json", '{"title":"B","properties":{"a":{"$ref":"A.schema.json"}}}'),
    ])
    with pytest.raises(RegistryPushError) as caught:
        plan_jsonschema_push(emit)
    assert caught.value.code == "REGISTRY_PUSH_REFERENCE_CYCLE"


@pytest.mark.parametrize(("files", "code"), [
    ([], "REGISTRY_PUSH_EMPTY"),
    ([_file("A.schema.json", "not json")], "REGISTRY_PUSH_NOT_JSON_SCHEMA"),
])
def test_a_jsonschema_export_a_registry_cannot_hold_is_refused(files: List[EmittedFile], code: str) -> None:
    with pytest.raises(RegistryPushError) as caught:
        plan_jsonschema_push(EmitResult(files=files))
    assert caught.value.code == code


def test_a_topic_strategy_without_a_topic_is_refused_by_the_plan() -> None:
    with pytest.raises(RegistryPushError) as caught:
        _json_units(naming="topic_name")
    assert caught.value.code == "REGISTRY_PUSH_SUBJECT_NAMING"


# ---------------------------------------------------------------------------
# Protobuf plan
# ---------------------------------------------------------------------------


def test_the_protobuf_plan_is_one_subject_per_file_imports_first() -> None:
    units = _proto_units()
    assert [(u.subject, u.file) for u in units] == [
        ("acme.common.Owner-value", "acme/common.proto"),
        ("acme.Widget-value", "acme.proto"),
    ]
    assert {u.schema_type for u in units} == {"PROTOBUF"}
    # The import of the other file is a reference; google/protobuf/timestamp.proto is the registry's own.
    assert units[0].references == ()
    assert list(units[1].references) == [("acme/common.proto", "acme.common.Owner-value")]
    assert 'import "google/protobuf/timestamp.proto";' in units[0].schema


def test_a_protobuf_file_is_named_by_its_first_message_else_its_first_enum() -> None:
    emit = EmitResult(files=[
        _file("a.proto",
              'syntax = "proto3";\npackage a;\nenum Kind {\n  K = 0;\n}\nmessage Box {\n  message Inner {}\n}\n'),
        _file("b.proto", 'syntax = "proto3";\nenum Only {\n  O = 0;\n}\n'),
    ])
    assert {u.file: u.record for u in plan_protobuf_push(emit)} == {"a.proto": "a.Box", "b.proto": "Only"}


def test_a_protobuf_file_with_no_message_or_enum_is_refused() -> None:
    emit = EmitResult(files=[_file("svc.proto", 'syntax = "proto3";\nservice S {\n  rpc Do (A) returns (B);\n}\n')])
    with pytest.raises(RegistryPushError) as caught:
        plan_protobuf_push(emit)
    assert caught.value.code == "REGISTRY_PUSH_NO_RECORD" and "svc.proto" in caught.value.message


def test_protobuf_files_on_one_topic_subject_are_refused() -> None:
    with pytest.raises(RegistryPushError) as caught:
        _proto_units(naming="topic_name", topic="widgets")
    assert caught.value.code == "REGISTRY_PUSH_DUPLICATE_SUBJECT"


def test_dependencies_are_ordered_first_and_a_cycle_is_refused() -> None:
    assert order_by_dependencies({"c": {"a", "b"}, "b": {"a"}, "a": set()}, lambda p: RegistryPushError("X", "")) == [
        "a", "b", "c"]
    with pytest.raises(RegistryPushError) as caught:
        order_by_dependencies({"a": {"b"}, "b": {"a"}, "z": set()}, lambda p: RegistryPushError("CYCLE", ",".join(p)))
    assert caught.value.message == "a,b"


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------


def test_a_jsonschema_push_registers_with_schema_type_json_and_references() -> None:
    fake = PushRegistry()
    results = {r.subject: r for r in _push(fake, _json_units())}
    assert {s: r.status for s, r in results.items()} == {
        "Colour-value": "registered", "Owner-value": "registered", "Widget-value": "registered"}
    widget = results["Widget-value"]
    assert widget.schema_type == "JSON" and widget.version == 1
    assert [r.model_dump() for r in widget.references] == [
        {"name": "Colour.schema.json", "subject": "Colour-value", "version": 1},
        {"name": "Owner.schema.json", "subject": "Owner-value", "version": 1},
    ]
    held = fake.subjects["Widget-value"][0]
    assert held["schemaType"] == "JSON" and held["references"] == [r.model_dump() for r in widget.references]
    assert {b["schemaType"] for b in fake.bodies("POST /subjects/Widget-value/versions")} == {"JSON"}


def test_a_protobuf_push_registers_with_schema_type_protobuf_and_its_import() -> None:
    fake = PushRegistry()
    results = _push(fake, _proto_units())
    assert [(r.subject, r.status, r.schema_type) for r in results] == [
        ("acme.common.Owner-value", "registered", "PROTOBUF"),
        ("acme.Widget-value", "registered", "PROTOBUF"),
    ]
    assert fake.subjects["acme.Widget-value"][0]["references"] == [
        {"name": "acme/common.proto", "subject": "acme.common.Owner-value", "version": 1}]
    assert fake.subjects["acme.Widget-value"][0]["schemaType"] == "PROTOBUF"


def test_an_avro_push_leaves_schema_type_out() -> None:
    fake = PushRegistry()
    _push(fake, to_registry_units(plan_avro_push(_emit("avro"))))
    assert all("schemaType" not in body for body in fake.bodies("POST /subjects/acme.Widget-value/versions"))


@pytest.mark.parametrize("units", [_json_units, _proto_units])
def test_a_second_push_writes_nothing(units) -> None:
    fake = PushRegistry()
    first = _push(fake, units())
    writes = len(fake.writes())
    second = _push(fake, units())
    assert {r.status for r in second} == {"already_registered"}
    assert [(r.schema_id, r.version) for r in second] == [(r.schema_id, r.version) for r in first]
    assert len(fake.writes()) == writes


def test_the_same_text_under_another_schema_type_is_not_already_registered() -> None:
    fake = PushRegistry({"Thing-value": ['{"title":"Thing"}']})  # held as AVRO
    unit = plan_jsonschema_push(EmitResult(files=[_file("Thing.schema.json", '{"title":"Thing"}')]))
    (result,) = _push(fake, unit)
    assert result.status == "registered" and result.version == 2


def test_a_compatibility_level_is_set_before_the_check() -> None:
    fake = PushRegistry({"Owner-value": ["{}"]})
    results = {r.subject: r for r in _push(fake, _json_units(), compatibility_level="FULL_TRANSITIVE")}
    assert fake.levels == {s: "FULL_TRANSITIVE" for s in ("Colour-value", "Owner-value", "Widget-value")}
    assert all(r.compatibility_level == "FULL_TRANSITIVE" for r in results.values())
    calls = fake.calls()
    check = "POST /compatibility/subjects/Owner-value/versions/latest"
    assert calls.index("PUT /config/Owner-value") < calls.index(check)


def test_a_dry_run_sets_no_level_and_says_so() -> None:
    fake = PushRegistry()
    results = _push(fake, _proto_units(), dry_run=True, compatibility_level="BACKWARD")
    assert fake.levels == {} and fake.writes() == []
    assert not any(c.startswith("PUT") for c in fake.calls())
    owner, widget = results
    assert owner.status == "would_register" and owner.compatibility_level == "BACKWARD"
    assert owner.messages == ["Compatibility level BACKWARD would be set; this check used the subject's current level."]
    assert widget.status == "would_register" and widget.compatibility == "unchecked"


def test_an_already_registered_subject_keeps_its_level() -> None:
    fake = PushRegistry()
    _push(fake, _json_units())
    _push(fake, _json_units(), compatibility_level="NONE")
    assert fake.levels == {}


def test_a_refused_level_fails_the_subject_and_skips_its_dependents() -> None:
    fake = PushRegistry(refuse_config={"acme.common.Owner-value"})
    owner, widget = _push(fake, _proto_units(), compatibility_level="FULL")
    assert owner.status == "failed"
    assert owner.messages == ["The schema registry answered 422 to PUT /config/acme.common.Owner-value: "
                              "error_code 42203: Invalid compatibility level"]
    assert widget.status == "skipped"
    assert fake.writes() == []


def test_an_unknown_level_is_refused() -> None:
    with pytest.raises(ValueError):
        _push(PushRegistry(), _json_units(), compatibility_level="SIDEWAYS")


def test_an_incompatible_jsonschema_is_not_registered() -> None:
    fake = PushRegistry({"Owner-value": ["{}"]}, incompatible={"Owner-value"})
    results = {r.subject: r for r in _push(fake, _json_units())}
    assert results["Owner-value"].status == "incompatible"
    assert results["Widget-value"].status == "skipped"


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


class _Route:
    """The route's collaborators, faked: the connector, its credentials, the source and the database."""

    def __init__(self, fake: PushRegistry, api: Optional[CanonicalApi] = None,
                 connector: Optional[Mapping[str, Any]] = None) -> None:
        self.fake = fake
        self.connector = dict(connector or {"id": _CONNECTOR, "tenant_id": _TENANT, "kind": "schema-registry",
                                            "name": "Prod registry", "base_url": _URL, "scope": {},
                                            "status": "active"})
        self.db = MagicMock()
        self.permission = MagicMock(return_value=_ACTOR)
        source = ExportSource(api=api or _widgets(), artifact_id="artifact-1", version_record_id="rev-1",
                              version_label="1.0.0")
        self.load = MagicMock(return_value=source)

    def __enter__(self) -> TestClient:
        module = "app.schema_registry_push_routes"
        fake = self.fake
        self._patches = [
            patch(f"{module}.enforce_permission", self.permission),
            patch(f"{module}.db", self.db),
            patch(f"{module}.store.get_connector",
                  lambda db, tenant, cid: self.connector if cid == _CONNECTOR else None),
            patch(f"{module}.unseal_connector_credentials", lambda db, cid: (dict(_CREDS), False)),
            patch(f"{module}.load_export_source", self.load),
            patch(f"{module}.SchemaRegistrySource",
                  lambda c, creds: SchemaRegistrySource(c, creds, transport=fake.transport())),
        ]
        for p in self._patches:
            p.start()
        app.dependency_overrides[validate_authentication] = lambda: _AUTH
        return TestClient(app)

    def __exit__(self, *exc: Any) -> None:
        app.dependency_overrides.clear()
        for p in reversed(self._patches):
            p.stop()


def _body(fmt: str, **overrides: Any) -> Dict[str, Any]:
    return {"format": fmt, "artifact": "artifact-1", "version": "1.0.0", "connector_id": _CONNECTOR, **overrides}


def test_the_route_pushes_json_schema_per_type_and_audits() -> None:
    route = _Route(PushRegistry())
    with route as client:
        response = client.post(_ROUTE, json=_body("json-schema"))
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"] == "json-schema" and body["summary"]["registered"] == 3
    assert [(s["subject"], s["schema_type"]) for s in body["subjects"]] == [
        ("Colour-value", "JSON"), ("Owner-value", "JSON"), ("Widget-value", "JSON")]
    assert route.permission.call_args.args[2:] == ("imports", "edit")
    audit = route.db.insert_workflow_audit.call_args.args
    assert audit[3] == "export.json_schema.pushed" and audit[6]["subjects"] == [
        "Colour-value", "Owner-value", "Widget-value"]


def test_the_route_pushes_protobuf_and_audits() -> None:
    route = _Route(PushRegistry(), api=_packages())
    with route as client:
        body = client.post(_ROUTE, json=_body("protobuf", compatibility_level="BACKWARD_TRANSITIVE")).json()
    assert [(s["subject"], s["schema_type"], s["status"]) for s in body["subjects"]] == [
        ("acme.common.Owner-value", "PROTOBUF", "registered"), ("acme.Widget-value", "PROTOBUF", "registered")]
    assert route.fake.levels == {"acme.common.Owner-value": "BACKWARD_TRANSITIVE",
                                 "acme.Widget-value": "BACKWARD_TRANSITIVE"}
    assert route.db.insert_workflow_audit.call_args.args[3] == "export.protobuf.pushed"


@pytest.mark.parametrize(("fmt", "first"), [
    ("avro", "widgets-acme.Colour-key"),
    ("json-schema", "widgets-Colour-key"),
])
def test_the_route_names_subjects_from_the_request_for_every_format(fmt: str, first: str) -> None:
    route = _Route(PushRegistry())
    with route as client:
        body = client.post(_ROUTE, json=_body(fmt, subject_naming="topic_record_name", topic="widgets",
                                              subject_role="key")).json()
    assert body["subjects"][0]["subject"] == first


def test_the_route_avro_push_is_audited_as_before() -> None:
    route = _Route(PushRegistry())
    with route as client:
        body = client.post(_ROUTE, json=_body("avro")).json()
    assert body["subjects"][0]["schema_type"] == "AVRO"
    assert route.db.insert_workflow_audit.call_args.args[3] == "export.avro.pushed"


def test_the_route_dry_run_writes_nothing() -> None:
    route = _Route(PushRegistry())
    with route as client:
        body = client.post(_ROUTE, json=_body("json-schema", dry_run=True, compatibility_level="FULL")).json()
    assert body["dry_run"] is True and body["summary"]["would_register"] == 3
    assert route.fake.writes() == [] and route.fake.levels == {}
    route.db.insert_workflow_audit.assert_not_called()


@pytest.mark.parametrize(("fmt", "overrides", "code"), [
    ("avro", {"options": {"output_syntax": "avdl"}}, "REGISTRY_PUSH_NOT_AVSC"),
    ("avro", {"options": {"subject_naming": "topic_name", "topic": "t"}}, "REGISTRY_PUSH_SUBJECT_OPTIONS"),
    ("json-schema", {"options": {"mode": "jtd"}}, "REGISTRY_PUSH_NOT_JSON_SCHEMA"),
    ("json-schema", {"subject_naming": "topic_name", "topic": "widgets"}, "REGISTRY_PUSH_DUPLICATE_SUBJECT"),
])
def test_the_route_refuses_what_a_registry_cannot_take(fmt: str, overrides: Dict[str, Any], code: str) -> None:
    route = _Route(PushRegistry())
    with route as client:
        response = client.post(_ROUTE, json=_body(fmt, **overrides))
    assert response.status_code == 422 and response.json()["detail"]["code"] == code
    assert route.fake.requests == []


@pytest.mark.parametrize("overrides", [
    {"subject_naming": "topic_name"},
    {"compatibility_level": "SIDEWAYS"},
    {"format": "xml"},
])
def test_the_route_validates_the_request(overrides: Dict[str, Any]) -> None:
    route = _Route(PushRegistry())
    with route as client:
        response = client.post(_ROUTE, json={**_body("protobuf"), **overrides})
    assert response.status_code == 422
    route.load.assert_not_called()


def test_the_route_refuses_another_kind_of_connector() -> None:
    route = _Route(PushRegistry(), connector={"id": _CONNECTOR, "kind": "kong", "name": "Gateway"})
    with route as client:
        response = client.post(_ROUTE, json=_body("protobuf"))
    assert response.status_code == 422 and response.json()["detail"]["code"] == "REGISTRY_PUSH_CONNECTOR_KIND"
    assert "a Protobuf push" in response.json()["detail"]["message"]
    route.load.assert_not_called()


def test_the_route_refuses_without_permission() -> None:
    route = _Route(PushRegistry())
    route.permission.side_effect = HTTPException(status_code=403, detail="Forbidden")
    with route as client:
        response = client.post(_ROUTE, json=_body("json-schema"))
    assert response.status_code == 403 and route.fake.requests == []


# ---------------------------------------------------------------------------
# Optional: a live registry
# ---------------------------------------------------------------------------

_LIVE = os.environ.get("APIOME_TEST_SCHEMA_REGISTRY_URL")


@pytest.mark.skipif(not _LIVE, reason="set APIOME_TEST_SCHEMA_REGISTRY_URL to push to a live registry")
@pytest.mark.parametrize("units", [_json_units, _proto_units])
def test_a_live_registry_registers_json_schema_and_protobuf_subjects(units) -> None:
    """Register under a fresh topic, then push again: every subject comes back already registered."""
    topic = f"apiome-test-{uuid.uuid4().hex[:8]}"
    plan = units(naming="topic_record_name", topic=topic)
    credentials = {k: v for k, v in {
        "username": os.environ.get("APIOME_TEST_SCHEMA_REGISTRY_USERNAME"),
        "password": os.environ.get("APIOME_TEST_SCHEMA_REGISTRY_PASSWORD"),
    }.items() if v}
    connector = {"id": _CONNECTOR, "kind": "schema-registry", "name": "Live", "base_url": _LIVE, "scope": {},
                 "status": "active"}
    source = SchemaRegistrySource(connector, credentials or None)
    with source.http_client() as client:
        first = push_registry_subjects(client, source.registry_url, plan, credentials=credentials)
        assert {r.status for r in first} == {"registered"}, [r.messages for r in first]
        second = push_registry_subjects(client, source.registry_url, plan, credentials=credentials)
    assert {r.status for r in second} == {"already_registered"}
