"""EDI X12 / UN/EDIFACT lint, diff rules and UBL document schemas — MFI-20.5 (#3989).

Covers :mod:`app.edi_envelope_controls`, the ``edix12`` / ``edifact`` lint packs
(:mod:`app.edix12_lint`, :mod:`app.edifact_lint`), the EDI breaking-change classifiers
(:mod:`app.edi_breaking`) with the version fixtures in ``fixtures/edi_versions``, and UBL 2.1 /
Peppol recognition on the XSD normalizer (:mod:`app.ubl_schema`) with the two corpus sets.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from app.breaking_change import classify_models, get_breaking_change_classifier
from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from app.edi_breaking import EdifactBreakingChangeClassifier, EdiX12BreakingChangeClassifier, segment_of
from app.edi_envelope_controls import edifact_controls, x12_controls
from app.edifact_normalizer import EdifactNormalizer
from app.edifact_parser import parse_edifact
from app.edix12_lint import FUNCTIONAL_ID_FOR_SET
from app.edix12_normalizer import EdiX12Normalizer
from app.edix12_parser import parse_edix12
from app.fileset import IntakeFileset
from app.format_lint_capabilities import MODE_NATIVE, capability_for_format
from app.lint_engine import get_rule_pack, lint_canonical_model
from app.ubl_schema import PEPPOL_BIS_BILLING, ubl_document_type, ubl_extras
from app.xsd_import_source import XsdImportSource
from app.xsd_parser import parse_xsd

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_VERSIONS = _TESTS / "fixtures" / "edi_versions"
_X12_850 = (_EXAMPLES / "edi-x12" / "01-850-purchase-order.edi").read_text(encoding="utf-8")
_ORDERS = (_EXAMPLES / "edifact" / "01-minimal-orders-d96a.edi").read_text(encoding="utf-8")


def _x12(text: str) -> CanonicalApi:
    return EdiX12Normalizer().normalize(parse_edix12(text), include_raw=False)


def _edifact(text: str) -> CanonicalApi:
    return EdifactNormalizer().normalize(parse_edifact(text), include_raw=False)


def _findings(api: CanonicalApi, prefix: str) -> List[Tuple[str, str, str]]:
    """``(rule, severity, path)`` of every finding whose rule starts with *prefix*."""
    return sorted(
        (f.rule, f.severity, f.path) for f in lint_canonical_model(api).findings if f.rule.startswith(prefix)
    )


def _grades(base: CanonicalApi, target: CanonicalApi) -> Dict[str, str]:
    """``{rule_id: worst severity}`` of a diff's per-change grades."""
    order = ["safe", "dangerous", "breaking"]
    result = classify_models(base, target)
    grades: Dict[str, str] = {}
    for item in result.classifications:
        current = grades.get(item.rule_id)
        if current is None or order.index(item.severity.value) > order.index(current):
            grades[item.rule_id] = item.severity.value
    return grades


# ===========================================================================
# Envelope controls
# ===========================================================================


def test_x12_controls_read_every_envelope_declared_beside_observed() -> None:
    controls = x12_controls(_X12_850)
    assert controls["interchange"] == {
        "control_number": "000000001",
        "usage_indicator": "P",
        "trailer_control_number": "000000001",
        "declared_group_count": 1,
        "group_count": 1,
    }
    group = controls["groups"][0]
    assert (group["functional_id"], group["version"], group["declared_transaction_count"]) == ("PO", "004010", 1)
    assert group["transactions"] == [
        {"set_id": "850", "control_number": "0001", "trailer_control_number": "0001",
         "declared_segment_count": 9, "segment_count": 9}
    ]


def test_x12_controls_need_a_header() -> None:
    assert x12_controls("GS*PO*A*B~") is None


def test_x12_controls_leave_an_unclosed_envelope_undeclared() -> None:
    text = _X12_850.split("SE*")[0]
    transaction = x12_controls(text)["groups"][0]["transactions"][0]
    assert transaction["declared_segment_count"] is None and transaction["trailer_control_number"] is None


def test_edifact_controls_read_every_envelope_declared_beside_observed() -> None:
    controls = edifact_controls(parse_edifact(_ORDERS))
    assert controls["interchange"] == {
        "control_reference": "000000001", "test_indicator": None, "trailer_reference": "000000001",
        "declared_count": 1, "count": 1,
    }
    assert controls["groups"] == []
    assert controls["messages"] == [
        {"message_type": "ORDERS", "reference": "1", "directory": "D:96A", "trailer_reference": "1",
         "declared_segment_count": 10, "segment_count": 10}
    ]


