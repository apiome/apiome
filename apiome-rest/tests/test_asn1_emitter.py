"""ASN.1 emitter — MFX-27.1 (#4163).

Covers, in order:

* a typed source written as one module that compiles under ``asn1tools`` (BER, UPER, JER): records,
  unions, enums, lists, maps and nested / recursive types;
* constraints as subtype notation — SIZE, value ranges (intersected with an integer's width, exact for
  exclusive integer bounds), value sets, PATTERN — checked by ``asn1tools`` when encoding, and what has
  no notation recorded;
* ``DEFAULT`` / ``OPTIONAL``;
* ASN.1 names (identifiers, typereferences, reserved words, collisions);
* the ``module_name`` / ``oid`` / ``automatic_tags`` options and the namespace-first module name;
* every corpus representative and every ASN.1 example compiling, and an ASN.1 item round-tripping;
* the fidelity pack filing the writer's losses;
* :mod:`app.asn1_notation` helpers.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

import asn1tools
import pytest

from app.asn1_emitter import Asn1EmitOptions, Asn1Emitter, validate_asn1_module
from app.asn1_notation import (
    Namer,
    cstring_literal,
    identifier,
    integer_bounds,
    module_oid,
    number_literal,
    size_constraint,
    type_reference,
    value_range,
)
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
from app.import_source import canonical_diff, get_import_source
from app.lossiness import LossinessKind, LossinessSeverity

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "asn1"


# ===========================================================================
# Helpers
# ===========================================================================


def _field(owner: str, name: str, ref: TypeRef, **kw) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref, **kw)


def _record(key: str, *fields: CanonicalField, name: str | None = None) -> Type:
    return Type(key=key, name=name or key.split(".")[-1], kind=TypeKind.RECORD, fields=list(fields))


def _api(*types: Type, name: str = "Shop", namespace: str | None = None, **kw) -> CanonicalApi:
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema",
                        identity=ApiIdentity(name=name, namespace=namespace), types=list(types), **kw)


def _orders_api() -> CanonicalApi:
    """Nested, constrained, recursive: records, a union, an enum, lists, a map and a self reference."""
    o = "shop.Order"
    order = _record(
        o,
        _field(o, "order_id", TypeRef(name="uint32", nullable=False), constraints=Constraints(minimum=1)),
        _field(o, "sku", TypeRef(name="string", nullable=False),
               constraints=Constraints(min_length=3, max_length=20, pattern="[A-Z]{3}-[0-9]+")),
        _field(o, "quantity", TypeRef(name="i32", nullable=False),
               constraints=Constraints(exclusive_minimum=0, maximum=100)),
        _field(o, "ratio", TypeRef(name="double"), constraints=Constraints(minimum=0, exclusive_maximum=1)),
        _field(o, "status", TypeRef(name="shop.Status", nullable=False), default="OPEN"),
        _field(o, "lines", TypeRef(item=TypeRef(name="shop.Line"), nullable=False),
               constraints=Constraints(min_items=1, max_items=50)),
        _field(o, "codes", TypeRef(item=TypeRef(name="string")), constraints=Constraints(max_length=4)),
        _field(o, "payment", TypeRef(name="shop.Payment")),
        _field(o, "tags", TypeRef(name="shop.Tags")),
        _field(o, "placed", TypeRef(name="string"), constraints=Constraints(format="date-time")),
        _field(o, "digest", TypeRef(name="bytes"), constraints=Constraints(max_length=32)),
        _field(o, "gift", TypeRef(name="bool"), default=False),
        _field(o, "parent", TypeRef(name="shop.Order")),
        _field(o, "matrix", TypeRef(item=TypeRef(item=TypeRef(name="int8")))),
    )
    line = _record("shop.Line", _field("shop.Line", "price", TypeRef(name="double", nullable=False)))
    status = Type(key="shop.Status", name="Status", kind=TypeKind.ENUM, enum_values=[
        EnumValue(key="shop.Status.OPEN", name="OPEN", value=0),
        EnumValue(key="shop.Status.SHIPPED", name="SHIPPED", value=1),
    ])
    card = _record("shop.Card", _field("shop.Card", "number", TypeRef(name="string", nullable=False)))
    payment = Type(key="shop.Payment", name="Payment", kind=TypeKind.UNION, union_members=["shop.Card", "string"])
    tags = Type(key="shop.Tags", name="Tags", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
                value_type=TypeRef(name="i64"))
    return _api(order, line, status, card, payment, tags, namespace="shop")


def _emit(api: CanonicalApi, **opts):
    return Asn1Emitter().emit(api, opts=Asn1EmitOptions(**opts))


def _text(api: CanonicalApi, **opts) -> str:
    return _emit(api, **opts).files[0].content


def _compile(text: str, codec: str = "jer"):
    return asn1tools.compile_string(text, codec)


def _subjects(result) -> List[tuple]:
    return sorted((loss.subject, loss.pointer) for loss in result.losses)


# ===========================================================================
# The module
# ===========================================================================


@pytest.mark.parametrize("codec", ["ber", "uper", "jer"])
def test_a_nested_constrained_model_compiles(codec: str) -> None:
    text = _text(_orders_api())
    validate_asn1_module(text)
    _compile(text, codec)


def test_types_become_sequence_choice_enumerated_and_sequence_of() -> None:
    text = _text(_orders_api())
    assert "shop DEFINITIONS" not in text
    assert "Shop DEFINITIONS AUTOMATIC TAGS ::= BEGIN" in text
    assert "  Order ::= SEQUENCE {" in text
    assert "  Status ::= ENUMERATED { open(0), shipped(1) }" in text
    assert "  Payment ::= CHOICE {\n    card Card,\n    string UTF8String\n  }" in text
    assert "  Tags ::= SEQUENCE OF SEQUENCE { key UTF8String, value INTEGER " in text
    assert "    parent Order OPTIONAL," in text
    assert "    matrix SEQUENCE OF SEQUENCE OF INTEGER (-128..127) OPTIONAL" in text
    assert "    placed GeneralizedTime OPTIONAL," in text
    assert text.rstrip().endswith("END")


def test_constraints_are_subtype_notation() -> None:
    text = _text(_orders_api())
    assert "    order-id INTEGER (1..4294967295)," in text
    assert "    -- pattern: [A-Z]{3}-[0-9]+\n    sku UTF8String (SIZE (3..20))," in text
    assert "    quantity INTEGER (1..100)," in text
    assert "    ratio REAL (0..1) OPTIONAL," in text
    assert "    lines SEQUENCE (SIZE (1..50)) OF Line," in text
    assert "    codes SEQUENCE OF UTF8String (SIZE (0..4)) OPTIONAL," in text
    assert "    digest OCTET STRING (SIZE (0..32)) OPTIONAL," in text


def test_asn1tools_checks_the_constraints_when_encoding() -> None:
    spec = _compile(_text(_orders_api()))
    good = {"order-id": 7, "sku": "ABC-1", "quantity": 5, "status": "open", "lines": [{"price": 1.5}]}
    spec.encode("Order", good, check_constraints=True)
    for bad in ({"sku": "AB"}, {"quantity": 0}, {"quantity": 101}, {"order-id": 0}, {"lines": []},
                {"digest": b"x" * 33}):
        with pytest.raises(asn1tools.ConstraintsError):
            spec.encode("Order", {**good, **bad}, check_constraints=True)


def test_what_has_no_notation_is_recorded() -> None:
    result = _emit(_orders_api())
    subjects = _subjects(result)
    assert ("pattern-as-comment", "shop.Order.sku") in subjects
    assert ("exclusive-bound-inclusive", "shop.Order.ratio") in subjects
    assert ("map-as-sequence", "shop.Tags") in subjects
    assert ("name-respelled", "shop.Order.order_id") in subjects
    assert ("name-respelled", "shop.Status.OPEN") in subjects


def test_rules_without_notation_are_dropped_and_recorded() -> None:
    t = "T.Row"
    api = _api(_record(
        t,
        _field(t, "n", TypeRef(name="i32", nullable=False), constraints=Constraints(multiple_of=5)),
        _field(t, "tags", TypeRef(item=TypeRef(name="string"), nullable=False),
               constraints=Constraints(unique_items=True)),
        _field(t, "mode", TypeRef(name="string", nullable=False), constraints=Constraints(enum=["a", "b"])),
        _field(t, "level", TypeRef(name="int", nullable=False), constraints=Constraints(enum=[1, 2, 5])),
        _field(t, "flag", TypeRef(name="bool", nullable=False), constraints=Constraints(max_length=3)),
        _field(t, "email", TypeRef(name="string", nullable=False), constraints=Constraints(format="email")),
        _field(t, "quoted", TypeRef(name="string", nullable=False), constraints=Constraints(pattern='a"b')),
        _field(t, "empty", TypeRef(name="int", nullable=False), constraints=Constraints(minimum=5, maximum=1)),
    ))
    result = _emit(api)
    text = result.files[0].content
    _compile(text)
    assert "    level INTEGER (1 | 2 | 5)," in text
    assert "    n INTEGER (-2147483648..2147483647)," in text
    dropped = [loss.detail for loss in result.losses if loss.subject == "constraint-dropped"]
    for keyword in ("multipleOf", "uniqueItems", "`enum`", "max_length", "format email", "minimum/maximum"):
        assert any(keyword in detail for detail in dropped), keyword
    assert ("pattern-as-comment", "T.Row.quoted") in _subjects(result)
    assert '    -- pattern: a"b\n    quoted UTF8String,' in text


def test_an_integer_width_is_a_value_range_intersected_with_the_bounds() -> None:
    t = "T.R"
    text = _text(_api(_record(
        t,
        _field(t, "a", TypeRef(name="uint8", nullable=False)),
        _field(t, "b", TypeRef(name="int16", nullable=False), constraints=Constraints(minimum=-5, maximum=99999)),
        _field(t, "c", TypeRef(name="integer", nullable=False), constraints=Constraints(exclusive_maximum=9.5)),
        _field(t, "d", TypeRef(name="integer", nullable=False), constraints=Constraints(minimum=3, maximum=3)),
    )))
    assert "    a INTEGER (0..255)," in text
    assert "    b INTEGER (-5..32767)," in text
    assert "    c INTEGER (MIN..9)," in text
    assert "    d INTEGER (3)" in text
    _compile(text)


def test_a_type_alias_and_scalar_carry_their_constraints() -> None:
    api = _api(
        Type(key="T.Name", name="Name", kind=TypeKind.ALIAS, aliased=TypeRef(name="string"),
             constraints=Constraints(min_length=1, max_length=64)),
        Type(key="T.Id", name="uuid", kind=TypeKind.SCALAR),
        Type(key="T.When", name="When", kind=TypeKind.ALIAS, aliased=TypeRef(name="date")),
    )
    text = _text(api)
    assert "  Name ::= UTF8String (SIZE (1..64))" in text
    assert "  Uuid ::= UTF8String" in text
    assert "  When ::= DATE" in text
    _compile(text)


def test_an_unknown_scalar_is_text_and_recorded() -> None:
    t = "T.R"
    result = _emit(_api(_record(t, _field(t, "x", TypeRef(name="Money", nullable=False)))))
    assert "    x UTF8String" in result.files[0].content
    assert ("unmapped-scalar", "T.R.x") in _subjects(result)


def test_asn1_built_in_types_are_written_as_themselves() -> None:
    t = "M.R"
    text = _text(_api(_record(
        t,
        _field(t, "oid", TypeRef(name="M.OBJECT IDENTIFIER", nullable=False)),
        _field(t, "code", TypeRef(name="PrintableString", nullable=False), constraints=Constraints(max_length=2)),
        _field(t, "bits", TypeRef(name="M.BIT STRING", nullable=False)),
    )))
    assert "    oid OBJECT IDENTIFIER," in text
    assert "    code PrintableString (SIZE (0..2))," in text
    assert "    bits BIT STRING\n" in text
    _compile(text)


def test_an_empty_enum_union_and_record_compile() -> None:
    api = _api(
        Type(key="T.E", name="E", kind=TypeKind.ENUM),
        Type(key="T.U", name="U", kind=TypeKind.UNION),
        _record("T.Empty"),
    )
    result = _emit(api)
    text = result.files[0].content
    assert "  E ::= NULL" in text and "  U ::= NULL" in text and "  Empty ::= SEQUENCE { }" in text
    assert {"empty-enum", "empty-choice"} <= {s for s, _ in _subjects(result)}
    _compile(text)


def test_an_enum_is_numbered_only_with_distinct_integer_values() -> None:
    api = _api(
        Type(key="T.A", name="A", kind=TypeKind.ENUM, enum_values=[
            EnumValue(key="T.A.x", name="x", value="X"), EnumValue(key="T.A.y", name="y", value="Y")]),
        Type(key="T.B", name="B", kind=TypeKind.ENUM, enum_values=[
            EnumValue(key="T.B.x", name="x", value=1), EnumValue(key="T.B.y", name="y", value=1)]),
    )
    text = _text(api)
    assert "  A ::= ENUMERATED { x, y }" in text and "  B ::= ENUMERATED { x, y }" in text
    _compile(text)


# ===========================================================================
# DEFAULT / OPTIONAL
# ===========================================================================


def test_defaults_are_written_in_value_notation_and_never_with_optional() -> None:
    t = "T.R"
    api = _api(_record(
        t,
        _field(t, "flag", TypeRef(name="bool"), default=True),
        _field(t, "count", TypeRef(name="i32"), default=3),
        _field(t, "rate", TypeRef(name="double"), default=1.5),
        _field(t, "label", TypeRef(name="string"), default="hi"),
        _field(t, "quote", TypeRef(name="string"), default='say "hi"'),
        _field(t, "half", TypeRef(name="i32"), default=1.5),
        _field(t, "items", TypeRef(item=TypeRef(name="string")), default=[]),
        _field(t, "plain", TypeRef(name="string", nullable=False)),
    ))
    result = _emit(api)
    text = result.files[0].content
    assert "    flag BOOLEAN DEFAULT TRUE," in text
    assert "    count INTEGER (-2147483648..2147483647) DEFAULT 3," in text
    assert "    rate REAL DEFAULT 1.5," in text
    assert '    label UTF8String DEFAULT "hi",' in text
    assert "    quote UTF8String OPTIONAL," in text
    assert "    half INTEGER (-2147483648..2147483647) OPTIONAL," in text
    assert "    items SEQUENCE OF UTF8String OPTIONAL," in text
    assert "    plain UTF8String\n" in text
    assert "DEFAULT" not in "".join(line for line in text.splitlines() if "OPTIONAL" in line)
    assert [p for s, p in _subjects(result) if s == "default-dropped"] == ["T.R.half", "T.R.items", "T.R.quote"]
    _compile(text)


def test_an_enum_default_is_the_written_item() -> None:
    text = _text(_orders_api())
    assert "    status Status DEFAULT open," in text


# ===========================================================================
# Names
# ===========================================================================


def test_names_follow_the_asn1_rules_and_stay_unique() -> None:
    t = "T.order_line"
    api = _api(
        _record(t, _field(t, "Line_No", TypeRef(name="int", nullable=False)),
                _field(t, "line-no", TypeRef(name="int", nullable=False)),
                _field(t, "2nd", TypeRef(name="int", nullable=False)),
                _field(t, "__x__", TypeRef(name="int", nullable=False))),
        _record("T.END"),
        _record("T.Order_Line", name="Order-line"),
    )
    text = _text(api)
    assert "  Order-line ::= SEQUENCE {" in text
    assert "    line-No INTEGER," in text and "    line-no-2 INTEGER," in text
    assert "    x-2nd INTEGER," in text and "    x INTEGER\n" in text
    assert "  END-Type ::= SEQUENCE { }" in text
    assert "  Order-line-2 ::= SEQUENCE { }" in text
    _compile(text)


def test_a_reference_uses_the_target_s_written_name() -> None:
    api = _api(_record("T.a_b", _field("T.a_b", "next", TypeRef(name="T.a_b"))))
    text = _text(api)
    assert "  A-b ::= SEQUENCE {\n    next A-b OPTIONAL\n  }" in text


# ===========================================================================
# Options and the module header
# ===========================================================================


def test_module_name_and_dotted_oid() -> None:
    text = _text(_orders_api(), module_name="shop_orders", oid="1.3.6.1.4.1.99999.1")
    assert "Shop-orders { 1 3 6 1 4 1 99999 1 } DEFINITIONS AUTOMATIC TAGS ::= BEGIN" in text
    assert _emit(_orders_api(), module_name="shop_orders").files[0].path == "Shop-orders.asn1"
    _compile(text)


def test_a_brace_oid_is_kept() -> None:
    text = _text(_orders_api(), oid="{ iso(1) identified-organization(3) 6 }")
    assert "Shop { iso(1) identified-organization(3) 6 } DEFINITIONS" in text
    _compile(text)


@pytest.mark.parametrize("bad", ["3.1", "1", "1..2", "{ Iso(1) }", "abc"])
def test_an_invalid_oid_is_rejected(bad: str) -> None:
    with pytest.raises(ValueError, match="oid must be"):
        Asn1EmitOptions(oid=bad)


def test_a_module_name_needs_a_letter_or_digit() -> None:
    with pytest.raises(ValueError, match="module_name"):
        Asn1EmitOptions(module_name="--")
    assert Asn1EmitOptions(module_name="  ").module_name is None


def test_tagging_without_automatic_tags() -> None:
    api = _orders_api()
    assert "Shop DEFINITIONS ::= BEGIN" in _text(api, automatic_tags=False)
    api.extras["asn1_tags"] = "IMPLICIT"
    assert "Shop DEFINITIONS IMPLICIT TAGS ::= BEGIN" in _text(api, automatic_tags=False)


def test_the_module_is_named_after_a_namespace_that_is_a_module_reference() -> None:
    record = _record("ACME-ORDERS.Order")
    assert "ACME-ORDERS DEFINITIONS" in _text(_api(record, name="Acme orders", namespace="ACME-ORDERS"))
    assert "Acme-orders DEFINITIONS" in _text(_api(record, name="Acme orders", namespace="acme.orders"))


def test_comments_are_safe_and_optional() -> None:
    api = _api(Type(key="T.R", name="R", kind=TypeKind.RECORD, description="Uses -- inside\nsecond line",
                    fields=[_field("T.R", "a", TypeRef(name="int"), description="the -- a")]))
    text = _text(api)
    assert "  -- Uses - - inside\n  -- second line\n  R ::= SEQUENCE {" in text
    assert "    -- the - - a\n    a INTEGER OPTIONAL" in text
    _compile(text)
    assert {s for s, _ in _subjects(_emit(api))} >= {"description-as-comment"}
    plain = _emit(api, include_comments=False)
    assert "--" not in plain.files[0].content
    assert [p for s, p in _subjects(plain) if s == "description-dropped"] == ["T.R", "T.R.a"]


def test_the_report_notes_a_document_of_another_format() -> None:
    items = {i.target_mapping: i for i in _report(_orders_api()).items if i.construct_key == ""}
    assert items["document → ASN.1 module"].kind is LossinessKind.APPROX
    described = _api(Type(key="T.R", name="R", kind=TypeKind.RECORD, description="d"))
    note = next(i for i in _report(described).items if i.target_mapping == "description-as-comment")
    assert (note.construct_key, note.severity) == ("T.R", LossinessSeverity.INFO)


def test_services_are_dropped_and_recorded() -> None:
    from app.canonical_model import Operation, OperationKind, Service

    api = _orders_api()
    api.services.append(Service(key="S", name="S", operations=[
        Operation(key="S.get", name="get", kind=OperationKind.REQUEST_RESPONSE)]))
    assert ("services-dropped", None) in _subjects(_emit(api))


# ===========================================================================
# Corpus
# ===========================================================================


def _asn1_item(path: Path) -> CanonicalApi:
    adapter = get_import_source("asn1")
    return adapter.normalize(adapter.parse(path.read_text(), source_label=path.name), include_raw=True)


@pytest.mark.parametrize("name", sorted(p.name for p in _EXAMPLES.glob("*.asn1")))
def test_every_asn1_example_re_emits_a_compiling_module(name: str) -> None:
    try:
        api = _asn1_item(_EXAMPLES / name)
    except Exception as exc:  # noqa: BLE001 - an import failure belongs to the import adapter
        pytest.skip(f"the example does not import: {type(exc).__name__}")
    validate_asn1_module(_text(api))


@pytest.mark.parametrize("name", ["01-person.asn1", "02-identifier.asn1", "03-minimal-module.asn1",
                                  "05-stress-grammar.asn1", "06-x509-certificate-shape.asn1"])
def test_an_asn1_item_round_trips_without_changes(name: str) -> None:
    api = _asn1_item(_EXAMPLES / name)
    adapter = get_import_source("asn1")
    back = adapter.normalize(adapter.parse(_text(api)), include_raw=False)
    assert not canonical_diff(api, back).entries


def test_a_type_imported_from_another_module_is_text_and_recorded() -> None:
    result = _emit(_asn1_item(_EXAMPLES / "04-imports-reuse.asn1"))
    assert "    buyer UTF8String," in result.files[0].content
    assert ("unmapped-scalar", "OrderModule.Order.buyer") in _subjects(result)


def test_every_corpus_representative_compiles() -> None:
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
        try:
            validate_asn1_module(_text(api))
        except Exception as exc:  # noqa: BLE001 - collect every failure
            failures.append(f"{family}: {exc}")
    assert not failures, "\n".join(failures)


# ===========================================================================
# Fidelity pack
# ===========================================================================


def _report(api: CanonicalApi):
    from app.fidelity_engine import compute_lossiness_for_emitter

    return compute_lossiness_for_emitter(api, Asn1Emitter)


def test_the_report_files_the_writer_losses_on_their_constructs() -> None:
    items = {(i.construct_key, i.target_mapping): i for i in _report(_orders_api()).items}
    assert items[("shop.Order.sku", "pattern-as-comment")].kind is LossinessKind.DROP
    assert items[("shop.Tags", "map-as-sequence")].severity is LossinessSeverity.WARN
    assert ("shop.Status", "name-respelled") in items  # an enum value's loss lands on its enum
    assert items[("", "namespace → module Shop")].severity is LossinessSeverity.INFO


def test_the_report_has_no_module_note_when_the_namespace_is_kept() -> None:
    api = _api(_record("ACME.Order"), namespace="ACME")
    assert not [i for i in _report(api).items if (i.target_mapping or "").startswith("namespace")]


def test_the_report_records_dropped_rules_as_drop() -> None:
    t = "T.R"
    api = _api(_record(t, _field(t, "n", TypeRef(name="i32", nullable=False), constraints=Constraints(multiple_of=2))))
    item = next(i for i in _report(api).items if i.target_mapping == "constraint-dropped")
    assert (item.construct_key, item.kind) == ("T.R.n", LossinessKind.DROP)


# ===========================================================================
# Notation helpers
# ===========================================================================


@pytest.mark.parametrize(("source", "expected"), [
    ("order_line", "Order-line"), ("2fa", "T-2fa"), ("END", "END-Type"), ("", "Type"), ("a--b-", "A-b"),
    ("UTF8String", "UTF8String-Type"),
])
def test_type_reference(source: str, expected: str) -> None:
    assert type_reference(source) == expected


@pytest.mark.parametrize(("source", "expected"), [
    ("OPEN", "open"), ("SHIPPED_LATE", "shipped-late"), ("Id", "id"), ("camelCase", "camelCase"),
    ("1st", "x-1st"), ("", "value"),
])
def test_identifier(source: str, expected: str) -> None:
    assert identifier(source) == expected


def test_namer_suffixes_collisions_case_insensitively_and_reuses_keys() -> None:
    namer = Namer(type_reference)
    assert [namer.name("a"), namer.name("A"), namer.name("a")] == ["A", "A-2", "A-3"]
    assert namer.name("x", key="k") == namer.name("other", key="k") == "X"


def test_literals_and_ranges() -> None:
    assert [number_literal(v) for v in (3, 3.0, -1.5, 1e-7)] == ["3", "3", "-1.5", "0.0000001"]
    with pytest.raises(ValueError):
        number_literal(True)
    assert cstring_literal("hi") == '"hi"' and cstring_literal('a"b') is None and cstring_literal("a\nb") is None
    ranges = [(0, 255), (None, 5), (1, None), (5, 5), (None, None)]
    assert [value_range(lo, hi) for lo, hi in ranges] == ["(0..255)", "(MIN..5)", "(1..MAX)", "(5)", ""]
    sizes = [size_constraint(1, 20), size_constraint(None, 4), size_constraint(2, None), size_constraint(None, None)]
    assert sizes == ["(SIZE (1..20))", "(SIZE (0..4))", "(SIZE (2..MAX))", ""]


def test_integer_bounds_are_exact() -> None:
    assert integer_bounds(None, None, 0, 10) == (1, 9)
    assert integer_bounds(0.5, 9.5, None, None) == (1, 9)
    assert integer_bounds(2, None, 4, None) == (5, None)


def test_module_oid_forms() -> None:
    assert module_oid("1.3.6.1") == "{ 1 3 6 1 }"
    assert module_oid("{iso(1)   3}") == "{ iso(1) 3 }"


# ===========================================================================
# Fidelity pack — MFX-27.2 (#4164)
# ===========================================================================


def _items(api: CanonicalApi, key: str):
    """The report items of ``key``, without the field-number SYNTH every unnumbered field gets (field identity)."""
    return [i for i in _report(api).items
            if i.construct_key == key and i.target_mapping != "synthesized field number"]


def _constrained_api() -> CanonicalApi:
    t = "T.R"
    return _api(_record(
        t,
        _field(t, "name", TypeRef(name="string", nullable=False),
               constraints=Constraints(min_length=1, max_length=64)),
        _field(t, "age", TypeRef(name="int", nullable=False),
               constraints=Constraints(minimum=0, exclusive_maximum=150)),
        _field(t, "score", TypeRef(name="double", nullable=False), constraints=Constraints(minimum=0, maximum=1)),
        _field(t, "tags", TypeRef(item=TypeRef(name="string"), nullable=False), constraints=Constraints(max_items=5)),
        _field(t, "level", TypeRef(name="int", nullable=False), constraints=Constraints(enum=[1, 2, 3])),
        _field(t, "code", TypeRef(name="string", nullable=False), constraints=Constraints(pattern="^[A-Z0-9_]{3,8}$")),
        _field(t, "ref", TypeRef(name="string", nullable=False), constraints=Constraints(pattern="^[A-Z]{3}-\\d+$")),
        _field(t, "step", TypeRef(name="int", nullable=False), constraints=Constraints(multiple_of=5)),
        _field(t, "plain", TypeRef(name="string", nullable=False)),
    ))


def test_constraints_covered_by_subtype_notation_are_reported_ok() -> None:
    expected = {
        "T.R.name": "minLength/maxLength → SIZE",
        "T.R.age": "minimum/maximum → value range",
        "T.R.score": "minimum/maximum → value range",
        "T.R.tags": "minItems/maxItems → SEQUENCE (SIZE) OF",
        "T.R.level": "enum → value set",
    }
    api = _constrained_api()
    for key, mapping in expected.items():
        items = _items(api, key)
        assert [i.kind for i in items] == [LossinessKind.OK], (key, items)
        assert items[0].target_mapping == mapping
    assert _items(api, "T.R.plain") == []


def test_constrained_fields_are_no_longer_demoted_to_documentation() -> None:
    assert not [i for i in _report(_constrained_api()).items if i.target_mapping == "constraints → doc comment"]


def test_a_simple_pattern_is_a_permitted_alphabet_approx() -> None:
    api = _constrained_api()
    text = _text(api)
    assert '    code UTF8String (SIZE (3..8)) (FROM ("A".."Z" | "0".."9" | "_")),' in text
    (item,) = [i for i in _items(api, "T.R.code") if i.kind is not LossinessKind.OK]
    assert (item.kind, item.severity, item.target_mapping) == (
        LossinessKind.APPROX, LossinessSeverity.INFO, "pattern-as-alphabet")
    spec = _compile(text)
    row = {"name": "a", "age": 1, "score": 0.5, "tags": [], "level": 1, "code": "AB_1", "ref": "x",
           "step": 5, "plain": "p"}
    spec.encode("R", row, check_constraints=True)
    for bad in ("ab_1", "AB", "ABCDEFGHI"):
        with pytest.raises(asn1tools.ConstraintsError):
            spec.encode("R", {**row, "code": bad}, check_constraints=True)


def test_any_other_pattern_is_a_comment_and_a_drop() -> None:
    api = _constrained_api()
    assert "    -- pattern: ^[A-Z]{3}-\\d+$\n    ref UTF8String," in _text(api)
    (item,) = _items(api, "T.R.ref")
    assert (item.kind, item.target_mapping) == (LossinessKind.DROP, "pattern-as-comment")
    plain = _emit(api, include_comments=False)
    assert "pattern:" not in plain.files[0].content
    details = [loss.detail for loss in plain.losses if loss.subject == "pattern-as-comment"]
    assert any("comments are switched off" in detail for detail in details)


def test_a_pattern_comment_cannot_break_out_of_its_line() -> None:
    t = "T.R"
    api = _api(_record(t, _field(t, "x", TypeRef(name="string", nullable=False),
                                 constraints=Constraints(pattern="a\nEND -- b"))))
    text = _text(api)
    assert "    -- pattern: a END - - b\n    x UTF8String" in text
    _compile(text)


def test_a_rule_without_notation_is_a_drop_beside_the_covered_ones() -> None:
    kinds = [i.kind for i in _items(_constrained_api(), "T.R.step")]
    assert kinds == [LossinessKind.DROP]


def test_a_pattern_narrows_the_length_already_in_force() -> None:
    t = "T.R"
    api = _api(_record(t, _field(t, "x", TypeRef(name="string", nullable=False),
                                 constraints=Constraints(max_length=4, pattern="^[a-z]{2,10}$"))))
    assert '    x UTF8String (SIZE (2..4)) (FROM ("a".."z"))' in _text(api)


def test_names_respelled_are_synthesized() -> None:
    t = "T.R"
    api = _api(_record(t, _field(t, "order_id", TypeRef(name="int", nullable=False))))
    (item,) = [i for i in _items(api, "T.R.order_id") if i.target_mapping == "name-respelled"]
    assert (item.kind, item.severity) == (LossinessKind.SYNTH, LossinessSeverity.INFO)


def test_a_map_is_a_key_value_sequence_approx() -> None:
    (item,) = [i for i in _items(_orders_api(), "shop.Tags") if i.target_mapping == "map-as-sequence"]
    assert item.kind is LossinessKind.APPROX


def test_a_recursive_type_is_carried() -> None:
    t = "T.Node"
    api = _api(_record(t, _field(t, "next", TypeRef(name="T.Node")),
                       _field(t, "children", TypeRef(item=TypeRef(name="T.Node"), nullable=False))))
    for key in ("T.Node", "T.Node.next", "T.Node.children"):
        assert {i.kind for i in _items(api, key)} <= {LossinessKind.OK, LossinessKind.SYNTH}, key
    _compile(_text(api))


def test_operations_and_channels_are_dropped_with_the_types_only_advisory() -> None:
    from app.canonical_model import Channel, Operation, OperationKind, Service

    api = _orders_api()
    api.services.append(Service(key="S", name="S", operations=[
        Operation(key="S.get", name="get", kind=OperationKind.REQUEST_RESPONSE)]))
    api.channels.append(Channel(key="orders", name="orders", address="orders"))
    report = _report(api)
    advisory = next(i for i in report.items if i.target_mapping == "types-only")
    assert (advisory.construct_key, advisory.kind, advisory.severity) == ("", LossinessKind.DROP,
                                                                          LossinessSeverity.CRITICAL)
    for key in ("S.get", "orders"):
        item = next(i for i in report.items if i.construct_key == key)
        assert (item.kind, item.severity) == (LossinessKind.DROP, LossinessSeverity.CRITICAL)
    assert any(loss.detail == advisory.message for loss in _emit(api).losses)


def test_the_report_matches_the_export_losses() -> None:
    api = _constrained_api()
    emitted = {loss.detail for loss in _emit(api).losses}
    reported = {i.message for i in _report(api).items if i.kind is not LossinessKind.OK}
    assert {d for d in emitted if "pattern" in d} <= reported


@pytest.mark.parametrize(("pattern", "expected"), [
    ("^[A-Z]{3}$", ('(FROM ("A".."Z"))', 3, 3)),
    ("^[A-Z0-9_-]+$", ('(FROM ("A".."Z" | "0".."9" | "_" | "-"))', 1, None)),
    ("^\\d{4,}$", ('(FROM ("0".."9"))', 4, None)),
    ("^\\w*$", ('(FROM ("A".."Z" | "a".."z" | "0".."9" | "_"))', 0, None)),
    ("^[a-z.\\-]{1,5}$", ('(FROM ("a".."z" | "." | "-"))', 1, 5)),
    ("^[\\dA-F]{2}$", ('(FROM ("0".."9" | "A".."F"))', 2, 2)),
    ("^[a-]?$", ('(FROM ("a" | "-"))', 0, 1)),
    ("[A-Z]+", None), ("^[^a]+$", None), ("^[A-Z]{3}-[0-9]+$", None), ("^[\\s]+$", None),
    ("^[z-a]+$", None), ('^["]+$', None), ("^.+$", None), ("", None),
])
def test_pattern_alphabet(pattern: str, expected) -> None:
    from app.asn1_notation import pattern_alphabet

    assert pattern_alphabet(pattern) == expected
