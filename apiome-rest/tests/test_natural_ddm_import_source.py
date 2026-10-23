"""Natural / ADABAS DDM import — FMT-11.4 (#5486).

Covers the listing reader (header, banner, token-read field lines, type prefixes, formats, lengths,
suppression and descriptor flags, remarks), the level tree (groups, periodic groups, redefinitions),
descriptor sources, Natural views in a fileset, the canonical projection (scalars, byte lengths,
arrays with occurrence bounds, nested records, declared key metadata, length assumptions, declared
limits), every refusal's taxonomy code, detection, and the registry / ledger wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import pytest

from app.canonical_model import ApiParadigm, CanonicalApi, CanonicalField, Type, TypeKind
from app.data_contract_facts import SCHEMA_ONLY_FORMATS
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.format_version_coverage import version_coverage_for
from app.import_preview_manifest import PROVENANCE_EXTRA_KEYS, _natural_ddm_capability_rows
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.natural_ddm_import_source import NaturalDdmImportSource
from app.natural_ddm_normalizer import (
    LENGTH_ASSUMPTIONS,
    NATURAL_DDM_EXTRAS_KEY,
    NATURAL_DDM_LIMIT_DETAILS,
    byte_length,
)
from app.natural_ddm_parser import has_ddm_header, parse_ddm_text

load_builtin_import_sources()

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "natural-ddm"

HEADER = """DDM Name ...... TEST-FILE
DB ............ 001
File .......... 077
Default Sequence AA

T L DB Name                             F Leng  S D Remark
- - -- -------------------------------- - ----  - - ------------------------------
"""


def _line(
    level: int,
    short: str,
    name: str,
    fmt: str = "",
    length: str = "",
    flags: str = "",
    remark: str = "",
    *,
    type_code: str = " ",
) -> str:
    """One field line in the listing's columns."""
    return f"{type_code} {level} {short} {name:<32} {fmt:1} {length:>4}  {flags:>3} {remark}".rstrip() + "\n"


BASE = HEADER + "".join(
    [
        _line(1, "AA", "KEY-FIELD", "A", "10", "U", "Primary key"),
        _line(1, "AB", "NAME-FIELD", "A", "40", "D"),
        _line(1, "AC", "AMOUNT", "P", "11.2", "N"),
        _line(1, "AD", "COUNTER", "N", "5.0", "N"),
        _line(1, "AE", "PHONE", "A", "20", "N", type_code="M"),
        _line(1, "AF", "LINES", remark="Periodic group", type_code="P"),
        _line(2, "AG", "LINE-SKU", "A", "18", "D"),
        _line(2, "AH", "LINE-NOTE", "A", "30", "N", type_code="M"),
        _line(1, "S1", "SUPER-KEY", "A", "50", "D", "AA(1-10),AB(1-40)", type_code="S"),
    ]
)


def _adapter() -> NaturalDdmImportSource:
    return NaturalDdmImportSource()


def _import(text: str, name: str = "test.ddm") -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse(text, source_label=name))


def _import_fileset(members: Dict[str, str], root: str) -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root=root)))


def _code(text: str, name: str = "test.ddm") -> Optional[str]:
    try:
        _adapter().parse(text, source_label=name)
    except ImportSourceError as exc:
        return exc.code
    return None


def _fileset_code(members: Dict[str, str], root: str) -> Optional[str]:
    try:
        _adapter().parse_fileset(IntakeFileset.from_members(members, root=root))
    except ImportSourceError as exc:
        return exc.code
    return None


def _type(api: CanonicalApi, key: str) -> Type:
    found = api.type_by_key(key)
    assert found is not None, f"{key} not in {[t.key for t in api.types]}"
    return found


def _field(api: CanonicalApi, type_key: str, name: str) -> CanonicalField:
    return next(f for f in _type(api, type_key).fields if f.name == name)


def _limits(api: CanonicalApi) -> Dict[str, int]:
    return {limit["construct"]: limit["count"] for limit in api.extras[NATURAL_DDM_EXTRAS_KEY]["capability_limits"]}


def _descriptors(api: CanonicalApi, key: str = "natural.TEST-FILE") -> List[Dict[str, object]]:
    return _type(api, key).extras[NATURAL_DDM_EXTRAS_KEY]["descriptors"]


def _example(name: str) -> CanonicalApi:
    return _import((EXAMPLES / name).read_text(encoding="utf-8"), name)


# ===========================================================================
# Listing reader
# ===========================================================================