def test_edifact_controls_count_a_groups_messages() -> None:
    text = (_EXAMPLES / "edifact" / "04-stress-multi-message-group.edi").read_text(encoding="utf-8")
    controls = edifact_controls(parse_edifact(text))
    group = controls["groups"][0]
    assert group["declared_message_count"] == group["message_count"] == len(group["messages"]) > 1
    assert controls["interchange"]["count"] == len(controls["groups"])


def test_the_normalizers_record_the_controls() -> None:
    assert _x12(_X12_850).extras["x12_controls"] == x12_controls(_X12_850)
    assert _edifact(_ORDERS).extras["edifact_controls"] == edifact_controls(parse_edifact(_ORDERS))


# ===========================================================================
# EDI X12 lint pack
# ===========================================================================


def test_the_x12_pack_is_registered() -> None:
    assert get_rule_pack("edix12") is not None
    assert capability_for_format("edix12").mode == MODE_NATIVE


@pytest.mark.parametrize("path", sorted((_EXAMPLES / "edi-x12").glob("*.edi")), ids=lambda p: p.name)
def test_every_x12_corpus_interchange_is_clean(path: Path) -> None:
    assert _findings(_x12(path.read_text(encoding="utf-8")), "edix12.") == []


@pytest.mark.parametrize(
    ("old", "new", "path"),
    [
        ("SE*9*0001~", "SE*9*0002~", "GS[1]/ST[0001]"),
        ("GE*1*1~", "GE*1*2~", "GS[1]"),
        ("IEA*1*000000001~", "IEA*1*000000002~", "ISA"),
    ],
)
def test_a_trailer_that_does_not_repeat_its_control_number_is_an_error(old: str, new: str, path: str) -> None:
    assert _findings(_x12(_X12_850.replace(old, new)), "edix12.") == [
        ("edix12.control-numbers-match", "error", path)
    ]


@pytest.mark.parametrize(
    ("old", "new", "path"),
    [
        ("SE*9*0001~", "SE*12*0001~", "GS[1]/ST[0001]"),
        ("GE*1*1~", "GE*3*1~", "GS[1]"),
        ("IEA*1*000000001~", "IEA*2*000000001~", "ISA"),
    ],
)
def test_a_wrong_control_total_is_an_error(old: str, new: str, path: str) -> None:
    findings = lint_canonical_model(_x12(_X12_850.replace(old, new))).findings
    found = [f for f in findings if f.rule.startswith("edix12.")]
    assert [(f.rule, f.severity, f.path) for f in found] == [("edix12.control-totals-match", "error", path)]
    assert "declares" in found[0].message and "number" in found[0].message


def test_duplicate_control_numbers_in_a_group_are_a_warning() -> None:
    text = (_EXAMPLES / "edi-x12" / "05-856-asn-hierarchical.edi").read_text(encoding="utf-8")
    text = text.replace("ST*856*0002", "ST*856*0001").replace("SE*11*0002", "SE*11*0001")
    assert _findings(_x12(text), "edix12.") == [("edix12.control-numbers-unique", "warning", "GS[5]")]


def test_a_functional_id_that_does_not_match_the_set_is_a_warning() -> None:
    assert _findings(_x12(_X12_850.replace("GS*PO*", "GS*IN*")), "edix12.") == [
        ("edix12.functional-id-matches-set", "warning", "GS[1]/ST[0001]")
    ]


def test_the_functional_id_table_names_the_corpus_sets() -> None:
    assert {FUNCTIONAL_ID_FOR_SET[s] for s in ("850", "810", "997", "856", "834", "837")} == {
        "PO", "IN", "FA", "SH", "BE", "HC"
    }


def test_an_empty_gs08_is_a_warning() -> None:
    assert _findings(_x12(_X12_850.replace("*1*X*004010~", "*1*X*~")), "edix12.") == [
        ("edix12.version-declared", "warning", "GS[1]")
    ]


def test_the_usage_indicator_must_be_p_t_or_i() -> None:
    assert _findings(_x12(_X12_850.replace("*0*P*>~", "*0*Q*>~")), "edix12.") == [
        ("edix12.usage-indicator-valid", "warning", "ISA.15")
    ]


def test_a_test_interchange_is_noted() -> None:
    assert _findings(_x12(_X12_850.replace("*0*P*>~", "*0*T*>~")), "edix12.") == [
        ("edix12.test-interchange", "info", "ISA.15")
    ]


