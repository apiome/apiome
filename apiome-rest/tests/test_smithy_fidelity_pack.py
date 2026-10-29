"""Smithy fidelity pack — MFX-20.2 (#3915).

:class:`app.smithy_emitter.SmithyFidelityRulePack` predicts, before an emit, what the Smithy writer
reports, construct by construct:

* **trait coverage** — constraints Smithy has traits for (``@length`` / ``@range`` / ``@pattern`` /
  ``@uniqueItems``) are carried; the rest (``multipleOf``, an enum list, a length on a number) are a
  ``DROP``, as are defaults that do not fit and a Smithy source's traits imported without their value;
  renames, inlined aliases and wrapped payloads are an ``APPROX``;
* **protocol-binding gaps** — an HTTP operation keeps ``@http`` (``OK``, its mapping names the binding);
  unbindable routes, GET bodies, cookie / transport-header parameters and non-record errors are a ``DROP``;
* **the document** — a non-Smithy source's root (namespace, title, description, version, servers) and
  agent descriptors.

The prediction agrees with the losses the writer records on emit.
"""

from __future__ import annotations

from typing import Dict, List

from app.canonical_model import (
    AgentDescriptor,
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    EnumValue,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import LossKind
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind, LossinessSeverity, LossItem
from app.smithy_emitter import SmithyEmitter


def _field(owner: str, name: str, ref: str = "string", *, nullable: bool = True,
           constraints: Constraints = None, default=None) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=TypeRef(name=ref, nullable=nullable),
                          constraints=constraints, default=default)


def _record(name: str, *fields: CanonicalField) -> Type:
    return Type(key=name, name=name, kind=TypeKind.RECORD, fields=list(fields))


def _api(*, types=(), operations=(), fmt: str = "openapi-3.1", **kw) -> CanonicalApi:
    services = [Service(key="pets", name="PetService", operations=list(operations))] if operations else []
    defaults = dict(paradigm=ApiParadigm.REST, format=fmt, identity=ApiIdentity(name="Shop", namespace="com.acme"),
                    types=list(types), services=services)
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _op(key: str, method: str = None, path: str = None, *, params=(), messages=(), **kw) -> Operation:
    return Operation(key=key, name=kw.pop("name", "op"), kind=kw.pop("kind", OperationKind.REQUEST_RESPONSE),
                     http_method=method, http_path=path, parameters=list(params), messages=list(messages), **kw)


def _report(api: CanonicalApi) -> Dict[str, List[LossItem]]:
    items: Dict[str, List[LossItem]] = {}
    for item in compute_lossiness_for_emitter(api, SmithyEmitter()).items:
        items.setdefault(item.construct_key, []).append(item)
    return items


def _kinds(items: List[LossItem]) -> List[LossinessKind]:
    return [item.kind for item in items]


# ===========================================================================
# Trait coverage
# ===========================================================================


def test_constraints_with_a_trait_are_carried() -> None:
    pet = _record("Pet",
                  _field("Pet", "name", nullable=False, constraints=Constraints(min_length=1, max_length=40,
                                                                                pattern="^[a-z]+$")),
                  _field("Pet", "age", "integer", constraints=Constraints(minimum=0, maximum=30)),
                  _field("Pet", "kind", default="cat"))
    report = _report(_api(types=[pet]))
    assert "Pet.name" not in report and "Pet.age" not in report and "Pet.kind" not in report
    assert report["Pet"][0].kind is LossinessKind.OK
    assert report["Pet"][0].target_mapping == "structure Pet"


def test_constraints_without_a_trait_are_dropped() -> None:
    pet = _record("Pet",
                  _field("Pet", "weight", "number", constraints=Constraints(multiple_of=0.5, minimum=0)),
                  _field("Pet", "size", "integer", constraints=Constraints(max_length=3)),
                  _field("Pet", "color", constraints=Constraints(enum=["red", "blue"])))
    report = _report(_api(types=[pet]))
    for key, word in (("Pet.weight", "multipleOf"), ("Pet.size", "length"), ("Pet.color", "enum")):
        (item,) = report[key]
        assert item.kind is LossinessKind.DROP and item.severity is LossinessSeverity.WARN
        assert item.target_mapping == "constraint-dropped" and word in item.message


