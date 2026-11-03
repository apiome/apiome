"""RELAX NG and DTD output modes of the XSD emitter — MFX-22.3 (#4134).

Covers the acceptance criteria:

* **the emitted RELAX NG validates with jing** — the export gate runs jing on a ``.rng`` / ``.rnc`` export
  when the toolchain has it (:mod:`app.relaxng_jing`); jing is stood in by a fake runner here, answering the
  way jing 20220510 does (exit 1 with ``file:line:column: error:`` lines). Every grammar is also parsed and
  re-imported by Apiome's RELAX NG reader, which these tests run for real;
* **the emitted DTD parses** — by Apiome's DTD reader, and re-imports;
* **mode-specific losses are enumerated** — each mode's fidelity report lists what that mode cannot carry
  (RELAX NG: element defaults, repeat counts, null; DTD: datatypes, facets, merged element names,
  namespaces), and the report follows the ``mode`` option.

Also: the ``mode`` option and its interplay with ``xsd_version``; file names and media types; the compact
syntax's names, literals and namespaces; any-content; an XSD source's attributes; the round trip.
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional

import pytest
from pydantic import ValidationError
from test_xsd_emitter import _NS, _api, _emit, _field, _pet_api, _record

from app import relaxng_jing
from app.canonical_model import Constraints, Type, TypeKind, TypeRef
from app.dtd_import_source import DtdImportSource
from app.export_validation import _validate_xsd
from app.fidelity_engine import compute_lossiness_for_emitter
from app.lossiness import LossinessKind
from app.relaxng_import_source import RelaxNgImportSource
from app.relaxng_jing import RelaxNgCheckError, check_relaxng_with_jing, jing_diagnostics
from app.roundtrip_matrix import import_source_text
from app.toolchain_packaging import bundled_tool
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError
from app.xml_schema_modes import RELAXNG_NS, relaxng_compact, restate_xsd_losses
from app.xsd_emitter import XsdEmitOptions, XsdEmitter
from app.xsd_roundtrip import check_emitted_xsd, output_mode_of, reimport_xsd, round_trip_xsd

_RNG = f"{{{RELAXNG_NS}}}"
_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "xsd"


def _losses(result, subject: str) -> List[str]:
    """The pointers of the export's losses with ``subject``."""
    return sorted(loss.pointer or "" for loss in result.losses if loss.subject == subject)


def _define(root: ET.Element, name: str) -> ET.Element:
    return next(el for el in root.findall(f"{_RNG}define") if el.get("name") == name)


def _report(api, mode: str):
    return compute_lossiness_for_emitter(api, XsdEmitter(), options={"mode": mode})


def _items(report, key: str):
    return [item for item in report.items if item.construct_key == key]


# ===========================================================================
# The option
# ===========================================================================


def test_the_mode_option_defaults_to_xsd_and_names_each_file() -> None:
    assert XsdEmitOptions().mode == "xsd"
    expected = {
        "xsd": ("Pets.xsd", "application/xml"),
        "relaxng": ("Pets.rng", "application/xml"),
        "relaxng-compact": ("Pets.rnc", "application/relax-ng-compact-syntax"),
        "dtd": ("Pets.dtd", "application/xml-dtd"),
    }
    for mode, (path, media_type) in expected.items():
        result = _emit(_pet_api(namespace=_NS), mode=mode)
        assert [(f.path, f.media_type) for f in result.files] == [(path, media_type)]
        assert result.media_type == media_type
        assert output_mode_of(result) == mode


def test_xsd_version_applies_to_the_xsd_mode_only() -> None:
    with pytest.raises(ValidationError, match="leave xsd_version unset"):
        XsdEmitOptions(mode="dtd", xsd_version="1.1")
    assert XsdEmitOptions(mode="relaxng", xsd_version="1.0").mode == "relaxng"
    with pytest.raises(ValidationError):
        XsdEmitOptions(mode="schematron")


