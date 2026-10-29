"""JSON Schema emitter — MFX-21.1 (#4126).

Covers, in order:

* the 2020-12 bundle from a typed (non-JSON-Schema) source: every type in ``$defs``, scalars as JSON
  types, constraints as keywords, enums as their JSON values, the root ``$ref`` — validated against
  the metaschema and with instance documents;
* per-type packaging: one file per type, cross-file ``$ref`` s, several files (a zip with a manifest);
* the ``id_base`` option;
* draft-07 / draft-04 downgrades: valid against the older metaschema, keywords rewritten or dropped
  and recorded;
* a JSON Schema source re-emitted unchanged when nothing asks for a change;
* :func:`app.jsonschema_emitter.validate_jsonschema_document` rejecting a schema its metaschema rejects.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from jsonschema import Draft4Validator, Draft7Validator, Draft202012Validator
from referencing import Registry, Resource

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import LossKind
from app.export_job_engine import build_export_zip
from app.import_source import get_import_source
from app.jsonschema_drafts import DRAFT_URIS, dialect_of
from app.jsonschema_emitter import JsonSchemaEmitOptions, JsonSchemaEmitter, validate_jsonschema_document

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


# ===========================================================================
# Helpers
# ===========================================================================


def _field(owner: str, name: str, ref: TypeRef, **kw) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref, **kw)


def _orders_api(**identity) -> CanonicalApi:
    """A protobuf-flavoured model: canonical scalar names, numbered enums, a union, a map."""
    order = Type(
        key="shop.Order", name="Order", kind=TypeKind.RECORD,
        fields=[
            _field("shop.Order", "id", TypeRef(name="i64", nullable=False)),
            _field("shop.Order", "sku", TypeRef(name="string", nullable=False),
                   constraints=Constraints(pattern="^[A-Z]{3}-[0-9]+$", max_length=20)),
            _field("shop.Order", "quantity", TypeRef(name="i32", nullable=False),
                   constraints=Constraints(minimum=1, exclusive_maximum=100)),
            _field("shop.Order", "note", TypeRef(name="string")),
            _field("shop.Order", "status", TypeRef(name="shop.Status", nullable=False), deprecated=True),
            _field("shop.Order", "lines", TypeRef(item=TypeRef(name="shop.Line"), nullable=False)),
            _field("shop.Order", "payment", TypeRef(name="shop.Payment")),
            _field("shop.Order", "tags", TypeRef(name="shop.Tags")),
        ],
    )
    line = Type(key="shop.Line", name="Line", kind=TypeKind.RECORD,
                fields=[_field("shop.Line", "price", TypeRef(name="double", nullable=False))])
    status = Type(key="shop.Status", name="Status", kind=TypeKind.ENUM, enum_values=[
        EnumValue(key="shop.Status.OPEN", name="OPEN", value=0),
        EnumValue(key="shop.Status.SHIPPED", name="SHIPPED", value=1),
    ])
    card = Type(key="shop.Card", name="Card", kind=TypeKind.RECORD,
                fields=[_field("shop.Card", "number", TypeRef(name="string", nullable=False))])
    cash = Type(key="shop.Cash", name="Cash", kind=TypeKind.RECORD,
                fields=[_field("shop.Cash", "currency", TypeRef(name="string", nullable=False))])
    payment = Type(key="shop.Payment", name="Payment", kind=TypeKind.UNION,
                   union_members=["shop.Card", "shop.Cash"])
    tags = Type(key="shop.Tags", name="Tags", kind=TypeKind.MAP,
                key_type=TypeRef(name="string"), value_type=TypeRef(name="string"))
    return CanonicalApi(
        paradigm=ApiParadigm.RPC, format="protobuf", title="Order",
        identity=ApiIdentity(name="Order", **identity),
        types=[order, line, status, card, cash, payment, tags],
    )


def _emit(api: CanonicalApi, **opts):
    return JsonSchemaEmitter().emit(api, opts=JsonSchemaEmitOptions(**opts))


def _documents(result) -> Dict[str, Dict[str, Any]]:
    return {f.path: json.loads(f.content) for f in result.files}


def _only(result) -> Dict[str, Any]:
    (document,) = _documents(result).values()
    return document


# ===========================================================================
# 2020-12 bundle
# ===========================================================================


def test_a_typed_source_becomes_a_valid_2020_12_bundle() -> None:
    result = _emit(_orders_api())
    assert [f.path for f in result.files] == ["Order.schema.json"]
    document = _only(result)
    Draft202012Validator.check_schema(document)
    assert document["$schema"] == DRAFT_URIS["2020-12"]
    assert document["$ref"] == "#/$defs/Order"
    assert list(document["$defs"]) == ["Order", "Line", "Status", "Card", "Cash", "Payment", "Tags"]


def test_scalars_constraints_enums_unions_and_maps() -> None:
    defs = _only(_emit(_orders_api()))["$defs"]
    order = defs["Order"]
    assert order["required"] == ["id", "sku", "quantity", "status", "lines"]
    props = order["properties"]
    assert props["id"] == {"type": "integer", "format": "int64"}
    assert props["sku"] == {"type": "string", "pattern": "^[A-Z]{3}-[0-9]+$", "maxLength": 20}
    assert props["quantity"] == {"type": "integer", "format": "int32", "minimum": 1, "exclusiveMaximum": 100}
    assert props["status"] == {"$ref": "#/$defs/Status", "deprecated": True}
    assert props["lines"] == {"type": "array", "items": {"$ref": "#/$defs/Line"}}
    # A protobuf enum's JSON form carries the name, not the tag.
    assert defs["Status"] == {"type": "string", "enum": ["OPEN", "SHIPPED"]}
    assert defs["Payment"] == {"oneOf": [{"$ref": "#/$defs/Card"}, {"$ref": "#/$defs/Cash"}]}
    assert defs["Tags"] == {"type": "object", "additionalProperties": {"type": "string"}}


def test_instances_validate_against_the_bundle() -> None:
    validator = Draft202012Validator(_only(_emit(_orders_api())))
    good = {"id": 1, "sku": "ABC-1", "quantity": 3, "status": "OPEN", "lines": [{"price": 2.5}],
            "payment": {"number": "4111"}, "tags": {"a": "b"}}
    assert validator.is_valid(good)
    assert not validator.is_valid({**good, "status": 0})
    assert not validator.is_valid({**good, "sku": "abc"})
    assert not validator.is_valid({**good, "quantity": 100})
    assert not validator.is_valid({k: v for k, v in good.items() if k != "lines"})


def test_a_numeric_enum_stays_numeric() -> None:
    level = Type(key="Level", name="Level", kind=TypeKind.ENUM, enum_values=[
        EnumValue(key="Level.1", name="1", value=1), EnumValue(key="Level.2", name="2", value=2),
    ])
    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="openapi", identity=ApiIdentity(name="L"),
                       types=[level])
    assert _only(_emit(api))["$defs"]["Level"] == {"type": "integer", "enum": [1, 2]}


def test_colliding_type_names_get_distinct_defs_keys() -> None:
    a = Type(key="v1.Pet", name="Pet", kind=TypeKind.RECORD)
    b = Type(key="v2.Pet", name="Pet", kind=TypeKind.RECORD)
    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="protobuf", identity=ApiIdentity(name="Pets"),
                       types=[a, b])
    assert sorted(_only(_emit(api))["$defs"]) == ["v1.Pet", "v2.Pet"]


def test_an_unmapped_scalar_is_written_as_any_and_recorded() -> None:
    thing = Type(key="Thing", name="Thing", kind=TypeKind.RECORD,
                 fields=[_field("Thing", "blob", TypeRef(name="Geometry", nullable=False))])
    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="avro", identity=ApiIdentity(name="Thing"),
                       types=[thing])
    result = _emit(api)
    assert _only(result)["$defs"]["Thing"]["properties"]["blob"] == {}
    assert any(loss.subject == "unmapped-scalar" and "Geometry" in loss.detail for loss in result.losses)


def test_operations_are_dropped_and_recorded() -> None:
    api = _orders_api()
    api.services.append(Service(key="Shop", name="Shop", operations=[
        Operation(key="Shop.Get", name="Get", kind=OperationKind.REQUEST_RESPONSE),
    ]))
    result = _emit(api)
    assert any(loss.kind is LossKind.NA and loss.subject == "services-dropped" for loss in result.losses)
    assert "Get" not in result.files[0].content


# ===========================================================================
# Per-type packaging and id_base
# ===========================================================================


def test_per_type_writes_one_valid_file_per_type_with_file_refs() -> None:
    result = _emit(_orders_api(), packaging="per-type")
    documents = _documents(result)
    assert sorted(documents) == sorted(f"{name}.schema.json" for name in
                                       ("Order", "Line", "Status", "Card", "Cash", "Payment", "Tags"))
    for document in documents.values():
        Draft202012Validator.check_schema(document)
        assert "$defs" not in document
    order = documents["Order.schema.json"]
    assert order["title"] == "Order"
    assert order["properties"]["lines"]["items"] == {"$ref": "Line.schema.json"}


def test_per_type_files_resolve_each_other_through_id_base() -> None:
    result = _emit(_orders_api(), packaging="per-type", id_base="https://example.com/schemas/")
    documents = _documents(result)
    assert documents["Order.schema.json"]["$id"] == "https://example.com/schemas/Order.schema.json"
    registry = Registry().with_resources(
        (doc["$id"], Resource.from_contents(doc)) for doc in documents.values()
    )
    validator = Draft202012Validator(documents["Order.schema.json"], registry=registry)
    good = {"id": 1, "sku": "ABC-1", "quantity": 3, "status": "OPEN", "lines": [{"price": 2.5}]}
    assert validator.is_valid(good)
    assert not validator.is_valid({**good, "lines": [{"price": "x"}]})


def test_per_type_downloads_as_a_zip_with_a_manifest() -> None:
    import io
    import zipfile

    result = _emit(_orders_api(), packaging="per-type")
    archive = zipfile.ZipFile(io.BytesIO(build_export_zip(result, "json-schema")))
    names = set(archive.namelist())
    assert "manifest.json" in names and "Order.schema.json" in names


def test_id_base_sets_the_bundle_id() -> None:
    document = _only(_emit(_orders_api(), id_base="urn:example:schemas"))
    assert document["$id"] == "urn:example:schemas/Order.schema.json"


@pytest.mark.parametrize("bad", ["schemas", "/relative/path", "example.com"])
def test_id_base_must_be_an_absolute_uri(bad: str) -> None:
    with pytest.raises(ValueError):
        JsonSchemaEmitOptions(id_base=bad)


def test_unknown_options_are_rejected() -> None:
    with pytest.raises(ValueError):
        JsonSchemaEmitOptions(draft="2019-09")
    with pytest.raises(ValueError):
        JsonSchemaEmitOptions(packaging="zip")


# ===========================================================================
# Draft downgrades
# ===========================================================================


def test_draft_07_is_valid_and_rewrites_defs_and_ref_siblings() -> None:
    result = _emit(_orders_api(), draft="draft-07")
    document = _only(result)
    Draft7Validator.check_schema(document)
    assert document["$schema"] == DRAFT_URIS["draft-07"]
    assert "$defs" not in document and "Order" in document["definitions"]
    assert document["allOf"] == [{"$ref": "#/definitions/Order"}]
    # `deprecated` is 2019-09: the sibling of `$ref` goes, so the reference stands alone again.
    assert document["definitions"]["Order"]["properties"]["status"] == {"$ref": "#/definitions/Status"}
    dropped = [loss for loss in result.losses if loss.subject == "keyword-dropped"]
    assert [loss.pointer for loss in dropped] == ["#/$defs/Order/properties/status"]
    validator = Draft7Validator(document)
    assert validator.is_valid({"id": 1, "sku": "ABC-1", "quantity": 3, "status": "OPEN", "lines": []})
    assert not validator.is_valid({"id": 1, "sku": "ABC-1", "quantity": 3, "status": "NOPE", "lines": []})


def test_draft_04_is_valid_and_rewrites_exclusive_bounds_and_id() -> None:
    result = _emit(_orders_api(), draft="draft-04", id_base="https://example.com/s")
    document = _only(result)
    Draft4Validator.check_schema(document)
    assert document["id"] == "https://example.com/s/Order.schema.json" and "$id" not in document
    quantity = document["definitions"]["Order"]["properties"]["quantity"]
    assert quantity == {"type": "integer", "format": "int32", "minimum": 1, "maximum": 100,
                        "exclusiveMaximum": True}
    validator = Draft4Validator(document)
    good = {"id": 1, "sku": "ABC-1", "quantity": 99, "status": "OPEN", "lines": []}
    assert validator.is_valid(good)
    assert not validator.is_valid({**good, "quantity": 100})


def test_draft_04_keeps_the_stricter_bound_and_records_the_other() -> None:
    box = Type(key="Box", name="Box", kind=TypeKind.RECORD, fields=[
        _field("Box", "size", TypeRef(name="integer", nullable=False),
               constraints=Constraints(minimum=5, exclusive_minimum=1)),
    ])
    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="avro", identity=ApiIdentity(name="Box"),
                       types=[box])
    result = _emit(api, draft="draft-04")
    size = _only(result)["definitions"]["Box"]["properties"]["size"]
    assert size == {"type": "integer", "minimum": 5}
    assert any(loss.subject == "exclusive-bound-merged" for loss in result.losses)


def test_a_property_named_like_a_keyword_is_not_rewritten() -> None:
    thing = Type(key="Thing", name="Thing", kind=TypeKind.RECORD, fields=[
        _field("Thing", "deprecated", TypeRef(name="bool", nullable=False)),
        _field("Thing", "$id", TypeRef(name="string", nullable=False)),
    ])
    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="avro", identity=ApiIdentity(name="Thing"),
                       types=[thing])
    for draft in ("draft-07", "draft-04"):
        props = _only(_emit(api, draft=draft))["definitions"]["Thing"]["properties"]
        assert set(props) == {"deprecated", "$id"}


# ===========================================================================
# JSON Schema sources
# ===========================================================================


def _json_schema_item(name: str) -> CanonicalApi:
    """A JSON Schema example imported as the catalog does: with its raw document."""
    adapter = get_import_source("json-schema")
    text = (_EXAMPLES / "json-schema" / name).read_text()
    return adapter.normalize(adapter.parse(text, source_label=name), include_raw=True)


def test_a_json_schema_source_is_re_emitted_unchanged_by_default() -> None:
    api = _json_schema_item("03-multiple-defs.json")
    result = _emit(api)
    assert _only(result) == api.raw["source"]
    assert not result.losses


def test_a_json_schema_source_is_rebuilt_for_another_draft_or_packaging() -> None:
    api = _json_schema_item("03-multiple-defs.json")
    downgraded = _emit(api, draft="draft-07")
    assert dialect_of(_only(downgraded)) == "draft-07"
    assert any(loss.subject == "rebuilt-from-canonical" for loss in downgraded.losses)
    assert len(_emit(api, packaging="per-type").files) == len(api.types)


@pytest.mark.parametrize("name", sorted(p.name for p in (_EXAMPLES / "json-schema").glob("*.json")))
@pytest.mark.parametrize("draft", ["2020-12", "draft-07", "draft-04"])
def test_every_json_schema_example_exports_to_every_draft(name: str, draft: str) -> None:
    for emitted in _emit(_json_schema_item(name), draft=draft).files:
        validate_jsonschema_document(emitted.content)


# ===========================================================================
# Validation helper
# ===========================================================================


def test_validate_rejects_a_schema_its_metaschema_rejects() -> None:
    with pytest.raises(ValueError, match="Not a valid JSON Schema"):
        validate_jsonschema_document(json.dumps({"$schema": DRAFT_URIS["2020-12"], "type": "i32"}))
    with pytest.raises(ValueError):
        validate_jsonschema_document(json.dumps({"$schema": DRAFT_URIS["draft-04"], "exclusiveMinimum": 3}))
    validate_jsonschema_document(json.dumps({"$schema": DRAFT_URIS["draft-07"], "type": "integer"}))


def test_dialect_of_reads_the_schema_uri() -> None:
    cases: List[tuple] = [
        ({"$schema": "https://json-schema.org/draft/2020-12/schema"}, "2020-12"),
        ({"$schema": "http://json-schema.org/draft-07/schema#"}, "draft-07"),
        ({"$schema": "https://json-schema.org/draft-07/schema"}, "draft-07"),
        ({"$schema": "http://json-schema.org/draft-04/schema#"}, "draft-04"),
        ({"$schema": "https://example.com/custom"}, None),
        ({}, None),
    ]
    for document, draft in cases:
        assert dialect_of(document) == draft


# ===========================================================================
# Fidelity report (what the bundle changes about the model as a whole)
# ===========================================================================


def test_the_report_names_the_rewrite_and_each_renamed_type() -> None:
    from app.fidelity_engine import compute_lossiness_for_emitter
    from app.lossiness import LossinessKind

    report = compute_lossiness_for_emitter(_orders_api(), JsonSchemaEmitter)
    by_key = {item.construct_key: item for item in report.items}
    assert by_key[""].kind is LossinessKind.APPROX and "written as JSON Schema" in by_key[""].message
    assert by_key["shop.Order"].kind is LossinessKind.APPROX
    assert by_key["shop.Order"].target_mapping == "shop.Order → $defs/Order"


def test_a_json_schema_source_is_not_reported_as_rewritten_or_renamed() -> None:
    from app.fidelity_engine import compute_lossiness_for_emitter

    report = compute_lossiness_for_emitter(_json_schema_item("03-multiple-defs.json"), JsonSchemaEmitter)
    assert not [item for item in report.items if item.construct_key == ""]
    assert not [item for item in report.items if "$defs/" in (item.target_mapping or "")]


# ===========================================================================
# Fidelity pack — MFX-21.2 (#4127)
# ===========================================================================


def _report(api: CanonicalApi, **options):
    from app.fidelity_engine import compute_lossiness_for_emitter

    return compute_lossiness_for_emitter(api, JsonSchemaEmitter, options=options or None)


def _with_surface() -> CanonicalApi:
    api = _orders_api()
    api.services.append(Service(key="Shop", name="Shop", operations=[
        Operation(key="Shop.Get", name="Get", kind=OperationKind.REQUEST_RESPONSE),
        Operation(key="Shop.Put", name="Put", kind=OperationKind.REQUEST_RESPONSE),
    ]))
    from app.canonical_model import Channel

    api.channels.append(Channel(key="orders", name="orders", address="orders"))
    return api


def test_an_operation_bearing_source_carries_the_critical_types_only_advisory_with_counts() -> None:
    from app.lossiness import LossinessKind, LossinessSeverity

    report = _report(_with_surface())
    advisory = next(item for item in report.items if item.target_mapping == "types-only")
    assert advisory.construct_key == ""
    assert (advisory.kind, advisory.severity) == (LossinessKind.DROP, LossinessSeverity.CRITICAL)
    assert "1 service(s) with 2 operation(s) and 1 channel(s) are not exported" in advisory.message
    for key in ("Shop.Get", "Shop.Put", "orders"):
        item = next(i for i in report.items if i.construct_key == key)
        assert (item.kind, item.severity) == (LossinessKind.DROP, LossinessSeverity.CRITICAL)
    emitted = _emit(_with_surface())
    assert any(advisory.message == loss.detail for loss in emitted.losses)


def test_a_types_only_source_has_no_advisory() -> None:
    assert not [i for i in _report(_orders_api()).items if i.target_mapping == "types-only"]


def _downgrades(report) -> Dict[str, List[str]]:
    subjects = {"keyword-dropped", "exclusive-bound-merged", "exclusive-bound-boolean", "const-as-enum",
                "prefix-items-as-tuple", "unevaluated-as-additional"}
    out: Dict[str, List[str]] = {}
    for item in report.items:
        if item.target_mapping in subjects:
            out.setdefault(item.construct_key, []).append(item.target_mapping)
    return out


def test_2020_12_reports_no_downgrade() -> None:
    assert _downgrades(_report(_orders_api())) == {}


def test_draft_07_enumerates_each_dropped_keyword_on_its_field() -> None:
    from app.lossiness import LossinessKind

    report = _report(_orders_api(), draft="draft-07")
    assert _downgrades(report) == {"shop.Order.status": ["keyword-dropped"]}
    item = next(i for i in report.items if i.target_mapping == "keyword-dropped")
    assert item.kind is LossinessKind.DROP and "`deprecated`" in item.message


def test_draft_04_enumerates_drops_and_approximations() -> None:
    from app.lossiness import LossinessKind, LossinessSeverity

    report = _report(_orders_api(), draft="draft-04")
    assert _downgrades(report) == {
        "shop.Order.quantity": ["exclusive-bound-boolean"],
        "shop.Order.status": ["keyword-dropped"],
    }
    bound = next(i for i in report.items if i.target_mapping == "exclusive-bound-boolean")
    assert (bound.kind, bound.severity) == (LossinessKind.APPROX, LossinessSeverity.INFO)


def test_the_report_matches_the_export_losses_for_the_same_options() -> None:
    options = {"draft": "draft-04", "packaging": "per-type"}
    emitted = {loss.detail for loss in _emit(_orders_api(), **options).losses
               if loss.subject in {"keyword-dropped", "exclusive-bound-boolean"}}
    reported = {i.message for i in _report(_orders_api(), **options).items
                if i.target_mapping in {"keyword-dropped", "exclusive-bound-boolean"}}
    assert emitted == reported and len(reported) == 2


def test_per_type_and_bundle_downgrades_land_on_the_same_constructs() -> None:
    bundle = _downgrades(_report(_orders_api(), draft="draft-04"))
    per_type = _downgrades(_report(_orders_api(), draft="draft-04", packaging="per-type"))
    assert bundle == per_type


def test_invalid_options_fall_back_to_the_defaults() -> None:
    assert _downgrades(_report(_orders_api(), draft="draft-99")) == {}


def test_format_is_reported_as_an_annotation() -> None:
    from app.lossiness import LossinessKind, LossinessSeverity

    report = _report(_orders_api())
    notes = {i.construct_key: i for i in report.items if (i.target_mapping or "").startswith("format ")}
    assert set(notes) == {"shop.Order.id", "shop.Order.quantity", "shop.Line.price"}
    assert notes["shop.Order.id"].target_mapping == "format int64 → annotation"
    assert (notes["shop.Order.id"].kind, notes["shop.Order.id"].severity) == (
        LossinessKind.APPROX, LossinessSeverity.INFO,
    )


def test_other_targets_ignore_options() -> None:
    from app.fidelity_engine import compute_lossiness_for_emitter
    from app.xsd_emitter import XsdEmitter

    plain = compute_lossiness_for_emitter(_orders_api(), XsdEmitter)
    with_options = compute_lossiness_for_emitter(_orders_api(), XsdEmitter, options={"xsd_version": "1.1"})
    assert plain == with_options


# ===========================================================================
# Draft downgrader — keywords the emitter does not write itself
# ===========================================================================


def _downgrade(schema: Dict[str, Any], draft: str):
    from app.emitter import LossTracker
    from app.jsonschema_drafts import downgrade_schema

    losses = LossTracker()
    out = downgrade_schema({"$schema": DRAFT_URIS["2020-12"], **schema}, draft, losses)
    return out, {(loss.subject, loss.pointer) for loss in losses.records()}


def test_prefix_items_become_the_tuple_form() -> None:
    out, losses = _downgrade({"type": "array", "prefixItems": [{"type": "string"}], "items": {"type": "integer"}},
                             "draft-07")
    assert out["items"] == [{"type": "string"}] and out["additionalItems"] == {"type": "integer"}
    Draft7Validator.check_schema(out)
    assert losses == {("prefix-items-as-tuple", "#")}


def test_unevaluated_properties_and_dynamic_refs() -> None:
    out, losses = _downgrade({"type": "object", "properties": {"a": {"type": "string"}},
                              "unevaluatedProperties": False, "$dynamicAnchor": "node"}, "draft-07")
    assert out["additionalProperties"] is False and "$dynamicAnchor" not in out
    assert losses == {("unevaluated-as-additional", "#"), ("keyword-dropped", "#")}
    out, losses = _downgrade({"allOf": [{"type": "object"}], "unevaluatedProperties": False}, "draft-07")
    assert "unevaluatedProperties" not in out and "additionalProperties" not in out
    assert losses == {("keyword-dropped", "#")}


def test_dependent_keywords_become_dependencies() -> None:
    out, losses = _downgrade({"dependentRequired": {"a": ["b"]}, "dependentSchemas": {"c": {"required": ["d"]}}},
                             "draft-04")
    assert out["dependencies"] == {"a": ["b"], "c": {"required": ["d"]}}
    Draft4Validator.check_schema(out)
    assert not losses


def test_draft_04_const_and_newer_keywords() -> None:
    out, losses = _downgrade({"properties": {"kind": {"const": "pet", "readOnly": True}},
                              "if": {"required": ["a"]}, "then": {"required": ["b"]}}, "draft-04")
    assert out["properties"]["kind"] == {"enum": ["pet"]} and "if" not in out
    Draft4Validator.check_schema(out)
    assert ("const-as-enum", "#/properties/kind") in losses
    assert ("keyword-dropped", "#/properties/kind") in losses and ("keyword-dropped", "#") in losses
