"""Apache Arrow / Parquet schema emitter — MFX-36.1 (#4317).

Pins :class:`app.arrow_emitter.ArrowEmitter` against the issue's acceptance criteria:

* **pyarrow constructs the emitted schema** — every ``<table>.arrow.json`` parses back and
  :func:`app.arrow_ipc.schema_to_pyarrow` builds it; the Parquet message is pyarrow's own;
* **nested and logical types are correct** — records are ``struct``, lists ``list<item>``, maps
  ``map<key, value>``, unions dense ``union``; dates ``date32``, date-times ``timestamp[us, UTC]``,
  times ``time64[us]``, durations ``duration[us]``, decimals ``decimal128(p, s)``, UUIDs a 16-byte
  ``fixed_size_binary`` with the ``arrow.uuid`` extension.

Plus: an item imported from Arrow exports back to the same schema, the options, the export gate and
the fidelity report (what a re-import reads back, measured).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List

import pyarrow as pa
import pytest

from app.arrow_emitter import (
    LOSS_DECIMAL_SYNTHESIZED,
    LOSS_EMPTY_RECORD,
    LOSS_ENUM_DICTIONARY,
    LOSS_INTERVAL_UNIT,
    LOSS_PARQUET_UNSUPPORTED,
    LOSS_RECURSION,
    ArrowEmitOptions,
    ArrowEmitter,
    arrow_schema_json,
    check_emitted_arrow,
    parquet_message,
    project_arrow_tables,
)
from app.arrow_ipc import schema_to_pyarrow
from app.arrow_parser import parse_arrow
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import (
    EmitOptionsError,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    get_emitter,
    load_builtin_emitters,
)
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import load_builtin_import_sources
from app.lossiness import LossinessKind, LossinessSeverity

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _f(owner: str, name: str, type_: str, *, nullable: bool = True, item: bool = False, **constraints: Any
       ) -> CanonicalField:
    ref = TypeRef(item=TypeRef(name=type_), nullable=nullable) if item else TypeRef(name=type_, nullable=nullable)
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref,
                          constraints=Constraints(**constraints) if constraints else None)


def _model(*types: Type) -> CanonicalApi:
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="m"),
                        types=list(types))


def _imported(fmt: str, relative: str) -> CanonicalApi:
    text = (_EXAMPLES / relative).read_text(encoding="utf-8")
    return build_conversion_source({"id": "i", "name": "x", "source_format": fmt,
                                    "format_metadata": {"sourceContent": text}}).api


def _pyarrow(result: EmitResult, path: str) -> pa.Schema:
    """The emitted schema at ``path``, as pyarrow constructs it."""
    [file] = [f for f in result.files if f.path == path]
    return schema_to_pyarrow(parse_arrow(file.content, source_label=path).schema)


def _shop() -> CanonicalApi:
    line = Type(key="Line", name="Line", kind=TypeKind.RECORD, fields=[
        _f("Line", "sku", "string", nullable=False), _f("Line", "qty", "int32")])
    status = Type(key="Status", name="Status", kind=TypeKind.ENUM, enum_values=[
        EnumValue(key="Status.open", name="open"), EnumValue(key="Status.shipped", name="shipped")])
    tags = Type(key="Tags", name="Tags", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
                value_type=TypeRef(name="int64"))
    order = Type(key="Order", name="Order", kind=TypeKind.RECORD, description="An order", fields=[
        _f("Order", "id", "string", nullable=False, format="uuid"),
        _f("Order", "placed", "date"),
        _f("Order", "placedAt", "string", format="date-time"),
        _f("Order", "slot", "string", format="time"),
        _f("Order", "ttl", "string", format="duration"),
        _f("Order", "total", "decimal", multiple_of=0.01),
        _f("Order", "rate", "decimal"),
        _f("Order", "weight", "float"),
        _f("Order", "count", "uint16"),
        _f("Order", "lines", "Line", item=True),
        _f("Order", "status", "Status"),
        _f("Order", "tags", "Tags"),
        _f("Order", "blob", "bytes"),
        _f("Order", "digest", "bytes", min_length=32, max_length=32),
        _f("Order", "extra", "any"),
    ])
    return _model(line, status, tags, order)


# ===========================================================================
# pyarrow constructs the emitted schema
# ===========================================================================


def test_the_emitter_is_registered_as_arrow() -> None:
    emitter = get_emitter("arrow")
    assert emitter is ArrowEmitter and emitter.multi_file and emitter.requires_source == ("record-type",)


def test_pyarrow_constructs_the_emitted_schema_and_derives_its_parquet_message() -> None:
    result = ArrowEmitter().emit(_shop())
    assert [f.path for f in result.files] == ["Order.arrow.json", "Order.parquet.txt"]
    schema = _pyarrow(result, "Order.arrow.json")
    assert schema.names[:2] == ["id", "placed"] and len(schema) == 15
    parquet = next(f.content for f in result.files if f.path == "Order.parquet.txt")
    assert parquet.startswith("required group schema {")
    assert "required fixed_len_byte_array(16) id;" in parquet
    assert "optional int32 placed (Date);" in parquet
    assert "field_id" not in parquet and "<pyarrow" not in parquet


def test_the_json_is_the_integration_form_the_arrow_reader_reads() -> None:
    document = json.loads(ArrowEmitter().emit(_shop()).files[0].content)
    [order_id] = [f for f in document["schema"]["fields"] if f["name"] == "id"]
    assert order_id["type"] == {"name": "fixedsizebinary", "byteWidth": 16}
    assert {"key": "ARROW:extension:name", "value": "arrow.uuid"} in order_id["metadata"]
    assert {"key": "name", "value": "Order"} in document["schema"]["metadata"]
    assert {"key": "description", "value": "An order"} in document["schema"]["metadata"]


def test_an_openapi_item_exports_its_root_records_as_tables() -> None:
    result = ArrowEmitter().emit(_imported("openapi", "openapi/30-openapi-3.0-petstore.yaml"))
    schema = _pyarrow(result, "Pet.arrow.json")
    assert pa.types.is_struct(schema.field("category").type)  # Category is nested, not its own table
    assert not schema.field("id").nullable and schema.field("age").nullable
    assert check_emitted_arrow(result) == []


# ===========================================================================
# Nested and logical types
# ===========================================================================


def test_logical_types_map_to_arrow_logical_types() -> None:
    schema = _pyarrow(ArrowEmitter().emit(_shop()), "Order.arrow.json")
    assert schema.field("id").type == pa.binary(16)
    assert schema.field("id").metadata[b"ARROW:extension:name"] == b"arrow.uuid"
    assert schema.field("placed").type == pa.date32()
    assert schema.field("placedAt").type == pa.timestamp("us", tz="UTC")
    assert schema.field("slot").type == pa.time64("us")
    assert schema.field("ttl").type == pa.duration("us")
    assert schema.field("total").type == pa.decimal128(38, 2)
    assert schema.field("rate").type == pa.decimal128(38, 9)
    assert schema.field("weight").type == pa.float32()
    assert schema.field("count").type == pa.uint16()
    assert schema.field("blob").type == pa.binary()
    assert schema.field("digest").type == pa.binary(32)


def test_nested_types_map_natively() -> None:
    schema = _pyarrow(ArrowEmitter().emit(_shop()), "Order.arrow.json")
    lines = schema.field("lines").type
    assert pa.types.is_list(lines) and lines.value_field.name == "item"
    assert pa.types.is_struct(lines.value_type)
    assert lines.value_type.field("sku").type == pa.string() and not lines.value_type.field("sku").nullable
    tags = schema.field("tags").type
    assert pa.types.is_map(tags) and tags.key_type == pa.string() and tags.item_type == pa.int64()
    status = schema.field("status").type
    assert pa.types.is_dictionary(status) and status.index_type == pa.int32() and status.value_type == pa.string()


def test_a_union_is_a_dense_union_and_has_no_parquet_message() -> None:
    circle = Type(key="Circle", name="Circle", kind=TypeKind.RECORD, fields=[_f("Circle", "r", "double")])
    square = Type(key="Square", name="Square", kind=TypeKind.RECORD, fields=[_f("Square", "side", "double")])
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION, union_members=["Circle", "Square"])
    picture = Type(key="Picture", name="Picture", kind=TypeKind.RECORD, fields=[_f("Picture", "shape", "Shape")])
    result = ArrowEmitter().emit(_model(circle, square, shape, picture))
    union = _pyarrow(result, "Picture.arrow.json").field("shape").type
    assert pa.types.is_union(union) and union.mode == "dense" and union.type_codes == [0, 1]
    assert [union.field(i).name for i in range(2)] == ["Circle", "Square"]
    assert [f.path for f in result.files] == ["Picture.arrow.json"]
    assert any(loss.subject == LOSS_PARQUET_UNSUPPORTED for loss in result.losses)


def test_a_recursive_record_holds_itself_as_json() -> None:
    node = Type(key="Node", name="Node", kind=TypeKind.RECORD, fields=[
        _f("Node", "value", "string"), _f("Node", "children", "Node", item=True)])
    result = ArrowEmitter().emit(_model(node))
    children = _pyarrow(result, "Node.arrow.json").field("children")
    assert children.type.value_type == pa.string()
    assert children.type.value_field.metadata[b"ARROW:extension:name"] == b"arrow.json"
    assert [loss.subject for loss in result.losses] == [LOSS_RECURSION]


def test_an_empty_record_and_an_untyped_value_are_json_columns() -> None:
    empty = Type(key="Empty", name="Empty", kind=TypeKind.RECORD, fields=[])
    holder = Type(key="Holder", name="Holder", kind=TypeKind.RECORD, fields=[
        _f("Holder", "meta", "Empty"), _f("Holder", "free", "any")])
    result = ArrowEmitter().emit(_model(empty, holder))
    schema = _pyarrow(result, "Holder.arrow.json")
    for name in ("meta", "free"):
        assert schema.field(name).type == pa.string()
        assert schema.field(name).metadata[b"ARROW:extension:name"] == b"arrow.json"
    assert LOSS_EMPTY_RECORD in {loss.subject for loss in result.losses}


def test_every_made_up_decision_is_a_loss() -> None:
    subjects = {loss.subject for loss in ArrowEmitter().emit(_shop()).losses}
    assert {LOSS_DECIMAL_SYNTHESIZED, LOSS_ENUM_DICTIONARY} <= subjects
    assert all(loss.pointer for loss in ArrowEmitter().emit(_shop()).losses)


# ===========================================================================
# Arrow → Arrow
# ===========================================================================


@pytest.mark.parametrize("name", ["01-minimal-schema.json", "02-typical-orders-schema.json",
                                  "03-composition-nested-types.json", "05-real-world-trip-records-schema.json"])
def test_an_item_imported_from_arrow_exports_back_to_the_same_schema(name: str) -> None:
    raw = (_EXAMPLES / "arrow" / name).read_text(encoding="utf-8")
    result = ArrowEmitter().emit(_imported("arrow", f"arrow/{name}"))
    original = schema_to_pyarrow(parse_arrow(raw).schema)
    assert _pyarrow(result, result.files[0].path).equals(original, check_metadata=True)


def test_a_flight_schema_keeps_its_metadata_and_names_its_table() -> None:
    result = ArrowEmitter().emit(_imported("arrow", "arrow/06-typical-flight-getschema-response.json"))
    schema = _pyarrow(result, "shipments.arrow.json")
    assert schema.metadata[b"flight.endpoint"] == b"grpc+tls://flight.example.com:443"
    assert schema.metadata[b"name"] == b"shipments"


def test_an_interval_pyarrow_cannot_build_is_written_as_month_day_nano() -> None:
    result = ArrowEmitter().emit(_imported("arrow", "arrow/04-stress-type-coverage.json"))
    assert LOSS_INTERVAL_UNIT in {loss.subject for loss in result.losses}
    assert check_emitted_arrow(result) == []


# ===========================================================================
# Options and preconditions
# ===========================================================================


def test_every_root_record_is_its_own_table() -> None:
    a = Type(key="A", name="A", kind=TypeKind.RECORD, fields=[_f("A", "x", "string")])
    b = Type(key="B b", name="B b", kind=TypeKind.RECORD, fields=[_f("B b", "y", "int64")])
    tables = project_arrow_tables(_model(a, b))
    assert [t.key for t in tables] == ["A", "B b"]
    paths = [f.path for f in ArrowEmitter().emit(_model(a, b)).files]
    assert paths == ["A.arrow.json", "A.parquet.txt", "B-b.arrow.json", "B-b.parquet.txt"]


def test_the_table_option_exports_one_record_and_parquet_can_be_left_out() -> None:
    result = ArrowEmitter().emit(_shop(), opts=ArrowEmitOptions(table="Line", parquet=False))
    assert [f.path for f in result.files] == ["Line.arrow.json"]
    assert result.media_type == "application/json"
    with pytest.raises(EmitOptionsError):
        ArrowEmitter().emit(_shop(), opts=ArrowEmitOptions(table="Nope"))


def test_a_model_with_no_record_is_refused() -> None:
    enum = Type(key="E", name="E", kind=TypeKind.ENUM, enum_values=[EnumValue(key="E.a", name="a")])
    with pytest.raises(EmitPreconditionError):
        ArrowEmitter().emit(_model(enum))


def test_the_writer_and_parquet_helpers_round_trip_a_projected_schema() -> None:
    [table] = project_arrow_tables(_shop())
    assert parse_arrow(json.dumps(arrow_schema_json(table.schema))).schema.fields[0].name == "id"
    assert "optional group lines (List)" in parquet_message(table.schema)


# ===========================================================================
# The export gate
# ===========================================================================


def test_the_gate_passes_an_export_and_rejects_a_broken_one() -> None:
    api = _shop()
    passed = asyncio.run(validate_emitted_artifact("arrow", ArrowEmitter().emit(api), api=api))
    assert passed.validated and passed.valid
    broken = EmitResult(files=[EmittedFile(path="x.arrow.json", content='{"schema": {"fields": [{"name": 1}]}}')])
    problems = check_emitted_arrow(broken)
    assert problems and problems[0]["file"] == "x.arrow.json"
    rejected = asyncio.run(validate_emitted_artifact("arrow", broken, api=api))
    assert rejected.validated and not rejected.valid
    assert check_emitted_arrow(EmitResult(files=[EmittedFile(path="a.txt", content="")]))[0]["rule"] == "schema"


# ===========================================================================
# Fidelity
# ===========================================================================


def _items(api: CanonicalApi, **match: Any) -> List[Any]:
    report = compute_lossiness_for_emitter(api, ArrowEmitter)
    return [i for i in report.items if all(getattr(i, k) == v for k, v in match.items())]


def test_a_runtime_without_pyarrow_reports_fidelity_instead_of_failing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-flight ranks every target: an Arrow round trip that cannot run must not fail the ranking."""
    from app import arrow_ipc
    from app.arrow_ipc import ArrowIpcError

    def _missing() -> Any:
        raise ArrowIpcError("pyarrow is not available in this runtime", code="FORMAT_UNSUPPORTED")

    monkeypatch.setattr(arrow_ipc, "_require_pyarrow", _missing)
    report = compute_lossiness_for_emitter(_shop(), ArrowEmitter)
    assert report.items is not None