def test_a_model_without_controls_raises_nothing() -> None:
    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="edix12", identity=ApiIdentity(name="t"),
                       title="t", types=[])
    assert _findings(api, "edix12.") == []


# ===========================================================================
# UN/EDIFACT lint pack
# ===========================================================================


def test_the_edifact_pack_is_registered() -> None:
    assert get_rule_pack("edifact") is not None
    assert capability_for_format("edifact").mode == MODE_NATIVE


_EDIFACT_CORPUS = [
    path
    for path in sorted((_EXAMPLES / "edifact").glob("**/*.edi"))
    if "negative" not in path.parts and path.name != "07-stress-control-count-mismatch.edi"
]


@pytest.mark.parametrize("path", _EDIFACT_CORPUS, ids=lambda p: p.name)
def test_every_well_formed_edifact_corpus_interchange_is_clean(path: Path) -> None:
    assert _findings(_edifact(path.read_text(encoding="utf-8")), "edifact.") == []


def test_the_control_count_mismatch_fixture_imports_with_both_counts_flagged() -> None:
    text = (_EXAMPLES / "edifact" / "07-stress-control-count-mismatch.edi").read_text(encoding="utf-8")
    assert _findings(_edifact(text), "edifact.") == [
        ("edifact.control-counts-match", "error", "UNB"),
        ("edifact.control-counts-match", "error", "UNH[1]"),
    ]


@pytest.mark.parametrize(
    ("old", "new", "path"),
    [("UNT+10+1'", "UNT+10+2'", "UNH[1]"), ("UNZ+1+000000001'", "UNZ+1+000000009'", "UNB")],
)
def test_a_trailer_that_does_not_repeat_its_reference_is_an_error(old: str, new: str, path: str) -> None:
    assert _findings(_edifact(_ORDERS.replace(old, new)), "edifact.") == [
        ("edifact.control-references-match", "error", path)
    ]


def test_a_group_trailer_is_checked_too() -> None:
    text = (_EXAMPLES / "edifact" / "04-stress-multi-message-group.edi").read_text(encoding="utf-8")
    controls = edifact_controls(parse_edifact(text))
    reference = controls["groups"][0]["reference"]
    broken = text.replace(f"UNE+{controls['groups'][0]['declared_message_count']}+{reference}'",
                          f"UNE+9+{reference}'")
    assert ("edifact.control-counts-match", "error", f"UNG[{reference}]") in _findings(_edifact(broken), "edifact.")


def test_duplicate_message_references_are_a_warning() -> None:
    text = (_EXAMPLES / "edifact" / "04-stress-multi-message-group.edi").read_text(encoding="utf-8")
    messages = edifact_controls(parse_edifact(text))["groups"][0]["messages"]
    first, second = messages[0]["reference"], messages[1]["reference"]
    duplicated = text.replace(f"UNH+{second}+", f"UNH+{first}+").replace(f"+{second}'\nUNE", f"+{first}'\nUNE")
    rules = {rule for rule, _severity, _path in _findings(_edifact(duplicated), "edifact.")}
    assert "edifact.message-references-unique" in rules


def test_a_message_without_a_directory_is_a_warning() -> None:
    assert _findings(_edifact(_ORDERS.replace("UNH+1+ORDERS:D:96A:UN'", "UNH+1+ORDERS'")), "edifact.") == [
        ("edifact.directory-declared", "warning", "UNH[1]")
    ]


def test_a_test_interchange_is_noted_for_edifact() -> None:
    text = _ORDERS.replace("+000000001'\nUNH", "+000000001++++++1'\nUNH")
    assert edifact_controls(parse_edifact(text))["interchange"]["test_indicator"] == "1"
    assert _findings(_edifact(text), "edifact.") == [("edifact.test-interchange", "info", "UNB")]


# ===========================================================================
# Breaking-change classifiers
# ===========================================================================


def test_the_classifiers_are_registered() -> None:
    assert get_breaking_change_classifier("edix12") is EdiX12BreakingChangeClassifier
    assert get_breaking_change_classifier("edifact") is EdifactBreakingChangeClassifier


@pytest.mark.parametrize(
    ("reference", "segment"),
    [("BEG03", "BEG"), ("PO101", "PO1"), ("N104", "N1"), ("DTM01-2", "DTM"), ("value", None), ("", None)],
)
def test_segment_of_reads_the_reference_designator(reference: str, segment) -> None:
    assert segment_of(reference) == segment


