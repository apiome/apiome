"""HL7 v2 segment-definition guide emitter — MFX-26.3 (#4159).

Covers the acceptance criterion — **a coherent segment guide for a typed source; table values from enums**:

* **coherent** — a typed source gives a guide whose message starts with ``MSH`` (the standard header, naming the
  message type and version), whose segments are site-defined Z-segments with fields ``SEG-1`` upward, HL7 data
  types, lengths, optionality and repetition, whose segment groups follow the type nesting, and which passes the
  guide checks (:mod:`app.hl7v2_guide_validation`) and the export gate; the CSV and Markdown say what the JSON says;
* **tables from enums** — each enum is a user-defined table numbered from ``first_table_number`` with the enum's
  values as its codes (a renamed value keeps its value as the description), the coded field is bound to it, and a
  boolean is bound to HL7 table 0136.

Also: version-dependent data types (``DTM`` from 2.6, ``CWE`` from 2.7), an imported HL7 v2 message keeping its
segments and order, the shared plan (the X12 guide's segments and values), options, the checks' rules and the
fidelity report.
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError
from test_x12_guide_emitter import _api, _field, _orders, _record

from app.canonical_model import Constraints, EnumValue, Service, Type, TypeKind, TypeRef
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, load_builtin_emitters
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.hl7v2_guide_emitter import Hl7v2GuideEmitOptions, Hl7v2GuideEmitter, abstract_syntax, hl7v2_csv, hl7v2_markdown
from app.hl7v2_guide_validation import check_guide_files, guide_problems
from app.import_source import load_builtin_import_sources
from app.lossiness import LossinessKind
from app.x12_guide_emitter import X12GuideEmitter

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_HL7 = sorted(p.name for p in (_EXAMPLES / "hl7v2").glob("*.hl7"))


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _emit(api, **opts):
    return Hl7v2GuideEmitter().emit(api, opts=Hl7v2GuideEmitOptions(**opts))


def _guide(api, **opts) -> Dict[str, Any]:
    return json.loads(_emit(api, **opts).files[0].content)


def _segment_of(guide: Dict[str, Any], source: str) -> Dict[str, Any]:
    return next(s for s in guide["segments"] if s.get("source") == source)


def _field_of(segment: Dict[str, Any], source: str) -> Dict[str, Any]:
    return next(f for f in segment["fields"] if f.get("source") == source)


def _load(path: str, fmt: str):
    file = _EXAMPLES / path
    return build_conversion_source({"id": "i", "name": file.stem, "source_format": fmt,
                                    "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}).api


# ===========================================================================
# A coherent guide for a typed source
# ===========================================================================


def test_the_export_is_three_files() -> None:
    result = _emit(_orders())
    assert [(f.path, f.media_type) for f in result.files] == [
        ("Orders.hl7v2-guide.json", "application/json"), ("Orders.hl7v2-segments.csv", "text/csv"),
        ("Orders.hl7v2-guide.md", "text/markdown")]


def test_the_message_starts_with_the_standard_msh() -> None:
    guide = _guide(_orders())
    assert guide["structure"][0] == {"type": "segment", "segment": "MSH", "optionality": "R", "repetition": "N"}
    msh = guide["segments"][0]
    assert msh["id"] == "MSH" and [f["ref"] for f in msh["fields"]] == [f"MSH-{n}" for n in range(1, 13)]
    values = {f["seq"]: f.get("value") for f in msh["fields"]}
    assert (values[1], values[9], values[12]) == ("|", "ZZZ^Z01", "2.5.1")


def test_segments_made_from_types_are_z_segments() -> None:
    guide = _guide(_orders())
    for segment in guide["segments"][1:]:
        assert segment["id"].startswith("Z") and len(segment["id"]) == 3, segment["id"]


def test_fields_have_hl7_data_types_lengths_and_optionality() -> None:
    po = _segment_of(_guide(_orders()), "PurchaseOrder")
    assert [f["ref"] for f in po["fields"]] == [f"{po['id']}-{n}" for n in range(1, len(po["fields"]) + 1)]
    number = _field_of(po, "PurchaseOrder.poNumber")
    assert (number["dataType"], number["length"], number["optionality"], number["repetition"]) == ("ST", 22, "R", "N")
    assert _field_of(po, "PurchaseOrder.orderDate")["dataType"] == "DT"
    assert _field_of(po, "PurchaseOrder.rush")["optionality"] == "O"


@pytest.mark.parametrize(("scalar", "constraints", "data_type"), [
    ("string", Constraints(max_length=12), "ST"),
    ("int32", None, "NM"),
    ("decimal", Constraints(multiple_of=0.01), "NM"),
    ("double", None, "NM"),
    ("date", None, "DT"),
    ("time", None, "TM"),
    ("datetime", None, "TS"),
])
def test_scalar_data_types(scalar: str, constraints, data_type: str) -> None:
    api = _api(_record("R", _field("R", "v", TypeRef(name=scalar, nullable=False), constraints=constraints)))
    [field] = _guide(api)["segments"][1]["fields"]
    assert field["dataType"] == data_type


def test_a_timestamp_is_one_field() -> None:
    api = _api(_record("R", _field("R", "placed", TypeRef(name="datetime"))))
    result = _emit(api)
    [field] = json.loads(result.files[0].content)["segments"][1]["fields"]
    assert (field["name"], field["dataType"], field["length"]) == ("placed", "TS", 26)
    [detail] = [loss.detail for loss in result.losses if loss.subject == "timestamp-split"]
    assert "one date/time field" in detail


def test_segment_groups_follow_the_nesting_and_repeat() -> None:
    guide = _guide(_orders())
    group = next(n for n in guide["structure"] if n["type"] == "group")
    assert group["group"] == "ORDER_LINE" and group["repetition"] == 100
    assert group["children"][0]["segment"].startswith("Z")
    notes = next(n for n in guide["structure"] if n.get("source") == "PurchaseOrder.notes")
    assert (notes["optionality"], notes["repetition"]) == ("O", "Y")


def test_the_abstract_message_syntax() -> None:
    guide = _guide(_orders())
    syntax = abstract_syntax(guide["structure"])
    assert syntax.startswith("MSH ")
    assert "{ " in syntax and "[ { " in syntax  # a repeating group, and an optional repeating segment
    assert f"```\n{syntax}\n```" in _emit(_orders()).files[2].content


def test_the_guide_passes_the_checks_and_the_gate() -> None:
    api = _orders()
    result = _emit(api)
    assert check_guide_files({f.path: f.content for f in result.files}) == []
    assert asyncio.run(validate_emitted_artifact("hl7v2-guide", result, api=api)).valid


@pytest.mark.parametrize("name", ["openapi", "json-schema", *_HL7])
@pytest.mark.parametrize("version", ["2.3", "2.5.1", "2.8"])
def test_every_fixture_gives_a_valid_guide(name: str, version: str) -> None:
    api = {"openapi": lambda: _load("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
           "json-schema": lambda: _load("json-schema/03-multiple-defs.json", "json-schema")}.get(
        name, lambda: _load(f"hl7v2/{name}", "hl7v2"))()
    result = _emit(api, version=version)
    assert check_guide_files({f.path: f.content for f in result.files}) == []


def test_it_shares_the_x12_guides_plan() -> None:
    """The same segments, in the same order, holding the same values (by source field) as the X12 guide."""
    api = _orders()
    x12 = json.loads(X12GuideEmitter().emit(api).files[0].content)
    hl7 = _guide(api)
    x12_values = [[e.get("source") for e in s["elements"]] for s in x12["segments"] if s["id"] not in ("ST", "SE")]
    hl7_values = [[f.get("source") for f in s["fields"]] for s in hl7["segments"] if s["id"] != "MSH"]
    # A timestamp is one HL7 field where X12 has two elements.
    assert [list(dict.fromkeys(v)) for v in x12_values] == [list(dict.fromkeys(v)) for v in hl7_values]


# ===========================================================================
# Table values from enums
# ===========================================================================


def test_each_enum_is_a_user_defined_table_of_its_values() -> None:
    guide = _guide(_orders())
    po = _segment_of(guide, "PurchaseOrder")
    purpose = _field_of(po, "PurchaseOrder.purpose")
    assert (purpose["dataType"], purpose["table"]) == ("IS", "9001")
    table = next(t for t in guide["tables"] if t["id"] == "9001")
    assert table["type"] == "User" and [v["code"] for v in table["values"]] == ["00", "01"]


def test_a_renamed_value_keeps_its_value_as_the_description() -> None:
    api = _api(_record("R", _field("R", "state", TypeRef(name="State"))),
               Type(key="State", name="State", kind=TypeKind.ENUM,
                    enum_values=[EnumValue(key="State.a", name="a", value="on-hold"),
                                 EnumValue(key="State.b", name="b", value="OPEN")]))
    guide = _guide(api, max_code_length=4)
    [table] = guide["tables"]
    assert table["values"] == [{"code": "ONHO", "description": "on-hold"}, {"code": "OPEN", "description": "OPEN"}]


def test_a_boolean_is_bound_to_hl7_table_0136() -> None:
    guide = _guide(_orders())
    rush = _field_of(_segment_of(guide, "PurchaseOrder"), "PurchaseOrder.rush")
    assert (rush["dataType"], rush["table"]) == ("ID", "0136")
    yes_no = next(t for t in guide["tables"] if t["id"] == "0136")
    assert yes_no["type"] == "HL7" and [v["code"] for v in yes_no["values"]] == ["Y", "N"]


def test_tables_are_numbered_from_first_table_number() -> None:
    guide = _guide(_orders(), first_table_number=500)
    assert [t["id"] for t in guide["tables"] if t["type"] == "User"] == ["0500", "0501"]


def test_each_table_is_listed_in_the_markdown() -> None:
    text = _emit(_orders()).files[2].content
    assert "### Table 9001 — purpose (User)" in text and "### Table 0136 — Yes/no indicator (HL7)" in text


def test_a_synthesized_table_is_reported() -> None:
    report = compute_lossiness_for_emitter(_orders(), Hl7v2GuideEmitter(), options={})
    items = [i for i in report.items if i.target_mapping == "table-synthesized"]
    assert {i.construct_key for i in items} == {"PurchaseOrder.purpose", "OrderLine.unit"}
    assert all(i.kind is LossinessKind.SYNTH for i in items)


# ===========================================================================
# Versions, imports, options
# ===========================================================================


def test_later_versions_use_dtm_and_cwe() -> None:
    api = _api(_record("R", _field("R", "at", TypeRef(name="datetime")),
                       _field("R", "s", TypeRef(name="State"))),
               Type(key="State", name="State", kind=TypeKind.ENUM, enum_values=[EnumValue(key="State.a", name="A")]))
    v25 = [f["dataType"] for f in _guide(api, version="2.5")["segments"][1]["fields"]]
    v26 = [f["dataType"] for f in _guide(api, version="2.6")["segments"][1]["fields"]]
    v27 = [f["dataType"] for f in _guide(api, version="2.7")["segments"][1]["fields"]]
    assert (v25, v26, v27) == (["TS", "IS"], ["DTM", "IS"], ["DTM", "CWE"])


def test_an_imported_message_keeps_its_segments_and_order() -> None:
    guide = _guide(_load("hl7v2/01-adt-a01.hl7", "hl7v2"))
    assert (guide["message"]["type"], guide["version"]) == ("ADT^A01", "2.5")
    assert [n.get("segment") for n in guide["structure"]] == ["MSH", "EVN", "PID", "NK1", "PV1"]
    pid = next(s for s in guide["segments"] if s["id"] == "PID")
    assert pid["fields"][0]["ref"] == "PID-1"


def test_message_type_and_version_are_chosen() -> None:
    guide = _guide(_orders(), message_type="zpm^z01", version="2.8")
    assert (guide["message"]["type"], guide["version"]) == ("ZPM^Z01", "2.8")
    values = {f["seq"]: f.get("value") for f in guide["segments"][0]["fields"]}
    assert (values[9], values[12]) == ("ZPM^Z01", "2.8")


@pytest.mark.parametrize("option", [{"message_type": "ADT"}, {"message_type": "AD^A01"}, {"version": "3.0"},
                                    {"version": "2"}, {"first_table_number": 0}, {"default_field_length": 0}])
def test_invalid_options_are_rejected(option) -> None:
    with pytest.raises(ValidationError):
        Hl7v2GuideEmitOptions(**option)


def test_a_model_without_records_is_refused() -> None:
    api = _api(Type(key="E", name="E", kind=TypeKind.ENUM, enum_values=[EnumValue(key="E.a", name="A")]))
    with pytest.raises(EmitPreconditionError):
        _emit(api)


def test_operations_get_the_types_only_advisory() -> None:
    api = _orders().model_copy(update={"services": [Service(key="S", name="S")]})
    assert any("HL7 v2 segment guide" in loss.detail for loss in _emit(api).losses
               if loss.subject == "services-dropped")


# ===========================================================================
# Files and checks
# ===========================================================================


def test_the_csv_and_markdown_say_what_the_json_says() -> None:
    result = _emit(_orders())
    guide = json.loads(result.files[0].content)
    assert result.files[1].content == hl7v2_csv(guide) and result.files[2].content == hl7v2_markdown(guide)
    assert result.files[1].content.splitlines()[0].startswith("segment,segment_name,seq,ref,field,data_type")


def _broken(mutate) -> List[str]:
    guide = _guide(_orders())
    mutate(guide)
    return [p.rule for p in guide_problems(guide)]


@pytest.mark.parametrize(("mutate", "rule"), [
    (lambda g: g["segments"][1].update(id="Z1"), "hl7v2-guide.segment-id"),
    (lambda g: g["segments"][1]["fields"][0].update(ref="ZZZ-9"), "hl7v2-guide.field-ref"),
    (lambda g: g["segments"][1]["fields"][0].update(dataType="XX"), "hl7v2-guide.data-type"),
    (lambda g: g["segments"][1]["fields"][0].update(length=0), "hl7v2-guide.length"),
    (lambda g: g["segments"][1]["fields"][0].update(optionality="M"), "hl7v2-guide.optionality"),
    (lambda g: g["segments"][1]["fields"][0].update(repetition="maybe"), "hl7v2-guide.repetition"),
    (lambda g: g["segments"][1]["fields"][2].pop("table"), "hl7v2-guide.table"),
    (lambda g: g["segments"][1]["fields"][2].update(table="7777"), "hl7v2-guide.table"),
    (lambda g: g["tables"].append({"id": "8888", "name": "x", "type": "User",
                                   "values": [{"code": "A", "description": "A"}]}), "hl7v2-guide.table"),
    (lambda g: g["message"].update(type="ADT"), "hl7v2-guide.message"),
    (lambda g: g["structure"].pop(0), "hl7v2-guide.envelope"),
    (lambda g: g["segments"][0]["fields"][8].update(value="ADT^A01"), "hl7v2-guide.envelope"),
    (lambda g: g["structure"][1].update(segment="ZZZ"), "hl7v2-guide.undefined-segment"),
    (lambda g: g.pop("tables"), "hl7v2-guide.schema"),
])
def test_the_checks_reject_broken_guides(mutate, rule: str) -> None:
    assert rule in _broken(mutate)


def test_the_files_must_agree() -> None:
    result = _emit(_orders())
    files = {f.path: f.content for f in result.files}
    files[result.files[1].path] = files[result.files[1].path].replace("poNumber", "po")
    assert [p.rule for p in check_guide_files(files)] == ["hl7v2-guide.files"]


def test_a_broken_guide_fails_the_gate() -> None:
    api = _orders()
    result = _emit(api)
    broken = copy.deepcopy(json.loads(result.files[0].content))
    broken["segments"][1]["id"] = "Z1"
    files = [result.files[0].model_copy(update={"content": json.dumps(broken)}), *result.files[1:]]
    verdict = asyncio.run(validate_emitted_artifact("hl7v2-guide", result.model_copy(update={"files": files}),
                                                    api=api))
    assert not verdict.valid and "hl7v2-guide.segment-id" in {f.keyword for f in verdict.findings}


# ===========================================================================
# Fidelity
# ===========================================================================


def test_the_report_names_the_hl7_message() -> None:
    report = compute_lossiness_for_emitter(_orders(), Hl7v2GuideEmitter(), options={})
    [note] = [i for i in report.items if i.target_mapping == "types → HL7 v2 message"]
    assert note.message.startswith("The openapi types are laid out as an HL7 v2 message")


def test_messages_use_hl7_terms() -> None:
    for loss in _emit(_orders()).losses:
        assert "real (explicit decimal point)" not in loss.detail
        assert "without its decimal point" not in loss.detail
    details = {loss.subject: loss.detail for loss in _emit(_orders()).losses}
    assert "site-defined segment" in details["segment-id-synthesized"]
