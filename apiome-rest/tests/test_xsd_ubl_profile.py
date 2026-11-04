"""UBL and Peppol BIS profiles of the XSD export — MFX-24.6 (#4346).

Covers the acceptance criteria:

* **the UBL guide emits and validates against UBL 2.x schemas** — with ``profile="ubl"`` the export is a UBL 2.1
  document schema that imports the official OASIS UBL 2.1 component schemas, shipped unmodified beside it; every
  fixture's export builds with an XML Schema processor against them (sandboxed: only the export's own files are
  read) and passes the export gate;
* **Peppol BIS profile conventions are applied when selected** — with ``profile="peppol"`` the document is an
  ``Invoice`` or a ``CreditNote``, its ``cbc:CustomizationID`` / ``cbc:ProfileID`` are mandatory and documented with
  the BIS Billing 3.0 values, and ``cbc:ID``, ``cbc:IssueDate``, the type code and ``cbc:DocumentCurrencyCode`` are
  mandatory — the item's own, else added and reported; the gate checks those conventions.

Also: UBL data types and names, ``cbc:`` reuse, aggregates, the document root and record, the shipped files and
notice, the guide, the options and the fidelity report.
"""

from __future__ import annotations

import asyncio
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List

import pytest
import xmlschema
from pydantic import ValidationError
from test_xsd_emitter import _api, _field, _pet_api, _record
from test_xsd_iso20022_profile import _payment_api

from app.canonical_model import Constraints, EnumValue, Type, TypeKind, TypeRef
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitOptionsError, EmittedFile, load_builtin_emitters
from app.export_validation import _validate_xsd
from app.fidelity_engine import compute_lossiness_for_emitter
from app.fidelity_rulepack import ROOT_CONSTRUCT_KEY
from app.import_source import get_import_source, load_builtin_import_sources
from app.lossiness import LossinessKind, LossinessSeverity
from app.ubl_xsd_profile import (
    BUNDLE_DIR,
    PEPPOL_CUSTOMIZATION_ID,
    PEPPOL_PROFILE_ID,
    UBL_NOTICE_PATH,
    bundled_files,
    cbc_components,
    peppol_problems,
    ubl_data_type,
    ubl_element_name,
)
from app.xsd_emitter import XsdEmitOptions, XsdEmitter
from app.xsd_roundtrip import check_emitted_xsd, reimport_xsd

_XS = "{http://www.w3.org/2001/XMLSchema}"
_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_COMMON = ("common/CCTS_CCT_SchemaModule-2.1.xsd", "common/UBL-CommonBasicComponents-2.1.xsd",
           "common/UBL-QualifiedDataTypes-2.1.xsd", "common/UBL-UnqualifiedDataTypes-2.1.xsd")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _emit(api, **opts):
    return XsdEmitter().emit(api, opts=XsdEmitOptions(**opts))


def _schema(result) -> ET.Element:
    return ET.fromstring(result.files[0].content)


def _type(root: ET.Element, name: str) -> ET.Element:
    return next(el for el in root.findall(f"{_XS}complexType") if el.get("name") == name)


def _children(complex_el: ET.Element) -> List[str]:
    return [el.get("ref") or el.get("name") for el in complex_el.find(f"{_XS}sequence").findall(f"{_XS}element")]


def _element(complex_el: ET.Element, name: str) -> ET.Element:
    return next(el for el in complex_el.find(f"{_XS}sequence").findall(f"{_XS}element")
                if name in (el.get("name"), el.get("ref")))