def _version(name: str) -> str:
    return (_VERSIONS / name).read_text(encoding="utf-8")


def test_the_x12_compatible_version_is_safe() -> None:
    result = classify_models(_x12(_version("x12-850.v1.edi")), _x12(_version("x12-850.v2-compatible.edi")))
    assert result.overall_severity.value == "safe"
    assert {item.rule_id for item in result.classifications} == {"edix12.sample-value-changed"}


def test_the_x12_breaking_version_names_the_removed_segment_and_the_added_element() -> None:
    grades = _grades(_x12(_version("x12-850.v1.edi")), _x12(_version("x12-850.v3-breaking.edi")))
    assert grades["edix12.segment-removed"] == "breaking"
    assert grades["edix12.element-added"] == "dangerous"
    # Every element after PER moved only in the flattened record.
    assert grades["edix12.ordinal-shifted"] == "safe"
    assert "modified-breaking" not in grades


def test_an_x12_element_removed_from_a_repeating_segment_is_breaking() -> None:
    target = _X12_850.replace("*BP*WIDGET-001~", "~").replace("*BP*GADGET-007~", "~")
    assert _grades(_x12(_X12_850), _x12(target)) == {"edix12.element-removed": "breaking"}


def test_an_x12_segment_added_is_dangerous() -> None:
    target = _X12_850.replace("CTT*2~", "CTT*2~\nAMT*TT*9475~").replace("SE*9*", "SE*10*")
    assert _grades(_x12(_X12_850), _x12(target)) == {"edix12.segment-added": "dangerous"}


def test_a_segment_that_stops_repeating_is_dangerous_not_removed() -> None:
    target = _X12_850.replace("PO1*2*50*EA*42.00*PE*BP*GADGET-007~\n", "").replace("SE*9*", "SE*8*")
    grades = _grades(_x12(_X12_850), _x12(target))
    assert grades["edix12.segment-repetition-changed"] == "dangerous"
    assert "edix12.segment-removed" not in grades and "removed-entity" not in grades


def test_another_transaction_set_is_breaking() -> None:
    grades = _grades(_x12(_X12_850), _x12(_X12_850.replace("ST*850", "ST*855")))
    assert grades == {"edix12.transaction-set-changed": "breaking"}


def test_the_edifact_compatible_version_is_safe() -> None:
    result = classify_models(
        _edifact(_version("edifact-orders.v1.edi")), _edifact(_version("edifact-orders.v2-compatible.edi"))
    )
    assert result.overall_severity.value == "safe"
    assert {item.rule_id for item in result.classifications} == {"edifact.sample-value-changed"}


def test_the_edifact_breaking_version_names_the_removed_segment() -> None:
    grades = _grades(_edifact(_version("edifact-orders.v1.edi")), _edifact(_version("edifact-orders.v3-breaking.edi")))
    assert grades["edifact.segment-removed"] == "breaking"
    assert set(grades) <= {"edifact.segment-removed", "edifact.ordinal-shifted"}


def test_another_edifact_message_type_is_breaking() -> None:
    target = _ORDERS.replace("ORDERS:D:96A", "ORDRSP:D:96A")
    assert _grades(_edifact(_ORDERS), _edifact(target)) == {"edifact.message-type-changed": "breaking"}


def test_the_version_fixtures_are_clean_interchanges() -> None:
    for path in sorted(_VERSIONS.glob("x12-*.edi")):
        assert _findings(_x12(path.read_text(encoding="utf-8")), "edix12.") == [], path.name
    for path in sorted(_VERSIONS.glob("edifact-*.edi")):
        assert _findings(_edifact(path.read_text(encoding="utf-8")), "edifact.") == [], path.name


# ===========================================================================
# UBL 2.1 / Peppol document schemas
# ===========================================================================

_UBL_SETS = {
    "Invoice": ("07-ubl-2.1-invoice-set", "UBL-Invoice-2.1.xsd"),
    "CreditNote": ("08-ubl-2.1-creditnote-set", "UBL-CreditNote-2.1.xsd"),
}


def _ubl(document: str) -> CanonicalApi:
    directory, root = _UBL_SETS[document]
    folder = _EXAMPLES / "xsd" / directory
    fileset = IntakeFileset.from_members(
        {path.name: path.read_text(encoding="utf-8") for path in folder.iterdir()}, root=root
    )
    source = XsdImportSource()
    return source.normalize(source.parse_fileset(fileset, source_label=root))


