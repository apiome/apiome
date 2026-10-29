"""TypeSpec fidelity pack — MFX-15.2 (#3894).

:class:`app.typespec_emitter.TypeSpecFidelityRulePack` predicts, before an emit, what the TypeSpec writer
reports. This step adds:

* **non-REST losses** — a source of another paradigm is reported at the root as reframed to HTTP; an
  operation without an HTTP binding names its kind (GraphQL query / mutation / subscription, one-way, RPC)
  and its POST route; a subscription or a stream is one request and response; event messages and a
  second request are dropped;
* **decorator coverage** — tags (``@tag``), parameter and header docs (``@doc``) and deprecations
  (``#deprecated``), ``enum`` constraints (a union of literals) and server-variable enums are written and
  not reported; a response's own description, a type's namespace and the identity id are reported.

The prediction agrees with the losses the writer records, and the TypeSpec reader reads ``@tag`` back.
"""

from __future__ import annotations

from typing import Dict, List

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Server,
    ServerVariable,
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import LossKind
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind, LossinessSeverity, LossItem
from app.roundtrip_matrix import reimport_emitted
from app.typespec_emitter import TypeSpecEmitter
from app.typespec_import_source import TypeSpecImportSource


def _field(owner: str, name: str, ref: str = "string", **kw) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=TypeRef(name=ref), **kw)


def _record(name: str, *fields: CanonicalField, **kw) -> Type:
    return Type(key=name, name=name, kind=TypeKind.RECORD, fields=list(fields), **kw)


def _api(*, types=(), operations=(), paradigm=ApiParadigm.REST, fmt: str = "openapi-3.1", **kw) -> CanonicalApi:
    services = [Service(key="svc", name="Shop", operations=list(operations))] if operations else []
    defaults = dict(paradigm=paradigm, format=fmt, identity=ApiIdentity(name="Shop"), title="Shop",
                    types=list(types), services=services)
    defaults.update(kw)
    return CanonicalApi(**defaults)


def _op(key: str, method: str = None, path: str = None, **kw) -> Operation:
    return Operation(key=key, name=kw.pop("name", key.split(".")[-1]),
                     kind=kw.pop("kind", OperationKind.REQUEST_RESPONSE), http_method=method, http_path=path, **kw)


def _report(api: CanonicalApi) -> Dict[str, List[LossItem]]:
    items: Dict[str, List[LossItem]] = {}
    for item in compute_lossiness_for_emitter(api, TypeSpecEmitter()).items:
        items.setdefault(item.construct_key, []).append(item)
    return items


def _text(api: CanonicalApi) -> str:
    return TypeSpecEmitter().emit(api).files[0].content


# ===========================================================================
# Non-REST losses
# ===========================================================================


def test_a_non_rest_source_is_reported_as_reframed_to_http() -> None:
    api = _api(types=[_record("Pet", _field("Pet", "id"))], paradigm=ApiParadigm.GRAPH, fmt="graphql")
    mappings = {item.target_mapping: item for item in _report(api)[""]}
    assert mappings["graph → REST"].kind is LossinessKind.APPROX
    assert "POST routes" in mappings["graph → REST"].message
    rest = _report(_api(types=[_record("Pet", _field("Pet", "id"))]))
    assert all("REST" not in (item.target_mapping or "") for item in rest[""])


def test_operations_without_http_name_their_kind_and_route() -> None:
    ops = [_op("Query.pets", name="pets", kind=OperationKind.QUERY),
           _op("Mutation.addPet", name="addPet", kind=OperationKind.MUTATION),
           _op("Pets.ping", name="ping", kind=OperationKind.ONE_WAY),
           _op("Pets.get", name="get")]
    report = _report(_api(operations=ops, paradigm=ApiParadigm.GRAPH, fmt="graphql"))
    messages = {key: report[key][0].message for key in ("Query.pets", "Mutation.addPet", "Pets.ping", "Pets.get")}
    assert "GraphQL query 'Query.pets' is written as POST /Shop/pets" in messages["Query.pets"]
    assert "GraphQL mutation" in messages["Mutation.addPet"]
    assert "one-way operation" in messages["Pets.ping"] and "empty 204" in messages["Pets.ping"]
    assert "RPC operation 'Pets.get'" in messages["Pets.get"]
    assert all(report[key][0].kind is LossinessKind.APPROX for key in messages)