def test_a_default_that_does_not_fit_is_dropped() -> None:
    report = _report(_api(types=[_record("Pet", _field("Pet", "age", "integer", default="old"))]))
    assert [(i.kind, i.target_mapping) for i in report["Pet.age"]] == [(LossinessKind.DROP, "default-dropped")]


def test_a_renamed_member_and_enum_value_are_cosmetic_approximations() -> None:
    status = Type(key="Status", name="Status", kind=TypeKind.ENUM,
                  enum_values=[EnumValue(key="Status.in-progress", name="in-progress", value="in-progress")])
    report = _report(_api(types=[_record("Pet", _field("Pet", "order-id")), status]))
    (member,) = report["Pet.order-id"]
    assert member.kind is LossinessKind.APPROX and member.severity is LossinessSeverity.INFO
    assert member.target_mapping == "renamed-member" and "@jsonName" in member.message
    (value,) = report["Status"]
    assert value.target_mapping == "renamed-enum-member"


def test_an_alias_of_a_named_shape_is_inlined() -> None:
    alias = Type(key="PetRef", name="PetRef", kind=TypeKind.ALIAS, aliased=TypeRef(name="Pet"))
    report = _report(_api(types=[_record("Pet", _field("Pet", "id")), alias]))
    (item,) = report["PetRef"]
    assert item.kind is LossinessKind.APPROX and item.target_mapping == "alias → inlined"


def test_an_unknown_scalar_is_reported_on_its_field() -> None:
    report = _report(_api(types=[_record("User", _field("User", "id", "ID"))]))
    (item,) = report["User.id"]
    assert item.kind is LossinessKind.APPROX and item.target_mapping == "unknown-type"
    assert "" not in report or all(i.target_mapping != "unknown-type" for i in report[""])


def test_a_required_cycle_is_reported_on_the_field() -> None:
    a = _record("A", _field("A", "b", "B", nullable=False))
    b = _record("B", _field("B", "a", "A", nullable=False))
    report = _report(_api(types=[a, b]))
    cycle = [item for key in ("A.b", "B.a") for item in report.get(key, [])]
    assert [item.target_mapping for item in cycle] == ["recursive-member-optional"]


def test_a_smithy_source_trait_without_its_value_is_dropped() -> None:
    field = _field("Pay", "amount")
    field.extras["smithy_traits"] = ["length", "required"]
    report = _report(_api(types=[_record("Pay", field)], fmt="smithy"))
    assert [(i.kind, i.target_mapping) for i in report["Pay.amount"]] == [
        (LossinessKind.DROP, "trait-value-unknown")]
    assert "" not in report


def test_a_field_number_is_dropped_as_info() -> None:
    field = _field("Pet", "id").model_copy(update={"field_number": 3})
    (item,) = _report(_api(types=[_record("Pet", field)]))["Pet.id"]
    assert item.kind is LossinessKind.DROP and item.severity is LossinessSeverity.INFO


# ===========================================================================
# Protocol-binding gaps
# ===========================================================================


def test_an_http_operation_keeps_its_binding() -> None:
    op = _op("GET /pets/{id}", "GET", "/pets/{id}", name="getPet",
             params=[Parameter(key="GET /pets/{id}#path.id", name="id", location=ParameterLocation.PATH,
                               type=TypeRef(name="string"), required=True)])
    (item,) = _report(_api(operations=[op]))["GET /pets/{id}"]
    assert item.kind is LossinessKind.OK
    assert item.target_mapping == "operation getPet @http(GET /pets/{id})"


def test_an_rpc_operation_is_carried_without_a_binding() -> None:
    (item,) = _report(_api(operations=[_op("Pets.list", name="ListPets")]))["Pets.list"]
    assert item.kind is LossinessKind.OK and item.target_mapping == "operation ListPets"