def test_a_multi_namespace_source_is_one_file_in_every_other_mode() -> None:
    order = _record("Order", _field("id", TypeRef(name="string"), owner="Order"), namespace="urn:orders")
    line = _record("Line", _field("sku", TypeRef(name="string"), owner="Line"), namespace="urn:lines")
    order.fields.append(_field("line", TypeRef(name="Line"), owner="Order"))
    api = _api([order, line], namespace="urn:orders")
    assert len(_emit(api).files) == 2
    for mode in ("relaxng", "relaxng-compact", "dtd"):
        assert len(_emit(api, mode=mode).files) == 1


# ===========================================================================
# RELAX NG — XML syntax
# ===========================================================================


def test_relaxng_writes_types_as_defines_with_facets_as_params() -> None:
    result = _emit(_pet_api(namespace=_NS), mode="relaxng")
    root = ET.fromstring(result.files[0].content)
    assert root.tag == f"{_RNG}grammar"
    assert root.get("ns") == _NS
    assert root.get("datatypeLibrary") == "http://www.w3.org/2001/XMLSchema-datatypes"
    pet = _define(root, "Pet")
    name = next(el for el in pet.iter(f"{_RNG}element") if el.get("name") == "name")
    params = {p.get("name"): p.text for p in name.iter(f"{_RNG}param")}
    assert params == {"minLength": "1", "maxLength": "40", "pattern": "[A-Za-z ]+"}
    tags = next(el for el in pet.iter(f"{_RNG}element") if el.get("name") == "tags")
    assert tags in list(next(z for z in pet.iter(f"{_RNG}zeroOrMore")))
    status = _define(root, "Status")
    assert [v.text for v in status.iter(f"{_RNG}value")] == ["available", "sold"]
    contact = _define(root, "Contact")
    assert [el.get("name") for el in contact.find(f"{_RNG}choice")] == ["email", "phone"]
    start_refs = [ref.get("name") for ref in root.find(f"{_RNG}start").iter(f"{_RNG}ref")]
    assert start_refs == ["Pet.element", "Contact.element"]


def test_relaxng_parses_and_reimports_with_its_facets() -> None:
    result = _emit(_pet_api(namespace=_NS), mode="relaxng")
    assert check_emitted_xsd(result) == []
    api = reimport_xsd(result)
    assert api.format == "relaxng"
    pet = next(t for t in api.types if t.name == "Pet")
    name = next(f for f in pet.fields if f.name == "name")
    assert (name.constraints.min_length, name.constraints.max_length) == (1, 40)


def test_relaxng_losses_name_what_the_grammar_cannot_say() -> None:
    result = _emit(_pet_api(namespace=_NS), mode="relaxng")
    assert _losses(result, "default-dropped") == ["Pet.legs"]
    assert "Pet.nickname" in _losses(result, "null-as-optional")
    assert not _losses(result, "null-as-nillable")
    assert not _losses(result, "datatype-dropped")  # RELAX NG keeps the XSD datatypes
    union = next(loss for loss in result.losses if loss.subject == "union-as-choice")
    assert union.detail.startswith("RELAX NG has no union of shapes") and "xs:" not in union.detail


def test_repeat_counts_are_widened_and_reported() -> None:
    pet = _record(
        "Pet", _field("tags", TypeRef(item=TypeRef(name="string")), constraints=Constraints(min_items=2, max_items=5))
    )
    for mode in ("relaxng", "dtd"):
        result = _emit(_api([pet]), mode=mode)
        assert _losses(result, "occurrence-bounds") == ["Pet.tags"]
        detail = next(loss.detail for loss in result.losses if loss.subject == "occurrence-bounds")
        assert "(2..5)" in detail and "one or more" in detail
    root = ET.fromstring(_emit(_api([pet]), mode="relaxng").files[0].content)
    assert _define(root, "Pet").find(f"{_RNG}oneOrMore") is not None
    assert "<!ELEMENT Pet (tags+)>" in _emit(_api([pet]), mode="dtd").files[0].content