def test_subscriptions_and_streams_are_one_request_and_response() -> None:
    ops = [_op("Subscription.onPet", name="onPet", kind=OperationKind.SUBSCRIPTION),
           _op("Pets.watch", name="watch", streaming=StreamingMode.SERVER)]
    report = _report(_api(operations=ops, paradigm=ApiParadigm.GRAPH, fmt="graphql"))
    sub = {item.target_mapping: item for item in report["Subscription.onPet"]}
    assert sub["streaming-dropped"].kind is LossinessKind.DROP and "GraphQL subscription" in sub[
        "streaming-dropped"].message
    assert "rpc-as-http" in sub
    watch = {item.target_mapping: item.message for item in report["Pets.watch"]}
    assert "server-streaming" in watch["streaming-dropped"]


def test_event_messages_and_a_second_request_are_dropped() -> None:
    op = _op("POST /pets", "POST", "/pets", name="add", messages=[
        Message(key="POST /pets#request", role=MessageRole.REQUEST, payload=TypeRef(name="string")),
        Message(key="POST /pets#request2", role=MessageRole.REQUEST, payload=TypeRef(name="integer")),
        Message(key="POST /pets#event", role=MessageRole.EVENT, payload=TypeRef(name="string")),
    ])
    items = [item for item in _report(_api(operations=[op]))["POST /pets"] if item.target_mapping == "message-dropped"]
    assert len(items) == 2
    assert any("'POST /pets#event' (event)" in i.message for i in items)
    assert any("'POST /pets#request2' (request)" in i.message for i in items)


# ===========================================================================
# Decorator coverage
# ===========================================================================


def test_tags_docs_deprecations_and_enum_literals_are_written_not_reported() -> None:
    op = _op("GET /pets", "GET", "/pets", name="list", tags=["pets", "read"], parameters=[
        Parameter(key="GET /pets#query.sort", name="sort", location=ParameterLocation.QUERY,
                  type=TypeRef(name="string"), description="Sort order.", default="name",
                  constraints=Constraints(enum=["name", "age"])),
        Parameter(key="GET /pets#query.old", name="old", location=ParameterLocation.QUERY, type=TypeRef(name="string"),
                  deprecated=True),
    ], messages=[
        Message(key="GET /pets#request", role=MessageRole.REQUEST, headers=[
            CanonicalField(key="GET /pets#request.X-Trace", name="X-Trace", type=TypeRef(name="string"),
                           description="Trace id.")]),
        Message(key="GET /pets#200", role=MessageRole.RESPONSE, status_code="200", payload=TypeRef(name="string"),
                headers=[CanonicalField(key="GET /pets#200.X-Rate", name="X-Rate", type=TypeRef(name="integer"),
                                        description="Rate left.", deprecated=True)]),
    ])
    pet = _record("Pet", _field("Pet", "level", "integer", constraints=Constraints(enum=[1, 2])))
    api = _api(types=[pet], operations=[op],
               servers=[Server(url="https://{env}.example.com", description="S",
                               variables=[ServerVariable(name="env", default="prod", enum=["prod", "dev"],
                                                         description="The env.")])])
    text = _text(api)
    assert '@tag("pets") @tag("read") @get @route("/pets") list(' in text
    assert '@query @doc("Sort order.") sort?: "name" | "age" = "name"' in text
    assert '#deprecated "Deprecated."\n    @query old?: string' in text
    assert '@header("X-Trace") @doc("Trace id.") xTrace?: string' in text
    assert '#deprecated "Deprecated."\n    @header("X-Rate") @doc("Rate left.") xRate?: int32' in text
    assert "level?: 1 | 2;" in text
    assert '{ @doc("The env.") `env`?: "prod" | "dev" = "prod" }' in text  # `env` is reserved
    report = _report(api)
    assert [item.kind for item in report["GET /pets"]] == [LossinessKind.OK]
    assert "Pet.level" not in report


