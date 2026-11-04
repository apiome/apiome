"""UN/EDIFACT message-guide emitter — MFX-24.2 (#4146).

Covers the acceptance criterion: **an EDIFACT guide from the same fixtures as 24.1; shared core, no drift**.

* **The same fixtures** — the X12 guide's own model (``_orders`` in ``test_x12_guide_emitter``), every X12
  corpus example and the other corpus sources the X12 guide is tested with each give a valid EDIFACT guide;
* **no drift** — both guides come from one plan (:func:`app.edi_guide.plan_guide`), so for every one of those
  sources the EDIFACT guide has the X12 guide's structure: the same segments and loops (segment groups) in the
  same order, each with the same usage and repetition, holding the same data values (by source field, kind and
  usage) — only the spelling differs. The plan's losses are the X12 guide's, with the same subjects and grades.

Also: EDIFACT terms (tags, representations, composites, qualifiers, status, segment groups, ``UNH`` / ``UNT``),
an imported EDIFACT message keeping its tags and composites, the message-type and release options, the CSV and
Markdown files, the checks (:mod:`app.edifact_guide_validation`) and the fidelity report.
"""

from __future__ import annotations

import asyncio
import copy
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from pydantic import ValidationError
from test_x12_guide_emitter import _api, _field, _orders, _record