def test_free_form_content_is_any_element() -> None:
    bag = Type(key="Bag", name="Bag", kind=TypeKind.MAP, value_type=None)
    holder = _record("Holder", _field("bag", TypeRef(name="Bag"), owner="Holder"))
    result = _emit(_api([holder, bag]), mode="relaxng")
    root = ET.fromstring(result.files[0].content)
    names = {el.get("name") for el in root.findall(f"{_RNG}define")}
    assert {"any.element", "any.content"} <= names
    assert check_emitted_xsd(result) == []
    assert "ANY" in _emit(_api([holder, bag]), mode="dtd").files[0].content


def test_relaxng_keeps_each_namespace() -> None:
    order = _record("Order", _field("id", TypeRef(name="string"), owner="Order"), namespace="urn:orders")
    line = _record("Line", _field("sku", TypeRef(name="string"), owner="Line"), namespace="urn:lines")
    order.fields.append(_field("line", TypeRef(name="Line"), owner="Order"))
    api = _api([order, line], namespace="urn:orders")
    root = ET.fromstring(_emit(api, mode="relaxng").files[0].content)
    assert root.get("ns") == "urn:orders"
    sku = next(el for el in root.iter(f"{_RNG}element") if el.get("name") == "sku")
    assert sku.get("ns") == "urn:lines"
    compact = _emit(api, mode="relaxng-compact").files[0].content
    assert 'namespace ns1 = "urn:lines"' in compact and "element ns1:sku" in compact
    assert check_emitted_xsd(_emit(api, mode="relaxng-compact")) == []


def test_descriptions_are_documentation_and_comments() -> None:
    pet = _record("Pet", _field("name", TypeRef(name="string"), description="The pet's\ncalled name."))
    pet.description = "A pet."
    rng = _emit(_api([pet]), mode="relaxng").files[0].content
    assert "<a:documentation>A pet.</a:documentation>" in rng
    rnc = _emit(_api([pet]), mode="relaxng-compact").files[0].content
    assert "## A pet.\nPet = " in rnc
    dtd = _emit(_api([pet]), mode="dtd").files[0].content
    assert "<!-- A pet. -->" in dtd


# ===========================================================================
# RELAX NG — compact syntax
# ===========================================================================


def test_compact_syntax_reads_back_as_the_same_grammar() -> None:
    api = _pet_api(namespace=_NS)
    compact = _emit(api, mode="relaxng-compact")
    text = compact.files[0].content
    assert text.startswith("# Generated RELAX NG for Pets\ndatatypes xsd = ")
    assert f'default namespace = "{_NS}"' in text
    assert 'xsd:string { minLength = "1" maxLength = "40" pattern = "[A-Za-z ]+" }' in text
    assert "element tags { xsd:string }*" in text
    assert check_emitted_xsd(compact) == []
    xml_names = {t.name for t in reimport_xsd(_emit(api, mode="relaxng")).types}
    assert {t.name for t in reimport_xsd(compact).types} == xml_names


def test_compact_names_that_are_keywords_are_escaped() -> None:
    pet = _record("Pet", _field("text", TypeRef(name="string")), _field("element", TypeRef(name="string")))
    result = _emit(_api([pet]), mode="relaxng-compact")
    assert "element \\text { xsd:string }" in result.files[0].content
    assert "element \\element { xsd:string }" in result.files[0].content
    assert check_emitted_xsd(result) == []


def test_compact_literals_hold_any_quote() -> None:
    quote = Type(
        key="Quote", name="Quote", kind=TypeKind.SCALAR,
        constraints=Constraints(enum=['say "hi"', "it's"]),
    )
    holder = _record("Holder", _field("q", TypeRef(name="Quote"), owner="Holder"))
    result = _emit(_api([holder, quote]), mode="relaxng-compact")
    text = result.files[0].content
    assert """xsd:string 'say "hi"'""" in text and '''xsd:string "it's"''' in text
    assert check_emitted_xsd(result) == []


def test_relaxng_compact_renders_a_grammar_built_by_hand() -> None:
    grammar = ET.fromstring(
        f'<grammar xmlns="{RELAXNG_NS}"><start><element name="a"><optional><attribute name="b"/></optional>'
        "<choice><text/><empty/></choice></element></start></grammar>"
    )
    text = relaxng_compact(grammar)
    assert "start = element a { (attribute b { text }?, (text | empty)) }" in text


