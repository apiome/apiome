"""Thrift fidelity pack — MFX-25.3 (#4153).

Thrift has no validation facets, no null, no HTTP or event bindings and no struct inheritance;
:class:`app.thrift_emitter.ThriftFidelityRulePack` enumerates each loss, and the writer records the same:

* **constraints** become a ``// constraints: …`` comment above the field, parameter or typedef
  (``APPROX``, and the comment is really written);
* **nullability** — a nullable field is written ``optional`` (``APPROX``);
* **HTTP bindings** — the method is an ``APPROX`` and its verb / path / status codes a separate ``DROP``;
* **events** — event operations and channels are ``DROP`` (the writer used to skip them silently);
* **inheritance** — a record that extends others is written flattened (``APPROX``);
* **field ids** — a field with no id gets one (``SYNTH``);
* the keys a re-import gives back: a renamed type / service / method or the ``<Method>Request`` struct
  are ``DROP`` + ``SYNTH`` pairs, so the round trip of a cross-format source is fully explained;
* a Thrift source reports none of it.

Acceptance: a rich REST source enumerates its losses; an event source flags its channel ``DROP``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Dict, List

import pytest

from app import thrift_compile
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind, LossItem
from app.thrift_emitter import ThriftEmitter, inherited_parents
from app.thrift_roundtrip import round_trip_thrift, spot_check_thrift

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


@pytest.fixture(autouse=True)
def no_compiler(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Thrift compiler is not in CI; thriftpy2 and the reader still check the output."""
    monkeypatch.setattr(thrift_compile, "thrift_available", lambda: False)


def _field(owner: str, name: str, ref: str = "string", *, nullable: bool = False, **kw) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=TypeRef(name=ref, nullable=nullable), **kw)


def _corpus_api(path: Path, fmt: str) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _rich_rest_api() -> CanonicalApi:
    """A REST API with constraints, a nullable field, inheritance, HTTP operations and no field ids."""
    pet = Type(
        key="Pet", name="Pet", kind=TypeKind.RECORD,
        fields=[
            _field("Pet", "id", "integer", constraints=Constraints(minimum=1)),
            _field("Pet", "name", constraints=Constraints(min_length=1, max_length=40, pattern="^[A-Za-z ]+$")),
            _field("Pet", "tag", nullable=True),
        ],
    )
    dog = Type(
        key="Dog", name="Dog", kind=TypeKind.RECORD, extras={"typescript_extends": ["Pet"]},
        fields=[_field("Dog", "id", "integer"), _field("Dog", "breed")],
    )
    get_pet = Operation(
        key="GET /pets/{petId}", name="getPet", kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET", http_path="/pets/{petId}",
        parameters=[Parameter(key="GET /pets/{petId}#path.petId", name="petId", location=ParameterLocation.PATH,
                              type=TypeRef(name="integer"), required=True, constraints=Constraints(minimum=1))],
        messages=[Message(key="GET /pets/{petId}#response.200", role=MessageRole.RESPONSE, status_code="200",
                          payload=TypeRef(name="Pet"))],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="Pets"), title="Pets",
        version="1.0", services=[Service(key="default", name="default", operations=[get_pet])], types=[pet, dog],
    )


def _event_api() -> CanonicalApi:
    publish = Operation(key="publishPetAdopted", name="publishPetAdopted", kind=OperationKind.PUBLISH)
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT, format="asyncapi-3.0", identity=ApiIdentity(name="Pet events"),
        services=[Service(key="events", name="events", operations=[publish])],
        channels=[Channel(key="pets.adopted", name="pets.adopted", address="pets.adopted")],
        types=[Type(key="Adopted", name="Adopted", kind=TypeKind.RECORD, fields=[_field("Adopted", "petId")])],
    )


def _items(api: CanonicalApi) -> Dict[str, List[LossItem]]:
    out: Dict[str, List[LossItem]] = {}
    for item in compute_lossiness_for_emitter(api, ThriftEmitter).items:
        out.setdefault(item.construct_key, []).append(item)
    return out


def _kinds(items: Dict[str, List[LossItem]], key: str) -> List[LossinessKind]:
    return [item.kind for item in items.get(key, [])]


# ===========================================================================
# Acceptance: a rich REST source enumerates its losses
# ===========================================================================


def test_constraints_are_written_as_a_comment_and_reported_as_approx() -> None:
    api = _rich_rest_api()
    items = _items(api)
    (constraint,) = [i for i in items["Pet.name"] if i.target_mapping == "constraints → comment"]
    assert constraint.kind is LossinessKind.APPROX
    assert "min length 1; max length 40; pattern ^[A-Za-z ]+$" in constraint.message
    result = ThriftEmitter().emit(api)
    text = result.files[0].content
    assert "  // constraints: min length 1; max length 40; pattern ^[A-Za-z ]+$\n" in text
    assert "  // constraints: >= 1\n" in text  # the path parameter, in the synthesized request struct
    assert {loss.pointer for loss in result.losses if loss.subject == "constraints-as-comment"} >= {
        "Pet.id", "Pet.name", "GET /pets/{petId}#path.petId"
    }
    assert spot_check_thrift({result.files[0].path: text}) == [], "the comments keep the IDL parseable"


