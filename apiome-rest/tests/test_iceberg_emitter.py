"""Apache Iceberg schema emitter — MFX-36.3 (#4319).

Pins :class:`app.iceberg_emitter.IcebergEmitter` against the issue's acceptance criteria:

* **pyiceberg parses the schema** — every ``<table>.iceberg.json`` is a ``pyiceberg.schema.Schema``;
* **re-export preserves field IDs (SYNTH-reported)** — IDs assigned on the first export come back
  from the MFX-12.2 field-identity store and are reused; a new column gets an ID above every one the
  table has had (a dropped column's ID is never reused); an Arrow source's ``PARQUET:field_id`` wins;
  the fidelity report lists each synthesized ID as ``SYNTH``.

Plus the type mapping, the export gate, and the export service's store wiring.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest
from pyiceberg.schema import Schema
from pyiceberg.types import DecimalType, ListType, MapType, NestedField, StructType, UUIDType

from app.arrow_emitter import ArrowTable
from app.arrow_schema import ArrowField, ArrowSchema, ArrowType
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitResult, EmittedFile, get_emitter, load_builtin_emitters
from app.export_service import ExportPersistenceContext, _field_identity_target, emit_canonical
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.field_identity_store import ICEBERG_TARGET
from app.format_matrix import FormatDirection, build_format_matrix
from app.iceberg_emitter import (
    LOSS_ICEBERG_APPROX,
    IcebergEmitOptions,
    IcebergEmitter,
    _store_key,
    check_emitted_iceberg,
    iceberg_schema,
)
from app.import_source import load_builtin_import_sources
from app.lossiness import LossinessKind, LossinessSeverity

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _f(owner: str, name: str, type_: str, *, nullable: bool = True, item: bool = False,
       extras: Dict[str, Any] | None = None, **constraints: Any) -> CanonicalField:
    ref = TypeRef(item=TypeRef(name=type_), nullable=nullable) if item else TypeRef(name=type_, nullable=nullable)
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref, extras=extras or {},
                          constraints=Constraints(**constraints) if constraints else None)


def _model(*types: Type) -> CanonicalApi:
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="m"),
                        types=list(types))


def _order(*extra: CanonicalField) -> CanonicalApi:
    line = Type(key="Line", name="Line", kind=TypeKind.RECORD, fields=[
        _f("Line", "sku", "string", nullable=False), _f("Line", "qty", "int32")])
    tags = Type(key="Tags", name="Tags", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
                value_type=TypeRef(name="decimal"))
    order = Type(key="Order", name="Order", kind=TypeKind.RECORD, fields=[
        _f("Order", "id", "string", nullable=False, format="uuid"),
        _f("Order", "placed", "date"),
        _f("Order", "placedAt", "string", format="date-time"),
        _f("Order", "slot", "string", format="time"),
        _f("Order", "total", "decimal", multiple_of=0.01),
        _f("Order", "count", "uint32"),
        _f("Order", "digest", "bytes", min_length=32, max_length=32),
        _f("Order", "lines", "Line", item=True),
        _f("Order", "tags", "Tags"),
        _f("Order", "ttl", "string", format="duration"),
        *extra,
    ])
    return _model(line, tags, order)


def _imported(fmt: str, relative: str) -> CanonicalApi:
    text = (_EXAMPLES / relative).read_text(encoding="utf-8")
    return build_conversion_source({"id": "i", "name": "x", "source_format": fmt,
                                    "format_metadata": {"sourceContent": text}}).api


def _schema(result: EmitResult, index: int = 0) -> Schema:
    return Schema.model_validate_json(result.files[index].content)


def _ids(result: EmitResult) -> Dict[str, int]:
    """Column name path → field ID, over the whole schema."""
    schema = _schema(result)
    return {schema.find_column_name(field_id): field_id for field_id in schema._lazy_id_to_field}


# ===========================================================================
# pyiceberg parses the schema
# ===========================================================================


def test_the_emitter_is_registered_as_an_export_only_iceberg_target() -> None:
    assert get_emitter("iceberg") is IcebergEmitter
    row = next(r for r in build_format_matrix().formats if r.key == "iceberg")
    assert row.direction is FormatDirection.EXPORT_ONLY


def test_pyiceberg_parses_one_schema_per_table() -> None:
    result = IcebergEmitter().emit(_order())
    assert [f.path for f in result.files] == ["Order.iceberg.json"]
    document = json.loads(result.files[0].content)
    assert document["type"] == "struct" and document["schema-id"] == 0
    schema = _schema(result)
    assert schema.find_field("id").required and not schema.find_field("placed").required
    assert check_emitted_iceberg(result) == []


def test_types_map_to_iceberg_types() -> None:
    schema = _schema(IcebergEmitter().emit(_order()))
    assert isinstance(schema.find_field("id").field_type, UUIDType)
    assert str(schema.find_field("placed").field_type) == "date"
    assert str(schema.find_field("placedAt").field_type) == "timestamptz"
    assert str(schema.find_field("slot").field_type) == "time"
    assert schema.find_field("total").field_type == DecimalType(38, 2)
    assert str(schema.find_field("count").field_type) == "long"  # uint32 fits a signed long
    assert str(schema.find_field("digest").field_type) == "fixed[32]"
    assert str(schema.find_field("ttl").field_type) == "long"


def test_nested_types_carry_their_own_ids() -> None:
    schema = _schema(IcebergEmitter().emit(_order()))
    lines = schema.find_field("lines").field_type
    assert isinstance(lines, ListType) and isinstance(lines.element_type, StructType)
    assert not lines.element_required
    assert schema.find_field("lines.element.sku").required
    tags = schema.find_field("tags").field_type
    assert isinstance(tags, MapType) and tags.key_type == schema.find_field("tags.key").field_type
    ids = list(schema._lazy_id_to_field)
    assert len(ids) == len(set(ids)) and min(ids) == 1


def test_an_arrow_source_maps_too_with_each_approximation_reported() -> None:
    result = IcebergEmitter().emit(_imported("arrow", "arrow/04-stress-type-coverage.json"))
    schema = _schema(result)
    assert str(schema.find_field("f_timestamp_naive").field_type) == "timestamp"
    assert schema.find_field("f_decimal256").field_type == DecimalType(38, 12)
    assert isinstance(schema.find_field("f_dense_union").field_type, StructType)
    assert not any(f.required for f in schema.find_field("f_dense_union").field_type.fields)
    details = " ".join(loss.detail for loss in result.losses if loss.subject == LOSS_ICEBERG_APPROX)
    assert "union" in details and "38 digits" in details and "interval" in details
    assert check_emitted_iceberg(result) == []


def test_operations_are_not_written() -> None:
    result = IcebergEmitter().emit(_imported("openapi", "openapi/30-openapi-3.0-petstore.yaml"))
    assert [f.path for f in result.files] == ["Pet.iceberg.json"]
    assert "iceberg-services-dropped" in {loss.subject for loss in result.losses}


# ===========================================================================
# Re-export preserves field IDs
# ===========================================================================


def test_a_first_export_assigns_every_id_and_reports_it() -> None:
    result = IcebergEmitter().emit(_order())
    assigned = result.field_identity_assignments
    assert assigned["Order/id"] == _ids(result)["id"]
    assert assigned["Order/lines/element/sku"] == _ids(result)["lines.element.sku"]
    assert assigned["Order/tags/key"] and assigned["Order/tags/value"]
    assert sorted(assigned.values()) == list(range(1, len(assigned) + 1))


def test_a_re_export_reuses_every_stored_id_and_assigns_nothing() -> None:
    first = IcebergEmitter().emit(_order())
    again = IcebergEmitter().emit(_order(), opts=IcebergEmitOptions(
        persisted_field_numbers=first.field_identity_assignments))
    assert again.field_identity_assignments == {}
    assert again.files[0].content == first.files[0].content


def test_a_new_column_gets_an_id_above_every_id_the_table_has_had() -> None:
    first = IcebergEmitter().emit(_order())
    stored = {**first.field_identity_assignments, "Order/retired": 500}
    added = IcebergEmitter().emit(_order(_f("Order", "note", "string")), opts=IcebergEmitOptions(
        persisted_field_numbers=stored))
    assert added.field_identity_assignments == {"Order/note": 501}
    ids = _ids(added)
    assert ids["note"] == 501 and 500 not in ids.values()
    assert {k: v for k, v in ids.items() if k != "note"} == _ids(first)


def test_columns_keep_their_ids_when_others_are_dropped_or_reordered() -> None:
    first = IcebergEmitter().emit(_order())
    smaller = _order()
    order = next(t for t in smaller.types if t.key == "Order")
    order.fields = [f for f in reversed(order.fields) if f.name != "placed"]
    again = IcebergEmitter().emit(smaller, opts=IcebergEmitOptions(
        persisted_field_numbers=first.field_identity_assignments))
    before = _ids(first)
    assert again.field_identity_assignments == {}
    assert all(before[name] == number for name, number in _ids(again).items())


def test_a_source_field_id_wins_and_is_never_handed_out_again() -> None:
    api = _model(Type(key="T", name="T", kind=TypeKind.RECORD, fields=[
        _f("T", "a", "string", extras={"arrow_metadata": {"PARQUET:field_id": "1"}}),
        _f("T", "b", "string")]))
    result = IcebergEmitter().emit(api, opts=IcebergEmitOptions(persisted_field_numbers={"T/b": 1}))
    ids = _ids(result)
    assert ids["a"] == 1 and ids["b"] == 2
    assert result.field_identity_assignments == {"T/b": 2}
    assert "T/a" not in result.field_identity_assignments


def test_two_tables_number_independently() -> None:
    a = Type(key="A", name="A", kind=TypeKind.RECORD, fields=[_f("A", "x", "string")])
    b = Type(key="B", name="B", kind=TypeKind.RECORD, fields=[_f("B", "y", "int64")])
    result = IcebergEmitter().emit(_model(a, b))
    assert [f.path for f in result.files] == ["A.iceberg.json", "B.iceberg.json"]
    assert result.field_identity_assignments == {"A/x": 1, "B/y": 1}
    assert [f.path for f in IcebergEmitter().emit(_model(a, b), opts=IcebergEmitOptions(table="B")).files] == [
        "B.iceberg.json"]


def test_a_store_key_past_the_column_width_is_hashed() -> None:
    table = ArrowTable(name="T", key="T", schema=ArrowSchema(fields=()))
    key = _store_key(table, ["x" * 600])
    assert len(key) <= 512 and key != _store_key(table, ["x" * 599 + "y"])
    assert _store_key(table, ["a", "element"]) == "T/a/element"


def test_iceberg_schema_returns_the_new_assignments() -> None:
    table = ArrowTable(name="T", key="T", schema=ArrowSchema(fields=(
        ArrowField(name="a", type=ArrowType("utf8"), nullable=False),)))
    schema, ids = iceberg_schema(table, persisted={"T/a": 7})
    assert schema["fields"][0]["id"] == 7 and ids.assigned == {}


# ===========================================================================
# The export service persists IDs in the field-identity store
# ===========================================================================


def test_the_export_service_uses_the_iceberg_store_key() -> None:
    assert _field_identity_target(IcebergEmitter) == ICEBERG_TARGET == "iceberg"


@patch("app.export_service.load_persisted_field_numbers")
@patch("app.export_service.persist_field_number_assignments")
def test_emit_canonical_loads_and_persists_iceberg_ids(mock_persist: MagicMock, mock_load: MagicMock) -> None:
    api = _model(Type(key="T", name="T", kind=TypeKind.RECORD, fields=[
        _f("T", "a", "string"), _f("T", "b", "string")]))
    mock_load.return_value = {"T/b": 4}
    result = emit_canonical(api, "iceberg", persistence=ExportPersistenceContext(tenant_id="tenant-1",
                                                                              artifact_id="project-1"))
    fields = json.loads(result.files[0].content)["fields"]
    assert [(f["name"], f["id"]) for f in fields] == [("a", 5), ("b", 4)]
    mock_load.assert_called_once_with("tenant-1", "project-1", "iceberg")
    mock_persist.assert_called_once_with("tenant-1", "project-1", "iceberg", {"T/a": 5})


# ===========================================================================
# The export gate
# ===========================================================================


def test_the_gate_passes_an_export_and_rejects_broken_ones() -> None:
    api = _order()
    verdict = asyncio.run(validate_emitted_artifact("iceberg", IcebergEmitter().emit(api), api=api))
    assert verdict.validated and verdict.valid
    duplicate = json.dumps({"type": "struct", "fields": [
        {"id": 1, "name": "a", "required": True, "type": "int"},
        {"id": 1, "name": "b", "required": True, "type": "int"}]})
    for content, rule in ((duplicate, "iceberg.field-id"),
                          ('{"type": "struct", "fields": [{"id": 1, "name": "a", "required": true, "type": "intt"}]}',
                           "pyiceberg"), ("{not json", "pyiceberg")):
        broken = EmitResult(files=[EmittedFile(path="t.iceberg.json", content=content)])
        assert rule in {p["rule"] for p in check_emitted_iceberg(broken)}
        rejected = asyncio.run(validate_emitted_artifact("iceberg", broken, api=api))
        assert rejected.validated and not rejected.valid
    assert check_emitted_iceberg(EmitResult(files=[EmittedFile(path="x.txt", content="")]))[0]["rule"] == "schema"


def test_pyiceberg_round_trips_the_emitted_schema() -> None:
    schema = _schema(IcebergEmitter().emit(_order()))
    again = Schema.model_validate_json(schema.model_dump_json())
    assert again == schema and isinstance(again.columns[0], NestedField)


# ===========================================================================
# Fidelity
# ===========================================================================


def _items(api: CanonicalApi, **match: Any) -> List[Any]:
    report = compute_lossiness_for_emitter(api, IcebergEmitter)
    return [i for i in report.items if all(getattr(i, k) == v for k, v in match.items())]


def test_every_synthesized_field_id_is_a_synth_item() -> None:
    synth = _items(_order(), kind=LossinessKind.SYNTH, target_mapping="synthesized field ID (persisted)")
    assert {i.construct_key for i in synth} >= {"Order.id", "Order.lines", "Line.sku"}
    assert all(i.severity is LossinessSeverity.INFO and "re-export" in i.message for i in synth)


def test_a_source_field_id_is_not_synthesized() -> None:
    api = _model(Type(key="T", name="T", kind=TypeKind.RECORD, fields=[
        _f("T", "a", "string", extras={"arrow_metadata": {"PARQUET:field_id": "3"}}), _f("T", "b", "string")]))
    synth = {i.construct_key for i in _items(api, kind=LossinessKind.SYNTH)}
    assert synth == {"T.b"}


def test_operations_get_the_types_only_advisory_and_unions_are_approximated() -> None:
    api = _imported("openapi", "openapi/30-openapi-3.0-petstore.yaml")
    [advisory] = _items(api, construct_key="", target_mapping="types-only")
    assert advisory.severity is LossinessSeverity.CRITICAL
    circle = Type(key="Circle", name="Circle", kind=TypeKind.RECORD, fields=[_f("Circle", "r", "double")])
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION, union_members=["Circle"])
    holder = Type(key="H", name="H", kind=TypeKind.RECORD, fields=[_f("H", "s", "Shape")])
    [union] = _items(_model(circle, shape, holder), construct_key="Shape")
    assert union.kind is LossinessKind.APPROX and union.severity is LossinessSeverity.INFO


def test_iceberg_approximations_are_filed_under_their_table() -> None:
    order = _items(_order(), construct_key="Order")
    assert {i.kind for i in order} == {LossinessKind.APPROX}
    assert any("duration" in i.message for i in order)
