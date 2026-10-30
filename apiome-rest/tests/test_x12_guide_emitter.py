"""X12 implementation-guide emitter — MFX-24.1 (#4145).

Covers, in order:

* a nested typed source with enums: a structurally valid guide (:func:`validate_x12_guide`), its
  structure (envelope, positions, loops, maximum use), code sets from enums, usage from requiredness;
* the deterministic element type / length mapping (``AN``/``ID``/``N0``/``Nn``/``R``/``DT``/``TM``);
* segment IDs: made from names, unique, never an envelope ID;
* an imported X12 transaction keeping its segment IDs, element refs, order and not-used positions;
* the three files (JSON, CSV dictionary, Markdown), the options, and what was recorded;
* the validator rejecting broken guides; every corpus source giving a valid guide or a refusal.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Dict, List

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
from app.emitter import EmitPreconditionError
from app.import_source import get_import_source
from app.x12_guide_emitter import (
    X12GuideEmitOptions,
    X12GuideEmitter,
    validate_x12_guide,
    validate_x12_guide_document,
)

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "edi-x12"


# ===========================================================================
# Helpers
# ===========================================================================


def _field(owner: str, name: str, ref: TypeRef, **kw) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref, **kw)


def _record(key: str, *fields: CanonicalField) -> Type:
    return Type(key=key, name=key.split(".")[-1], kind=TypeKind.RECORD, fields=list(fields))


def _api(*types: Type, **kw) -> CanonicalApi:
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="openapi", identity=ApiIdentity(name="Orders"),
                        title="Orders", types=list(types), **kw)


def _orders() -> CanonicalApi:
    """A nested typed model: a purchase order with a party, repeating lines and enums."""
    o, line, party = "PurchaseOrder", "OrderLine", "Party"
    return _api(
        _record(o,
                _field(o, "poNumber", TypeRef(name="string", nullable=False), constraints=Constraints(max_length=22)),
                _field(o, "orderDate", TypeRef(name="date", nullable=False)),
                _field(o, "purpose", TypeRef(name="Purpose", nullable=False)),
                _field(o, "rush", TypeRef(name="bool")),
                _field(o, "buyer", TypeRef(name=party, nullable=False)),
                _field(o, "lines", TypeRef(item=TypeRef(name=line), nullable=False),
                       constraints=Constraints(max_items=100)),
                _field(o, "notes", TypeRef(item=TypeRef(name="string")), constraints=Constraints(max_length=60))),
        _record(party,
                _field(party, "name", TypeRef(name="string", nullable=False), constraints=Constraints(max_length=60)),
                _field(party, "idCode", TypeRef(name="string"), constraints=Constraints(min_length=2, max_length=80))),
        _record(line,
                _field(line, "quantity", TypeRef(name="i32", nullable=False)),
                _field(line, "unitPrice", TypeRef(name="decimal", nullable=False),
                       constraints=Constraints(multiple_of=0.01)),
                _field(line, "unit", TypeRef(name="Unit", nullable=False)),
                _field(line, "weight", TypeRef(name="double")),
                _field(line, "shippedAt", TypeRef(name="timestamp"))),
        Type(key="Purpose", name="Purpose", kind=TypeKind.ENUM, enum_values=[
            EnumValue(key="Purpose.original", name="original", value="00"),
            EnumValue(key="Purpose.cancel", name="cancel", value="01")]),
        Type(key="Unit", name="Unit", kind=TypeKind.ENUM, enum_values=[
            EnumValue(key="Unit.each", name="each", value="EA"), EnumValue(key="Unit.case", name="case", value="CA"),
            EnumValue(key="Unit.pallet", name="pallet", value="PLT")]),
    )


def _emit(api: CanonicalApi, **opts):
    return X12GuideEmitter().emit(api, opts=X12GuideEmitOptions(**opts))


def _guide(api: CanonicalApi, **opts) -> Dict[str, Any]:
    return json.loads(_emit(api, **opts).files[0].content)


def _segment(guide: Dict[str, Any], seg_id: str) -> Dict[str, Any]:
    return next(s for s in guide["segments"] if s["id"] == seg_id)


def _segment_of(guide: Dict[str, Any], source: str) -> Dict[str, Any]:
    """The segment made from the record or field ``source`` (whatever ID it was given)."""
    return next(s for s in guide["segments"] if s.get("source") == source)


def _flat(nodes: List[Dict[str, Any]], loops: tuple = ()) -> List[tuple]:
    """``(position, segment, usage, maxUse, loop path)`` for every segment use, in order."""
    out: List[tuple] = []
    for node in nodes:
        if node["type"] == "loop":
            out += _flat(node["children"], (*loops, f"{node['loopId']}:{node['maxUse']}"))
        else:
            out.append((node["position"], node["segment"], node["usage"], node["maxUse"], loops))
    return out


# ===========================================================================
# A nested typed source
# ===========================================================================


def test_a_nested_typed_source_gives_a_valid_guide() -> None:
    result = _emit(_orders())
    assert [f.path for f in result.files] == ["Orders.x12-guide.json", "Orders.x12-segments.csv",
                                              "Orders.x12-guide.md"]
    validate_x12_guide_document(result.files[0].content)
    guide = json.loads(result.files[0].content)
    assert (guide["standard"], guide["version"], guide["transactionSet"]["id"]) == ("X12", "005010", "850")


def test_the_structure_follows_the_type_nesting() -> None:
    assert _flat(_guide(_orders())["structure"]) == [
        ("0100", "ST", "M", 1, ()),
        ("0200", "PUR", "M", 1, ()),
        ("0300", "PAR", "M", 1, ()),
        ("0400", "ORD", "M", 1, ("ORD:100",)),
        ("0500", "NOT", "O", ">1", ()),
        ("0600", "SE", "M", 1, ()),
    ]


def test_code_sets_come_from_enums_and_usage_from_requiredness() -> None:
    guide = _guide(_orders())
    po = {e["name"]: e for e in _segment(guide, "PUR")["elements"]}
    assert po["purpose"]["type"] == "ID" and po["purpose"]["codes"] == ["00", "01"]
    assert (po["purpose"]["minLength"], po["purpose"]["maxLength"]) == (2, 2)
    assert po["rush"]["codes"] == ["Y", "N"] and po["rush"]["usage"] == "O"
    assert po["poNumber"]["usage"] == "M" and po["orderDate"]["usage"] == "M"
    unit = next(e for e in _segment(guide, "ORD")["elements"] if e["name"] == "unit")
    assert (unit["codes"], unit["minLength"], unit["maxLength"]) == (["EA", "CA", "PLT"], 2, 3)


def test_element_types_and_lengths_are_deterministic() -> None:
    guide = _guide(_orders())
    rows = [(e["ref"], e["type"], e["minLength"], e["maxLength"]) for e in _segment(guide, "ORD")["elements"]]
    assert rows == [("ORD01", "N0", 1, 10), ("ORD02", "N2", 1, 15), ("ORD03", "ID", 2, 3), ("ORD04", "R", 1, 15),
                    ("ORD05", "DT", 8, 8), ("ORD06", "TM", 4, 8)]
    party = [(e["ref"], e["type"], e["minLength"], e["maxLength"]) for e in _segment(guide, "PAR")["elements"]]
    assert party == [("PAR01", "AN", 1, 60), ("PAR02", "AN", 2, 80)]
    assert _emit(_orders()).files[0].content == _emit(_orders()).files[0].content


@pytest.mark.parametrize(("scalar", "constraints", "expected"), [
    ("string", None, ("AN", 1, 80)), ("string", Constraints(min_length=3, max_length=9), ("AN", 3, 9)),
    ("uuid", None, ("AN", 36, 36)), ("int8", None, ("N0", 1, 3)), ("int16", None, ("N0", 1, 5)),
    ("int64", None, ("N0", 1, 18)), ("decimal", None, ("R", 1, 15)),
    ("decimal", Constraints(multiple_of=0.001), ("N3", 1, 15)), ("float", None, ("R", 1, 15)),
    ("date", None, ("DT", 8, 8)), ("time", None, ("TM", 4, 8)),
    ("string", Constraints(format="date"), ("DT", 8, 8)), ("bool", None, ("ID", 1, 1)),
])
def test_scalar_mapping(scalar: str, constraints, expected) -> None:
    api = _api(_record("R", _field("R", "v", TypeRef(name=scalar), constraints=constraints)))
    (element,) = _segment_of(_guide(api), "R")["elements"]
    assert (element["type"], element["minLength"], element["maxLength"]) == expected


def test_what_was_synthesized_or_dropped_is_recorded() -> None:
    o = "R"
    api = _api(_record(o, _field(o, "text", TypeRef(name="string")), _field(o, "at", TypeRef(name="timestamp")),
                       _field(o, "u", TypeRef(name="U")), _field(o, "m", TypeRef(name="M")),
                       _field(o, "self", TypeRef(name="R")), _field(o, "grid", TypeRef(item=TypeRef(item=TypeRef(
                           name="i32")))), _field(o, "x", TypeRef(name="null"))),
               Type(key="U", name="U", kind=TypeKind.UNION, union_members=["R"]),
               Type(key="M", name="M", kind=TypeKind.MAP, value_type=TypeRef(name="string")))
    subjects = {(loss.subject, loss.pointer) for loss in _emit(api).losses}
    for expected in (("length-synthesized", "R.text"), ("timestamp-split", "R.at"), ("union-dropped", "R.u"),
                     ("map-dropped", "R.m"), ("recursion-cut", "R.self"), ("list-flattened", "R.grid"),
                     ("field-dropped", "R.x"), ("segment-id-synthesized", "R")):
        assert expected in subjects, expected


# ===========================================================================
# Segment IDs
# ===========================================================================


def test_segment_ids_are_unique_and_never_the_envelope() -> None:
    api = _api(_record("Root", *[_field("Root", n, TypeRef(name=n)) for n in ("Stock", "Set", "Store", "Storage")]),
               *[_record(n, _field(n, "v", TypeRef(name="i32"))) for n in ("Stock", "Set", "Store", "Storage")])
    guide = _guide(api)
    ids = [s["id"] for s in guide["segments"]]
    assert len(ids) == len(set(ids)) and ids.count("ST") == 1 and ids.count("SE") == 1
    assert ids == ["ST", "ROO", "STO", "SET", "STR", "STA", "SE"]
    validate_x12_guide(guide)


def test_a_record_with_only_children_gets_a_marker_element() -> None:
    api = _api(_record("Wrapper", _field("Wrapper", "inner", TypeRef(name="Inner"))),
               _record("Inner", _field("Inner", "v", TypeRef(name="i32"))))
    wrapper = _segment(_guide(api), "WRA")
    assert wrapper["elements"] == [{"ref": "WRA01", "name": "Segment marker", "type": "ID", "minLength": 3,
                                    "maxLength": 3, "usage": "M", "codes": ["WRA"], "source": "Wrapper"}]


def test_more_than_99_values_are_cut_to_99_elements() -> None:
    api = _api(_record("Wide", *[_field("Wide", f"f{i}", TypeRef(name="string")) for i in range(120)]))
    result = _emit(api)
    assert len(_segment_of(json.loads(result.files[0].content), "Wide")["elements"]) == 99
    assert any(loss.subject == "elements-truncated" for loss in result.losses)


# ===========================================================================
# An imported X12 transaction
# ===========================================================================


def _x12_item(name: str) -> CanonicalApi:
    adapter = get_import_source("edix12")
    return adapter.normalize(adapter.parse((_EXAMPLES / name).read_text(), source_label=name), include_raw=True)


def test_an_x12_item_keeps_its_ids_order_and_refs() -> None:
    guide = _guide(_x12_item("01-850-purchase-order.edi"))
    assert [(seg, loops) for _, seg, _, _, loops in _flat(guide["structure"])] == [
        ("ST", ()), ("BEG", ()), ("REF", ()), ("PER", ()), ("N1", ()), ("PO1", ("PO1:>1",)), ("CTT", ()),
        ("SE", ())]
    beg = [(e["ref"], e["usage"]) for e in _segment(guide, "BEG")["elements"]]
    assert beg == [("BEG01", "M"), ("BEG02", "M"), ("BEG03", "M"), ("BEG04", "X"), ("BEG05", "M")]
    assert (guide["transactionSet"]["id"], guide["version"]) == ("850", "004010")
    validate_x12_guide(guide)


@pytest.mark.parametrize("name", sorted(p.name for p in _EXAMPLES.glob("*.edi")))
def test_every_x12_example_gives_a_valid_guide(name: str) -> None:
    validate_x12_guide(_guide(_x12_item(name)))


# ===========================================================================
# Files and options
# ===========================================================================


def test_the_csv_is_the_segment_dictionary() -> None:
    result = _emit(_orders())
    rows = list(csv.DictReader(io.StringIO(result.files[1].content)))
    guide = json.loads(result.files[0].content)
    assert len(rows) == sum(len(s["elements"]) for s in guide["segments"])
    purpose = next(r for r in rows if r["element"] == "purpose")
    assert (purpose["segment"], purpose["type"], purpose["codes"], purpose["source"]) == (
        "PUR", "ID", "00|01", "PurchaseOrder.purpose")


def test_the_markdown_guide() -> None:
    md = _emit(_orders(), transaction_set="810").files[2].content
    assert md.startswith("# X12 810 implementation guide — Orders\n")
    assert "| 0400 | ORD | OrderLine | M | 1 | ORD (max 100, M) |" in md
    assert "### PUR — PurchaseOrder" in md
    assert "| PUR03 | purpose | ID | 2/2 | M | 00, 01 |" in md


def test_options() -> None:
    guide = _guide(_orders(), transaction_set="810", version="004010", default_element_length=35)
    assert (guide["transactionSet"]["id"], guide["version"]) == ("810", "004010")
    assert _segment(guide, "ST")["elements"][0]["codes"] == ["810"]
    note = next(e for e in _segment(guide, "NOT")["elements"])
    assert note["maxLength"] == 60  # its own maxLength wins over the default
    api = _api(_record("R", _field("R", "s", TypeRef(name="string"))))
    assert _segment_of(_guide(api, default_element_length=35), "R")["elements"][0]["maxLength"] == 35


@pytest.mark.parametrize("option", [{"transaction_set": "85"}, {"transaction_set": "ABC"}, {"version": "5010"},
                                    {"default_element_length": 0}])
def test_invalid_options_are_rejected(option) -> None:
    with pytest.raises(ValueError):
        X12GuideEmitOptions(**option)


def test_a_model_without_records_is_refused() -> None:
    with pytest.raises(EmitPreconditionError, match="has none"):
        _emit(_api(Type(key="E", name="E", kind=TypeKind.ENUM)))


def test_operations_get_the_types_only_advisory() -> None:
    from app.canonical_model import Operation, OperationKind, Service
    from app.fidelity_engine import compute_lossiness_for_emitter
    from app.lossiness import LossinessSeverity

    api = _orders()
    api.services.append(Service(key="S", name="S", operations=[
        Operation(key="S.get", name="get", kind=OperationKind.REQUEST_RESPONSE)]))
    report = compute_lossiness_for_emitter(api, X12GuideEmitter)
    advisory = next(i for i in report.items if i.target_mapping == "types-only")
    assert advisory.severity is LossinessSeverity.CRITICAL
    assert any(loss.detail == advisory.message for loss in _emit(api).losses)


# ===========================================================================
# Validation
# ===========================================================================


def _break(mutate) -> Dict[str, Any]:
    guide = _guide(_orders())
    mutate(guide)
    return guide


@pytest.mark.parametrize(("mutate", "message"), [
    (lambda g: g["transactionSet"].update(id="85"), "3-digit"),
    (lambda g: g.update(version="5010"), "6-digit"),
    (lambda g: g["segments"][1].update(id="purchase"), "not 2-3"),
    (lambda g: g["segments"].append(dict(g["segments"][1])), "defined twice"),
    (lambda g: g["segments"][1]["elements"][1].update(ref="PUR09"), "must be PUR02"),
    (lambda g: g["segments"][1]["elements"][0].update(type="XX"), "not an X12 element type"),
    (lambda g: g["segments"][1]["elements"][0].update(minLength=5, maxLength=2), "minLength"),
    (lambda g: g["segments"][1]["elements"][0].update(usage="R"), "usage"),
    (lambda g: g["segments"][1]["elements"][2].pop("codes"), "needs a code list"),
    (lambda g: g["segments"][1]["elements"][2].update(codes=["TOOLONG"]), "is not 2-2"),
    (lambda g: g["segments"][1]["elements"][0].update(codes=["X"]), "only an ID"),
    (lambda g: g["structure"].pop(0), "start with the ST"),
    (lambda g: g["structure"].insert(1, {"type": "segment", "segment": "ZZZ", "usage": "M", "maxUse": 1}),
     "not defined"),
    (lambda g: g["structure"][3].update(loopId="PAR"), "start with its own segment"),
    (lambda g: g["structure"][1].update(maxUse=0), "maxUse"),
])
def test_the_validator_rejects_broken_guides(mutate, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_x12_guide(_break(mutate))


def test_validate_document_rejects_non_json() -> None:
    with pytest.raises(ValueError, match="Not a JSON guide"):
        validate_x12_guide_document("ST*850")


def test_every_corpus_source_gives_a_valid_guide_or_a_refusal() -> None:
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
            result = _emit(api)
        except EmitPreconditionError:
            continue
        try:
            validate_x12_guide_document(result.files[0].content)
        except Exception as exc:  # noqa: BLE001 - collect every failure
            failures.append(f"{family}: {exc}")
    assert not failures, "\n".join(failures)