def test_a_nullable_field_is_written_optional_and_reported() -> None:
    api = _rich_rest_api()
    items = _items(api)
    assert [i.target_mapping for i in items["Pet.tag"] if i.kind is LossinessKind.APPROX] == ["nullable → optional"]
    result = ThriftEmitter().emit(api)
    assert "optional string tag" in result.files[0].content
    assert any(loss.subject == "nullable-as-optional" and loss.pointer == "Pet.tag" for loss in result.losses)
    assert not [i for i in items["Pet.name"] if i.target_mapping == "nullable → optional"]


def test_an_http_operation_is_a_method_and_its_binding_a_drop() -> None:
    api = _rich_rest_api()
    items = _items(api)["GET /pets/{petId}"]
    mappings = {item.target_mapping: item.kind for item in items}
    assert mappings["HTTP operation → RPC method"] is LossinessKind.APPROX
    assert mappings["HTTP binding → dropped"] is LossinessKind.DROP
    drop = next(i for i in items if i.target_mapping == "HTTP binding → dropped")
    assert "method, path, status codes and parameter locations" in drop.message
    result = ThriftEmitter().emit(api)
    assert any(loss.subject == "http-binding-dropped" for loss in result.losses)


def test_inheritance_is_flattened_and_reported() -> None:
    api = _rich_rest_api()
    assert inherited_parents(api.types[1]) == ["Pet"]
    (flattened,) = [i for i in _items(api)["Dog"] if i.target_mapping == "inheritance → flattened struct"]
    assert flattened.kind is LossinessKind.APPROX and "from Pet" in flattened.message
    result = ThriftEmitter().emit(api)
    assert any(loss.subject == "inheritance-flattened" and loss.pointer == "Dog" for loss in result.losses)


def test_field_ids_are_synthesized() -> None:
    items = _items(_rich_rest_api())
    for key in ("Pet.id", "Pet.name", "Pet.tag", "Dog.breed"):
        assert LossinessKind.SYNTH in _kinds(items, key)


def test_the_keys_a_re_import_gives_back_are_dropped_and_synthesized() -> None:
    items = _items(_rich_rest_api())
    # `default` is a reserved word: the service is declared `default_`, and the method keyed by it.
    assert LossinessKind.DROP in _kinds(items, "default")
    assert _kinds(items, "default_") == [LossinessKind.SYNTH]
    assert _kinds(items, "default_.getPet") == [LossinessKind.SYNTH]
    assert _kinds(items, "GetPetRequest") == [LossinessKind.SYNTH]
    root = items[""]
    assert [i.kind for i in root] == [LossinessKind.DROP] and "title, version, description" in root[0].message


def test_a_rich_rest_round_trip_is_fully_explained() -> None:
    report = asyncio.run(round_trip_thrift(_rich_rest_api()))
    assert report.valid and report.diff is not None and report.diff.entries
    assert report.unexplained == [] and report.overclaims == []


# ===========================================================================
# Acceptance: an event source flags its channel DROP
# ===========================================================================


def test_an_event_source_flags_its_channel_and_operations_drop() -> None:
    api = _event_api()
    items = _items(api)
    assert _kinds(items, "pets.adopted") == [LossinessKind.DROP]
    assert _kinds(items, "publishPetAdopted") == [LossinessKind.DROP]
    result = ThriftEmitter().emit(api)
    subjects = {(loss.subject, loss.pointer) for loss in result.losses}
    assert ("channel-dropped", "pets.adopted") in subjects
    assert ("event-operation-dropped", "publishPetAdopted") in subjects
    assert "publishPetAdopted" not in result.files[0].content


# ===========================================================================
# A Thrift source reports none of it; corpus round trips stay explained
# ===========================================================================


def test_a_thrift_source_reports_no_document_rename_or_nullability_loss() -> None:
    api = _corpus_api(_EXAMPLES / "thrift" / "01-user-service.thrift", "thrift")
    items = compute_lossiness_for_emitter(api, ThriftEmitter).items
    mappings = {item.target_mapping for item in items}
    assert not mappings & {"document → IDL file", "nullable → optional", "HTTP binding → dropped",
                           "constraints → comment", "inheritance → flattened struct"}
    assert all(item.kind is not LossinessKind.SYNTH for item in items)


@pytest.mark.parametrize("path,fmt", [
    ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    ("protobuf/02-grpc-service.proto", "protobuf"),
    ("graphql/06-union-types.graphql", "graphql"),
    ("wsdl/02-order-service.wsdl", "wsdl"),
])
def test_cross_format_corpus_round_trips_are_explained(path: str, fmt: str) -> None:
    api = _corpus_api(_EXAMPLES / path, fmt)
    report = asyncio.run(round_trip_thrift(api))
    assert report.valid
    assert report.unexplained == [] and report.overclaims == [], (report.unexplained, report.overclaims)