# ===========================================================================
# DTD
# ===========================================================================


def test_dtd_writes_content_models_and_fixed_namespaces() -> None:
    result = _emit(_pet_api(namespace=_NS), mode="dtd")
    text = result.files[0].content
    assert "<!-- Root element: Pet -->" in text
    assert "<!ELEMENT Pet (id?, name?, age?, nickname?, tags*, status?, owner?, legs?)>" in text
    assert "<!ELEMENT owner (email | phone)>" in text
    assert "<!ELEMENT age (#PCDATA)>" in text
    assert f'xmlns CDATA #FIXED "{_NS}"' in text
    assert _losses(result, "namespace-as-fixed-xmlns") == ["$"]


def test_a_dtd_without_a_namespace_declares_no_xmlns() -> None:
    text = _emit(_pet_api(), mode="dtd").files[0].content
    assert "xmlns" not in text
    assert not _losses(_emit(_pet_api(), mode="dtd"), "namespace-as-fixed-xmlns")


def test_dtd_parses_and_reimports() -> None:
    result = _emit(_pet_api(namespace=_NS), mode="dtd")
    assert check_emitted_xsd(result) == []
    api = reimport_xsd(result)
    assert api.format == "dtd"
    assert {"Pet", "owner"} <= {t.name for t in api.types}


def test_dtd_losses_are_every_datatype_facet_and_enumeration() -> None:
    result = _emit(_pet_api(namespace=_NS), mode="dtd")
    assert _losses(result, "datatype-dropped") == ["Pet.age", "Pet.id", "Pet.legs"]
    assert _losses(result, "facet-dropped") == ["Pet.age", "Pet.name", "Status"]
    assert _losses(result, "default-dropped") == ["Pet.legs"]
    assert not _losses(result, "unsupported-facet")
    name = next(loss.detail for loss in result.losses if loss.subject == "facet-dropped" and loss.pointer == "Pet.name")
    assert "maxLength, minLength, pattern" in name


def test_two_elements_of_one_name_are_declared_once_as_any() -> None:
    first = _record("First", _field("item", TypeRef(name="string"), owner="First"))
    inner = _record("Inner", _field("x", TypeRef(name="string"), owner="Inner"))
    second = _record("Second", _field("item", TypeRef(name="Inner"), owner="Second"))
    result = _emit(_api([first, second, inner]), mode="dtd")
    assert "<!ELEMENT item ANY>" in result.files[0].content
    assert result.files[0].content.count("<!ELEMENT item ") == 1
    assert _losses(result, "element-merged") == ["First.item", "Second.item"]
    assert check_emitted_xsd(result) == []


def test_a_recursive_type_is_declared_once() -> None:
    node = _record("Node", _field("next", TypeRef(name="Node", nullable=True), owner="Node"))
    text = _emit(_api([node]), mode="dtd").files[0].content
    assert "<!ELEMENT Node (next?)>" in text and "<!ELEMENT next (next?)>" in text


# ===========================================================================
# An XSD source
# ===========================================================================


@pytest.mark.parametrize("mode", ["relaxng", "relaxng-compact", "dtd"])
@pytest.mark.parametrize("example", ["01-purchase-order.xsd", "03-library-extension.xsd", "04-kitchen-sink.xsd"])
def test_an_xsd_source_exports_to_a_grammar_that_parses(example: str, mode: str) -> None:
    from app.import_source import get_import_source

    api = import_source_text(get_import_source("xsd"), (_EXAMPLES / example).read_text(encoding="utf-8"))
    result = XsdEmitter().emit(api, opts=XsdEmitOptions(mode=mode))
    assert check_emitted_xsd(result) == []
    assert reimport_xsd(result).types