from app.canonical_model import Constraints, EnumValue, Service, Type, TypeKind, TypeRef
from app.catalog_conversion import build_conversion_source
from app.edi_guide import GuideOptions, plan_guide
from app.edifact_guide_emitter import (
    EdifactGuideEmitOptions,
    EdifactGuideEmitter,
    edifact_csv,
    edifact_markdown,
)
from app.edifact_guide_validation import check_guide_files, guide_problems
from app.emitter import LossTracker, load_builtin_emitters
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import load_builtin_import_sources
from app.lossiness import LossinessKind
from app.x12_guide_emitter import X12GuideEmitter

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_X12 = sorted(p.name for p in (_EXAMPLES / "edi-x12").glob("*.edi"))
_EDIFACT = sorted(p.name for p in (_EXAMPLES / "edifact").glob("*.edi"))
#: The other corpus sources the X12 guide is tested with that import without an external toolchain.
_CORPUS = {"openapi": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
           "json-schema": ("json-schema/03-multiple-defs.json", "json-schema")}


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _load(path: str, fmt: str) -> Any:
    file = _EXAMPLES / path
    return build_conversion_source({"id": "i", "name": file.stem, "source_format": fmt,
                                    "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}).api


def _source(name: str) -> Any:
    if name == "orders":
        return _orders()
    if name in _CORPUS:
        return _load(*_CORPUS[name])
    if name.endswith(".edi") and name in _X12:
        return _load(f"edi-x12/{name}", "edix12")
    return _load(f"edifact/{name}", "edifact")


def _emit(api, **opts):
    return EdifactGuideEmitter().emit(api, opts=EdifactGuideEmitOptions(**opts))


def _guide(api, **opts) -> Dict[str, Any]:
    return json.loads(_emit(api, **opts).files[0].content)


def _segment(guide: Dict[str, Any], tag: str) -> Dict[str, Any]:
    return next(s for s in guide["segments"] if s["tag"] == tag)


def _segment_of(guide: Dict[str, Any], source: str) -> Dict[str, Any]:
    return next(s for s in guide["segments"] if s.get("source") == source)


# ===========================================================================
# No drift: the EDIFACT guide has the X12 guide's structure
# ===========================================================================

_SAME_FIXTURES = ["orders", *_X12, *_CORPUS]


def _values_x12(segment: Dict[str, Any]) -> List[tuple]:
    return [(e.get("source", ""), _x12_kind(e["type"]), e["usage"]) for e in segment["elements"] if e["usage"] != "X"]


def _x12_kind(element_type: str) -> str:
    return {"AN": "text", "ID": "code", "DT": "date", "TM": "time", "R": "number"}.get(
        element_type, "number" if element_type.startswith("N") else element_type)


def _values_edifact(segment: Dict[str, Any]) -> List[tuple]:
    out = []
    for element in segment["elements"]:
        for value in element.get("components") or [element]:
            if value["status"] == "N":
                continue
            kind = "code" if value.get("codes") else (
                "date" if value.get("format", "").startswith("102") else "time" if value.get("format") else
                "number" if value["representation"].startswith("n") else "text")
            out.append((value.get("source", ""), kind, {"M": "M", "C": "O"}[value["status"]]))
    return out


def _skeleton(nodes: List[Dict[str, Any]], segments: Dict[str, Dict[str, Any]], values, *, edifact: bool,
              default_max: Optional[int] = None) -> List[tuple]:
    """The structure without its envelope and spelling: each segment's usage, repetition and data values."""
    out: List[tuple] = []
    for node in nodes:
        usage = {"C": "O"}.get(node.get("status"), node.get("status")) if edifact else node["usage"]
        max_use = node["maxUse"]
        if edifact and max_use == default_max and node.get("source"):
            max_use = ">1"  # a list with no maxItems: X12 says >1, EDIFACT states the default
        if node["type"] in ("loop", "group"):
            out.append(("loop", usage, max_use, _skeleton(node["children"], segments, values, edifact=edifact,
                                                          default_max=default_max)))
            continue
        if node["segment"] in ("ST", "SE", "UNH", "UNT"):
            continue
        out.append(("segment", usage, max_use, values(segments[node["segment"]])))
    return out


@pytest.mark.parametrize("name", _SAME_FIXTURES)
def test_the_edifact_guide_has_the_x12_guides_structure(name: str) -> None:
    api = _source(name)
    x12 = json.loads(X12GuideEmitter().emit(api).files[0].content)
    edifact = _guide(api)
    x12_skeleton = _skeleton(x12["structure"], {s["id"]: s for s in x12["segments"]}, _values_x12, edifact=False)
    edifact_skeleton = _skeleton(edifact["structure"], {s["tag"]: s for s in edifact["segments"]}, _values_edifact,
                                 edifact=True, default_max=EdifactGuideEmitOptions().default_max_use)
    # An X12 code element of an imported item is text in EDIFACT only when it lost its codes; none does.
    assert edifact_skeleton == x12_skeleton


@pytest.mark.parametrize("name", _SAME_FIXTURES)
def test_the_plan_losses_are_the_x12_guides(name: str) -> None:
    api = _source(name)
    x12 = {(loss.subject, loss.pointer) for loss in X12GuideEmitter().emit(api).losses}
    edifact = {(loss.subject, loss.pointer) for loss in _emit(api).losses}
    # The EDIFACT tag rule re-tags some imported X12 IDs (N1, PO1): those segments are new, and say so.
    shared = {entry for entry in edifact if entry[0] not in {"max-use-synthesized", "segment-id-synthesized",
                                                              "services-dropped"}}
    assert shared == {entry for entry in x12 if entry[0] not in {"segment-id-synthesized", "services-dropped"}}


def test_both_guides_share_one_plan() -> None:
    """The EDIFACT options only change how IDs are spelled and imported refs read: the X12 plan is untouched."""
    api = _orders()
    plain = plan_guide(api, GuideOptions(), LossTracker())
    edifact = plan_guide(api, GuideOptions(segment_id_rule=r"^(?!U)[A-Z]{3}$", edifact_refs=True), LossTracker())
    assert [type(n).__name__ for n in plain.structure] == [type(n).__name__ for n in edifact.structure]
    assert [[e.source for e in s.elements] for s in plain.segments.values()] == [
        [e.source for e in s.elements] for s in edifact.segments.values()]


# ===========================================================================
# The same fixtures give valid guides
# ===========================================================================


@pytest.mark.parametrize("name", [*_SAME_FIXTURES, *_EDIFACT])
def test_every_fixture_gives_a_valid_guide(name: str) -> None:
    api = _source(name)
    result = _emit(api)
    suffixes = (".edifact-guide.json", ".edifact-segments.csv", ".edifact-guide.md")
    assert [f.path.endswith(suffix) for f, suffix in zip(result.files, suffixes)] == [True, True, True]
    assert check_guide_files({f.path: f.content for f in result.files}) == []
    assert asyncio.run(validate_emitted_artifact("edifact-guide", result, api=api)).valid


# ===========================================================================
# EDIFACT terms
# ===========================================================================


def test_the_message_is_wrapped_in_unh_and_unt() -> None:
    guide = _guide(_orders())
    assert [n.get("segment") for n in (guide["structure"][0], guide["structure"][-1])] == ["UNH", "UNT"]
    unh = _segment(guide, "UNH")
    assert [e["ref"] for e in unh["elements"]] == ["UNH01", "UNH02"]
    identifier = unh["elements"][1]
    assert identifier["composite"] is True
    assert [c["codes"] for c in identifier["components"][:4]] == [["ORDERS"], ["D"], ["01B"], ["UN"]]
    assert guide["message"] == {"type": "ORDERS", "version": "D", "release": "01B", "agency": "UN",
                                "name": "Orders"}


def test_tags_are_three_letters_and_never_a_service_tag() -> None:
    for name in _SAME_FIXTURES:
        for segment in _guide(_source(name))["segments"]:
            assert re.fullmatch(r"[A-Z]{3}", segment["tag"]), segment["tag"]
            assert segment["tag"] in ("UNH", "UNT") or not segment["tag"].startswith("U")


def test_representations_and_status() -> None:
    guide = _guide(_orders())
    po = _segment_of(guide, "PurchaseOrder")
    by_source = {e.get("source"): e for e in po["elements"]}
    assert by_source["PurchaseOrder.poNumber"]["representation"] == "an..22"
    assert by_source["PurchaseOrder.orderDate"]["representation"] == "n8"
    assert by_source["PurchaseOrder.orderDate"]["format"] == "102 (CCYYMMDD)"
    assert by_source["PurchaseOrder.rush"]["status"] == "C"
    assert by_source["PurchaseOrder.poNumber"]["status"] == "M"


def test_enums_are_coded_values_with_their_codes() -> None:
    guide = _guide(_orders())
    purpose = next(e for e in _segment_of(guide, "PurchaseOrder")["elements"]
                   if e.get("source") == "PurchaseOrder.purpose")
    assert purpose["codes"] == ["00", "01"] and purpose["representation"] == "an2"


def test_a_decimal_states_its_places_and_sends_its_mark() -> None:
    api = _api(_record("R", _field("R", "amount", TypeRef(name="decimal"), constraints=Constraints(multiple_of=0.01))))
    result = _emit(api)
    element = json.loads(result.files[0].content)["segments"][1]["elements"][0]
    assert (element["representation"], element["decimals"]) == ("n..15", 2)
    [detail] = [loss.detail for loss in result.losses if loss.subject == "decimal-implied"]
    assert "EDIFACT always sends the decimal mark" in detail and "without its decimal point" not in detail


def test_a_timestamp_is_one_composite_of_its_date_and_time() -> None:
    api = _api(_record("R", _field("R", "placed", TypeRef(name="datetime"))))
    result = _emit(api)
    [element] = json.loads(result.files[0].content)["segments"][1]["elements"]
    assert element["composite"] is True and element["name"] == "placed"
    assert [(c["ref"], c["representation"]) for c in element["components"]] == [
        (f"{element['ref']}-1", "n8"), (f"{element['ref']}-2", "n..8")]
    [detail] = [loss.detail for loss in result.losses if loss.subject == "timestamp-split"]
    assert "composite data element of two components" in detail


def test_loops_are_segment_groups_numbered_in_order() -> None:
    guide = _guide(_source("05-856-asn-hierarchical.edi"))
    groups: List[str] = []

    def walk(nodes):
        for node in nodes:
            if node["type"] == "group":
                groups.append(node["group"])
                assert node["children"][0]["segment"] == node["trigger"]
                walk(node["children"])

    walk(guide["structure"])
    assert groups and groups == [f"SG{i}" for i in range(1, len(groups) + 1)]


def test_a_list_with_no_max_items_repeats_the_default_and_says_so() -> None:
    api = _orders()
    guide = _guide(api, default_max_use=500)
    notes = next(n for n in guide["structure"] if n.get("source") == "PurchaseOrder.notes")
    assert notes["maxUse"] == 500
    report = compute_lossiness_for_emitter(api, EdifactGuideEmitter(), options={})
    [item] = [i for i in report.items if i.target_mapping == "max-use-synthesized"
              and i.construct_key == "PurchaseOrder.notes"]
    assert item.kind is LossinessKind.SYNTH


def test_positions_increase_in_steps_of_ten() -> None:
    positions: List[str] = []

    def walk(nodes):
        for node in nodes:
            if node["type"] == "group":
                walk(node["children"])
            else:
                positions.append(node["position"])

    walk(_guide(_orders())["structure"])
    assert positions[:3] == ["0010", "0020", "0030"]
    assert positions == sorted(positions)


# ===========================================================================
# An imported EDIFACT message
# ===========================================================================


def test_an_edifact_item_keeps_its_message_tags_and_composites() -> None:
    guide = _guide(_source("08-composition-nested-segment-groups.edi"))
    assert guide["message"]["type"] == "INVOIC" and guide["message"]["release"] == "96A"
    nad = _segment(guide, "NAD")
    assert [e["ref"] for e in nad["elements"]][:2] == ["NAD01", "NAD02"]
    composite = nad["elements"][1]
    assert composite["composite"] is True
    assert [(c["ref"], c["status"]) for c in composite["components"]] == [
        ("NAD02-1", "M"), ("NAD02-2", "N"), ("NAD02-3", "M")]


def test_an_edifact_item_keeps_its_segment_order() -> None:
    guide = _guide(_source("01-minimal-orders-d96a.edi"))
    tags = [s["tag"] for s in guide["segments"]]
    assert tags.index("BGM") < tags.index("DTM") < tags.index("NAD")


def test_a_service_segment_in_an_edifact_item_is_re_tagged() -> None:
    result = _emit(_source("08-composition-nested-segment-groups.edi"))
    guide = json.loads(result.files[0].content)
    renamed = next(s for s in guide["segments"] if s["name"] == "UNS")
    assert not renamed["tag"].startswith("U")
    assert any(loss.subject == "segment-id-synthesized" for loss in result.losses)


# ===========================================================================
# Options
# ===========================================================================


def test_message_type_and_release_are_chosen() -> None:
    guide = _guide(_orders(), message_type="invoic", release="D.96A")
    assert (guide["message"]["type"], guide["message"]["release"]) == ("INVOIC", "96A")
    assert _segment(guide, "UNH")["elements"][1]["components"][0]["codes"] == ["INVOIC"]


@pytest.mark.parametrize("option", [{"message_type": "ORDER"}, {"message_type": "ORD3RS"}, {"release": "1B"},
                                    {"release": "D96"}, {"default_max_use": 0}, {"default_element_length": 0}])
def test_invalid_options_are_rejected(option) -> None:
    with pytest.raises(ValidationError):
        EdifactGuideEmitOptions(**option)


def test_the_default_text_length_is_35() -> None:
    api = _api(_record("R", _field("R", "note", TypeRef(name="string"))))
    element = _guide(api)["segments"][1]["elements"][0]
    assert element["representation"] == "an..35"


def test_a_model_without_records_is_refused() -> None:
    from app.emitter import EmitPreconditionError

    api = _api(Type(key="E", name="E", kind=TypeKind.ENUM, enum_values=[EnumValue(key="E.a", name="A")]))
    with pytest.raises(EmitPreconditionError):
        _emit(api)


def test_operations_get_the_types_only_advisory() -> None:
    api = _orders().model_copy(update={"services": [Service(key="S", name="S")]})
    assert any("UN/EDIFACT message guide" in loss.detail for loss in _emit(api).losses
               if loss.subject == "services-dropped")


# ===========================================================================
# Files
# ===========================================================================


def test_the_csv_lists_each_element_and_component() -> None:
    result = _emit(_source("08-composition-nested-segment-groups.edi"))
    guide = json.loads(result.files[0].content)
    rows = result.files[1].content.splitlines()
    assert rows[0].startswith("segment,segment_name,ref,element,kind,representation")
    assert any(row.startswith("NAD,NAD,NAD02,NAD02,composite") for row in rows)
    assert any(row.startswith("NAD,NAD,NAD02-3,") and ",component," in row for row in rows)
    assert result.files[1].content == edifact_csv(guide)


def test_the_markdown_guide() -> None:
    result = _emit(_orders())
    text = result.files[2].content
    assert text.startswith("# UN/EDIFACT ORDERS message implementation guide — Orders")
    assert "| 0010 | UNH | Message header | M | 1 | — |" in text
    assert "SG1 (max 100, M)" in text
    assert text == edifact_markdown(json.loads(result.files[0].content))


# ===========================================================================
# The checks
# ===========================================================================


def _break(mutate) -> List[str]:
    guide = _guide(_orders())
    mutate(guide)
    return [p.rule for p in guide_problems(guide)]


@pytest.mark.parametrize(("mutate", "rule"), [
    (lambda g: g["segments"][1].update(tag="PU"), "edifact-guide.segment-tag"),
    (lambda g: g["segments"][1].update(tag="UPO"), "edifact-guide.segment-tag"),
    (lambda g: g["segments"][1]["elements"][0].update(ref="PUR09"), "edifact-guide.element-ref"),
    (lambda g: g["segments"][1]["elements"][0].update(representation="x..9"), "edifact-guide.representation"),
    (lambda g: g["segments"][1]["elements"][0].update(representation="an..5"), "edifact-guide.lengths"),
    (lambda g: g["segments"][1]["elements"][0].update(status="O"), "edifact-guide.status"),
    (lambda g: g["segments"][0]["elements"][1]["components"][0].update(codes=["INVOIC"]), "edifact-guide.envelope"),
    (lambda g: g["message"].update(type="ORDER"), "edifact-guide.message"),
    (lambda g: g["structure"].pop(0), "edifact-guide.envelope"),
    (lambda g: g["structure"][2].update(segment="ZZZ"), "edifact-guide.undefined-segment"),
    (lambda g: g["structure"][2].update(maxUse=0), "edifact-guide.max-use"),
    (lambda g: g["structure"][2].update(position="0001"), "edifact-guide.position"),
    (lambda g: next(n for n in g["structure"] if n["type"] == "group").update(group="SG7"), "edifact-guide.group"),
    (lambda g: g["segments"][1]["elements"][2].update(codes=["000"]), "edifact-guide.codes"),
    (lambda g: g.pop("message"), "edifact-guide.schema"),
])
def test_the_checks_reject_broken_guides(mutate, rule: str) -> None:
    assert rule in _break(mutate)


def test_the_files_must_agree() -> None:
    result = _emit(_orders())
    files = {f.path: f.content for f in result.files}
    csv_path = result.files[1].path
    files[csv_path] = files[csv_path].replace("poNumber", "po")
    assert [p.rule for p in check_guide_files(files)] == ["edifact-guide.files"]
    del files[result.files[2].path]
    assert any("edifact-guide.md" in p.message for p in check_guide_files(files))


def test_a_broken_guide_fails_the_export_gate() -> None:
    api = _orders()
    result = _emit(api)
    guide = json.loads(result.files[0].content)
    broken = copy.deepcopy(guide)
    broken["segments"][1]["tag"] = "UPO"
    files = [result.files[0].model_copy(update={"content": json.dumps(broken)}), *result.files[1:]]
    verdict = asyncio.run(validate_emitted_artifact("edifact-guide", result.model_copy(update={"files": files}),
                                                    api=api))
    assert not verdict.valid
    assert "edifact-guide.segment-tag" in {f.keyword for f in verdict.findings}


# ===========================================================================
# The fidelity report
# ===========================================================================


def test_the_report_grades_each_rule_as_the_x12_guide_does() -> None:
    api = _orders()
    graded = lambda emitter: {(i.construct_key, i.target_mapping, i.kind, i.severity)  # noqa: E731
                              for i in compute_lossiness_for_emitter(api, emitter, options={}).items
                              if i.target_mapping and "→" not in i.target_mapping}
    shared = {entry for entry in graded(X12GuideEmitter()) if entry[1] != "segment-id-synthesized"}
    assert shared <= graded(EdifactGuideEmitter())


def test_the_root_note_names_the_edifact_message() -> None:
    report = compute_lossiness_for_emitter(_orders(), EdifactGuideEmitter(), options={})
    [note] = [i for i in report.items if i.target_mapping == "types → UN/EDIFACT message"]
    assert note.message.startswith("The openapi types are laid out as a UN/EDIFACT message")


def test_restated_messages_use_edifact_terms() -> None:
    for name in _SAME_FIXTURES:
        for loss in _emit(_source(name)).losses:
            assert "real (explicit decimal point)" not in loss.detail, loss.detail
            assert "without its decimal point" not in loss.detail, loss.detail