def test_parameters_smithy_cannot_bind_are_dropped_on_their_operation() -> None:
    def param(name: str, location: ParameterLocation) -> Parameter:
        return Parameter(key=f"GET /pets#{location.value}.{name}", name=name, location=location,
                         type=TypeRef(name="string"))

    op = _op("GET /pets", "GET", "/pets", name="listPets",
             params=[param("session", ParameterLocation.COOKIE), param("Authorization", ParameterLocation.HEADER),
                     param("limit", ParameterLocation.QUERY)])
    items = _report(_api(operations=[op]))["GET /pets"]
    assert _kinds(items) == [LossinessKind.DROP, LossinessKind.DROP]
    assert {i.severity for i in items} == {LossinessSeverity.CRITICAL}
    assert all(i.target_mapping == "parameter-dropped" for i in items)
    assert any("session" in i.message for i in items) and any("Authorization" in i.message for i in items)


def test_a_get_body_an_unbindable_route_and_a_non_record_error_are_reported() -> None:
    pet = _record("Pet", _field("Pet", "id"))
    get = _op("GET /pets", "GET", "/pets", name="listPets", messages=[
        Message(key="GET /pets#request", role=MessageRole.REQUEST, payload=TypeRef(name="Pet")),
        Message(key="GET /pets#400", role=MessageRole.ERROR, status_code="400", payload=TypeRef(name="string")),
    ])
    odd = _op("GET /files/{id}.json", "GET", "/files/{id}.json", name="getFile")
    report = _report(_api(types=[pet], operations=[get, odd]))
    assert sorted(i.target_mapping for i in report["GET /pets"]) == ["body-dropped", "error-dropped"]
    (route,) = report["GET /files/{id}.json"]
    assert route.kind is LossinessKind.DROP and route.target_mapping == "http-binding-dropped"
    assert route.severity is LossinessSeverity.WARN


def test_event_operations_and_channels_are_dropped() -> None:
    event = _op("onPet", name="onPet", kind=OperationKind.SUBSCRIBE)
    api = _api(operations=[event], channels=[Channel(key="pets", name="pets", address="pets")])
    report = _report(api)
    assert [(i.kind, i.target_mapping) for i in report["onPet"]] == [(LossinessKind.DROP, "event-operation-dropped")]
    assert _kinds(report["pets"]) == [LossinessKind.DROP]


# ===========================================================================
# The document
# ===========================================================================


def test_a_non_smithy_root_is_reported() -> None:
    api = _api(types=[_record("Pet", _field("Pet", "id"))], operations=[_op("Pets.list", name="ListPets")],
               title="Pet Store", description="Pets.", version="1.0.0",
               servers=[Server(url="https://api.example.com")])
    mappings = {i.target_mapping: i.kind for i in _report(api)[""]}
    assert mappings == {
        "document → namespace com.acme": LossinessKind.APPROX,
        "title → dropped": LossinessKind.DROP,
        "description → dropped": LossinessKind.DROP,
        "version → service version": LossinessKind.APPROX,
        "servers → dropped": LossinessKind.DROP,
    }


def test_a_version_without_a_service_is_dropped() -> None:
    report = _report(_api(types=[_record("Pet", _field("Pet", "id"))], version="2"))
    assert LossinessKind.DROP in [i.kind for i in report[""] if i.target_mapping == "version → dropped"]


def test_agents_are_dropped() -> None:
    api = _api(types=[_record("Pet", _field("Pet", "id"))], fmt="smithy",
               agents=[AgentDescriptor(key="helper", name="helper", protocol="a2a")])
    assert [(i.kind, i.target_mapping) for i in _report(api)[""]] == [(LossinessKind.DROP, "agents → dropped")]


# ===========================================================================
# Prediction agrees with the writer
# ===========================================================================


def test_every_writer_loss_is_predicted() -> None:
    pet = _record("Pet", _field("Pet", "order-id", constraints=Constraints(multiple_of=2)),
                  _field("Pet", "age", "integer", default="old"))
    get = _op("GET /pets", "GET", "/pets", name="listPets",
              params=[Parameter(key="GET /pets#cookie.s", name="s", location=ParameterLocation.COOKIE,
                                type=TypeRef(name="string"))],
              messages=[Message(key="GET /pets#request", role=MessageRole.REQUEST, payload=TypeRef(name="Pet"))])
    api = _api(types=[pet], operations=[get])
    predicted = {(item.target_mapping, item.kind) for items in _report(api).values() for item in items}
    for loss in SmithyEmitter().emit(api).losses:
        kind = LossinessKind.DROP if loss.kind is LossKind.NA else LossinessKind.APPROX
        assert (loss.subject, kind) in predicted, loss