class TestReader:
    def test_header_and_tree(self) -> None:
        ddm = parse_ddm_text(BASE).ddms[0]
        assert (ddm.name, ddm.database, ddm.file_number, ddm.default_sequence) == ("TEST-FILE", "001", "077", "AA")
        assert [f.name for f in ddm.fields] == ["KEY-FIELD", "NAME-FIELD", "AMOUNT", "COUNTER", "PHONE", "LINES"]
        lines = ddm.fields[-1]
        assert lines.periodic and [c.name for c in lines.children] == ["LINE-SKU", "LINE-NOTE"]
        assert ddm.descriptors[0].sources == [("AA", 1, 10), ("AB", 1, 40)]

    def test_lengths_and_flags(self) -> None:
        ddm = parse_ddm_text(BASE).ddms[0]
        amount = ddm.by_name("AMOUNT")
        assert amount is not None and (amount.length, amount.decimals) == (11, 2)
        key = ddm.by_name("KEY-FIELD")
        assert key is not None and key.descriptor == "U" and key.remark == "Primary key"
        counter = ddm.by_name("COUNTER")
        assert counter is not None and counter.descriptor is None

    def test_suppression_column_and_remark_markers(self) -> None:
        text = HEADER + _line(1, "AA", "ONE", "A", "4", "N  U") + _line(1, "AB", "TWO", "A", "4", "N", "NU Null")
        text += _line(1, "AC", "THREE", "A", "4", "F  N") + _line(1, "AD", "FOUR", "A", "4", "N", "FI fixed")
        ddm = parse_ddm_text(text).ddms[0]
        one, two, three, four = (ddm.by_name(n) for n in ("ONE", "TWO", "THREE", "FOUR"))
        assert one is not None and one.null_suppressed and one.descriptor == "U"
        assert two is not None and two.null_suppressed
        assert three is not None and three.fixed_storage and three.descriptor is None
        assert four is not None and four.fixed_storage

    def test_lines_are_read_by_token_not_exact_column(self) -> None:
        text = HEADER + "  1 AA KEY-FIELD  A 10 U\n" + "  1 AB OTHER       A   5   N  Drifted columns\n"
        ddm = parse_ddm_text(text).ddms[0]
        assert [(f.name, f.length) for f in ddm.fields] == [("KEY-FIELD", 10), ("OTHER", 5)]

    def test_comments_and_blank_lines_are_skipped(self) -> None:
        text = HEADER + "* a comment\n\n" + _line(1, "AA", "KEY-FIELD", "A", "10", "U")
        assert parse_ddm_text(text).ddms[0].fields[0].name == "KEY-FIELD"

    def test_occurrence_remark_sets_a_bound(self) -> None:
        text = BASE.replace("Periodic group", "Up to 12 occurrences")
        lines = parse_ddm_text(text).ddms[0].by_name("LINES")
        assert lines is not None and (lines.max_occurrences, lines.occurrence_source) == (12, "remark")

    @pytest.mark.parametrize(
        ("line", "code"),
        [
            ("1 AZ BROKEN\n", "INPUT_MALFORMED"),  # level in the type column
            ("  1 AZ\n", "INPUT_MALFORMED"),  # no name
            ("  X AZ NAME-X A 1 N\n", "INPUT_MALFORMED"),  # level is not a digit
            ("  1 A NAME-X A 1 N\n", "INPUT_MALFORMED"),  # one-character short name
            ("  1 AZ NAME-X A ONE N\n", "INPUT_MALFORMED"),  # length is not a number
            ("  1 AZ NAME-X Q 1 N\n", "INPUT_MALFORMED"),  # unknown format, not a group
            ("X 1 AZ NAME-X A 1 N\n", "INPUT_MALFORMED"),  # unknown type prefix
        ],
    )
    def test_malformed_lines(self, line: str, code: str) -> None:
        assert _code(BASE + line) == code

    def test_missing_banner_is_malformed(self) -> None:
        text = BASE.replace("T L DB Name", "Columns")
        assert _code(text) == "INPUT_MALFORMED"

    def test_no_field_lines_is_semantic(self) -> None:
        assert _code(HEADER.replace("Default Sequence AA", "Default Sequence")) == "INPUT_SEMANTIC_INVALID"

    def test_last_line_cut_after_its_length_is_truncated(self) -> None:
        assert _code(BASE + "  1 AZ CUT-FIELD                        A    10\n") == "INPUT_TRUNCATED"

    def test_listing_with_no_descriptor_columns_is_not_truncated(self) -> None:
        text = HEADER.replace("Default Sequence AA", "Default Sequence") + "  1 AA ONE A 4\n  1 AB TWO A 4\n"
        assert _code(text) is None

    @pytest.mark.parametrize(
        ("change", "code"),
        [
            # A level-2 field under a plain field.
            (lambda t: t + _line(2, "AZ", "ORPHAN", "A", "1", "N"), "INPUT_SEMANTIC_INVALID"),
            # A level that skips one.
            (lambda t: t.replace("  2 AG LINE-SKU", "  3 AG LINE-SKU"), "INPUT_SEMANTIC_INVALID"),
            # A name used twice.
            (lambda t: t.replace("COUNTER", "AMOUNT"), "INPUT_SEMANTIC_INVALID"),
            # A short name used twice.
            (lambda t: t.replace("1 AD COUNTER", "1 AC COUNTER"), "INPUT_SEMANTIC_INVALID"),
            # A periodic group inside a periodic group.
            (
                lambda t: t.replace(
                    _line(2, "AH", "LINE-NOTE", "A", "30", "N", type_code="M"),
                    _line(2, "AH", "INNER", type_code="P") + _line(3, "AI", "INNER-X", "A", "1", "N"),
                ),
                "INPUT_SEMANTIC_INVALID",
            ),
            # A group with no members.
            (lambda t: t + _line(1, "AZ", "EMPTY-GROUP", type_code="G"), "INPUT_SEMANTIC_INVALID"),
            # A superdescriptor whose length differs from its sources.
            (
                lambda t: t.replace(
                    "SUPER-KEY                        A   50", "SUPER-KEY                        A   49"
                ),
                "INPUT_SEMANTIC_INVALID",
            ),
            # A superdescriptor without sources.
            (lambda t: t.replace("AA(1-10),AB(1-40)", "no sources"), "INPUT_SEMANTIC_INVALID"),
            # A descriptor source that is not defined.
            (lambda t: t.replace("AB(1-40)", "ZZ(1-40)"), "INPUT_REFERENCE_UNRESOLVED"),
            # A default sequence that is not defined.
            (lambda t: t.replace("Default Sequence AA", "Default Sequence ZZ"), "INPUT_REFERENCE_UNRESOLVED"),
        ],
    )
    def test_structure_refusals(self, change, code: str) -> None:  # type: ignore[no-untyped-def]
        assert _code(change(BASE)) == code

    def test_redefinitions(self) -> None:
        text = (
            HEADER
            + _line(1, "AA", "KEY-FIELD", "A", "10", "U")
            + _line(1, "AB", "BLOCK", "A", "12", "N")
            + _line(2, "AB", "PART-ONE", "A", "4", "N", type_code="R")
            + _line(2, "AB", "PART-TWO", "N", "8.0", "N", type_code="R")
        )
        api = _import(text)
        two = _field(api, "natural.TEST-FILE", "PART-TWO")
        assert two.type.name == "integer"
        assert two.extras[NATURAL_DDM_EXTRAS_KEY]["redefines"] == {"field": "BLOCK", "shortName": "AB", "position": 5}
        assert _limits(api)["ddm.redefinition"] == 2
        too_long = text.replace("N  8.0", "N  9.0")
        assert _code(too_long) == "INPUT_SEMANTIC_INVALID"
        wrong_short = text.replace("R 2 AB PART-ONE", "R 2 AC PART-ONE")
        assert _code(wrong_short) == "INPUT_REFERENCE_UNRESOLVED"