@pytest.mark.parametrize(
    ("namespace", "expected"),
    [
        ("urn:oasis:names:specification:ubl:schema:xsd:Invoice-2", ("Invoice", "2")),
        ("urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2", ("CommonBasicComponents", "2")),
        ("urn:iso:std:iso:20022:tech:xsd:pain.001.001.09", None),
        ("http://example.com/ubl-shape/invoice", None),
        (None, None),
    ],
)
def test_ubl_document_type_reads_the_namespace(namespace, expected) -> None:
    assert ubl_document_type(namespace) == expected


@pytest.mark.parametrize("document", sorted(_UBL_SETS))
def test_a_ubl_document_schema_imports_as_xsd_labelled_ubl_with_the_peppol_note(document: str) -> None:
    api = _ubl(document)
    assert api.format == "xsd" and api.title == f"{document} (UBL 2.1)"
    assert api.extras["ubl_document"] == {
        "document_type": document,
        "kind": "document",
        "namespace": f"urn:oasis:names:specification:ubl:schema:xsd:{document}-2",
        "major_version": "2",
        "version": "2.1",
        "peppol": PEPPOL_BIS_BILLING,
    }
    profile = api.extras["format_profile"]
    assert (profile["key"], profile["label"], profile["peppol"]) == ("ubl", "UBL 2.1", PEPPOL_BIS_BILLING)
    assert profile["implementation_guide_consulted"] is False


@pytest.mark.parametrize("document", sorted(_UBL_SETS))
def test_a_ubl_document_reads_every_referenced_component(document: str) -> None:
    api = _ubl(document)
    root = next(t for t in api.types if t.name == f"{document}Type")
    names = {field.name for field in root.fields}
    assert {"CustomizationID", "ID", "IssueDate", "AccountingSupplierParty", "LegalMonetaryTotal",
            f"{document}Line"} <= names
    line = next(field for field in root.fields if field.name == f"{document}Line")
    assert line.type.item is not None  # maxOccurs="unbounded"
    amount = next(t for t in api.types if t.name == "AmountType")
    assert {field.name for field in amount.fields} == {"value", "currencyID"}


def test_a_ubl_document_lints_and_diffs_as_xsd() -> None:
    invoice, credit_note = _ubl("Invoice"), _ubl("CreditNote")
    assert lint_canonical_model(invoice).grade
    assert classify_models(invoice, credit_note).overall_severity.value == "breaking"


def test_a_component_library_is_labelled_but_has_no_peppol_note() -> None:
    extras = ubl_extras("urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
                        '<xsd:schema version="2.1">')
    assert extras["ubl_document"]["kind"] == "component-library"
    assert extras["ubl_document"]["peppol"] is None and "peppol" not in extras["format_profile"]


def test_a_ubl_document_of_another_type_or_release_has_no_peppol_note() -> None:
    order = ubl_extras("urn:oasis:names:specification:ubl:schema:xsd:Order-2", '<xs:schema version="2.1">')
    old = ubl_extras("urn:oasis:names:specification:ubl:schema:xsd:Invoice-2", '<xs:schema version="2.0">')
    unversioned = ubl_extras("urn:oasis:names:specification:ubl:schema:xsd:Invoice-2", "<xs:schema>")
    assert order["ubl_document"]["peppol"] is None and old["ubl_document"]["peppol"] is None
    assert unversioned["format_profile"]["label"] == "UBL 2" and unversioned["ubl_document"]["version"] is None


def test_any_other_schema_gets_no_ubl_extras() -> None:
    shape = (_EXAMPLES / "xsd" / "05-ubl-invoice-shape.xsd").read_text(encoding="utf-8")
    api = XsdImportSource().normalize(parse_xsd(shape))
    assert "ubl_document" not in api.extras and "format_profile" not in api.extras
    assert api.title == "Invoice"


def test_an_element_ref_reads_as_the_global_element_and_an_unresolved_one_is_skipped() -> None:
    schema = parse_xsd(
        '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:t="urn:t" targetNamespace="urn:t">'
        '<xs:element name="Code" type="xs:string"/>'
        '<xs:complexType name="Thing"><xs:sequence>'
        '<xs:element ref="t:Code"/><xs:element ref="t:Missing"/><xs:element name="Own" type="xs:int"/>'
        "</xs:sequence></xs:complexType></xs:schema>"
    )
    thing = next(t for t in schema.complex_types if t.name == "Thing")
    assert [(f.name, f.type_expr) for f in thing.fields] == [("Code", "string"), ("Own", "int")]
