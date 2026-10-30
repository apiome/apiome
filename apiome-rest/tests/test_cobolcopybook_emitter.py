"""COBOL copybook emitter — MFX-23.1 (#4139).

Covers, in order:

* a converted (non-copybook) model laid out as records: levels, scalar pictures, enum / boolean ``88``
  levels, nested groups, ``OCCURS`` (fixed, and ``DEPENDING ON`` a synthesized counter), unions as
  ``REDEFINES``, dropped maps and cut recursion — and what each synthesis recorded;
* the options: numeric usage, default lengths / occurrences / scale, fixed vs free format, comments;
* COBOL data names: the mangling rules, the 30-character limit, collisions, determinism;
* the output reading back through the copybook importer and layout analysis, every corpus source
  laid out (or refused with a reason), and copybook items re-emitted unchanged;
* ``cb2xml`` parsing the output (skipped unless ``APIOME_CB2XML_JAR`` names a cb2xml jar and ``java`` is
  installed — the toolchain wiring is MFX-23.4).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List

import pytest

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
from app.cobolcopybook_emitter import CobolCopybookEmitOptions, CobolCopybookEmitter
from app.cobolcopybook_layout import compute_layout
from app.cobolcopybook_parser import parse_cobolcopybook
from app.cobolcopybook_plan import CobolNamer, cobol_name, record_types
from app.emitter import EmitPreconditionError
from app.import_source import canonical_diff, get_import_source

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "cobol-copybook"
_CB2XML = os.environ.get("APIOME_CB2XML_JAR")
_needs_cb2xml = pytest.mark.skipif(
    not (_CB2XML and Path(_CB2XML).is_file() and shutil.which("java")),
    reason="cb2xml is not installed here (set APIOME_CB2XML_JAR and install java)",
)


# ===========================================================================
# Helpers
# ===========================================================================


def _field(owner: str, name: str, ref: TypeRef, **kw) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref, **kw)


def _record(key: str, *fields: CanonicalField) -> Type:
    return Type(key=key, name=key.split(".")[-1], kind=TypeKind.RECORD, fields=list(fields))


def _api(*types: Type, **kw) -> CanonicalApi:
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="openapi", identity=ApiIdentity(name="Shop"),
                        types=list(types), **kw)


def _shop() -> CanonicalApi:
    """A converted model: nested records, every scalar kind, enums, lists, a union, a map, recursion."""
    o = "Purchase"
    return _api(
        _record(o,
                _field(o, "orderId", TypeRef(name="i64", nullable=False)),
                _field(o, "customer_name", TypeRef(name="string"), constraints=Constraints(max_length=40)),
                _field(o, "note", TypeRef(name="string")),
                _field(o, "placed", TypeRef(name="string"), constraints=Constraints(format="date-time")),
                _field(o, "shipDate", TypeRef(name="date")),
                _field(o, "ref", TypeRef(name="uuid")),
                _field(o, "qty", TypeRef(name="i32"), constraints=Constraints(minimum=1)),
                _field(o, "small", TypeRef(name="int16")),
                _field(o, "total", TypeRef(name="decimal"), constraints=Constraints(multiple_of=0.001)),
                _field(o, "ratio", TypeRef(name="double")),
                _field(o, "gift", TypeRef(name="bool")),
                _field(o, "state", TypeRef(name="State")),
                _field(o, "level", TypeRef(name="Level")),
                _field(o, "address", TypeRef(name="Address")),
                _field(o, "lines", TypeRef(item=TypeRef(name="Line")), constraints=Constraints(max_items=50)),
                _field(o, "codes", TypeRef(item=TypeRef(name="string")),
                       constraints=Constraints(min_items=3, max_items=3, max_length=4)),
                _field(o, "grid", TypeRef(item=TypeRef(item=TypeRef(name="i32")))),
                _field(o, "payment", TypeRef(name="Payment")),
                _field(o, "attrs", TypeRef(name="Attrs")),
                _field(o, "parent", TypeRef(name="Purchase")),
                _field(o, "nothing", TypeRef(name="null"))),
        _record("Address", _field("Address", "street", TypeRef(name="string"), constraints=Constraints(max_length=30)),
                _field("Address", "zip", TypeRef(name="string"), constraints=Constraints(max_length=10))),
        _record("Line", _field("Line", "sku", TypeRef(name="string"), constraints=Constraints(max_length=12)),
                _field("Line", "tags", TypeRef(item=TypeRef(name="string"), nullable=False),
                       constraints=Constraints(max_items=4, max_length=8))),
        Type(key="State", name="State", kind=TypeKind.ENUM, enum_values=[
            EnumValue(key="State.open", name="open", value="OPEN"),
            EnumValue(key="State.held", name="held", value="ON-HOLD")]),
        Type(key="Level", name="Level", kind=TypeKind.ENUM, enum_values=[
            EnumValue(key="Level.low", name="low", value=1), EnumValue(key="Level.high", name="high", value=10)]),
        _record("Card", _field("Card", "number", TypeRef(name="string"), constraints=Constraints(max_length=19))),
        _record("Cash", _field("Cash", "currency", TypeRef(name="string"), constraints=Constraints(max_length=3)),
                _field("Cash", "memo", TypeRef(name="string"), constraints=Constraints(max_length=40))),
        Type(key="Payment", name="Payment", kind=TypeKind.UNION, union_members=["Card", "Cash"]),
        Type(key="Attrs", name="Attrs", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
             value_type=TypeRef(name="string")),
    )


def _emit(api: CanonicalApi, **opts):
    return CobolCopybookEmitter().emit(api, opts=CobolCopybookEmitOptions(**opts))


def _text(api: CanonicalApi, **opts) -> str:
    return _emit(api, **opts).files[0].content


def _entries(text: str) -> List[str]:
    """Each entry of a fixed-format copybook on one line (continuations joined), without the period."""
    joined, out = "", []
    for line in text.splitlines():
        if len(line) > 6 and line[6] == "*":
            continue
        code = line[7:72].strip() if len(line) > 7 else ""
        if not code:
            continue
        joined = f"{joined} {code}".strip()
        if joined.endswith("."):
            out.append(re.sub(r"\s+", " ", joined[:-1]))
            joined = ""
    return out


def _subjects(result) -> set:
    return {(loss.subject, loss.pointer) for loss in result.losses}


def _copybook_item(path: Path) -> CanonicalApi:
    adapter = get_import_source("cobolcopybook")
    return adapter.normalize(adapter.parse(path.read_text(), source_label=path.name), include_raw=True)


# ===========================================================================
# Layout
# ===========================================================================


def test_a_converted_model_is_one_record_with_levels_and_pictures() -> None:
    entries = _entries(_text(_shop()))
    assert entries[0] == "01 PURCHASE"
    expected = [
        "05 ORDER-ID PIC S9(18) COMP",
        "05 CUSTOMER-NAME PIC X(40)",
        "05 NOTE PIC X(255)",
        "05 PLACED PIC X(32)",
        "05 SHIP-DATE PIC X(10)",
        "05 REF PIC X(36)",
        "05 QTY PIC 9(9) COMP",
        "05 SMALL PIC S9(4) COMP",
        "05 TOTAL PIC S9(15)V9(3) COMP-3",
        "05 RATIO COMP-2",
        "05 GIFT PIC X(1)",
        "88 GIFT-TRUE VALUE 'Y'",
        "88 GIFT-FALSE VALUE 'N'",
        "05 STATE PIC X(7)",
        "88 STATE-OPEN-X VALUE 'OPEN'",
        "88 STATE-HELD VALUE 'ON-HOLD'",
        "05 LEVEL PIC 9(2)",
        "88 LEVEL-LOW VALUE 1",
        "88 LEVEL-HIGH VALUE 10",
        "05 ADDRESS-X",
        "10 STREET PIC X(30)",
        "10 ZIP PIC X(10)",
        "05 LINES-X-COUNT PIC S9(4) COMP",
        "05 LINES-X OCCURS 0 TO 50 TIMES DEPENDING ON LINES-X-COUNT",
        "10 SKU PIC X(12)",
        "10 TAGS PIC X(8) OCCURS 4 TIMES",
        "05 CODES PIC X(4) OCCURS 3 TIMES",
        "05 GRID-COUNT PIC S9(4) COMP",
        "05 GRID OCCURS 0 TO 10 TIMES DEPENDING ON GRID-COUNT",
        "10 GRID-ITEM PIC S9(9) COMP OCCURS 10 TIMES",
        "05 PAYMENT",
        "10 PAYMENT-CASH",
        "15 CURRENCY-X PIC X(3)",
        "15 MEMO PIC X(40)",
        "10 PAYMENT-CARD REDEFINES PAYMENT-CASH",
        "15 NUMBER-X PIC X(19)",
    ]
    assert [re.sub(r"\s+", " ", e) for e in entries[1:]] == expected


def test_what_was_synthesized_or_dropped_is_recorded() -> None:
    subjects = _subjects(_emit(_shop()))
    for expected in (
        ("length-synthesized", "Purchase.note"), ("counter-synthesized", "Purchase.lines"),
        ("occurs-synthesized", "Purchase.grid"), ("occurs-fixed", "Purchase.grid"),
        ("union-as-redefines", "Purchase.payment"), ("map-dropped", "Purchase.attrs"),
        ("recursion-cut", "Purchase.parent"), ("field-dropped", "Purchase.nothing"),
        ("name-mangled", "Purchase.customer_name"),
    ):
        assert expected in subjects, expected
    assert ("name-mangled", "Purchase.note") not in subjects  # upper-casing alone is not a rename


def test_each_top_level_record_is_its_own_01() -> None:
    api = _api(_record("A", _field("A", "x", TypeRef(name="i32"))), _record("B", _field("B", "a", TypeRef(name="A"))),
               _record("C", _field("C", "y", TypeRef(name="bool"))))
    assert [t.key for t in record_types(api)] == ["B", "C"]
    entries = _entries(_text(api))
    assert [e for e in entries if e.startswith("01")] == ["01 B", "01 C"]


def test_a_model_without_records_is_refused() -> None:
    with pytest.raises(EmitPreconditionError, match="has none"):
        _emit(_api(Type(key="E", name="E", kind=TypeKind.ENUM)))


def test_an_empty_group_gets_a_filler() -> None:
    assert _entries(_text(_api(_record("Empty"))))[1:] == ["05 FILLER PIC X(1)"]


def test_deep_nesting_steps_levels_within_49() -> None:
    types = [_record(f"T{i}", _field(f"T{i}", "next", TypeRef(name=f"T{i + 1}"))) for i in range(14)]
    types.append(_record("T14", _field("T14", "leaf", TypeRef(name="i32"))))
    levels = [int(e.split()[0]) for e in _entries(_text(_api(*types)))]
    assert levels[0] == 1 and max(levels) <= 49 and levels == sorted(levels)


# ===========================================================================
# Options
# ===========================================================================


def test_display_usage_writes_zoned_numbers() -> None:
    entries = _entries(_text(_shop(), numeric_usage="display"))
    assert "05 ORDER-ID PIC S9(18)" in entries
    assert "05 TOTAL PIC S9(15)V9(3)" in entries
    assert "05 RATIO PIC S9(16)V9(2)" in entries
    assert "05 LINES-X-COUNT PIC S9(4)" in entries
    assert ("float-as-decimal", "Purchase.ratio") in _subjects(_emit(_shop(), numeric_usage="display"))


def test_default_length_occurs_and_scale() -> None:
    api = _api(_record("R", _field("R", "s", TypeRef(name="string")), _field("R", "d", TypeRef(name="decimal")),
                       _field("R", "l", TypeRef(item=TypeRef(name="i32")))))
    entries = _entries(_text(api, default_string_length=80, default_occurs=7, decimal_scale=4))
    assert "05 S PIC X(80)" in entries
    assert "05 D PIC S9(14)V9(4) COMP-3" in entries
    assert "05 L PIC S9(9) COMP OCCURS 0 TO 7 TIMES DEPENDING ON L-COUNT" in entries


@pytest.mark.parametrize("option", [{"default_string_length": 0}, {"default_occurs": 0}, {"decimal_scale": 18},
                                    {"numeric_usage": "comp-5"}])
def test_options_are_validated(option) -> None:
    with pytest.raises(ValueError):
        CobolCopybookEmitOptions(**option)


def test_fixed_format_stays_in_the_code_area() -> None:
    o = "R"
    api = _api(_record(o, _field(o, "a_rather_long_field_name_here", TypeRef(item=TypeRef(name="string")),
                                 constraints=Constraints(max_items=99, max_length=1000))))
    text = _text(api)
    assert all(len(line) <= 72 for line in text.splitlines())
    assert all(line.startswith("       ") or line.startswith("      *") for line in text.splitlines())


def test_free_format() -> None:
    text = _text(_shop(), fixed_format=False)
    lines = text.splitlines()
    assert lines[0] == "*> Generated COBOL copybook for Shop"
    assert lines[1] == "01  PURCHASE."
    assert "05  LINES-X OCCURS 0 TO 50 TIMES DEPENDING ON LINES-X-COUNT." in lines
    assert not any(line.startswith(" ") for line in lines)
    assert parse_cobolcopybook(text).root.name == "PURCHASE"


def test_comments_are_optional() -> None:
    assert "*" not in _text(_shop(), include_comments=False).splitlines()[0]


# ===========================================================================
# Names
# ===========================================================================


@pytest.mark.parametrize(("source", "expected"), [
    ("orderLineItems", "ORDER-LINE-ITEMS"), ("order_id", "ORDER-ID"), ("2fa", "2FA"), ("2024", "X-2024"),
    ("status", "STATUS-X"),
    ("a--b__c", "A-B-C"), ("", "ITEM"), ("x" * 40, "X" * 30),
    ("customer_mailing_address_line_two", "CUSTOMER-MAILING-ADDRESS-LINE"),
])
def test_cobol_name(source: str, expected: str) -> None:
    name = cobol_name(source)
    assert name == expected
    assert len(name) <= 30 and not name.endswith("-") and "--" not in name


def test_collisions_get_suffixes_within_30_characters() -> None:
    namer = CobolNamer()
    long = "customer_mailing_address_line_two"
    names = [namer.name(long), namer.name("customer-mailing-address-line-three"), namer.name("A"), namer.name("a")]
    assert names == ["CUSTOMER-MAILING-ADDRESS-LINE", "CUSTOMER-MAILING-ADDRESS-LIN-2", "A", "A-2"]
    assert all(len(n) <= 30 for n in names)


def test_names_are_unique_across_the_copybook_and_deterministic() -> None:
    api = _api(_record("R", _field("R", "id", TypeRef(name="i32")), _field("R", "a", TypeRef(name="S")),
                       _field("R", "b", TypeRef(name="S"))),
               _record("S", _field("S", "id", TypeRef(name="i32"))))
    text = _text(api)
    names = [e.split()[1] for e in _entries(text)]
    assert names == ["R", "ID", "A", "ID-2", "B", "ID-3"]
    assert _text(api) == text


# ===========================================================================
# Reading it back
# ===========================================================================


def test_the_output_reads_back_through_the_importer_and_layout() -> None:
    api = _api(_record("R", _field("R", "id", TypeRef(name="i32")),
                       _field("R", "name", TypeRef(name="string"), constraints=Constraints(max_length=20)),
                       _field("R", "amt", TypeRef(name="decimal")),
                       _field("R", "tags", TypeRef(item=TypeRef(name="string")),
                              constraints=Constraints(min_items=2, max_items=2, max_length=5))))
    doc = parse_cobolcopybook(_text(api))
    assert compute_layout(doc.root)  # the layout analysis reads it
    assert [c.name for c in doc.root.children] == ["ID", "NAME", "AMT", "TAGS"]
    tags = doc.root.children[3]
    assert (tags.picture, tags.occurs_min, tags.occurs_max, tags.depending_on) == ("X(5)", 2, 2, None)
    amount = doc.root.children[2]
    assert (amount.picture, amount.usage) == ("S9(16)V9(2)", "COMP-3")


def test_every_corpus_source_is_laid_out_or_refused() -> None:
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
            text = _text(api)
        except EmitPreconditionError:
            continue
        try:
            parse_cobolcopybook(text)
            assert all(len(line) <= 72 for line in text.splitlines())
        except Exception as exc:  # noqa: BLE001 - collect every failure
            failures.append(f"{family}: {exc}")
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("name", sorted(p.name for p in _EXAMPLES.glob("*.cpy")))
def test_a_copybook_item_is_re_emitted_unchanged(name: str) -> None:
    api = _copybook_item(_EXAMPLES / name)
    adapter = get_import_source("cobolcopybook")
    back = adapter.normalize(adapter.parse(_text(api)), include_raw=True)
    assert not canonical_diff(api, back).entries


def test_a_fixed_table_is_written_occurs_n_times() -> None:
    source = "       01  REC.\n           05  ITEM PIC X(2) OCCURS 5 TIMES.\n"
    text = _text(_copybook_item_from(source))
    assert "05  ITEM PIC X(2) OCCURS 5 TIMES." in text


def _copybook_item_from(source: str) -> CanonicalApi:
    adapter = get_import_source("cobolcopybook")
    return adapter.normalize(adapter.parse(source), include_raw=True)


def test_condition_values_quote_and_escape() -> None:
    e = Type(key="E", name="E", kind=TypeKind.ENUM, enum_values=[EnumValue(key="E.a", name="a", value="it's")])
    text = _text(_api(_record("R", _field("R", "e", TypeRef(name="E"))), e))
    assert "88  E-A                      VALUE 'it''s'." in text


def test_the_report_notes_a_document_of_another_format() -> None:
    from app.fidelity_engine import compute_lossiness_for_emitter

    report = compute_lossiness_for_emitter(_shop(), CobolCopybookEmitter)
    assert any(i.target_mapping == "document → COBOL copybook" and i.construct_key == "" for i in report.items)
    own = compute_lossiness_for_emitter(_copybook_item(_EXAMPLES / "01-customer-record.cpy"), CobolCopybookEmitter)
    assert not any(i.target_mapping == "document → COBOL copybook" for i in own.items)


# ===========================================================================
# cb2xml
# ===========================================================================


@_needs_cb2xml
@pytest.mark.parametrize("fixed_format", [True, False])
def test_cb2xml_parses_a_nested_typed_copybook(tmp_path: Path, fixed_format: bool) -> None:
    path = tmp_path / "Shop.cpy"
    path.write_text(_text(_shop(), fixed_format=fixed_format))
    args = ["java", "-jar", _CB2XML, "-cobol", str(path)]
    if not fixed_format:
        args += ["-font", "cp037", "-free"]
    run = subprocess.run(args, capture_output=True, text=True, timeout=120, check=False)
    assert run.returncode == 0, run.stderr
    assert 'name="PURCHASE"' in run.stdout and 'name="LINES-X"' in run.stdout
    assert 'depending-on="LINES-X-COUNT"' in run.stdout


# ===========================================================================
# Parser: PICTURE and USAGE wherever they stand (MFX-23.1)
# ===========================================================================


@pytest.mark.parametrize(("clauses", "picture", "usage"), [
    ("PIC X(2) OCCURS 5 TIMES.", "X(2)", None),
    ("PIC S9(9) COMP OCCURS 10 TIMES.", "S9(9)", "COMP"),
    ("OCCURS 3 TIMES PIC 9(4).", "9(4)", None),
    ("PIC S9(9)V99 COMP-3.", "S9(9)V99", "COMP-3"),
    ("PICTURE IS X(10) USAGE IS DISPLAY.", "X(10)", None),
    ("COMP-2.", None, "COMP-2"),
    ("PIC 9(3).99.", "9(3).99", None),
    ("PIC 9(4) COMPUTATIONAL-5.", "9(4)", "COMP-5"),
    ("OCCURS 1 TO 5 TIMES DEPENDING ON COMP-COUNT.", None, None),
])
def test_the_parser_reads_picture_and_usage(clauses: str, picture, usage) -> None:
    from app.cobolcopybook_parser import _parse_picture

    assert _parse_picture(clauses) == (picture, usage)


def test_a_float_item_imports_as_a_float() -> None:
    api = _copybook_item_from("       01  REC.\n           05  RATE COMP-2.\n           05  CODE PIC X(1).\n")
    rate = next(f for t in api.types for f in t.fields if f.name == "RATE")
    assert rate.type.name == "double"


# ===========================================================================
# Fidelity pack — MFX-23.2 (#4140)
# ===========================================================================


def _report(api: CanonicalApi, **options):
    from app.fidelity_engine import compute_lossiness_for_emitter

    return compute_lossiness_for_emitter(api, CobolCopybookEmitter, options=options or None)


def _items(report, key: str, mapping: str):
    return [i for i in report.items if i.construct_key == key and i.target_mapping == mapping]


def test_every_synthesized_length_counter_and_rename_is_listed_with_its_source_path() -> None:
    from app.lossiness import LossinessKind

    api = _shop()
    emitted = {(loss.subject, loss.pointer) for loss in _emit(api).losses
               if loss.subject in ("length-synthesized", "counter-synthesized", "name-mangled")}
    report = _report(api)
    synthesized = {(i.target_mapping, i.construct_key) for i in report.items if i.kind is LossinessKind.SYNTH}
    assert emitted and emitted <= synthesized
    (length,) = _items(report, "Purchase.note", "length-synthesized")
    assert "PIC X(255)" in length.message and "'Purchase.note'" in length.message
    (counter,) = _items(report, "Purchase.lines", "counter-synthesized")
    assert "LINES-X-COUNT" in counter.message
    (rename,) = _items(report, "Purchase.customer_name", "name-mangled")
    assert "'CUSTOMER-NAME'" in rename.message


def test_an_operation_bearing_source_carries_the_critical_types_only_advisory() -> None:
    from app.canonical_model import Channel, Operation, OperationKind, Service
    from app.lossiness import LossinessKind, LossinessSeverity

    api = _shop()
    api.services.append(Service(key="Shop", name="Shop", operations=[
        Operation(key="Shop.get", name="get", kind=OperationKind.REQUEST_RESPONSE)]))
    api.channels.append(Channel(key="orders", name="orders", address="orders"))
    report = _report(api)
    advisory = next(i for i in report.items if i.target_mapping == "types-only")
    assert (advisory.construct_key, advisory.kind, advisory.severity) == ("", LossinessKind.DROP,
                                                                          LossinessSeverity.CRITICAL)
    assert "1 service(s) with 1 operation(s) and 1 channel(s)" in advisory.message
    for key in ("Shop.get", "orders"):
        item = next(i for i in report.items if i.construct_key == key)
        assert (item.kind, item.severity) == (LossinessKind.DROP, LossinessSeverity.CRITICAL)
    assert any(loss.detail == advisory.message for loss in _emit(api).losses)


def test_an_unbounded_list_is_approximated_and_its_counter_synthesized() -> None:
    from app.lossiness import LossinessKind, LossinessSeverity

    report = _report(_shop())
    (maximum,) = _items(report, "Purchase.grid", "occurs-synthesized")
    assert (maximum.kind, maximum.severity) == (LossinessKind.APPROX, LossinessSeverity.WARN)
    (counter,) = _items(report, "Purchase.grid", "counter-synthesized")
    assert counter.kind is LossinessKind.SYNTH
    # A bounded list that varies in size only synthesizes its counter.
    assert not _items(report, "Purchase.lines", "occurs-synthesized")


def test_unions_maps_recursion_and_optional_fields() -> None:
    from app.lossiness import LossinessKind, LossinessSeverity

    report = _report(_shop())
    assert _items(report, "Purchase.payment", "union-as-redefines")[0].kind is LossinessKind.APPROX
    assert _items(report, "Purchase.attrs", "map-dropped")[0].kind is LossinessKind.DROP
    assert _items(report, "Purchase.parent", "recursion-cut")[0].kind is LossinessKind.DROP
    (optional,) = _items(report, "Purchase.note", "optional → always present (spaces / zeros when absent)")
    assert (optional.kind, optional.severity) == (LossinessKind.APPROX, LossinessSeverity.INFO)
    assert not _items(report, "Purchase.orderId", "optional → always present (spaces / zeros when absent)")
    assert not [i for i in report.items if i.target_mapping == "synthesized field number"]


def test_a_union_whose_member_varies_in_size_is_dropped() -> None:
    from app.lossiness import LossinessKind

    api = _api(
        _record("R", _field("R", "id", TypeRef(name="i32")), _field("R", "u", TypeRef(name="U"))),
        _record("A", _field("A", "items", TypeRef(item=TypeRef(name="i32")))),
        _record("B", _field("B", "code", TypeRef(name="string"), constraints=Constraints(max_length=4))),
        Type(key="U", name="U", kind=TypeKind.UNION, union_members=["A", "B"]),
    )
    entries = _entries(_text(api))
    assert entries == ["01 R", "05 ID PIC S9(9) COMP"]
    (item,) = _items(_report(api), "R.u", "union-dropped")
    assert item.kind is LossinessKind.DROP and "OCCURS DEPENDING ON" in item.message


def test_patterns_and_formats_become_comment_lines() -> None:
    from app.lossiness import LossinessKind, LossinessSeverity

    long_pattern = "^[A-Z]{3}-" + "[0-9]" * 20 + "$"
    api = _api(_record("R",
                       _field("R", "code", TypeRef(name="string"), constraints=Constraints(max_length=10,
                                                                                           pattern=long_pattern)),
                       _field("R", "mail", TypeRef(name="string"), constraints=Constraints(max_length=60,
                                                                                           format="email"))))
    text = _text(api)
    lines = text.splitlines()
    code_at = next(i for i, line in enumerate(lines) if "05  CODE" in line)
    assert lines[code_at - 2].startswith("      * pattern: ^[A-Z]{3}-")
    assert all(len(line) <= 72 for line in lines)
    assert "      * format: email\n           05  MAIL PIC X(60)." in text
    assert "*> format: email\n05  MAIL PIC X(60)." in _text(api, fixed_format=False)
    report = _report(api)
    (pattern,) = _items(report, "R.code", "pattern-as-comment")
    assert (pattern.kind, pattern.severity) == (LossinessKind.APPROX, LossinessSeverity.WARN)
    assert _items(report, "R.mail", "format-as-comment")[0].severity is LossinessSeverity.INFO
    assert parse_cobolcopybook(text).root.children[0].name == "CODE-X"


def test_the_report_follows_the_options() -> None:
    (length,) = _items(_report(_shop(), default_string_length=80), "Purchase.note", "length-synthesized")
    assert "PIC X(80)" in length.message
    (fallback,) = _items(_report(_shop(), default_string_length=0), "Purchase.note", "length-synthesized")
    assert "PIC X(255)" in fallback.message  # invalid options fall back to the defaults
    assert _items(_report(_shop(), numeric_usage="display"), "Purchase.ratio", "float-as-decimal")


def test_a_copybook_item_reports_nothing_invented() -> None:
    from app.lossiness import LossinessKind

    report = _report(_copybook_item(_EXAMPLES / "04-warehouse-stress.cpy"))
    assert [i for i in report.items if i.kind is not LossinessKind.OK] == []


def test_a_model_without_records_still_gets_a_report() -> None:
    report = _report(_api(Type(key="E", name="E", kind=TypeKind.ENUM)))
    assert any(i.target_mapping == "document → COBOL copybook" for i in report.items)