# ===========================================================================
# Projection
# ===========================================================================


class TestProjection:
    def test_document_shape(self) -> None:
        api = _import(BASE)
        assert api.paradigm is ApiParadigm.DATA_SCHEMA and api.format == "natural-ddm"
        assert api.identity.name == "TEST-FILE" and api.identity.namespace == "natural"
        assert {t.key for t in api.types} == {"natural.TEST-FILE", "natural.TEST-FILE.LINES"}
        assert all(t.kind is TypeKind.RECORD for t in api.types)
        assert api.extras[NATURAL_DDM_EXTRAS_KEY]["lengthAssumptions"] == list(LENGTH_ASSUMPTIONS)
        assert _adapter().normalize(_adapter().parse(BASE), include_raw=False).raw is None

    def test_scalars_and_byte_lengths(self) -> None:
        api = _import(BASE)
        key = _field(api, "natural.TEST-FILE", "KEY-FIELD")
        assert key.type.name == "string" and key.constraints is not None and key.constraints.max_length == 10
        amount = _field(api, "natural.TEST-FILE", "AMOUNT").extras[NATURAL_DDM_EXTRAS_KEY]
        assert (amount["digits"], amount["decimals"], amount["bytes"]) == (13, 2, 7)
        assert _field(api, "natural.TEST-FILE", "AMOUNT").type.name == "decimal"
        counter = _field(api, "natural.TEST-FILE", "COUNTER")
        assert counter.type.name == "integer" and counter.extras[NATURAL_DDM_EXTRAS_KEY]["bytes"] == 5

    @pytest.mark.parametrize(
        ("fmt", "length", "scalar", "size"),
        [
            ("B", "4", "bytes", 4),
            ("F", "4", "float", 4),
            ("F", "8", "double", 8),
            ("G", "8", "double", 8),
            ("L", "1", "boolean", 1),
            ("D", "4", "date", 4),
            ("T", "7", "datetime", 7),
            ("I", "4", "integer", 4),
            ("U", "40", "string", 40),
            ("N", "7.2", "decimal", 9),
            ("P", "13.3", "decimal", 9),
        ],
    )
    def test_every_format(self, fmt: str, length: str, scalar: str, size: int) -> None:
        api = _import(HEADER + _line(1, "AA", "KEY-FIELD", "A", "10", "U") + _line(1, "AZ", "X", fmt, length, "N"))
        item = _field(api, "natural.TEST-FILE", "X")
        assert item.type.name == scalar and item.extras[NATURAL_DDM_EXTRAS_KEY]["bytes"] == size
        if fmt == "U":
            assert item.constraints is not None and item.constraints.max_length == 20

    def test_lob_field(self) -> None:
        api = _import(BASE + _line(1, "AZ", "LOB", "A", "0", "N"))
        lob = _field(api, "natural.TEST-FILE", "LOB")
        assert lob.constraints is None and "bytes" not in lob.extras[NATURAL_DDM_EXTRAS_KEY]
        assert _limits(api)["ddm.lob_field"] == 1

    def test_multiple_value_and_periodic_group_are_arrays(self) -> None:
        api = _import(BASE)
        phone = _field(api, "natural.TEST-FILE", "PHONE")
        assert phone.type.item is not None and phone.type.item.name == "string"
        assert phone.constraints is not None and phone.constraints.extras == {"item_max_length": 20}
        assert phone.constraints.max_items is None
        lines = _field(api, "natural.TEST-FILE", "LINES")
        assert lines.type.item is not None and lines.type.item.name == "natural.TEST-FILE.LINES"
        note = _field(api, "natural.TEST-FILE.LINES", "LINE-NOTE")
        assert note.type.item is not None  # MU inside PE: an array inside the group's record
        assert _limits(api)["ddm.unbounded_occurrences"] == 3

    def test_group_is_a_nested_record(self) -> None:
        text = BASE + _line(1, "AZ", "BILLING", type_code="G") + _line(2, "AY", "DAY", "N", "2.0", "N")
        api = _import(text)
        billing = _field(api, "natural.TEST-FILE", "BILLING")
        assert billing.type.name == "natural.TEST-FILE.BILLING" and billing.type.item is None
        assert _type(api, "natural.TEST-FILE.BILLING").extras[NATURAL_DDM_EXTRAS_KEY]["kind"] == "group"

    def test_descriptors_are_declared_key_metadata(self) -> None:
        api = _import(BASE)
        keys = _descriptors(api)
        assert keys[:3] == [
            {"kind": "unique-descriptor", "shortName": "AA", "field": "KEY-FIELD", "unique": True},
            {"kind": "descriptor", "shortName": "AB", "field": "NAME-FIELD", "unique": False},
            {"kind": "descriptor", "shortName": "AG", "field": "LINE-SKU", "unique": False},
        ]
        superkey = keys[3]
        assert superkey["kind"] == "superdescriptor" and superkey["length"] == 50
        assert superkey["sources"] == [
            {"shortName": "AA", "field": "KEY-FIELD", "from": 1, "to": 10},
            {"shortName": "AB", "field": "NAME-FIELD", "from": 1, "to": 40},
        ]
        assert _field(api, "natural.TEST-FILE", "KEY-FIELD").extras[NATURAL_DDM_EXTRAS_KEY]["descriptor"] == {
            "unique": True
        }
        assert "SUPER-KEY" not in {f.name for f in _type(api, "natural.TEST-FILE").fields}
        assert _limits(api)["ddm.derived_descriptor"] == 1
        sequence = _type(api, "natural.TEST-FILE").extras[NATURAL_DDM_EXTRAS_KEY]["defaultSequence"]
        assert sequence == {"shortName": "AA", "field": "KEY-FIELD"}

    def test_byte_length_helper(self) -> None:
        ddm = parse_ddm_text(BASE).ddms[0]
        assert byte_length(ddm.by_name("LINES")) is None  # type: ignore[arg-type]
        assert byte_length(ddm.by_name("AMOUNT")) == 7  # type: ignore[arg-type]