def _build(result) -> xmlschema.XMLSchema10:
    """Build the export as it unpacks, with an XML Schema processor that may read only the export's own files."""
    with tempfile.TemporaryDirectory() as folder:
        for emitted in result.files:
            target = Path(folder, emitted.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(emitted.content, encoding="utf-8")
        return xmlschema.XMLSchema10(str(Path(folder, result.files[0].path)), allow="sandbox")


def _losses(result, subject: str) -> List[str]:
    return sorted(loss.pointer or "" for loss in result.losses if loss.subject == subject)


def _report(api, **opts):
    return compute_lossiness_for_emitter(api, XsdEmitter(), options=opts)


def _load(path: str, fmt: str):
    file = _EXAMPLES / path
    return build_conversion_source({"id": "i", "name": file.stem, "source_format": fmt,
                                    "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}).api


def _ubl_item(folder: str):
    """An imported UBL 2.1 document schema set (MFI-20.5)."""
    adapter = get_import_source("xsd")
    from app.fileset import IntakeFileset

    members = {p.name: p.read_text(encoding="utf-8") for p in sorted((_EXAMPLES / "xsd" / folder).glob("*.xsd"))}
    root = next(name for name in members if not name.startswith("UBL-Common"))
    fileset = IntakeFileset.from_members(members, root=root)
    return adapter.normalize(adapter.parse_fileset(fileset, source_label=root))


def _invoice_api():
    """A typed invoice with its own number, issue date, currency and a note — the values Peppol wants."""
    o = "Bill"
    return _api([
        _record(o,
                _field("ID", TypeRef(name="string"), owner=o, field_number=1),
                _field("issueDate", TypeRef(name="date"), owner=o, field_number=2),
                _field("note", TypeRef(name="string", nullable=True), owner=o, field_number=3),
                _field("documentCurrencyCode", TypeRef(name="Currency"), owner=o, field_number=4),
                _field("totalAmount", TypeRef(name="decimal"), owner=o, field_number=5),
                _field("paid", TypeRef(name="boolean"), owner=o, field_number=6)),
        Type(key="Currency", name="Currency", kind=TypeKind.ENUM,
             enum_values=[EnumValue(key="Currency.EUR", name="EUR"), EnumValue(key="Currency.USD", name="USD")]),
    ])


# ===========================================================================
# The bundled OASIS schemas
# ===========================================================================


def test_the_oasis_schemas_are_bundled_with_their_notice() -> None:
    # Exactly the schemas an export imports: nothing from the distribution that is not used.
    assert sorted(f"common/{p.name}" for p in (BUNDLE_DIR / "common").glob("*.xsd")) == sorted(_COMMON)
    notice = (BUNDLE_DIR / "NOTICE.md").read_text(encoding="utf-8")
    assert "Copyright © OASIS Open 2001-2013. All Rights Reserved." in notice
    assert "may not be modified in any way" in notice
    for path in BUNDLE_DIR.rglob("*.xsd"):
        # Every file keeps its own copyright notice: OASIS's, or UN/CEFACT's for the CCTS module.
        header = path.read_text(encoding="utf-8")[:2000]
        assert "Copyright" in header and ("OASIS" in header or "UN/CEFACT" in header), path
    assert "UN/CEFACT" in notice


def test_the_bundled_basic_components_build_on_their_own() -> None:
    schema = xmlschema.XMLSchema10(str(BUNDLE_DIR / "common" / "UBL-CommonBasicComponents-2.1.xsd"), allow="sandbox")
    assert len(schema.elements) == len(cbc_components())


def test_the_component_catalog_is_read_from_the_bundle() -> None:
    components = cbc_components()
    assert len(components) > 800
    assert (components["IssueDate"], components["Note"], components["ID"]) == ("DateType", "TextType",
                                                                               "IdentifierType")
    assert components["DocumentCurrencyCode"] == "CodeType"


def test_an_export_ships_the_import_closure_it_needs() -> None:
    assert tuple(bundled_files()) == _COMMON


# ===========================================================================
# The options
# ===========================================================================


@pytest.mark.parametrize("field", ["ubl_document", "ubl_namespace", "document_record"])
def test_the_ubl_options_need_a_ubl_profile(field: str) -> None:
    value = {"ubl_document": "Invoice", "ubl_namespace": "urn:x", "document_record": "Bill"}[field]
    with pytest.raises(ValidationError, match="apply to profile 'ubl' or 'peppol' only"):
        XsdEmitOptions(**{field: value})


@pytest.mark.parametrize("profile", ["ubl", "peppol"])
@pytest.mark.parametrize("mode", ["relaxng", "dtd"])
def test_a_ubl_profile_writes_xml_schema_only(profile: str, mode: str) -> None:
    with pytest.raises(ValidationError, match="writes an XML Schema"):
        XsdEmitOptions(profile=profile, mode=mode)


def test_peppol_writes_an_invoice_or_a_credit_note() -> None:
    with pytest.raises(ValidationError, match="Invoice or a CreditNote"):
        XsdEmitOptions(profile="peppol", ubl_document="Order")
    assert XsdEmitOptions(profile="peppol", ubl_document="CreditNote").ubl_document == "CreditNote"
    assert XsdEmitOptions(profile="ubl", ubl_document="Order").ubl_document == "Order"


@pytest.mark.parametrize(("option", "value"), [("ubl_document", "invoice"), ("ubl_document", "Bad-Name"),
                                               ("ubl_namespace", "not a uri")])
def test_invalid_ubl_options_are_rejected(option: str, value: str) -> None:
    with pytest.raises(ValidationError):
        XsdEmitOptions(profile="ubl", **{option: value})


def test_an_unknown_document_record_is_refused() -> None:
    with pytest.raises(EmitOptionsError, match="names no record type"):
        _emit(_invoice_api(), profile="ubl", document_record="Nope")


# ===========================================================================
# AC 1 — emits and validates against the UBL 2.x schemas
# ===========================================================================

_FIXTURES = {
    "invoice": _invoice_api,
    "payment": _payment_api,
    "pets": lambda: _pet_api(namespace="http://example.com/pets"),
    "openapi": lambda: _load("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "json-schema": lambda: _load("json-schema/03-multiple-defs.json", "json-schema"),
    "xsd-purchase-order": lambda: _load("xsd/01-purchase-order.xsd", "xsd"),
    "xsd-kitchen-sink": lambda: _load("xsd/04-kitchen-sink.xsd", "xsd"),
    "ubl-2.1-invoice-set": lambda: _ubl_item("07-ubl-2.1-invoice-set"),
}


@pytest.mark.parametrize("profile", ["ubl", "peppol"])
@pytest.mark.parametrize("name", _FIXTURES)
def test_every_fixture_validates_against_the_ubl_schemas(name: str, profile: str) -> None:
    api = _FIXTURES[name]()
    result = _emit(api, profile=profile)
    schema = _build(result)  # raises unless the document schema is valid against the shipped OASIS schemas
    assert len(schema.elements) == 1
    assert check_emitted_xsd(result) == []
    assert asyncio.run(_validate_xsd("xsd", result, api)).valid


def test_the_export_files() -> None:
    result = _emit(_invoice_api(), profile="ubl", ubl_document="Invoice")
    assert [(f.path, f.media_type) for f in result.files] == [
        ("Invoice.xsd", "application/xml"),
        *((path, "application/xml") for path in _COMMON),
        (UBL_NOTICE_PATH, "text/markdown"),
        ("Invoice.ubl-guide.md", "text/markdown"),
    ]
    for path in _COMMON:
        shipped = next(f.content for f in result.files if f.path == path)
        assert shipped == (BUNDLE_DIR / path).read_text(encoding="utf-8")


def test_the_schema_imports_the_ubl_components_it_uses() -> None:
    root = _schema(_emit(_invoice_api(), profile="ubl"))
    imports = {(el.get("namespace"), el.get("schemaLocation")) for el in root.findall(f"{_XS}import")}
    assert imports == {
        ("urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
         "common/UBL-CommonBasicComponents-2.1.xsd"),
        ("urn:oasis:names:specification:ubl:schema:xsd:UnqualifiedDataTypes-2",
         "common/UBL-UnqualifiedDataTypes-2.1.xsd"),
    }
    assert root.get("targetNamespace") == "urn:apiome:names:specification:ubl:schema:xsd:Pets-2"


def test_an_instance_of_the_document_validates() -> None:
    """The schema is not only valid: a UBL instance of it validates, with UBL's own data types."""
    result = _emit(_invoice_api(), profile="ubl", ubl_document="Invoice")
    ns = "urn:apiome:names:specification:ubl:schema:xsd:Invoice-2"
    cbc = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
    instance = (
        f'<Invoice xmlns="{ns}" xmlns:cbc="{cbc}">'
        "<cbc:CustomizationID>urn:example</cbc:CustomizationID>"
        "<cbc:ID>INV-1</cbc:ID><cbc:IssueDate>2026-11-04</cbc:IssueDate>"
        "<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode>"
        '<cbc:TotalAmount currencyID="EUR">120.50</cbc:TotalAmount><PaidIndicator>true</PaidIndicator>'
        "</Invoice>"
    )
    with tempfile.TemporaryDirectory() as folder:
        for emitted in result.files:
            target = Path(folder, emitted.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(emitted.content, encoding="utf-8")
        schema = xmlschema.XMLSchema10(str(Path(folder, result.files[0].path)), allow="sandbox")
        Path(folder, "good.xml").write_text(instance, encoding="utf-8")
        Path(folder, "bad.xml").write_text(instance.replace(' currencyID="EUR"', ""), encoding="utf-8")
        schema.validate(str(Path(folder, "good.xml")))
        with pytest.raises(xmlschema.XMLSchemaValidationError):
            schema.validate(str(Path(folder, "bad.xml")))  # UBL requires an amount's currency


# ===========================================================================
# UBL conventions
# ===========================================================================


@pytest.mark.parametrize(("scalar", "name", "constraints", "enum", "expected"), [
    ("string", "note", None, False, "TextType"),
    ("string", "customerName", None, False, "NameType"),
    ("string", "invoiceId", None, False, "IdentifierType"),
    ("string", "ref", Constraints(format="uuid"), False, "IdentifierType"),
    ("string", "status", None, True, "CodeType"),
    ("boolean", "paid", None, False, "IndicatorType"),
    ("int32", "lineCount", None, False, "NumericType"),
    ("decimal", "totalAmount", None, False, "AmountType"),
    ("decimal", "unitPrice", None, False, "AmountType"),
    ("double", "ratio", None, False, "NumericType"),
    ("date", "due", None, False, "DateType"),
    ("string", "at", Constraints(format="date-time"), False, "DateTimeType"),
    ("time", "cutoff", None, False, "TimeType"),
    ("bytes", "scan", None, False, "BinaryObjectType"),
])
def test_ubl_data_type(scalar, name, constraints, enum, expected) -> None:
    assert ubl_data_type(scalar, name, constraints, enum=enum) == expected


@pytest.mark.parametrize(("raw", "data_type", "expected"), [
    ("status", "CodeType", "StatusCode"),
    ("paid", "IndicatorType", "PaidIndicator"),
    ("issueDate", "DateType", "IssueDate"),
    ("orderId", "IdentifierType", "OrderID"),
    ("note", "TextType", "Note"),
    ("total_amount", "AmountType", "TotalAmount"),
])
def test_ubl_element_names_end_with_their_representation_term(raw, data_type, expected) -> None:
    assert ubl_element_name(raw, data_type)[0] == expected


def test_values_matching_a_ubl_component_reference_it() -> None:
    root = _schema(_emit(_invoice_api(), profile="ubl", ubl_document="Invoice"))
    children = _children(_type(root, "InvoiceType"))
    # TotalAmount is a UBL basic component too, so it is reused; PaidIndicator is not, so it is the item's own.
    assert {"cbc:ID", "cbc:IssueDate", "cbc:Note", "cbc:DocumentCurrencyCode", "cbc:TotalAmount"} <= set(children)
    paid = _element(_type(root, "InvoiceType"), "PaidIndicator")
    assert paid.get("type") == "udt:IndicatorType"


def test_aggregates_are_named_type_and_nothing_is_nillable() -> None:
    result = _emit(_payment_api(), profile="ubl")
    root = _schema(result)
    names = {el.get("name") for el in root.findall(f"{_XS}complexType")}
    assert {"GroupHeaderType", "PaymentType"} <= names
    assert all(name.endswith("Type") for name in names)
    assert not any(el.get("nillable") for el in root.iter(f"{_XS}element"))
    assert _losses(result, "null-as-nillable") == []


def test_rules_and_codes_are_documentation() -> None:
    result = _emit(_invoice_api(), profile="ubl")
    assert _losses(result, "codes-as-documentation") == ["Bill.documentCurrencyCode"]
    payment = _emit(_payment_api(), profile="ubl")
    assert "GroupHeader.message_id" in _losses(payment, "facets-as-documentation")
    docs = " ".join(d.text or "" for d in _schema(payment).iter(f"{_XS}documentation"))
    assert "maximum length: 35" in docs and "codes: EUR, USD" in docs


# ===========================================================================
# The document
# ===========================================================================


def test_the_document_is_one_element_headed_by_the_ubl_header() -> None:
    root = _schema(_emit(_invoice_api(), profile="ubl", ubl_document="Invoice"))
    assert [(el.get("name"), el.get("type")) for el in root.findall(f"{_XS}element")] == [("Invoice",
                                                                                            "tns:InvoiceType")]
    header = _children(_type(root, "InvoiceType"))[:3]
    assert header == ["cbc:UBLVersionID", "cbc:CustomizationID", "cbc:ProfileID"]
    assert all(_element(_type(root, "InvoiceType"), r).get("minOccurs") == "0" for r in header)


def test_the_document_defaults_to_the_item_name_or_an_imported_ubl_type() -> None:
    assert _schema(_emit(_invoice_api(), profile="ubl")).findall(f"{_XS}element")[0].get("name") == "Pets"
    ubl = _emit(_ubl_item("07-ubl-2.1-invoice-set"), profile="ubl")
    assert ubl.files[0].path == "Invoice.xsd"


def test_document_record_chooses_the_record() -> None:
    root = _schema(_emit(_payment_api(), profile="ubl", ubl_document="Remittance", document_record="Payment"))
    assert "Amount" in " ".join(_children(_type(root, "RemittanceType")))


def test_several_candidate_records_are_reported() -> None:
    api = _api([_record("A", _field("x", TypeRef(name="string"), owner="A")),
                _record("B", _field("y", TypeRef(name="string"), owner="B"))])
    report = _report(api, profile="ubl")
    [item] = [i for i in report.items if i.target_mapping == "ubl-document-record-inferred"]
    assert item.kind is LossinessKind.APPROX


def test_the_guide_lists_the_header_and_every_value() -> None:
    result = _emit(_invoice_api(), profile="peppol")
    guide = result.files[-1].content
    assert guide.startswith("# UBL 2.1 Invoice — Pets (Peppol BIS Billing 3.0)")
    assert f"| `cbc:CustomizationID` | 1..1 | `{PEPPOL_CUSTOMIZATION_ID}` |" in guide
    assert "| `TotalAmount` | `cbc:TotalAmount` | 0..1 | `Bill.totalAmount` |" in guide
    assert "| `PaidIndicator` | `udt:IndicatorType` | 0..1 | `Bill.paid` |" in guide
    # Peppol makes the item's own ID mandatory: the guide says what the schema says.
    assert "| `ID` | `cbc:ID` | 1..1 | `Bill.ID` |" in guide
    assert "## Not checked" in guide and "Schematron" in guide


# ===========================================================================
# AC 2 — the Peppol BIS conventions
# ===========================================================================


def test_peppol_makes_the_header_mandatory_with_the_bis_values() -> None:
    root = _schema(_emit(_invoice_api(), profile="peppol"))
    invoice = _type(root, "InvoiceType")
    for ref, value in (("cbc:CustomizationID", PEPPOL_CUSTOMIZATION_ID), ("cbc:ProfileID", PEPPOL_PROFILE_ID)):
        element = _element(invoice, ref)
        assert element.get("minOccurs") == "1"
        assert value in element.find(f"{_XS}annotation/{_XS}documentation").text


def test_peppol_uses_the_items_own_mandatory_values() -> None:
    result = _emit(_invoice_api(), profile="peppol")
    children = _children(_type(_schema(result), "InvoiceType"))
    assert children[3:7] == ["cbc:ID", "cbc:IssueDate", "cbc:InvoiceTypeCode", "cbc:DocumentCurrencyCode"]
    # Only the type code was missing from the item.
    assert len([l for l in result.losses if l.subject == "peppol-element-synthesized"]) == 1


def test_peppol_adds_the_mandatory_values_an_item_lacks() -> None:
    result = _emit(_payment_api(), profile="peppol", ubl_document="CreditNote")
    children = _children(_type(_schema(result), "CreditNoteType"))
    assert children[3:7] == ["cbc:ID", "cbc:IssueDate", "cbc:CreditNoteTypeCode", "cbc:DocumentCurrencyCode"]
    report = _report(_payment_api(), profile="peppol", ubl_document="CreditNote")
    synthesized = [i for i in report.items if i.target_mapping == "peppol-element-synthesized"]
    assert len(synthesized) == 4 and all(i.kind is LossinessKind.SYNTH for i in synthesized)


def test_the_ubl_profile_applies_no_peppol_convention() -> None:
    result = _emit(_payment_api(), profile="ubl")
    assert _losses(result, "peppol-element-synthesized") == []
    assert peppol_problems(result.files[0].content)  # a plain UBL document is not a Peppol one


def test_peppol_problems_accepts_a_peppol_export() -> None:
    assert peppol_problems(_emit(_payment_api(), profile="peppol").files[0].content) == []


@pytest.mark.parametrize(("old", "new", "message"), [
    ('name="Invoice"', 'name="Order"', "Invoice or CreditNote"),
    ('<xsd:element ref="cbc:CustomizationID" minOccurs="1">', '<xsd:element ref="cbc:CustomizationID" minOccurs="0">',
     "cbc:CustomizationID is mandatory"),
    (PEPPOL_PROFILE_ID, "urn:other", "documented with the BIS value"),
    ('<xsd:element ref="cbc:IssueDate" />', "", "must carry cbc:IssueDate"),
])
def test_the_gate_checks_the_peppol_conventions(old: str, new: str, message: str) -> None:
    api = _payment_api()
    result = _emit(api, profile="peppol")
    text = result.files[0].content
    assert old in text
    broken = _with(result, result.files[0].path, text.replace(old, new, 1))
    problems = check_emitted_xsd(broken)
    assert any(p["rule"] == "ubl.peppol" and message in p["message"] for p in problems), problems


def _with(result, path: str, content: str):
    files = [EmittedFile(path=f.path, content=content if f.path == path else f.content, media_type=f.media_type)
             for f in result.files]
    return result.model_copy(update={"files": files})


def test_the_gate_rejects_a_modified_oasis_schema() -> None:
    api = _payment_api()
    result = _emit(api, profile="ubl")
    path = "common/UBL-CommonBasicComponents-2.1.xsd"
    text = next(f.content for f in result.files if f.path == path)
    broken = _with(result, path, text.replace("Copyright (c) OASIS Open 2013.", "Copyright (c) Someone."))
    assert [p["rule"] for p in check_emitted_xsd(broken)] == ["ubl.bundled-schemas"]
    assert not asyncio.run(_validate_xsd("xsd", broken, api)).valid


def test_the_gate_requires_the_notice() -> None:
    result = _emit(_payment_api(), profile="ubl")
    without = result.model_copy(update={"files": [f for f in result.files if f.path != UBL_NOTICE_PATH]})
    assert [p["rule"] for p in check_emitted_xsd(without)] == ["ubl.notice"]


def test_a_ubl_export_reimports_as_an_xsd_item() -> None:
    result = _emit(_invoice_api(), profile="ubl", ubl_document="Invoice")
    back = reimport_xsd(result)
    assert back.format == "xsd"
    assert any(t.name == "InvoiceType" for t in back.types)


# ===========================================================================
# The fidelity report
# ===========================================================================


def test_the_report_names_the_ubl_document_and_its_root() -> None:
    report = _report(_payment_api(), profile="ubl")
    [note] = [i for i in report.items if i.target_mapping == "document → UBL document schema"]
    assert (note.kind, note.severity) == (LossinessKind.APPROX, LossinessSeverity.INFO)
    [root] = [i for i in report.items if i.target_mapping == "ubl-document-root"
              and i.construct_key == ROOT_CONSTRUCT_KEY]
    assert root.kind is LossinessKind.SYNTH
    peppol = _report(_payment_api(), profile="peppol")
    assert any(i.target_mapping == "document → Peppol BIS document schema" for i in peppol.items)


def test_the_report_predicts_the_export_losses() -> None:
    for profile in ("ubl", "peppol"):
        result = _emit(_payment_api(), profile=profile)
        reported = {i.target_mapping for i in _report(_payment_api(), profile=profile).items}
        assert {loss.subject for loss in result.losses} <= reported, profile


def test_other_profiles_are_unchanged() -> None:
    api = _pet_api(namespace="http://example.com/pets")
    assert [f.path for f in _emit(api).files] == ["Pets.xsd"]
    assert [f.path for f in _emit(api, profile="iso20022").files] == ["xxxx.001.001.01.xsd", "message-catalog.json"]