def test_an_operation_bearing_source_gets_the_critical_types_only_advisory() -> None:
    api = _imported("openapi", "openapi/30-openapi-3.0-petstore.yaml")
    [advisory] = _items(api, construct_key="", target_mapping="types-only")
    assert advisory.kind is LossinessKind.DROP and advisory.severity is LossinessSeverity.CRITICAL


def test_a_nested_record_is_reported_under_the_key_a_re_import_gives_it() -> None:
    api = _imported("openapi", "openapi/30-openapi-3.0-petstore.yaml")
    [dropped] = _items(api, construct_key="Category")
    assert dropped.kind is LossinessKind.DROP and dropped.severity is LossinessSeverity.INFO
    assert "path" in dropped.message
    synth = {i.construct_key for i in _items(api, kind=LossinessKind.SYNTH)}
    assert "category" in synth
    # The table itself reads back under its own key (changed only where Arrow's columns differ).
    assert [i.kind for i in _items(api, construct_key="Pet")] in ([LossinessKind.OK], [LossinessKind.APPROX])


def test_projection_decisions_are_filed_under_their_field() -> None:
    by_key: Dict[str, set] = {}
    for item in _items(_shop()):
        by_key.setdefault(item.construct_key, set()).add((item.kind, item.target_mapping))
    assert (LossinessKind.SYNTH, LOSS_DECIMAL_SYNTHESIZED) in by_key["Order.rate"]
    assert (LossinessKind.APPROX, LOSS_ENUM_DICTIONARY) in by_key["Order.status"]
    assert any("dictionary" in i.message for i in _items(_shop(), construct_key="Status"))


def test_a_second_table_is_reported_as_its_own_file() -> None:
    a = Type(key="A", name="A", kind=TypeKind.RECORD, fields=[_f("A", "x", "string")])
    b = Type(key="B", name="B", kind=TypeKind.RECORD, fields=[_f("B", "y", "int64")])
    [item] = _items(_model(a, b), construct_key="B")
    assert item.kind is LossinessKind.DROP and "B.arrow.json" in item.message


def test_an_arrow_source_round_trips_with_no_loss() -> None:
    api = _imported("arrow", "arrow/02-typical-orders-schema.json")
    assert not [i for i in _items(api) if i.kind is not LossinessKind.OK]