# ===========================================================================
# Filesets and views
# ===========================================================================


VIEW = """DEFINE DATA LOCAL
1 TEST-VIEW VIEW OF TEST-FILE
  2 KEY-FIELD
  2 PHONE (1:4)
  2 LINES (1:9)
    3 LINE-SKU
1 #WORK (A10)
END-DEFINE
READ TEST-VIEW BY KEY-FIELD
END-READ
END
"""


class TestViews:
    def test_view_bounds_apply_to_the_ddm(self) -> None:
        api = _import_fileset({"TEST.ddm": BASE, "PROG.nsp": VIEW}, root="TEST.ddm")
        phone = _field(api, "natural.TEST-FILE", "PHONE")
        assert phone.constraints is not None and phone.constraints.max_items == 4
        assert phone.extras[NATURAL_DDM_EXTRAS_KEY]["occurrences"] == {"maximum": 4, "source": "view TEST-VIEW"}
        lines = _field(api, "natural.TEST-FILE", "LINES")
        assert lines.constraints is not None and lines.constraints.max_items == 9
        views = api.extras[NATURAL_DDM_EXTRAS_KEY]["views"]
        assert views[0]["name"] == "TEST-VIEW" and views[0]["ddmResolved"] is True
        assert [f["name"] for f in views[0]["fields"]] == ["KEY-FIELD", "PHONE", "LINES", "LINE-SKU"]
        assert _limits(api)["ddm.unbounded_occurrences"] == 1  # only LINE-NOTE is left

    def test_view_field_the_ddm_lacks_is_unresolved(self) -> None:
        members = {"TEST.ddm": BASE, "PROG.nsp": VIEW.replace("2 KEY-FIELD", "2 GHOST-FIELD")}
        assert _fileset_code(members, root="TEST.ddm") == "INPUT_REFERENCE_UNRESOLVED"

    def test_view_over_another_ddm_is_listed(self) -> None:
        api = _import_fileset({"TEST.ddm": BASE, "PROG.nsp": VIEW.replace("OF TEST-FILE", "OF OTHER-FILE")}, "TEST.ddm")
        assert _limits(api)["ddm.unresolved_view"] == 1
        assert api.extras[NATURAL_DDM_EXTRAS_KEY]["views"][0]["ddmResolved"] is False

    def test_fileset_rules(self) -> None:
        assert _fileset_code({"a.txt": "hello\n", "b.ddm": BASE}, root="a.txt") == "FORMAT_MISMATCH"
        assert _fileset_code({"a.ddm": BASE, "b.ddm": BASE}, root="a.ddm") == "INPUT_SEMANTIC_INVALID"
        api = _import_fileset({"a.ddm": BASE, "notes.md": "ignored", "plain.nsp": "WRITE 'X'\nEND\n"}, root="a.ddm")
        assert api.extras[NATURAL_DDM_EXTRAS_KEY]["files"] == ["a.ddm"]


