"""ISO 20022 message profile of the XSD emitter — MFX-22.4 (#4135).

Covers the acceptance criteria:

* **the profile emits an ISO-20022-conventional message schema from a typed source** — one
  ``urn:iso:std:iso:20022:tech:xsd:<identifier>`` namespace, ``<identifier>.xsd``, a single global ``Document``
  element whose type wraps the business element, UpperCamelCase names, descriptions as ``xs:documentation``,
  and a message-catalog manifest. The schema is valid under XSD 1.0 and 1.1, passes the export gate, and an
  upload of it is detected and imported as an ISO 20022 message definition with the same message id;
* **convention deviations are reported as SYNTH / APPROX** — a synthesized message identifier, the added
  ``Document`` root and an invented name are ``SYNTH``; a name ISO 20022 cannot hold, a guessed message type
  and a merged namespace are ``APPROX``, in the export's losses and in its fidelity report.

Also: the options and their validation; an ISO 20022 source keeps its ``Document``, business element and
names; the generic profile is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List

import pytest
from pydantic import ValidationError
from test_xsd_emitter import _NS, _api, _field, _pet_api, _record

from app.canonical_model import Constraints, EnumValue, Operation, OperationKind, Service, Type, TypeKind, TypeRef
from app.emitter import EmitOptionsError, EmittedFile
from app.export_validation import _validate_xsd
from app.fidelity_engine import compute_lossiness_for_emitter
from app.fidelity_rulepack import ROOT_CONSTRUCT_KEY
from app.import_source import DetectionInput, detect_import_source
from app.iso20022_message_definition import normalize_message_definition, parse_message_definition
from app.iso20022_xsd_profile import MESSAGE_CATALOG_PATH, iso20022_name
from app.lossiness import LossinessKind, LossinessSeverity
from app.xsd_emitter import XsdEmitOptions, XsdEmitter
from app.xsd_roundtrip import check_emitted_xsd, reimport_xsd, round_trip_xsd, split_message_catalog

_XS = "{http://www.w3.org/2001/XMLSchema}"
_PAIN = "pain.001.001.09"
_PAIN_NS = f"urn:iso:std:iso:20022:tech:xsd:{_PAIN}"
_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "iso20022"
_ISO_NAME_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")


# ===========================================================================
# Helpers
# ===========================================================================


def _payment_api(**identity):
    """A typed (OpenAPI-shaped) payment initiation: a message, its header and payments, a currency code."""
    message = _record(
        "PaymentInitiation",
        _field("group_header", TypeRef(name="GroupHeader"), owner="PaymentInitiation",
               description="Set of characteristics shared by all payments.", field_number=1),
        _field("payments", TypeRef(item=TypeRef(name="Payment")), owner="PaymentInitiation", field_number=2),
    )
    message = message.model_copy(update={"description": "Initiates one or more credit transfers."})
    header = _record(
        "GroupHeader",
        _field("message_id", TypeRef(name="string"), owner="GroupHeader",
               constraints=Constraints(min_length=1, max_length=35), description="Point-to-point reference.",
               field_number=1),
        _field("created_at", TypeRef(name="string"), owner="GroupHeader",
               constraints=Constraints(format="date-time"), field_number=2),
        _field("numberOfTxs", TypeRef(name="integer"), owner="GroupHeader", field_number=3),
    )
    payment = _record(
        "Payment",
        _field("amount", TypeRef(name="number"), owner="Payment", field_number=1),
        _field("currency", TypeRef(name="Currency"), owner="Payment", field_number=2),
        _field("debtor-name", TypeRef(name="string", nullable=True), owner="Payment", field_number=3),
    )
    currency = Type(
        key="Currency", name="Currency", kind=TypeKind.ENUM,
        enum_values=[EnumValue(key="Currency.EUR", name="EUR"), EnumValue(key="Currency.USD", name="USD")],
    )
    return _api([message, header, payment, currency], **identity)


def _iso(api, **opts):
    return XsdEmitter().emit(api, opts=XsdEmitOptions(profile="iso20022", **opts))


def _schema_root(result) -> ET.Element:
    return ET.fromstring(str(result.files[0].content))


def _catalog(result) -> Dict:
    return json.loads(next(f.content for f in result.files if f.path == MESSAGE_CATALOG_PATH))


def _complex(root: ET.Element, name: str) -> ET.Element:
    return next(el for el in root.findall(f"{_XS}complexType") if el.get("name") == name)


def _children(complex_el: ET.Element) -> List[str]:
    return [el.get("name") for el in complex_el.iter(f"{_XS}element")]


def _losses(result, subject: str) -> List[str]:
    return sorted(loss.pointer or "" for loss in result.losses if loss.subject == subject)


def _report(api, **opts):
    return compute_lossiness_for_emitter(api, XsdEmitter(), options={"profile": "iso20022", **opts})


def _items(report, key: str, subject: str):
    return [i for i in report.items if i.construct_key == key and i.target_mapping == subject]


def _pain_api():
    raw = (_EXAMPLES / "07-pain.001.001.09-message-definition.xsd").read_text(encoding="utf-8")
    return normalize_message_definition(parse_message_definition(raw))


# ===========================================================================
# The options
# ===========================================================================


def test_the_profile_defaults_to_generic() -> None:
    options = XsdEmitOptions()
    assert options.profile == "generic"
    assert (options.message_identifier, options.business_area, options.message_type) == (None, None, None)


@pytest.mark.parametrize("field", ["message_identifier", "business_area", "message_type"])
def test_the_iso20022_options_need_the_profile(field: str) -> None:
    value = {"message_identifier": _PAIN, "business_area": "pain", "message_type": "Payment"}[field]
    with pytest.raises(ValidationError, match="apply to profile 'iso20022' only"):
        XsdEmitOptions(**{field: value})


@pytest.mark.parametrize("mode", ["relaxng", "relaxng-compact", "dtd"])
def test_the_profile_writes_xml_schema_only(mode: str) -> None:
    with pytest.raises(ValidationError, match="writes an XML Schema"):
        XsdEmitOptions(profile="iso20022", mode=mode)


@pytest.mark.parametrize("bad", ["pain.1.1.9", "pain-001-001-09", "pain.001.001", "pa1n.001.001.09", ""])
def test_the_message_identifier_must_be_well_formed(bad: str) -> None:
    with pytest.raises(ValidationError, match="message_identifier must be"):
        XsdEmitOptions(profile="iso20022", message_identifier=bad or " ")


@pytest.mark.parametrize("bad", ["pai", "paint", "pa1n", "pa.n"])
def test_the_business_area_must_be_four_letters(bad: str) -> None:
    with pytest.raises(ValidationError, match="business_area must be four letters"):
        XsdEmitOptions(profile="iso20022", business_area=bad)


def test_the_business_area_must_match_the_identifier() -> None:
    with pytest.raises(ValidationError, match="does not match message_identifier"):
        XsdEmitOptions(profile="iso20022", message_identifier=_PAIN, business_area="camt")
    assert XsdEmitOptions(profile="iso20022", message_identifier=_PAIN, business_area="pain").business_area == "pain"


def test_identifier_and_area_are_lower_cased() -> None:
    options = XsdEmitOptions(profile="iso20022", message_identifier=" PAIN.001.001.09 ", business_area="PAIN")
    assert (options.message_identifier, options.business_area) == (_PAIN, "pain")


def test_xsd_1_1_is_allowed_with_the_profile() -> None:
    result = _iso(_payment_api(), message_identifier=_PAIN, xsd_version="1.1")
    assert _schema_root(result).get("{http://www.w3.org/2007/XMLSchema-versioning}minVersion") == "1.1"
    assert check_emitted_xsd(result) == []


# ===========================================================================
# Names
# ===========================================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("GrpHdr", ("GrpHdr", "kept")),
        ("Document", ("Document", "kept")),
        ("customer_id", ("CustomerId", "recased")),
        ("debtor-name", ("DebtorName", "recased")),
        ("numberOfTxs", ("NumberOfTxs", "recased")),
        ("first name", ("FirstName", "recased")),
        ("créditeur", ("Crediteur", "lossy")),
        ("größe", ("Groe", "lossy")),
        ("2xx", ("X2xx", "lossy")),
        ("名前", ("Field", "synthesized")),
        ("--", ("Field", "synthesized")),
        ("", ("Field", "synthesized")),
    ],
)
def test_iso20022_name(raw: str, expected) -> None:
    assert iso20022_name(raw, "Field") == expected


# ===========================================================================
# AC 1 — an ISO-20022-conventional message schema from a typed source
# ===========================================================================


def test_the_export_is_the_message_definition_and_its_catalog() -> None:
    result = _iso(_payment_api(), message_identifier=_PAIN)
    assert [(f.path, f.media_type) for f in result.files] == [
        (f"{_PAIN}.xsd", "application/xml"),
        (MESSAGE_CATALOG_PATH, "application/json"),
    ]


def test_the_schema_is_in_the_message_namespace() -> None:
    root = _schema_root(_iso(_payment_api(namespace=_NS), message_identifier=_PAIN))
    assert root.get("targetNamespace") == _PAIN_NS
    assert root.get("elementFormDefault") == "qualified"


def test_document_is_the_one_global_element_and_wraps_the_business_element() -> None:
    root = _schema_root(_iso(_payment_api(), message_identifier=_PAIN))
    globals_ = root.findall(f"{_XS}element")
    assert [(el.get("name"), el.get("type")) for el in globals_] == [("Document", "tns:Document")]
    assert root[0] is globals_[0]
    document = _complex(root, "Document")
    assert root[1] is document
    business = document.find(f"{_XS}sequence/{_XS}element")
    assert (business.get("name"), business.get("type")) == ("PaymentInitiation", "tns:PaymentInitiation")


def test_every_type_and_element_name_is_upper_camel_case() -> None:
    root = _schema_root(_iso(_payment_api(), message_identifier=_PAIN))
    names = [el.get("name") for el in root.iter() if el.get("name") and el.tag != f"{_XS}enumeration"]
    assert names
    for name in names:
        assert name[0].isupper() and set(name) <= _ISO_NAME_CHARS, name
    assert _children(_complex(root, "GroupHeader")) == ["MessageId", "CreatedAt", "NumberOfTxs"]
    assert _children(_complex(root, "Payment")) == ["Amount", "Currency", "DebtorName"]
    assert _children(_complex(root, "PaymentInitiation")) == ["GroupHeader", "Payments"]


def test_descriptions_become_xs_documentation() -> None:
    root = _schema_root(_iso(_payment_api(), message_identifier=_PAIN))
    texts = [el.text for el in root.iter(f"{_XS}documentation")]
    assert "Initiates one or more credit transfers." in texts
    assert "Set of characteristics shared by all payments." in texts
    assert "Point-to-point reference." in texts
    document_doc = root[0].find(f"{_XS}annotation/{_XS}documentation").text
    assert document_doc == f"ISO 20022 message {_PAIN}: Pets"


def test_facets_and_types_are_kept() -> None:
    root = _schema_root(_iso(_payment_api(), message_identifier=_PAIN))
    message_id = next(el for el in _complex(root, "GroupHeader").iter(f"{_XS}element") if el.get("name") == "MessageId")
    facets = {f.tag.split("}")[1]: f.get("value") for f in message_id.iter() if f.get("value")}
    assert facets == {"minLength": "1", "maxLength": "35"}
    currency = next(el for el in root.findall(f"{_XS}simpleType") if el.get("name") == "Currency")
    assert [e.get("value") for e in currency.iter(f"{_XS}enumeration")] == ["EUR", "USD"]


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_the_schema_is_valid_and_passes_the_export_gate(version: str) -> None:
    api = _payment_api()
    result = _iso(api, message_identifier=_PAIN, xsd_version=version)
    assert check_emitted_xsd(result) == []
    assert asyncio.run(_validate_xsd("xsd", result, api)).valid


def test_an_upload_of_the_schema_is_an_iso20022_message_definition() -> None:
    result = _iso(_payment_api(), message_identifier=_PAIN)
    text = str(result.files[0].content)
    matched = detect_import_source(DetectionInput(text=text, filename=result.files[0].path))
    assert matched is not None and matched[0].key == "iso20022"
    reimported = reimport_xsd(result)
    assert reimported.format == "iso20022"
    assert reimported.extras["iso20022_message_id"] == _PAIN
    definition = reimported.extras["iso20022_message_definition"]
    assert (definition["root_element"], definition["business_element"], definition["business_type"]) == (
        "Document", "PaymentInitiation", "PaymentInitiation",
    )
    assert {"GroupHeader", "Payment", "Currency", "PaymentInitiation"} <= {t.name for t in reimported.types}


def test_the_round_trip_measures_through_the_iso20022_importer() -> None:
    report = round_trip_xsd(_payment_api(), opts=XsdEmitOptions(profile="iso20022", message_identifier=_PAIN))
    assert report.problems == [] and report.import_error is None
    assert report.import_path == "iso20022" and report.reimported


def test_the_message_catalog_lists_the_message() -> None:
    catalog = _catalog(_iso(_payment_api(), message_identifier=_PAIN))
    assert catalog["standard"] == "ISO 20022"
    [message] = catalog["messages"]
    assert message == {
        "message_identifier": _PAIN,
        "business_area": "pain",
        "message_number": "001",
        "variant": "001",
        "version": "09",
        "identifier_synthesized": False,
        "namespace": _PAIN_NS,
        "schema": f"{_PAIN}.xsd",
        "root_element": "Document",
        "business_element": "PaymentInitiation",
        "message_type": "PaymentInitiation",
        "title": "Pets",
        "description": None,
        "message_components": ["GroupHeader", "Payment", "PaymentInitiation"],
        "data_types": ["Currency"],
    }


def test_message_type_chooses_the_business_element() -> None:
    result = _iso(_payment_api(), message_identifier=_PAIN, message_type="GroupHeader")
    business = _complex(_schema_root(result), "Document").find(f"{_XS}sequence/{_XS}element")
    assert (business.get("name"), business.get("type")) == ("GroupHeader", "tns:GroupHeader")
    assert _catalog(result)["messages"][0]["message_type"] == "GroupHeader"


def test_a_versioned_message_type_names_its_business_element_without_the_version() -> None:
    api = _api([_record("CreditTransferV09", _field("id", TypeRef(name="string"), owner="CreditTransferV09"))])
    business = _complex(_schema_root(_iso(api, message_identifier=_PAIN)), "Document").find(
        f"{_XS}sequence/{_XS}element"
    )
    assert (business.get("name"), business.get("type")) == ("CreditTransfer", "tns:CreditTransferV09")


def test_an_unknown_message_type_is_refused() -> None:
    with pytest.raises(EmitOptionsError, match="names no record type"):
        _iso(_payment_api(), message_identifier=_PAIN, message_type="Nope")
    # The fidelity report for those options still computes (as if message_type were unset).
    assert _report(_payment_api(), message_identifier=_PAIN, message_type="Nope").items


def test_a_source_type_named_document_is_renamed() -> None:
    api = _api([_record("Document", _field("id", TypeRef(name="string"), owner="Document"))])
    result = _iso(api, message_identifier=_PAIN)
    root = _schema_root(result)
    assert [el.get("name") for el in root.findall(f"{_XS}complexType")] == ["Document", "Document2"]
    assert _complex(root, "Document").find(f"{_XS}sequence/{_XS}element").get("type") == "tns:Document2"
    assert "Document" in _losses(result, "renamed-identifier")
    assert check_emitted_xsd(result) == []


def test_operations_are_dropped_as_in_any_xsd_export() -> None:
    service = Service(key="Pets", name="Pets", operations=[
        Operation(key="Pets.getPet", name="getPet", kind=OperationKind.REQUEST_RESPONSE),
    ])
    result = _iso(_api(_pet_api().types, services=[service]), message_identifier=_PAIN)
    assert _losses(result, "types-only") == ["services"]


# ===========================================================================
# AC 2 — convention deviations are reported as SYNTH / APPROX
# ===========================================================================


def test_a_missing_identifier_is_synthesized() -> None:
    api = _payment_api()
    result = _iso(api)
    assert result.files[0].path == "xxxx.001.001.01.xsd"
    assert _schema_root(result).get("targetNamespace") == "urn:iso:std:iso:20022:tech:xsd:xxxx.001.001.01"
    assert _losses(result, "iso20022-message-id-synthesized") == [""]
    assert _catalog(result)["messages"][0]["identifier_synthesized"] is True
    [item] = _items(_report(api), ROOT_CONSTRUCT_KEY, "iso20022-message-id-synthesized")
    assert item.kind is LossinessKind.SYNTH
    assert "message_identifier" in item.message


def test_the_business_area_names_a_synthesized_identifier() -> None:
    result = _iso(_payment_api(), business_area="pacs")
    assert result.files[0].path == "pacs.001.001.01.xsd"
    assert _catalog(result)["messages"][0]["business_area"] == "pacs"


def test_a_given_identifier_is_not_reported() -> None:
    result = _iso(_payment_api(), message_identifier=_PAIN)
    assert _losses(result, "iso20022-message-id-synthesized") == []


def test_the_added_document_root_is_synth() -> None:
    api = _payment_api()
    result = _iso(api, message_identifier=_PAIN)
    assert _losses(result, "iso20022-document-root") == [""]
    [item] = _items(_report(api, message_identifier=_PAIN), ROOT_CONSTRUCT_KEY, "iso20022-document-root")
    assert item.kind is LossinessKind.SYNTH
    assert "'PaymentInitiation'" in item.message


def test_a_recased_name_is_a_cosmetic_approximation() -> None:
    api = _payment_api()
    report = _report(api, message_identifier=_PAIN)
    [item] = _items(report, "GroupHeader.message_id", "renamed-identifier")
    assert (item.kind, item.severity) == (LossinessKind.APPROX, LossinessSeverity.INFO)
    assert item.message == "ISO 20022 element names are UpperCamelCase; 'message_id' is written as 'MessageId'."


def test_a_name_iso20022_cannot_hold_is_approx() -> None:
    api = _api([_record("Party", _field("größe", TypeRef(name="string"), owner="Party"))])
    result = _iso(api, message_identifier=_PAIN)
    assert _children(_complex(_schema_root(result), "Party")) == ["Groe"]
    assert _losses(result, "iso20022-name-unmappable") == ["Party.größe"]
    [item] = _items(_report(api, message_identifier=_PAIN), "Party.größe", "iso20022-name-unmappable")
    assert (item.kind, item.severity) == (LossinessKind.APPROX, LossinessSeverity.WARN)


def test_a_name_with_nothing_to_keep_is_synthesized() -> None:
    api = _api([_record("Party", _field("名前", TypeRef(name="string"), owner="Party"))])
    result = _iso(api, message_identifier=_PAIN)
    assert _children(_complex(_schema_root(result), "Party")) == ["Field"]
    [item] = _items(_report(api, message_identifier=_PAIN), "Party.名前", "iso20022-name-synthesized")
    assert item.kind is LossinessKind.SYNTH
    assert check_emitted_xsd(result) == []


def test_several_candidate_messages_are_an_approximation() -> None:
    api = _api([
        _record("Invoice", _field("id", TypeRef(name="string"), owner="Invoice")),
        _record("Receipt", _field("id", TypeRef(name="string"), owner="Receipt")),
    ])
    result = _iso(api, message_identifier=_PAIN)
    assert _complex(_schema_root(result), "Document").find(f"{_XS}sequence/{_XS}element").get("name") == "Invoice"
    [item] = _items(_report(api, message_identifier=_PAIN), ROOT_CONSTRUCT_KEY, "iso20022-message-type-inferred")
    assert (item.kind, item.severity) == (LossinessKind.APPROX, LossinessSeverity.WARN)
    assert "Invoice, Receipt" in item.message
    # Naming the message type settles it.
    assert _losses(_iso(api, message_identifier=_PAIN, message_type="Receipt"), "iso20022-message-type-inferred") == []


def test_a_single_unused_record_is_the_message_without_a_report() -> None:
    assert _losses(_iso(_payment_api(), message_identifier=_PAIN), "iso20022-message-type-inferred") == []


def test_types_from_another_namespace_are_merged() -> None:
    api = _api([
        _record("Order", _field("id", TypeRef(name="string"), owner="Order"), namespace="urn:example:orders"),
    ])
    result = _iso(api, message_identifier=_PAIN)
    assert _schema_root(result).get("targetNamespace") == _PAIN_NS
    assert len(result.files) == 2  # one schema, one catalog: no xs:import
    [item] = _items(_report(api, message_identifier=_PAIN), ROOT_CONSTRUCT_KEY, "iso20022-namespace-merged")
    assert item.kind is LossinessKind.APPROX and "urn:example:orders" in item.message


def test_a_model_with_no_record_is_reported() -> None:
    api = _api([Type(key="Code", name="Code", kind=TypeKind.ENUM,
                     enum_values=[EnumValue(key="Code.A", name="A")])])
    result = _iso(api, message_identifier=_PAIN)
    assert _complex(_schema_root(result), "Document").find(f"{_XS}sequence/{_XS}element") is None
    assert _losses(result, "iso20022-no-message") == [""]
    [item] = _items(_report(api, message_identifier=_PAIN), ROOT_CONSTRUCT_KEY, "iso20022-no-message")
    assert item.kind is LossinessKind.DROP


def test_the_report_names_the_rewrite_of_another_format() -> None:
    report = _report(_payment_api(), message_identifier=_PAIN)
    [item] = _items(report, ROOT_CONSTRUCT_KEY, "document → ISO 20022 message definition")
    assert (item.kind, item.severity) == (LossinessKind.APPROX, LossinessSeverity.INFO)


def test_the_report_predicts_the_export_losses() -> None:
    api = _payment_api()
    result = _iso(api)
    subjects = {loss.subject for loss in result.losses}
    reported = {item.target_mapping for item in _report(api).items}
    assert subjects <= reported


# ===========================================================================
# An ISO 20022 source
# ===========================================================================


def test_an_iso20022_source_keeps_its_document_and_business_element() -> None:
    result = _iso(_pain_api())
    assert result.files[0].path == f"{_PAIN}.xsd"
    root = _schema_root(result)
    assert root.get("targetNamespace") == _PAIN_NS
    assert [el.get("name") for el in root.findall(f"{_XS}element")] == ["Document"]
    assert [el.get("name") for el in root.findall(f"{_XS}complexType")].count("Document") == 1
    assert _children(_complex(root, "Document")) == ["CstmrCdtTrfInitn"]
    for subject in ("iso20022-message-id-synthesized", "iso20022-document-root", "renamed-identifier"):
        assert _losses(result, subject) == [], subject
    catalog = _catalog(result)["messages"][0]
    assert (catalog["business_element"], catalog["message_type"]) == (
        "CstmrCdtTrfInitn", "CustomerCreditTransferInitiationV09",
    )
    assert "Document" not in catalog["message_components"]


def test_an_iso20022_source_keeps_the_standards_names() -> None:
    root = _schema_root(_iso(_pain_api()))
    names = {el.get("name") for el in root.findall(f"{_XS}simpleType")}
    assert "ActiveOrHistoricCurrencyAndAmount_SimpleType" in names
    assert _children(_complex(root, "GroupHeader85"))[:3] == ["MsgId", "CreDtTm", "NbOfTxs"]


def test_an_iso20022_source_round_trips_as_an_xsd_source_does() -> None:
    """The profile adds no difference: what differs is what the shared writer already approximates for XSD."""
    from app.xsd_import_source import XsdImportSource

    pain = _pain_api()
    report = round_trip_xsd(pain, opts=XsdEmitOptions(profile="iso20022"))
    assert report.problems == [] and report.import_error is None and report.import_path == "iso20022"
    raw = (_EXAMPLES / "07-pain.001.001.09-message-definition.xsd").read_text(encoding="utf-8")
    source = XsdImportSource()
    as_xsd = round_trip_xsd(source.normalize(source.parse(raw)))
    assert {e.key for e in report.unexplained} == {e.key for e in as_xsd.unexplained}


def test_an_iso20022_source_whose_business_type_is_missing_still_has_a_message() -> None:
    pain = _pain_api()
    definition = {**pain.extras["iso20022_message_definition"], "business_type": "Gone"}
    api = pain.model_copy(update={"extras": {**pain.extras, "iso20022_message_definition": definition}})
    result = _iso(api)
    assert _losses(result, "iso20022-no-message") == []
    business = _complex(_schema_root(result), "Document").find(f"{_XS}sequence/{_XS}element")
    assert business is not None and business.get("type") != "tns:Document"
    assert check_emitted_xsd(result) == []


def test_a_new_message_type_on_an_iso20022_source_gets_a_new_document() -> None:
    result = _iso(_pain_api(), message_type="GroupHeader85")
    root = _schema_root(result)
    # The source's own Document is a message component now; the new one wraps GroupHeader85.
    document = _complex(root, "Document")
    assert document.find(f"{_XS}sequence/{_XS}element").get("type") == "tns:GroupHeader85"
    assert _losses(result, "iso20022-document-root") == [""]
    assert check_emitted_xsd(result) == []


# ===========================================================================
# The export gate and the catalog
# ===========================================================================


def _with_catalog(result, text: str):
    files = [f if f.path != MESSAGE_CATALOG_PATH else EmittedFile(path=f.path, content=text,
                                                                     media_type=f.media_type)
             for f in result.files]
    return result.model_copy(update={"files": files})


def test_the_catalog_is_set_aside_for_the_schema_checks() -> None:
    result = _iso(_payment_api(), message_identifier=_PAIN)
    schemas, catalog = split_message_catalog(result)
    assert [f.path for f in schemas.files] == [f"{_PAIN}.xsd"]
    assert json.loads(catalog)["messages"][0]["schema"] == f"{_PAIN}.xsd"
    plain = XsdEmitter().emit(_pet_api(namespace=_NS))
    assert split_message_catalog(plain) == (plain, None)


@pytest.mark.parametrize(
    ("catalog", "message"),
    [
        ("not json", "not JSON"),
        ('{"messages": []}', "exactly one message"),
        ('{"messages": [{"schema": "other.xsd"}]}', "does not hold"),
        (json.dumps({"messages": [{"schema": f"{_PAIN}.xsd", "namespace": "urn:x"}]}), "targetNamespace"),
    ],
)
def test_a_catalog_that_does_not_describe_the_schema_fails_the_gate(catalog: str, message: str) -> None:
    api = _payment_api()
    result = _with_catalog(_iso(api, message_identifier=_PAIN), catalog)
    problems = check_emitted_xsd(result)
    assert [p["rule"] for p in problems] == ["xsd.iso20022-catalog"]
    assert message in problems[0]["message"]
    assert not asyncio.run(_validate_xsd("xsd", result, api)).valid


# ===========================================================================
# The generic profile is unchanged
# ===========================================================================


def test_the_generic_profile_writes_what_it_did() -> None:
    api = _pet_api(namespace=_NS)
    default = XsdEmitter().emit(api)
    explicit = XsdEmitter().emit(api, opts=XsdEmitOptions(profile="generic"))
    assert [(f.path, f.content) for f in default.files] == [(f.path, f.content) for f in explicit.files]
    assert [f.path for f in default.files] == ["Pets.xsd"]
    assert not any(loss.subject.startswith("iso20022-") for loss in default.losses)


# ===========================================================================
# Delivery
# ===========================================================================


def test_browse_delivers_the_schema_and_its_catalog_as_a_zip() -> None:
    import io
    import zipfile

    from app.export_routes import render_emitted_document

    options = {"profile": "iso20022", "message_identifier": _PAIN}
    response = render_emitted_document(_payment_api(), "xsd", options, None, bundle_multi_file=True)
    assert response.media_type == "application/zip"
    assert response.headers["content-disposition"].endswith('.zip"')
    names = zipfile.ZipFile(io.BytesIO(response.body)).namelist()
    # The bundle's own index (``manifest.json``, every multi-file export has one) lists both files.
    assert names == [f"{_PAIN}.xsd", MESSAGE_CATALOG_PATH, "manifest.json"]