def test_constraints_beside_an_enum_are_reported() -> None:
    pet = _record("Pet", _field("Pet", "code", constraints=Constraints(enum=["a", "b"], max_length=1)))
    (item,) = _report(_api(types=[pet]))["Pet.code"]
    assert item.kind is LossinessKind.DROP and "maxLength" in item.message and "enum" not in item.message.split(
        "decorator for ")[1].split(";")[0]


def test_response_descriptions_are_reported_as_info() -> None:
    op = _op("GET /pets", "GET", "/pets", name="list", messages=[
        Message(key="GET /pets#200", role=MessageRole.RESPONSE, status_code="200", payload=TypeRef(name="string"),
                description="The pets."),
        Message(key="GET /pets#404", role=MessageRole.ERROR, status_code="404", description="None."),
    ])
    (item,) = _report(_api(operations=[op]))["GET /pets"]
    assert item.kind is LossinessKind.DROP and item.severity is LossinessSeverity.INFO
    assert item.target_mapping == "response-description-dropped" and "200, 404" in item.message


def test_a_flattened_namespace_and_the_identity_id_are_reported() -> None:
    api = _api(types=[_record("Pet", _field("Pet", "id"), namespace="other.ns")],
               identity=ApiIdentity(name="Shop", namespace="com.acme", id="https://example.com/shop.json"))
    report = _report(api)
    (flattened,) = report["Pet"]
    assert flattened.target_mapping == "namespace-flattened" and flattened.severity is LossinessSeverity.INFO
    root = {item.target_mapping: item for item in report[""]}
    assert root["identity id → dropped"].kind is LossinessKind.DROP
    same = _api(types=[_record("Pet", _field("Pet", "id"), namespace="com.acme")],
                identity=ApiIdentity(name="Shop", namespace="com.acme"))
    assert _report(same)["Pet"][0].kind is LossinessKind.OK


def test_graphql_ids_are_strings_without_a_loss() -> None:
    assert "User.id" not in _report(_api(types=[_record("User", _field("User", "id", "ID"))]))


# ===========================================================================
# Agreement with the writer; the reader reads tags back
# ===========================================================================


def test_every_writer_loss_is_predicted() -> None:
    ops = [_op("Subscription.onPet", name="onPet", kind=OperationKind.SUBSCRIPTION),
           _op("GET /pets", "GET", "/pets", name="list", messages=[
               Message(key="GET /pets#200", role=MessageRole.RESPONSE, status_code="200",
                       payload=TypeRef(name="string"), description="Pets.")])]
    api = _api(types=[_record("Pet", _field("Pet", "id"), namespace="x.y")], operations=ops,
               paradigm=ApiParadigm.GRAPH, fmt="graphql")
    predicted = {(item.target_mapping, item.kind) for items in _report(api).values() for item in items}
    for loss in TypeSpecEmitter().emit(api).losses:
        kind = LossinessKind.DROP if loss.kind is LossKind.NA else LossinessKind.APPROX
        assert (loss.subject, kind) in predicted, loss


def test_tags_round_trip_through_the_reader() -> None:
    op = _op("GET /pets", "GET", "/pets", name="list", tags=["pets", 'say "hi"'])
    api = _api(operations=[op])
    back = reimport_emitted(TypeSpecImportSource(), TypeSpecEmitter().emit(api), multi_file=False)
    (reread,) = list(back.operations())
    assert reread.tags == ["pets", 'say "hi"']