# ===========================================================================
# Detection, registry and refusals
# ===========================================================================


class TestDetectionAndRegistry:
    def test_detection(self) -> None:
        assert _adapter().detect(DetectionInput(text=BASE)).confidence == 0.95
        assert _adapter().detect(DetectionInput(text="DDM Name ...... X\n")).confidence == 0.85
        assert _adapter().detect(DetectionInput(text="garbage", filename="x.ddm")).confidence == 0.5
        copybook = (EXAMPLES / "negative" / "04-wrong-format-cobol-copybook.cpy").read_text(encoding="utf-8")
        assert _adapter().detect(DetectionInput(text=copybook)).confidence == 0.0
        assert _adapter().detect(DetectionInput(data=b"\x00")).confidence == 0.0
        assert has_ddm_header(BASE) == (True, True)

    def test_adapter_is_registered(self) -> None:
        adapter = get_import_source("natural-ddm")
        assert isinstance(adapter, NaturalDdmImportSource) and adapter.paradigm is ApiParadigm.DATA_SCHEMA

    def test_capability_seed_version_coverage_and_facts(self) -> None:
        assert sorted(capability_for("natural-ddm").canonical_projection.dropped_constructs) == sorted(
            NATURAL_DDM_LIMIT_DETAILS
        )
        coverage = version_coverage_for("natural-ddm")
        assert coverage.reads and not coverage.writes
        assert "natural-ddm" in SCHEMA_ONLY_FORMATS
        assert NATURAL_DDM_EXTRAS_KEY in PROVENANCE_EXTRA_KEYS

    def test_ledger_rows(self) -> None:
        rows = {row.source_construct: row.coverage.value for row in _natural_ddm_capability_rows(_import(BASE))}
        assert rows == {
            "ddm.derived_descriptor": "not-parsed-by-adapter",
            "ddm.record_offsets": "partially-mapped",
            "ddm.unbounded_occurrences": "partially-mapped",
        }

    def test_normalize_rejects_a_foreign_document(self) -> None:
        with pytest.raises(ImportSourceError):
            _adapter().normalize(object())

    def test_empty_and_encoding(self) -> None:
        assert _code("  \n") == "INPUT_EMPTY"
        assert _code("﻿" + BASE) == "INPUT_ENCODING_INVALID"