def test_an_xsd_attribute_stays_an_attribute() -> None:
    from app.import_source import get_import_source

    source = (
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        '<xs:element name="note" type="Note"/>'
        '<xs:complexType name="Note"><xs:sequence><xs:element name="body" type="xs:string"/></xs:sequence>'
        '<xs:attribute name="lang" type="xs:language"/></xs:complexType></xs:schema>'
    )
    api = import_source_text(get_import_source("xsd"), source)
    rng = ET.fromstring(XsdEmitter().emit(api, opts=XsdEmitOptions(mode="relaxng")).files[0].content)
    attribute = next(rng.iter(f"{_RNG}attribute"))
    assert attribute.get("name") == "lang" and attribute.find(f"{_RNG}data").get("type") == "language"
    dtd = XsdEmitter().emit(api, opts=XsdEmitOptions(mode="dtd")).files[0].content
    assert "<!ATTLIST note\n  lang CDATA #IMPLIED\n>" in dtd


# ===========================================================================
# Fidelity follows the mode
# ===========================================================================


def test_the_fidelity_report_follows_the_mode() -> None:
    api = _pet_api(namespace=_NS)
    xsd = _report(api, "xsd")
    dtd = _report(api, "dtd")
    rng = _report(api, "relaxng")
    assert not [i for i in _items(xsd, "Pet.age") if i.kind is LossinessKind.DROP]
    assert [i for i in _items(dtd, "Pet.age") if i.kind is LossinessKind.DROP]
    assert [i for i in _items(rng, "Pet.legs") if i.kind is LossinessKind.DROP]
    assert not [i for i in _items(rng, "Pet.age") if i.kind is LossinessKind.DROP]
    root_messages = " ".join(i.message for i in dtd.items if i.construct_key in ("$", "root", ""))
    assert "written as a DTD" in root_messages


def test_the_report_names_the_mode_for_a_types_only_source() -> None:
    from app.canonical_model import Operation, OperationKind, Service

    api = _pet_api(namespace=_NS)
    api.services = [Service(key="Pets", name="Pets", operations=[
        Operation(key="Pets.list", name="list", kind=OperationKind.REQUEST_RESPONSE)
    ])]
    report = _report(api, "dtd")
    drop = next(i for i in report.items if i.construct_key == "Pets.list")
    assert drop.kind is LossinessKind.DROP and drop.message.startswith("DTD is types-only")


def test_invalid_options_fall_back_to_the_xsd_report() -> None:
    api = _pet_api(namespace=_NS)
    fallback = compute_lossiness_for_emitter(api, XsdEmitter(), options={"mode": "dtd", "xsd_version": "1.1"})
    assert not [i for i in _items(fallback, "Pet.age") if i.kind is LossinessKind.DROP]


def test_restated_losses_leave_the_xsd_writers_alone() -> None:
    result = _emit(_pet_api(namespace=_NS))
    from app.emitter import LossTracker

    tracker = LossTracker()
    for loss in result.losses:
        tracker.record(loss.kind, loss.subject, loss.detail, pointer=loss.pointer)
    restated = restate_xsd_losses(tracker, "dtd")
    assert {loss.subject for loss in tracker.records()} >= {"null-as-nillable"}
    assert "null-as-nillable" not in {loss.subject for loss in restated.records()}


# ===========================================================================
# The export gate — jing, then the readers
# ===========================================================================


class _FakeRunner:
    """Answers ``run_spec`` the way jing would: ``None`` for a valid grammar, or raises."""

    def __init__(self, error: Optional[Exception] = None) -> None:
        self.error = error
        self.calls: List[dict] = []

    async def run_spec(self, spec, args, **kwargs):
        self.calls.append({"executable": spec.executable, "args": list(spec.base_args) + list(args),
                           "cwd": kwargs.get("cwd")})
        if self.error is not None:
            raise self.error
        return None


def _jing_error(path: str) -> ToolExecutionError:
    stdout = f"/tmp/apiome-jing-x/{path}:12:5: error: reference to undefined pattern \"Missing\"\n"
    return ToolExecutionError("jing", 1, stdout, "")


def test_jing_is_called_with_c_for_the_compact_syntax() -> None:
    runner = _FakeRunner()
    asyncio.run(check_relaxng_with_jing("Pets.rnc", "start = empty\n", runner=runner))
    asyncio.run(check_relaxng_with_jing("Pets.rng", "<grammar/>", runner=runner))
    assert [call["args"] for call in runner.calls] == [["-c", "Pets.rnc"], ["Pets.rng"]]


