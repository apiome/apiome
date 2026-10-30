"""FlatBuffers emitter — MFX-30.1 (#4178).

Covers, in order:

* the schema: tables, structs, enums (underlying type, ascending values, a valid default), unions,
  vectors, maps as keyed entry tables, wrapper tables for what a vector or union cannot hold, aliases
  inlined, names and the namespace, ``required``, defaults, ``root_type``;
* field ids: a ``.fbs`` source keeps its own, any other source gets contiguous ids from 0 (a union
  taking two), stored ids are reused on re-export (byte-identical), a removed field's id stays a
  ``(deprecated)`` placeholder, and :func:`app.export_service.emit_canonical` loads and persists them
  under the ``flatbuffers`` store key;
* :class:`app.flatbuffers_identity.FieldIdAllocator`;
* the parser / normalizer reading attributes, ids and deprecated slots back, so every example
  round-trips;
* ``flatc`` compiling the output (skipped where ``flatc`` is not installed: the image bundles it, locally
  point ``APIOME_FLATC_BIN`` at a binary) and the export validator's fallback.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    EnumValue,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import EmitPreconditionError
from app.export_service import ExportPersistenceContext, emit_canonical
from app.export_validation import validate_emitted_artifact
from app.flatbuffers_compile import FLATC_TOOL_KEY, compile_fbs_schema
from app.flatbuffers_emitter import FlatBuffersEmitOptions, FlatBuffersEmitter, fbs_identifier
from app.flatbuffers_identity import FieldIdAllocator, compact_field_ids
from app.import_source import canonical_diff, get_import_source
from app.toolchain_packaging import probe_tool

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "flatbuffers"
_FLATC_AVAILABLE = bool(getattr(probe_tool(FLATC_TOOL_KEY), "available", False))
_needs_flatc = pytest.mark.skipif(not _FLATC_AVAILABLE, reason="flatc is not resolvable here (bundled in the image)")


# ===========================================================================
# Helpers
# ===========================================================================


def _field(owner: str, name: str, ref: TypeRef, **kw) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref, **kw)


def _record(key: str, *fields: CanonicalField, **kw) -> Type:
    return Type(key=key, name=key.split(".")[-1], kind=TypeKind.RECORD, fields=list(fields), **kw)


def _api(*types: Type, namespace: str | None = None, **kw) -> CanonicalApi:
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="openapi",
                        identity=ApiIdentity(name="Shop", namespace=namespace), types=list(types), **kw)


def _shop() -> CanonicalApi:
    """A converted (OpenAPI-like) model: no ids, a union, a map, nested and union vectors, an alias."""
    o = "shop.Order"
    return _api(
        _record(o,
                _field(o, "order-id", TypeRef(name="uint32", nullable=False)),
                _field(o, "sku", TypeRef(name="string", nullable=False)),
                _field(o, "status", TypeRef(name="shop.Status")),
                _field(o, "payment", TypeRef(name="shop.Payment")),
                _field(o, "tags", TypeRef(name="shop.Tags")),
                _field(o, "grid", TypeRef(item=TypeRef(item=TypeRef(name="i32")))),
                _field(o, "payments", TypeRef(item=TypeRef(name="shop.Payment"))),
                _field(o, "label", TypeRef(name="Name")),
                _field(o, "qty", TypeRef(name="i32"), default=3),
                _field(o, "raw", TypeRef(name="bytes", nullable=False)),
                description="An order"),
        Type(key="shop.Status", name="Status", kind=TypeKind.ENUM, enum_values=[
            EnumValue(key="shop.Status.OPEN", name="OPEN", value=5),
            EnumValue(key="shop.Status.SHIPPED", name="SHIPPED", value=2)]),
        _record("shop.Card", _field("shop.Card", "number", TypeRef(name="string"))),
        Type(key="shop.Payment", name="Payment", kind=TypeKind.UNION, union_members=["shop.Card", "string"]),
        Type(key="shop.Tags", name="Tags", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
             value_type=TypeRef(name="i64")),
        Type(key="Name", name="Name", kind=TypeKind.ALIAS, aliased=TypeRef(name="string")),
        namespace="acme.shop-v1",
    )


def _emit(api: CanonicalApi, store: Dict[str, int] | None = None, **opts):
    """Emit with ``store`` as the persisted map, then write the new rows back into it."""
    result = FlatBuffersEmitter().emit(
        api, opts=FlatBuffersEmitOptions(persisted_field_numbers=dict(store or {}), **opts))
    if store is not None:
        store.update(result.field_identity_assignments)
    return result


def _text(result) -> str:
    return result.files[0].content


def _block(text: str, keyword: str, name: str) -> str:
    match = re.search(rf"^{keyword} {name} \{{\n(.*?)^\}}", text, re.M | re.S)
    assert match, f"{keyword} {name} not found in:\n{text}"
    return match.group(1)


def _ids(text: str, table: str) -> Dict[str, int]:
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"^\s+(\w+): .*\(id: (\d+)", _block(text, "table", table),
                                                             re.M)}


def _subjects(result) -> set:
    return {(loss.subject, loss.pointer) for loss in result.losses}


def _fbs_item(path: Path) -> CanonicalApi:
    adapter = get_import_source("flatbuffers")
    return adapter.normalize(adapter.parse(path.read_text(), source_label=path.name), include_raw=True)


# ===========================================================================
# The schema
# ===========================================================================


def test_a_converted_model_becomes_tables_enums_and_unions() -> None:
    text = _text(_emit(_shop()))
    assert text.startswith("// Generated FlatBuffers schema for Shop\n\nnamespace acme.shop_v1;\n")
    assert "enum Status : byte {\n  SHIPPED = 2,\n  OPEN = 5\n}" in text
    assert "union Payment {\n  Card,\n  PaymentString\n}" in text
    assert "/// An order\ntable Order {" in text
    order = _block(text, "table", "Order")
    assert "  order_id: uint (id: 0);" in order
    assert "  sku: string (id: 1, required);" in order
    assert "  status: Status = SHIPPED (id: 2);" in order
    assert "  payment: Payment (id: 4);" in order
    assert "  tags: [TagsEntry] (id: 5);" in order
    assert "  grid: [OrderGridItem] (id: 6);" in order
    assert "  payments: [OrderPaymentsItem] (id: 7);" in order
    assert "  label: string (id: 8);" in order
    assert "  qty: int = 3 (id: 9);" in order
    assert "  raw: [ubyte] (id: 10, required);" in order


def test_declarations_come_before_their_use() -> None:
    text = _text(_emit(_shop()))
    assert text.index("enum Status") < text.index("union Payment") < text.index("table Order")


def test_synthesized_tables_and_what_was_recorded() -> None:
    result = _emit(_shop())
    text = _text(result)
    assert _block(text, "table", "TagsEntry") == "  key: string (id: 0, required, key);\n  value: long (id: 1);\n"
    assert _block(text, "table", "OrderGridItem") == "  items: [int] (id: 0);\n"
    assert _block(text, "table", "OrderPaymentsItem") == "  value: Payment (id: 1);\n"
    assert _block(text, "table", "PaymentString") == "  value: string (id: 0);\n"
    subjects = _subjects(result)
    for expected in (("map-as-vector", "shop.Tags"), ("alias-inlined", "Name"),
                     ("table-synthesized", "shop.Order.grid"), ("table-synthesized", "shop.Order.payments"),
                     ("table-synthesized", "shop.Payment"), ("name-respelled", "shop.Order.order-id"),
                     ("name-respelled", None)):
        assert expected in subjects, expected


def test_an_enum_field_defaults_to_a_value_the_enum_has() -> None:
    e = Type(key="E", name="E", kind=TypeKind.ENUM, enum_values=[EnumValue(key="E.A", name="A", value=1)])
    text = _text(_emit(_api(e, _record("R", _field("R", "e", TypeRef(name="E")),
                                       _field("R", "f", TypeRef(name="E"), default="A")))))
    assert "  e: E = A (id: 0);" in text and "  f: E = A (id: 1);" in text


def test_an_enum_of_text_values_is_numbered_by_position() -> None:
    e = Type(key="E", name="E", kind=TypeKind.ENUM, enum_values=[
        EnumValue(key="E.a", name="a", value="x"), EnumValue(key="E.b", name="b", value="y")])
    result = _emit(_api(e))
    assert "enum E : byte {\n  a = 0,\n  b = 1\n}" in _text(result)
    assert ("enum-renumbered", "E") in _subjects(result)


def test_an_enum_keeps_its_imported_base_type_only_when_values_fit() -> None:
    def enum(value: int) -> Type:
        return Type(key="E", name="E", kind=TypeKind.ENUM, extras={"fbs_base_type": "ushort"},
                    enum_values=[EnumValue(key="E.A", name="A", value=value)])

    assert "enum E : ushort {" in _text(_emit(_api(enum(7))))
    assert "enum E : int {" in _text(_emit(_api(enum(70000))))


def test_an_empty_enum_and_union_still_compile_shapes() -> None:
    result = _emit(_api(Type(key="E", name="E", kind=TypeKind.ENUM), Type(key="U", name="U", kind=TypeKind.UNION)))
    text = _text(result)
    assert "enum E : byte {\n  UNKNOWN = 0\n}" in text
    assert "union U {\n  UNone\n}" in text and "table UNone {\n}" in text
    assert {"empty-enum", "table-synthesized"} <= {s for s, _ in _subjects(result)}


def test_a_struct_stays_a_struct_only_when_it_can_be_one() -> None:
    vec = _record("V", _field("V", "x", TypeRef(name="float")), _field("V", "y", TypeRef(name="float")),
                  extras={"fbs_kind": "struct"})
    pose = _record("P", _field("P", "at", TypeRef(name="V")), _field("P", "roll", TypeRef(name="float")),
                   extras={"fbs_kind": "struct"})
    named = _record("N", _field("N", "name", TypeRef(name="string")), extras={"fbs_kind": "struct"})
    result = _emit(_api(pose, vec, named))
    text = _text(result)
    assert "struct V {\n  x: float;\n  y: float;\n}" in text
    assert text.index("struct V") < text.index("struct P")
    assert "table N {\n  name: string (id: 0);\n}" in text
    assert ("struct-as-table", "N") in _subjects(result)


def test_a_field_with_no_value_type_is_left_out() -> None:
    result = _emit(_api(_record("R", _field("R", "a", TypeRef(name="int")), _field("R", "b", TypeRef(name="null")))))
    assert _ids(_text(result), "R") == {"a": 0}
    assert ("field-dropped", "R.b") in _subjects(result)


@pytest.mark.parametrize(("ref", "default", "written"), [
    ("bool", True, " = true"), ("bool", "false", " = false"), ("int8", 5, " = 5"), ("int8", 999, ""),
    ("double", 1.5, " = 1.5"), ("double", 2, " = 2.0"), ("int", "0x10", " = 16"), ("string", "x", ""),
    ("int", 1.5, ""),
])
def test_scalar_defaults(ref: str, default, written: str) -> None:
    result = _emit(_api(_record("R", _field("R", "v", TypeRef(name=ref), default=default))))
    assert f"  v: {_text(result).split('v: ')[1].split(' ')[0].rstrip(';')}{written} (id: 0);" in _text(result)
    assert (("default-dropped", "R.v") in _subjects(result)) == (written == "")


def test_names_follow_the_flatbuffers_rules() -> None:
    assert [fbs_identifier(n) for n in ("order-id", "2fa", "string", "table", "ok_name", "")] == [
        "order_id", "_2fa", "string_", "table_", "ok_name", "value"]
    api = _api(_record("R", _field("R", "a b", TypeRef(name="int")), _field("R", "a_b", TypeRef(name="int")),
                       _field("R", "u", TypeRef(name="U")), _field("R", "u_type", TypeRef(name="int"))),
               Type(key="U", name="U", kind=TypeKind.UNION, union_members=["R"]))
    assert _ids(_text(_emit(api)), "R") == {"a_b": 0, "a_b_2": 1, "u": 3, "u_type_2": 4}


def test_root_type_option_and_imported_default() -> None:
    api = _shop()
    assert "root_type Order;" in _text(_emit(api, root_type="Order"))
    assert "root_type Order;" in _text(_emit(api, root_type="shop.Order"))
    assert "root_type" not in _text(_emit(api))
    api.extras["fbs_root_type"] = "Card"
    assert "root_type Card;" in _text(_emit(api))
    with pytest.raises(EmitPreconditionError, match="root_type 'Status' is not a table"):
        _emit(api, root_type="Status")
    api.extras["fbs_root_type"] = "Missing"
    result = _emit(api)
    assert "root_type" not in _text(result) and ("root-type-dropped", None) in _subjects(result)


def test_comments_are_optional() -> None:
    assert "//" not in _text(_emit(_shop(), include_comments=False))


def test_operations_are_dropped_with_the_types_only_advisory() -> None:
    from app.canonical_model import Operation, OperationKind

    api = _shop()
    api.services.append(Service(key="S", name="S", operations=[
        Operation(key="S.get", name="get", kind=OperationKind.REQUEST_RESPONSE)]))
    assert ("services-dropped", None) in _subjects(_emit(api))


# ===========================================================================
# Field ids
# ===========================================================================


def test_ids_are_contiguous_from_zero_with_a_union_taking_two() -> None:
    result = _emit(_shop())
    assert sorted(_ids(_text(result), "Order").values()) == [0, 1, 2, 4, 5, 6, 7, 8, 9, 10]
    assignments = result.field_identity_assignments
    assert assignments["shop.Order.payment"] == 4 and assignments["shop.Order.payment_type"] == 3


def test_re_export_reuses_stored_ids_byte_identically() -> None:
    store: Dict[str, int] = {}
    first = _emit(_shop(), store)
    second = _emit(_shop(), store)
    assert _text(second) == _text(first)
    assert second.field_identity_assignments == {}


def test_a_new_field_gets_the_next_id_and_old_ids_stay() -> None:
    store: Dict[str, int] = {}
    _emit(_shop(), store)
    api = _shop()
    order = api.types[0]
    api.types[0] = order.model_copy(update={"fields": [
        _field("shop.Order", "added", TypeRef(name="string")), *order.fields]})
    result = _emit(api, store)
    ids = _ids(_text(result), "Order")
    assert ids["added"] == 11 and ids["order_id"] == 0 and ids["payment"] == 4
    assert result.field_identity_assignments == {"shop.Order.added": 11}


def test_a_removed_field_keeps_its_id_as_a_deprecated_placeholder() -> None:
    store: Dict[str, int] = {}
    _emit(_shop(), store)
    api = _shop()
    api.types[0] = api.types[0].model_copy(update={"fields": [
        f for f in api.types[0].fields if f.name not in ("sku", "payment")]})
    api.types[0].fields.append(_field("shop.Order", "fresh", TypeRef(name="int")))
    text = _text(_emit(api, store))
    order = _block(text, "table", "Order")
    assert "  sku: ubyte (id: 1, deprecated);" in order
    assert "  payment_type: ubyte (id: 3, deprecated);" in order
    assert "  payment: ubyte (id: 4, deprecated);" in order
    assert _ids(text, "Order")["fresh"] == 11


def test_a_flatbuffers_source_keeps_its_own_ids() -> None:
    api = _fbs_item(_EXAMPLES / "04-robot-stress.fbs")
    result = _emit(api, {"example.robotics.Robot.name": 9})
    assert _ids(_text(result), "Robot") == {"name": 0, "flags": 1, "axes": 2, "waypoints": 3, "command": 5,
                                           "ready": 6, "batteryPct": 7}
    assert result.field_identity_assignments == {}


def test_ids_after_a_deprecated_slot_survive_a_round_trip() -> None:
    source = ("namespace n;\ntable T {\n  a: int (id: 0);\n  old: string (id: 1, deprecated);\n"
              "  b: string (id: 2);\n}\nroot_type T;\n")
    adapter = get_import_source("flatbuffers")
    api = adapter.normalize(adapter.parse(source), include_raw=True)
    table = next(t for t in api.types if t.name == "T")
    assert [f.name for f in table.fields] == ["a", "b"]
    assert table.extras["fbs_deprecated"] == {"1": "old"}
    assert next(f for f in table.fields if f.name == "b").extras["fbs_id"] == 2
    text = _text(_emit(api))
    assert _block(text, "table", "T") == ("  a: int (id: 0);\n  old: ubyte (id: 1, deprecated);\n"
                                          "  b: string (id: 2);\n")


@patch("app.export_service.load_persisted_field_numbers")
@patch("app.export_service.persist_field_number_assignments")
def test_emit_canonical_loads_and_persists_under_the_flatbuffers_key(
    mock_persist: MagicMock, mock_load: MagicMock
) -> None:
    mock_load.return_value = {"R.b": 0}
    api = _api(_record("R", _field("R", "a", TypeRef(name="int")), _field("R", "b", TypeRef(name="int"))))
    result = emit_canonical(api, "flatbuffers", opts={"include_comments": False},
                            persistence=ExportPersistenceContext(tenant_id="tenant-1", artifact_id="project-1"))
    assert _ids(_text(result), "R") == {"b": 0, "a": 1}
    mock_load.assert_called_once_with("tenant-1", "project-1", "flatbuffers")
    mock_persist.assert_called_once_with("tenant-1", "project-1", "flatbuffers", {"R.a": 1})


# ===========================================================================
# FieldIdAllocator
# ===========================================================================


def _slots(allocator: FieldIdAllocator) -> List[tuple]:
    return [(s.id, s.key, s.width, s.placeholder) for s in allocator.finish()]


def test_allocator_spans_unions_and_fills_holes() -> None:
    allocator = FieldIdAllocator("T", {"T.c": 5, "T.gone": 1})
    allocator.add("T.a", "a")
    allocator.add("T.u", "u", width=2)
    allocator.add("T.c", "c")
    assert _slots(allocator) == [(0, "T.a", 1, False), (1, "T.gone", 1, True), (3, "T.u", 2, False),
                                 (4, "T.reserved_4", 1, True), (5, "T.c", 1, False)]
    assert allocator.new_assignments == {"T.a": 0, "T.u": 3, "T.u_type": 2}


def test_allocator_source_ids_win_and_collisions_are_renumbered() -> None:
    allocator = FieldIdAllocator("T", {"T.b": 0})
    allocator.add("T.a", "a", source_id=0)
    allocator.add("T.b", "b")
    allocator.add("T.c", "c", source_id=0)
    assert [(s.id, s.key) for s in allocator.finish()] == [(0, "T.a"), (1, "T.b"), (2, "T.c")]


def test_allocator_reuses_a_stored_union_only_with_its_type_id() -> None:
    whole = FieldIdAllocator("T", {"T.u": 3, "T.u_type": 2})
    whole.add("T.u", "u", width=2)
    assert [s.id for s in whole.finish() if not s.placeholder] == [3]
    broken = FieldIdAllocator("T", {"T.u": 3})
    broken.add("T.u", "u", width=2)
    assert broken.new_assignments == {} and [s.id for s in broken.finish() if not s.placeholder] == [1]


def test_allocator_ignores_rows_of_other_tables_and_bad_values() -> None:
    allocator = FieldIdAllocator("T", {"T.Inner.x": 7, "Other.y": 3, "T.z": -1, "T.w": 99_999, "T.v": True})
    allocator.add("T.a", "a")
    assert [s.id for s in allocator.finish()] == [0]


def test_compact_ids() -> None:
    assert compact_field_ids([1, 2, 1]) == [0, 2, 3]
    assert compact_field_ids([]) == []


# ===========================================================================
# Parser and round trip
# ===========================================================================


@pytest.mark.parametrize("name", sorted(p.name for p in _EXAMPLES.glob("*.fbs")))
def test_every_example_round_trips_without_changes(name: str) -> None:
    api = _fbs_item(_EXAMPLES / name)
    adapter = get_import_source("flatbuffers")
    back = adapter.normalize(adapter.parse(_text(_emit(api))), include_raw=True)
    assert not canonical_diff(api, back).entries


def test_the_parser_reads_attributes() -> None:
    from app.flatbuffers_parser import _parse_fields

    fields = _parse_fields("a: int = 2 (id: 1); b: string (id: 0, required); c: ubyte (deprecated); d: ns.T")
    assert [(f.name, f.type_expr, f.default, f.field_id, f.deprecated) for f in fields] == [
        ("a", "int", "2", 1, False), ("b", "string", None, 0, False), ("c", "ubyte", None, None, True),
        ("d", "ns.T", None, None, False)]
    assert fields[1].attributes == (("id", "0"), ("required", None))


# ===========================================================================
# flatc and the export validator
# ===========================================================================


@_needs_flatc
@pytest.mark.parametrize("name", sorted(p.name for p in _EXAMPLES.glob("*.fbs")))
async def test_flatc_compiles_every_example(name: str) -> None:
    api = _fbs_item(_EXAMPLES / name)
    if api.extras.get("fbs_includes"):
        pytest.skip("the schema includes files that are not part of the export")
    result = _emit(api)
    await compile_fbs_schema(result.files[0].path, _text(result))


@_needs_flatc
async def test_flatc_compiles_a_converted_model_and_its_re_export() -> None:
    store: Dict[str, int] = {}
    for api in (_shop(), _shop()):
        result = _emit(api, store, root_type="Order")
        await compile_fbs_schema(result.files[0].path, _text(result))


@_needs_flatc
async def test_flatc_compiles_every_corpus_representative() -> None:
    from corpus_roundtrip import representatives_by_format
    from export_conformance import _import_entry

    failures = []
    for family, entry in sorted(representatives_by_format().items()):
        if entry is None:
            continue
        try:
            api = _import_entry(entry)
        except Exception:  # noqa: BLE001 - the import matrix owns import failures
            continue
        if api.extras.get("fbs_includes"):
            continue
        result = _emit(api)
        try:
            await compile_fbs_schema(result.files[0].path, _text(result))
        except Exception as exc:  # noqa: BLE001 - collect every failure
            failures.append(f"{family}: {exc}")
    assert not failures, "\n".join(failures)


async def test_the_validator_re_parses_when_flatc_is_unavailable() -> None:
    result = _emit(_shop())
    with patch("app.flatbuffers_compile.flatc_available", return_value=False):
        verdict = await validate_emitted_artifact("flatbuffers", result, api=_shop())
    assert verdict.applicable and verdict.validated and verdict.valid


async def test_the_validator_reports_flatc_diagnostics() -> None:
    from app.flatbuffers_compile import FlatcCompileError

    result = _emit(_shop())
    with patch("app.flatbuffers_compile.flatc_available", return_value=True), \
            patch("app.flatbuffers_compile.compile_fbs_schema",
                  side_effect=FlatcCompileError("x", diagnostics=["error: Shop.fbs:3: 1: bad"])):
        verdict = await validate_emitted_artifact("flatbuffers", result, api=_shop())
    assert verdict.validated and not verdict.valid
    assert "bad" in verdict.findings[0].message


async def test_compile_refuses_an_unsafe_path() -> None:
    from app.flatbuffers_compile import FlatcCompileError

    with pytest.raises(FlatcCompileError, match="Unsafe"):
        await compile_fbs_schema("../evil.txt", "table T {}")