# ===========================================================================
# Corpus
# ===========================================================================


class TestCorpus:
    def test_simple_ddm(self) -> None:
        api = _example("01-minimal-ddm.ddm")
        assert [f.name for f in _type(api, "natural.BEACON-FILE").fields] == ["BEACON-ID", "SEEN-AT"]
        assert _field(api, "natural.BEACON-FILE", "SEEN-AT").extras[NATURAL_DDM_EXTRAS_KEY]["bytes"] == 14

    def test_periodic_groups_with_remark_bounds(self) -> None:
        api = _example("06-typical-periodic-groups.ddm")
        line = _field(api, "natural.ORDER-FILE", "ORDER-LINE")
        assert line.constraints is not None and line.constraints.max_items == 99
        shipment = _field(api, "natural.ORDER-FILE", "SHIPMENT")
        assert shipment.constraints is not None and shipment.constraints.max_items == 20
        note = _field(api, "natural.ORDER-FILE.ORDER-LINE", "LINE-NOTE")
        assert note.type.item is not None and note.type.item.name == "string"

    def test_view_set(self) -> None:
        folder = EXAMPLES / "03-view-set"
        api = _import_fileset({p.name: p.read_text(encoding="utf-8") for p in folder.iterdir()}, root="CUSTOMER.ddm")
        phone = _field(api, "natural.CUSTOMER-FILE", "PHONE-NUMBER")
        contact = _field(api, "natural.CUSTOMER-FILE", "CONTACT")
        assert phone.constraints is not None and phone.constraints.max_items == 5
        assert contact.constraints is not None and contact.constraints.max_items == 3

    def test_stress_descriptor_kinds(self) -> None:
        api = _example("04-stress-formats-and-descriptors.ddm")
        kinds = [d["kind"] for d in _descriptors(api, "natural.COVERAGE-FILE")]
        assert kinds[-4:] == ["superdescriptor", "superdescriptor", "hyperdescriptor", "subdescriptor"]
        suppressed = _field(api, "natural.COVERAGE-FILE", "NULL-SUPPRESSED").extras[NATURAL_DDM_EXTRAS_KEY]
        assert suppressed["nullSuppressed"] is True

    def test_composition_nests_a_group_in_a_periodic_group(self) -> None:
        api = _example("07-composition-redefines-and-groups.ddm")
        status = _field(api, "natural.CONTRACT-FILE.INSTALMENT", "INSTALMENT-STATUS")
        assert status.type.name == "natural.CONTRACT-FILE.INSTALMENT.INSTALMENT-STATUS"

    @pytest.mark.parametrize(
        ("name", "code"),
        [
            ("01-syntactic-malformed-column-layout.ddm", "INPUT_MALFORMED"),
            ("02-semantic-no-fields.ddm", "INPUT_SEMANTIC_INVALID"),
            ("03-truncated-mid-field-list.ddm", "INPUT_TRUNCATED"),
            ("04-wrong-format-cobol-copybook.cpy", "FORMAT_MISMATCH"),
            ("06-unresolvable-superdescriptor-source.ddm", "INPUT_REFERENCE_UNRESOLVED"),
        ],
    )
    def test_negatives(self, name: str, code: str) -> None:
        assert _code((EXAMPLES / "negative" / name).read_text(encoding="utf-8"), name) == code