def test_jing_diagnostics_lose_the_scratch_folder() -> None:
    assert jing_diagnostics(_jing_error("Pets.rng").stdout) == [
        'Pets.rng:12:5: reference to undefined pattern "Missing"'
    ]
    assert jing_diagnostics("warning: nothing\n") == []


def test_a_grammar_jing_rejects_fails_the_export(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _pet_api(namespace=_NS)
    result = _emit(api, mode="relaxng")
    monkeypatch.setattr(relaxng_jing, "default_runner", _FakeRunner(_jing_error("Pets.rng")))
    validation = asyncio.run(_validate_xsd("xsd", result, api))
    assert not validation.valid
    assert [(f.keyword, f.file) for f in validation.findings] == [("relaxng.schema", "Pets.rng")]
    assert validation.findings[0].message == 'Pets.rng:12:5: reference to undefined pattern "Missing"'


def test_a_grammar_jing_accepts_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _pet_api(namespace=_NS)
    runner = _FakeRunner()
    monkeypatch.setattr(relaxng_jing, "default_runner", runner)
    for mode in ("relaxng", "relaxng-compact"):
        assert asyncio.run(_validate_xsd("xsd", _emit(api, mode=mode), api)).valid
    assert len(runner.calls) == 2


def test_without_jing_the_reader_decides(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _pet_api(namespace=_NS)
    monkeypatch.setattr(relaxng_jing, "default_runner", _FakeRunner(ToolNotAvailableError("jing", "jing")))
    assert asyncio.run(_validate_xsd("xsd", _emit(api, mode="relaxng"), api)).valid


def test_a_dtd_export_never_calls_jing(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _pet_api(namespace=_NS)
    runner = _FakeRunner()
    monkeypatch.setattr(relaxng_jing, "default_runner", runner)
    assert asyncio.run(_validate_xsd("xsd", _emit(api, mode="dtd"), api)).valid
    assert runner.calls == []


def test_an_unparseable_grammar_is_a_reader_finding() -> None:
    result = _emit(_pet_api(namespace=_NS), mode="relaxng-compact")
    result.files[0].content = "start = element a {"
    problems = check_emitted_xsd(result)
    assert [p["rule"] for p in problems] == ["relaxng.parse"]
    broken = _emit(_pet_api(namespace=_NS), mode="dtd")
    broken.files[0].content = "<!ELEMENT a (b"
    assert [p["rule"] for p in check_emitted_xsd(broken)] == ["dtd.parse"]


def test_an_unsafe_path_raises_before_jing_runs() -> None:
    runner = _FakeRunner()
    with pytest.raises(RelaxNgCheckError, match="Unsafe"):
        asyncio.run(check_relaxng_with_jing("notes.txt", "", runner=runner))
    asyncio.run(check_relaxng_with_jing("../escape/Pets.rng", "<grammar/>", runner=runner))
    assert runner.calls[0]["args"] == ["Pets.rng"]  # only the base name reaches the scratch folder


def test_jing_is_a_bundled_jvm_tool() -> None:
    tool = bundled_tool("jing")
    assert tool is not None
    assert (tool.version, tool.runtime, tool.env_override_key) == ("20220510", "jvm", "APIOME_JING_BIN")


# ===========================================================================
# Round trip
# ===========================================================================


@pytest.mark.parametrize(("mode", "path"), [("relaxng", "relaxng"), ("relaxng-compact", "relaxng"), ("dtd", "dtd")])
def test_the_round_trip_measures_through_the_modes_reader(mode: str, path: str) -> None:
    report = round_trip_xsd(_pet_api(namespace=_NS), opts=XsdEmitOptions(mode=mode))
    assert report.import_path == path
    assert report.reimported and not report.problems


def test_readers_accept_the_exports_directly() -> None:
    rng = _emit(_pet_api(namespace=_NS), mode="relaxng").files[0].content
    RelaxNgImportSource().parse(rng, source_label="Pets.rng")
    dtd = _emit(_pet_api(namespace=_NS), mode="dtd").files[0].content
    DtdImportSource().parse(dtd, source_label="Pets.dtd")
