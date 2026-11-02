"""Tests for COBOL copybooks as catalog items — MFI-21.1 (#3991).

Covers the normalizer's canonical types (nested groups, REDEFINES → unions, PIC → primitives with
their bounds, storage / EBCDIC notes), the record-layout hash, the ``cobolcopybook`` lint pack, the
layout-diff breaking-change classifier and the 88-level value round trip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

import pytest

from app.breaking_change import Severity, available_breaking_change_formats, classify_models
from app.canonical_model import TypeKind
from app.cobolcopybook_breaking import CobolCopybookBreakingChangeClassifier
from app.cobolcopybook_emitter import _condition_value
from app.cobolcopybook_fingerprint import LAYOUT_HASH_ALGORITHM, layout_signature, record_tree
from app.cobolcopybook_import_source import CobolCopybookImportSource
from app.cobolcopybook_lint import CobolCopybookRulePack, walk_record
from app.cobolcopybook_normalizer import STORAGE_NOTES, picture_class
from app.cobolcopybook_parser import condition_value, field_from_template, field_template, parse_cobolcopybook
from app.fingerprint import fingerprint
from app.format_lint_capabilities import MODE_NATIVE, capability_for_format
from app.lint_engine import get_rule_pack, lint_canonical_model

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "cobol-copybook"
_VERSIONS = Path(__file__).resolve().parent / "fixtures" / "cobolcopybook_versions"


def _copybook(*lines: str) -> str:
    """A fixed-format copybook from data-description lines (code area starts in column 8)."""
    return "\n".join(f"       {line}" for line in lines) + "\n"


def _api(text: str):
    adapter = CobolCopybookImportSource()
    return adapter.normalize(adapter.parse(text, source_label="test.cpy"), include_raw=False)


def _example(name: str):
    return _api((_EXAMPLES / name).read_text(encoding="utf-8"))


def _version(name: str):
    return _api((_VERSIONS / f"POLICY-RECORD.{name}.cpy").read_text(encoding="utf-8"))


def _types(api) -> Dict[str, object]:
    return {t.key: t for t in api.types}


def _fields(api, type_key: str) -> Dict[str, object]:
    return {f.name: f for f in _types(api)[type_key].fields}


def _findings(text: str) -> List[Tuple[str, str, str]]:
    result = lint_canonical_model(_api(text))
    return sorted((f.rule, f.severity, f.path) for f in result.findings if f.rule.startswith("cobolcopybook."))


def _rules(text: str) -> set:
    return {rule for rule, _severity, _path in _findings(text)}


def _grades(base, target) -> Dict[Tuple[str, str], Tuple[Severity, str]]:
    """``(kind, key)`` → ``(severity, rule_id)`` for the diff of two copybook models."""
    result = classify_models(base, target)
    assert result.classifier == "cobolcopybook-layout"
    return {(c.kind.value, c.key): (c.severity, c.rule_id) for c in result.classifications}


_POLICY = (
    "01  POLICY-RECORD.",
    "    05  POL-NUMBER      PIC X(10).",
    "    05  POL-STATUS      PIC X(1).",
    "        88  POL-ACTIVE  VALUE 'A'.",
    "    05  POL-PREMIUM     PIC S9(7)V99 COMP-3.",
    "    05  FILLER          PIC X(20).",
)


# --- the canonical types ------------------------------------------------------------------------


def test_every_group_becomes_a_type_not_only_the_record() -> None:
    """Nested groups used to be referenced by their fields but never emitted as types."""
    api = _example("01-customer-record.cpy")
    types = _types(api)
    assert {"CUSTOMER-RECORD.CUSTOMER-RECORD", "CUSTOMER-RECORD.CUST-NAME", "CUSTOMER-RECORD.CUST-PHONES"} <= set(types)
    referenced = {
        (f.type.item or f.type).name for t in api.types for f in t.fields if (f.type.item or f.type).name.count(".")
    }
    assert referenced <= set(types), "every field type reference resolves to a type"


def test_redefines_normalizes_to_a_union_of_every_layout() -> None:
    api = _example("03-payment-redefines.cpy")
    types = _types(api)
    union = types["PAYMENT-RECORD.PAYMENT-DETAIL-OVERLAY"]
    assert union.kind is TypeKind.UNION
    assert union.union_members == [
        "PAYMENT-RECORD.PAYMENT-DETAIL",
        "PAYMENT-RECORD.CARD-DETAIL",
        "PAYMENT-RECORD.BANK-DETAIL",
    ]
    assert union.extras["cobol_base"] == "PAYMENT-DETAIL"
    assert union.extras["cobol_offset"] == 18 and union.extras["cobol_storage_length"] == 30
    # The elementary base layout is an alias of its scalar; the redefining groups are records.
    assert types["PAYMENT-RECORD.PAYMENT-DETAIL"].kind is TypeKind.ALIAS
    assert types["PAYMENT-RECORD.PAYMENT-DETAIL"].aliased.name == "string"
    assert types["PAYMENT-RECORD.CARD-DETAIL"].kind is TypeKind.RECORD
    # The record keeps one field for the shared storage, typed by the union.
    fields = _fields(api, "PAYMENT-RECORD.PAYMENT-RECORD")
    assert "CARD-DETAIL" not in fields and "BANK-DETAIL" not in fields
    assert fields["PAYMENT-DETAIL"].type.name == "PAYMENT-RECORD.PAYMENT-DETAIL-OVERLAY"
    assert fields["PAYMENT-DETAIL"].extras["cobol_redefined_by"] == ["CARD-DETAIL", "BANK-DETAIL"]


def test_a_redefines_of_an_undeclared_item_stays_an_ordinary_field() -> None:
    api = _example("08-overlay-warnings.cpy")
    fields = _fields(api, "ACCOUNT-SNAPSHOT.ACCOUNT-SNAPSHOT")
    assert fields["SNAP-ORPHAN"].type.name == "ACCOUNT-SNAPSHOT.SNAP-ORPHAN"
    assert fields["SNAP-ORPHAN"].extras["cobol_redefines"] == "SNAP-MISSING"


def test_a_redefinition_of_a_redefinition_joins_the_original_overlay() -> None:
    api = _api(
        _copybook(
            "01  REC.",
            "    05  BODY     PIC X(8).",
            "    05  ALT-A REDEFINES BODY PIC 9(8).",
            "    05  ALT-B REDEFINES ALT-A PIC X(8).",
        )
    )
    assert _types(api)["REC.BODY-OVERLAY"].union_members == ["REC.BODY", "REC.ALT-A", "REC.ALT-B"]
    assert set(_fields(api, "REC.REC")) == {"BODY"}


@pytest.mark.parametrize(
    ("clause", "type_name", "constraints"),
    [
        ("PIC X(12)", "string", {"max_length": 12}),
        ("PIC A(3)", "string", {"max_length": 3}),
        ("PIC ZZ9.99", "string", {"max_length": 6}),
        ("PIC 9(4)", "i32", {"minimum": 0, "maximum": 9999}),
        ("PIC S9(9) COMP", "i32", {"minimum": -999999999, "maximum": 999999999}),
        ("PIC 9(12)", "i64", {"minimum": 0, "maximum": 999999999999}),
        ("PIC S9(5)V99 COMP-3", "decimal", {"minimum": -99999.99, "maximum": 99999.99}),
        ("PIC 9(18)", "i64", {}),
        ("PIC 9(20)", "decimal", {}),
        ("PIC 9(3)PP", "i32", {}),
        ("COMP-1", "float", {}),
        ("COMP-2", "double", {}),
    ],
)
def test_pictures_map_to_primitives_with_their_bounds(clause: str, type_name: str, constraints: dict) -> None:
    api = _api(_copybook("01  REC.", f"    05  ITEM  {clause}.", "    05  OTHER PIC X."))
    item = _fields(api, "REC.REC")["ITEM"]
    assert item.type.name == type_name
    got = item.constraints.model_dump(exclude_none=True, exclude={"extras"}) if item.constraints else {}
    assert got == constraints


def test_an_occurs_table_is_a_list_with_its_bounds() -> None:
    api = _example("01-customer-record.cpy")
    phones = _fields(api, "CUSTOMER-RECORD.CUSTOMER-RECORD")["CUST-PHONES"]
    assert phones.type.item.name == "CUSTOMER-RECORD.CUST-PHONES"
    assert (phones.constraints.min_items, phones.constraints.max_items) == (1, 5)


def test_every_item_records_its_offset_length_and_storage_note() -> None:
    api = _example("03-payment-redefines.cpy")
    fields = _fields(api, "PAYMENT-RECORD.PAYMENT-RECORD")
    amount = fields["PAYMENT-AMOUNT"].extras
    assert (amount["cobol_offset"], amount["cobol_length"], amount["cobol_total_length"]) == (12, 6, 6)
    assert amount["cobol_storage"] == {"kind": "packed-decimal", "note": STORAGE_NOTES["packed-decimal"]}
    assert fields["PAYMENT-ID"].extras["cobol_storage"]["kind"] == "zoned-decimal"
    assert fields["PAYMENT-TYPE"].extras["cobol_storage"]["kind"] == "ebcdic-text"
    assert api.extras["cobolcopybook_record_length"] == {"min": 55, "max": 55}
    assert api.extras["cobolcopybook_encoding"]["assumed"] == "EBCDIC"
    assert api.extras["cobolcopybook_encoding"]["notes"]


def test_items_after_a_variable_table_have_no_offset() -> None:
    api = _example("01-customer-record.cpy")
    created = _fields(api, "CUSTOMER-RECORD.CUSTOMER-RECORD")["CUST-CREATED-DATE"].extras
    assert created["cobol_offset"] is None and created["cobol_offset_variable"] is True


def test_repeated_filler_items_get_distinct_keys() -> None:
    api = _api(_copybook("01  REC.", "    05  FILLER PIC X(2).", "    05  CODE PIC X.", "    05  FILLER PIC X(3)."))
    keys = [f.key for f in _types(api)["REC.REC"].fields]
    assert sorted(keys) == ["REC.REC.CODE", "REC.REC.FILLER", "REC.REC.FILLER#2"]


@pytest.mark.parametrize(
    ("picture", "kind"),
    [
        ("X(4)", "text"),
        ("A", "text"),
        ("S9(4)V99", "numeric"),
        ("9(3)PP", "numeric"),
        ("Z,ZZ9.99-", "edited"),
        (None, None),
    ],
)
def test_picture_class(picture, kind) -> None:
    assert picture_class(picture) == kind


# --- parser helpers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "value", "written"),
    [
        ("'A'", "A", "'A'"),
        ("'O''B'", "O'B", "'O''B'"),
        ('"Q"', "Q", "'Q'"),
        ("'B' 'X'", "'B' 'X'", "'B' 'X'"),
        ("'A' THRU 'C'", "'A' THRU 'C'", "'A' THRU 'C'"),
        ("'A', 'B'", "'A', 'B'", "'A', 'B'"),
    ],
)
def test_88_values_round_trip(text: str, value: str, written: str) -> None:
    """A list of literals used to be fused into one (``B' 'X``) and written back as another value."""
    assert condition_value(text) == value
    assert _condition_value({"value": value}) == written


def test_a_field_template_rebuilds_the_same_tree() -> None:
    document = parse_cobolcopybook((_EXAMPLES / "04-warehouse-stress.cpy").read_text(encoding="utf-8"))
    assert field_template(field_from_template(field_template(document.root))) == field_template(document.root)


def test_a_malformed_template_is_refused() -> None:
    with pytest.raises(ValueError):
        field_from_template({"name": "X"})
    with pytest.raises(ValueError):
        field_from_template(["not", "a", "mapping"])  # type: ignore[arg-type]


# --- the record-layout hash ---------------------------------------------------------------------


def test_the_layout_hash_is_registered_and_attached() -> None:
    result = fingerprint(_example("02-order-line.cpy"))
    assert result.format_algorithm == LAYOUT_HASH_ALGORITHM
    assert result.format_hash and len(result.format_hash) == 64


def test_the_layout_hash_ignores_names_levels_and_conditions() -> None:
    base = _api(_copybook(*_POLICY))
    renamed = _api(
        _copybook(
            "01  POLICY.",
            "    10  POLICY-NO       PIC X(10).",
            "    10  POLICY-STATE    PIC X(1).",
            "        88  IS-ACTIVE   VALUE 'A'.",
            "        88  IS-LAPSED   VALUE 'L'.",
            "    10  PREMIUM         PIC S9(7)V99 COMP-3.",
            "    10  FILLER          PIC X(20).",
        )
    )
    assert fingerprint(base).format_hash == fingerprint(renamed).format_hash
    assert fingerprint(base).fingerprint != fingerprint(renamed).fingerprint


def test_the_layout_hash_changes_when_a_byte_moves() -> None:
    base = fingerprint(_version("v1")).format_hash
    assert fingerprint(_version("v3-breaking")).format_hash != base
    assert fingerprint(_version("v2-compatible")).format_hash != base


def test_a_model_without_a_tree_has_no_layout_hash() -> None:
    api = _api(_copybook(*_POLICY)).model_copy(update={"extras": {}})
    assert record_tree(api) is None
    assert fingerprint(api).format_hash is None


def test_a_redefines_is_hashed_by_position_not_name() -> None:
    root = record_tree(_example("03-payment-redefines.cpy"))
    redefining = [entry["redefines"] for entry in layout_signature(root) if entry["redefines"] is not None]
    assert redefining == [3, 3]


# --- lint ---------------------------------------------------------------------------------------


def test_the_pack_is_registered_and_native() -> None:
    assert get_rule_pack("cobolcopybook") is CobolCopybookRulePack
    assert capability_for_format("cobolcopybook").mode == MODE_NATIVE
    ids = [rule.rule_id for rule in CobolCopybookRulePack().rules()]
    assert len(ids) == len(set(ids)) == 12
    assert all(rule_id.startswith("cobolcopybook.") for rule_id in ids)


def test_a_clean_copybook_raises_no_layout_findings() -> None:
    clean = _copybook(
        "01  REC.",
        "    05  REC-TYPE   PIC X.",
        "        88  IS-CARD VALUE 'C'.",
        "    05  REC-BODY   PIC X(8).",
        "    05  REC-CARD REDEFINES REC-BODY PIC 9(8).",
        "    05  REC-AMOUNT PIC S9(7)V99 COMP-3.",
    )
    assert _findings(clean) == []


def test_ambiguous_and_ill_fitting_redefines_are_flagged() -> None:
    findings = _findings((_EXAMPLES / "08-overlay-warnings.cpy").read_text(encoding="utf-8"))
    assert ("cobolcopybook.redefines-target-declared", "warning", "ACCOUNT-SNAPSHOT.SNAP-ORPHAN") in findings
    assert ("cobolcopybook.redefines-fits", "warning", "ACCOUNT-SNAPSHOT.SNAP-WIDE") in findings
    assert ("cobolcopybook.redefines-discriminated", "info", "ACCOUNT-SNAPSHOT.SNAP-BODY") in findings


def test_an_overlay_with_a_type_code_is_not_ambiguous() -> None:
    rules = _rules((_EXAMPLES / "03-payment-redefines.cpy").read_text(encoding="utf-8"))
    assert "cobolcopybook.redefines-discriminated" not in rules


def test_too_few_conditions_leave_an_overlay_ambiguous() -> None:
    text = _copybook(
        "01  REC.",
        "    05  REC-TYPE  PIC X.",
        "        88  IS-A  VALUE 'A'.",
        "    05  BODY      PIC X(4).",
        "    05  ALT-A REDEFINES BODY PIC 9(4).",
        "    05  ALT-B REDEFINES BODY PIC X(4).",
    )
    assert "cobolcopybook.redefines-discriminated" in _rules(text)


def test_a_variable_table_in_an_overlay_is_flagged() -> None:
    text = _copybook(
        "01  REC.",
        "    05  N        PIC 9.",
        "    05  BODY.",
        "        10  ROWS OCCURS 1 TO 3 TIMES DEPENDING ON N PIC X.",
        "    05  ALT REDEFINES BODY PIC X(3).",
    )
    assert "cobolcopybook.redefines-variable" in _rules(text)


def test_depending_on_controllers_are_checked() -> None:
    undeclared = _copybook("01  REC.", "    05  ROWS OCCURS 1 TO 3 TIMES DEPENDING ON ROW-COUNT PIC X.")
    assert "cobolcopybook.odo-controller-declared" in _rules(undeclared)
    late = _copybook(
        "01  REC.",
        "    05  ROWS OCCURS 1 TO 3 TIMES DEPENDING ON ROW-COUNT PIC X.",
        "    05  ROW-COUNT PIC 9.",
    )
    assert "cobolcopybook.odo-controller-precedes" in _rules(late)
    assert "cobolcopybook.odo-trailing-items" in _rules(late)


def test_a_table_at_the_end_has_no_trailing_items() -> None:
    text = _copybook("01  REC.", "    05  N PIC 9.", "    05  ROWS OCCURS 1 TO 3 TIMES DEPENDING ON N PIC X.")
    assert _rules(text) == set()


def test_duplicate_names_unsized_storage_and_even_packed_digits() -> None:
    text = _copybook(
        "01  REC.",
        "    05  A.",
        "        10  CODE   PIC X.",
        "    05  B.",
        "        10  CODE   PIC X.",
        "    05  TITLE      PIC N(10).",
        "    05  AMOUNT     PIC S9(6) COMP-3.",
    )
    findings = _findings(text)
    assert ("cobolcopybook.duplicate-name", "warning", "REC.B.CODE") in findings
    assert ("cobolcopybook.storage-sized", "warning", "REC.TITLE") in findings
    assert ("cobolcopybook.packed-odd-digits", "info", "REC.AMOUNT") in findings


def test_filler_and_duplicate_condition_values() -> None:
    text = _copybook(
        "01  REC.",
        "    05  FLAG     PIC X.",
        "        88  ON-A VALUE 'Y'.",
        "        88  ON-B VALUE 'Y'.",
        "    05  FILLER   PIC X(9).",
    )
    findings = _findings(text)
    assert ("cobolcopybook.condition-values-unique", "warning", "REC.FLAG.ON-B") in findings
    assert ("cobolcopybook.filler-unused", "info", "REC.FILLER") in findings


def test_the_pack_ignores_a_model_without_a_tree() -> None:
    api = _api(_copybook(*_POLICY)).model_copy(update={"extras": {}})
    findings = lint_canonical_model(api).findings
    assert not [f for f in findings if f.rule.startswith("cobolcopybook.")]


def test_walk_record_yields_qualified_paths_in_source_order() -> None:
    root = record_tree(_example("03-payment-redefines.cpy"))
    paths = [path for _field, _parent, path, _index in walk_record(root)]
    assert paths[:3] == ["PAYMENT-RECORD", "PAYMENT-RECORD.PAYMENT-ID", "PAYMENT-RECORD.PAYMENT-TYPE"]
    assert "PAYMENT-RECORD.CARD-DETAIL.CARD-NUMBER" in paths


# --- the layout diff ----------------------------------------------------------------------------


def test_the_classifier_is_registered() -> None:
    assert "cobolcopybook" in available_breaking_change_formats()
    assert CobolCopybookBreakingChangeClassifier.classifier_id == "cobolcopybook-layout"


def test_a_field_carved_from_filler_is_safe() -> None:
    grades = _grades(_version("v1"), _version("v2-compatible"))
    assert grades[("added", "POLICY-RECORD.POLICY-RECORD.POL-AGENT-CODE")] == (
        Severity.SAFE,
        "cobolcopybook.field-added-in-place",
    )
    assert grades[("modified", "POLICY-RECORD.POLICY-RECORD.FILLER")] == (
        Severity.SAFE,
        "cobolcopybook.filler-reclaimed",
    )
    assert grades[("modified", "POLICY-RECORD.POLICY-RECORD.POL-STATUS")] == (
        Severity.SAFE,
        "cobolcopybook.condition-added",
    )
    assert all(severity is Severity.SAFE for severity, _rule in grades.values())


def test_an_inserted_field_moves_everything_after_it() -> None:
    grades = _grades(_version("v1"), _version("v3-breaking"))
    assert grades[("added", "POLICY-RECORD.POLICY-RECORD.POL-PRODUCT-CODE")] == (
        Severity.BREAKING,
        "cobolcopybook.field-inserted",
    )
    assert grades[("modified", "POLICY-RECORD.POLICY-RECORD.POL-HOLDER-NAME")] == (
        Severity.BREAKING,
        "cobolcopybook.offset-moved",
    )
    assert grades[("modified", "POLICY-RECORD.POLICY-RECORD")] == (
        Severity.BREAKING,
        "cobolcopybook.record-length-changed",
    )
    # The item before the insertion keeps its offset, so it is not a change at all.
    assert ("modified", "POLICY-RECORD.POLICY-RECORD.POL-NUMBER") not in grades


def test_a_field_appended_after_the_last_byte_is_dangerous() -> None:
    base = _api(_copybook(*_POLICY))
    target = _api(_copybook(*_POLICY, "    05  POL-AGENT PIC X(4)."))
    grades = _grades(base, target)
    assert grades[("added", "POLICY-RECORD.POLICY-RECORD.POL-AGENT")] == (
        Severity.DANGEROUS,
        "cobolcopybook.field-appended",
    )
    assert grades[("modified", "POLICY-RECORD.POLICY-RECORD")] == (
        Severity.DANGEROUS,
        "cobolcopybook.record-length-changed",
    )


def test_a_removed_field_is_breaking() -> None:
    base = _api(_copybook(*_POLICY))
    target = _api(_copybook(*[line for line in _POLICY if "POL-NUMBER" not in line]))
    grades = _grades(base, target)
    assert grades[("removed", "POLICY-RECORD.POLICY-RECORD.POL-NUMBER")] == (
        Severity.BREAKING,
        "cobolcopybook.field-removed",
    )


@pytest.mark.parametrize(
    ("old", "new", "rule"),
    [
        ("PIC X(10).", "PIC X(12).", "cobolcopybook.length-changed"),
        ("PIC X(10).", "PIC 9(10).", "cobolcopybook.picture-changed"),
        ("PIC X(10).", "PIC X OCCURS 10 TIMES.", "cobolcopybook.occurs-changed"),
    ],
)
def test_layout_changes_to_one_item_are_breaking(old: str, new: str, rule: str) -> None:
    base = _api(_copybook(*_POLICY))
    target = _api(_copybook(*[line.replace(old, new) if "POL-NUMBER" in line else line for line in _POLICY]))
    grades = _grades(base, target)
    assert grades[("modified", "POLICY-RECORD.POLICY-RECORD.POL-NUMBER")] == (Severity.BREAKING, rule)


def test_a_removed_condition_is_dangerous() -> None:
    base = _api(_copybook(*_POLICY))
    target = _api(_copybook(*[line for line in _POLICY if "88" not in line]))
    grades = _grades(base, target)
    assert grades[("modified", "POLICY-RECORD.POLICY-RECORD.POL-STATUS")] == (
        Severity.DANGEROUS,
        "cobolcopybook.condition-removed",
    )


def test_renumbered_levels_are_safe() -> None:
    base = _api(_copybook(*_POLICY))
    target = _api(_copybook(*[line.replace("05  ", "10  ") for line in _POLICY]))
    grades = _grades(base, target)
    assert grades and all(grade == (Severity.SAFE, "cobolcopybook.level-renumbered") for grade in grades.values())


def test_adding_and_removing_a_redefines_layout() -> None:
    one = _copybook(
        "01  REC.",
        "    05  REC-TYPE PIC X.",
        "    05  BODY     PIC X(8).",
        "    05  ALT-A REDEFINES BODY PIC 9(8).",
    )
    two = one + _copybook("    05  ALT-B REDEFINES BODY PIC X(8).")
    plain = _copybook("01  REC.", "    05  REC-TYPE PIC X.", "    05  BODY     PIC X(8).")
    grown = _grades(_api(one), _api(two))
    assert grown[("modified", "REC.BODY-OVERLAY")] == (Severity.DANGEROUS, "cobolcopybook.overlay-added")
    assert grown[("modified", "REC.REC.BODY")] == (Severity.DANGEROUS, "cobolcopybook.overlay-added")
    shrunk = _grades(_api(two), _api(one))
    assert shrunk[("modified", "REC.BODY-OVERLAY")] == (Severity.BREAKING, "cobolcopybook.overlay-removed")
    dropped = _grades(_api(one), _api(plain))
    assert dropped[("removed", "REC.BODY-OVERLAY")] == (Severity.BREAKING, "cobolcopybook.overlay-removed")
    added = _grades(_api(plain), _api(one))
    assert added[("added", "REC.BODY-OVERLAY")] == (Severity.DANGEROUS, "cobolcopybook.overlay-added")


def test_an_identical_copybook_has_no_changes() -> None:
    assert _grades(_version("v1"), _version("v1")) == {}
