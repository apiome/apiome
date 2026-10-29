"""Collection fidelity pack — MFX-31.2 (#4290).

:class:`app.client_collection_fidelity.ExampleCollectionFidelityRulePack` (Postman's pack) names
every trade a collection makes of a schema for an example, each as its own report item with its
reason. Acceptance:

* a rich OpenAPI source enumerates schema → example ``APPROX`` items with reasons;
* event and RPC sources surface ``DROP`` items, and the MFX-2.4 advisory fires.

Also covered, rule by rule: unions → one example, response schemas → example responses, status
ranges, generated values (``SYNTH``), streaming, auth beyond the collection's auth types, field
constraints, a native source, and the writer's matching ``union-representative-example`` loss.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import pytest

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
    Service,
    StreamingMode,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.client_collection_emit import reachable_unions
from app.fidelity_advisory import build_export_advisory
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind
from app.postman_emitter import PostmanEmitter

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


def _items(api: CanonicalApi) -> Dict[str, List]:
    out: Dict[str, List] = {}
    for item in compute_lossiness_for_emitter(api, PostmanEmitter()).items:
        out.setdefault(item.construct_key, []).append(item)
    return out


def _by_mapping(api: CanonicalApi, key: str) -> Dict[str, object]:
    return {item.target_mapping: item for item in _items(api)[key]}


def _corpus_api(path: Path, fmt: str) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _types() -> List[Type]:
    return [
        Type(key="Cat", name="Cat", kind=TypeKind.RECORD, fields=[
            CanonicalField(key="Cat.name", name="name", type=TypeRef(name="string", nullable=False), field_number=1,
                           constraints=Constraints(max_length=20)),
        ]),
        Type(key="Dog", name="Dog", kind=TypeKind.RECORD, fields=[
            CanonicalField(key="Dog.bark", name="bark", type=TypeRef(name="bool"), field_number=1),
        ]),
        Type(key="Pet", name="Pet", kind=TypeKind.UNION, union_members=["Cat", "Dog"]),
        Type(key="Owner", name="Owner", kind=TypeKind.RECORD, fields=[
            CanonicalField(key="Owner.pet", name="pet", type=TypeRef(name="Pet"), field_number=1),
        ]),
    ]


def _op(**kw) -> Operation:
    defaults = dict(key="POST /owners", name="Add owner", kind=OperationKind.REQUEST_RESPONSE, http_method="POST",
                    http_path="/owners", messages=[
                        Message(key="POST /owners#request", role=MessageRole.REQUEST, payload=TypeRef(name="Owner"),
                                content_types=["application/json"]),
                        Message(key="POST /owners#response.201", role=MessageRole.RESPONSE, status_code="201",
                                payload=TypeRef(name="Owner"), content_types=["application/json"]),
                        Message(key="POST /owners#response.204", role=MessageRole.RESPONSE, status_code="204"),
                        Message(key="POST /owners#response.4XX", role=MessageRole.RESPONSE, status_code="4XX",
                                payload=TypeRef(name="Cat")),
                    ])
    defaults.update(kw)
    return Operation(**defaults)


def _api(*operations: Operation, **kw) -> CanonicalApi:
    defaults = dict(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="Pets"), title="Pets",
                    services=[Service(key="svc", name="svc", operations=list(operations) or [_op()])], types=_types())
    defaults.update(kw)
    return CanonicalApi(**defaults)


# ===========================================================================
# Acceptance
# ===========================================================================


@pytest.mark.parametrize("name", ["30-openapi-3.0-petstore.yaml", "31-paths-comprehensive.yaml"])
def test_a_rich_openapi_source_enumerates_schema_to_example_items_with_reasons(name: str) -> None:
    api = _corpus_api(_EXAMPLES / "openapi" / name, "openapi")
    items = [item for item in compute_lossiness_for_emitter(api, PostmanEmitter()).items]
    bodies = [i for i in items if i.target_mapping == "request schema → example body"]
    responses = [i for i in items if i.target_mapping == "response schema → example response"]
    assert bodies and responses
    assert all(i.kind is LossinessKind.APPROX and "not enforced" in i.message for i in bodies)
    assert all(i.kind is LossinessKind.APPROX and "infers the schemas again" in i.message for i in responses)
    assert any(i.kind is LossinessKind.SYNTH for i in items)


def test_an_anyof_corpus_names_its_union() -> None:
    # The import keeps 23's `anyOf` as a union type; 22's `oneOf` schemas are flattened to records on
    # import, so by export time there is no union left to report.
    api = _corpus_api(_EXAMPLES / "openapi" / "23-advanced-anyof-flexible.yaml", "openapi")
    unions = [i for i in compute_lossiness_for_emitter(api, PostmanEmitter()).items
              if i.target_mapping == "union / oneOf → one representative example"]
    assert unions and all("example shows one of them" in i.message for i in unions)
    assert any("SearchCriteria" in i.message for i in unions)


def test_event_and_rpc_sources_surface_drops_and_the_advisory_fires() -> None:
    rpc = Operation(key="svc.GetPet", name="GetPet", kind=OperationKind.REQUEST_RESPONSE)
    event = Operation(key="petAdded", name="petAdded", kind=OperationKind.PUBLISH, channel_ref="pets")
    api = _api(rpc, event, channels=[Channel(key="pets", name="pets", address="pets")])
    items = _items(api)
    for key in ("svc.GetPet", "petAdded", "pets"):
        assert [i.kind for i in items[key]] == [LossinessKind.DROP], key
    advisory = build_export_advisory(compute_lossiness_for_emitter(api, PostmanEmitter()), "Postman")
    assert advisory.show and advisory.dropped >= 3
    assert "Postman" in advisory.message


@pytest.mark.parametrize(("path", "fmt"), [("asyncapi", "asyncapi"), ("protobuf", "protobuf")])
def test_event_and_rpc_corpus_sources(path: str, fmt: str) -> None:
    files = sorted((_EXAMPLES / path).glob("*.yaml" if fmt == "asyncapi" else "*.proto"))
    if not files:
        pytest.skip("corpus not checked out")
    api = _corpus_api(files[0], fmt)
    report = compute_lossiness_for_emitter(api, PostmanEmitter())
    assert report.kind_counts.get("drop", 0) > 0
    assert build_export_advisory(report, "Postman").show


# ===========================================================================
# Rule by rule
# ===========================================================================


def test_each_trade_on_an_operation_is_its_own_item() -> None:
    items = _by_mapping(_api(), "POST /owners")
    assert {mapping: item.kind for mapping, item in items.items()} == {
        "operation → saved request": LossinessKind.APPROX,
        "request schema → example body": LossinessKind.APPROX,
        "response schema → example response": LossinessKind.APPROX,
        "status range → dropped": LossinessKind.DROP,
        "union / oneOf → one representative example": LossinessKind.APPROX,
        "schema → generated example values": LossinessKind.SYNTH,
    }
    assert "(Owner)" in items["request schema → example body"].message
    assert "201" in items["response schema → example response"].message
    assert "204" not in items["response schema → example response"].message  # no body, nothing approximated
    assert "4XX" in items["status range → dropped"].message
    assert "Pet" in items["union / oneOf → one representative example"].message


def test_a_bodyless_operation_has_only_the_request_item() -> None:
    op = Operation(key="GET /health", name="Health", kind=OperationKind.REQUEST_RESPONSE, http_method="GET",
                   http_path="/health")
    assert list(_by_mapping(_api(op), "GET /health")) == ["operation → saved request"]


def test_streaming_is_dropped() -> None:
    op = _op(streaming=StreamingMode.SERVER)
    assert _by_mapping(_api(op), "POST /owners")["streaming → dropped"].kind is LossinessKind.DROP


@pytest.mark.parametrize(
    ("schemes", "expected"),
    [
        (["bearer"], {}),
        (["oauth2"], {}),
        (["openIdConnect"], {"openIdConnect → bearer token": LossinessKind.APPROX}),
        (["cookie"], {"auth → credential header": LossinessKind.APPROX}),
        (["mutualTLS"], {"auth scheme → dropped": LossinessKind.DROP}),
        (["bearer", "apiKey"], {"several auth schemes → the first": LossinessKind.APPROX}),
    ],
)
def test_auth_beyond_the_collection_auth_types(schemes: List[str], expected: Dict[str, LossinessKind]) -> None:
    op = Operation(key="GET /me", name="Me", kind=OperationKind.REQUEST_RESPONSE, http_method="GET", http_path="/me",
                   extras={"security": schemes})
    items = _by_mapping(_api(op), "GET /me")
    found = {mapping: item.kind for mapping, item in items.items() if "auth" in mapping or "bearer" in mapping}
    assert found == expected


def test_field_constraints_are_not_enforced() -> None:
    item = next(i for i in _items(_api())["Cat.name"] if i.target_mapping == "constraints → not enforced")
    assert item.kind is LossinessKind.APPROX and "example satisfies them" in item.message


def test_a_type_declaration_stays_a_drop() -> None:
    assert [i.kind for i in _items(_api())["Owner"]] == [LossinessKind.DROP]


def test_the_single_verdict_is_the_most_severe() -> None:
    from app.postman_emitter import PostmanFidelityRulePack

    pack = PostmanFidelityRulePack(PostmanEmitter.capability_profile(), "Postman collection")
    api = _api()
    pack.evaluate(api)
    assert pack.operation_verdict(api.operations()[0]).kind is LossinessKind.DROP  # the 4XX status range


def test_a_postman_source_reports_nothing() -> None:
    api = _api().model_copy(update={"format": "postman"})
    assert all(item.kind is LossinessKind.OK for item in compute_lossiness_for_emitter(api, PostmanEmitter()).items)


# ===========================================================================
# Union reach and the writer's matching loss
# ===========================================================================


def test_reachable_unions_follows_fields_items_and_inline_schemas() -> None:
    api = _api()
    owner = Message(key="m", role=MessageRole.REQUEST, payload=TypeRef(item=TypeRef(name="Owner")))
    assert reachable_unions(api, owner) == ["Pet"]
    inline = Message(key="m", role=MessageRole.REQUEST,
                     payload_schema={"type": "object", "properties": {"a": {"oneOf": [{"type": "string"}]}}})
    assert reachable_unions(api, inline) == ["inline oneOf"]
    assert reachable_unions(api, Message(key="m", role=MessageRole.REQUEST, payload=TypeRef(name="Dog"))) == []


def test_the_writer_reports_the_representative_example() -> None:
    losses = [loss for loss in PostmanEmitter().emit(_api()).losses if loss.subject == "union-representative-example"]
    assert losses and all(loss.pointer == "POST /owners" for loss in losses)
