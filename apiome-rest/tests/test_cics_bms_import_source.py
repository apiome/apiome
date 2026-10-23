"""CICS BMS map import — FMT-11.3 (#5484).

Covers the assembler statement reader (column-72 continuations, quoted values across lines,
over-long lines, comments), mapsets / maps / fields and their canonical projection (a record per
map, fields positioned by row and column, pictures to types, attributes as declared metadata,
literals kept on the map, OCCURS as lists), symbolic-map copybooks alone and beside their mapset,
every refusal's taxonomy code, detection, and the registry / ledger wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import pytest

from app.canonical_model import ApiParadigm, CanonicalApi, CanonicalField, Type, TypeKind
from app.cics_bms_parser import has_bms_macros, is_symbolic_map, parse_bms_text
from app.cobolcopybook_import_source import CobolCopybookImportSource
from app.data_contract_facts import SCHEMA_ONLY_FORMATS
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.format_version_coverage import version_coverage_for
from app.import_preview_manifest import PROVENANCE_EXTRA_KEYS, _mainframe_misc_capability_rows
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    detect_import_source,
    get_import_source,
    load_builtin_import_sources,
)
from app.mainframe_misc_import_source import CicsBmsImportSource, VsamIdcamsImportSource
from app.mainframe_misc_normalizer import BMS_EXTRAS_KEY, BMS_LIMIT_DETAILS, picture_scalar

load_builtin_import_sources()

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "cics-bms"


def _line(label: str, operation: str, operands: str, *, continued: bool = False) -> str:
    """One assembler line: label in column 1, operation in column 10, the mark in column 72."""
    text = f"{label:<8} {operation:<6} {operands}"
    return f"{text:<71}X" if continued else text


def _cont(operands: str, *, continued: bool = False) -> str:
    """A continuation line: operands from column 16."""
    text = " " * 15 + operands
    return f"{text:<71}X" if continued else text


def _mapset(*fields: str, size: str = "(24,80)", mapset_operands: str = "MODE=INOUT,LANG=COBOL") -> str:
    return "\n".join(
        [
            _line("TSTSET", "DFHMSD", f"TYPE=&SYSPARM,{mapset_operands}"),
            _line("TSTMAP", "DFHMDI", f"SIZE={size},LINE=1,COLUMN=1"),
            *fields,
            _line("", "DFHMSD", "TYPE=FINAL"),
            _line("", "END", ""),
        ]
    )


ENQUIRY = _mapset(
    _line("", "DFHMDF", "POS=(1,1),LENGTH=10,ATTRB=(PROT,BRT),INITIAL='ENQUIRY'"),
    _line("CUSTID", "DFHMDF", "POS=(3,17),LENGTH=10,ATTRB=(UNPROT,NUM,IC),", continued=True),
    _cont("PICIN='9(10)',COLOR=GREEN"),
    _line("AMOUNT", "DFHMDF", "POS=(5,17),LENGTH=12,ATTRB=(PROT,NORM),PICOUT='ZZZ,ZZ9.99-'"),
    _line("RATE", "DFHMDF", "POS=(6,17),LENGTH=6,ATTRB=UNPROT,PICIN='9(3)V99'"),
    _line("NAME", "DFHMDF", "POS=(7,17),LENGTH=30"),
)


def _adapter() -> CicsBmsImportSource:
    return CicsBmsImportSource()


def _import(text: str, name: str = "test.bms") -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse(text, source_label=name))


def _code(text: str, name: str = "test.bms") -> Optional[str]:
    try:
        _adapter().parse(text, source_label=name)
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
    return {limit["construct"]: limit["count"] for limit in api.extras[BMS_EXTRAS_KEY]["capability_limits"]}


# ===========================================================================
# Pictures
# ===========================================================================


class TestPictures:
    @pytest.mark.parametrize(
        ("picture", "expected"),
        [
            (None, ("string", False)),
            ("X(10)", ("string", False)),
            ("XXX", ("string", False)),
            ("9(8)", ("integer", False)),
            ("S9(4)", ("integer", False)),
            ("9(7)V99", ("decimal", False)),
            ("ZZZ,ZZ9.99-", ("string", True)),
            ("ZZ9", ("string", True)),
            ("A(5)", ("string", False)),
        ],
    )
    def test_picture_scalar(self, picture: Optional[str], expected: tuple) -> None:
        assert picture_scalar(picture) == expected


# ===========================================================================
# Maps → records
# ===========================================================================


class TestMap:
    def test_map_becomes_a_record_namespaced_by_mapset(self) -> None:
        api = _import(ENQUIRY)
        assert api.paradigm is ApiParadigm.DATA_SCHEMA and api.format == "cics-bms"
        assert api.identity.name == "TSTSET"
        record = _type(api, "TSTSET.TSTMAP")
        assert record.kind is TypeKind.RECORD
        assert record.extras[BMS_EXTRAS_KEY]["size"] == {"rows": 24, "columns": 80}

    def test_fields_are_positioned_and_numbered_in_screen_order(self) -> None:
        api = _import(ENQUIRY)
        fields = sorted(_type(api, "TSTSET.TSTMAP").fields, key=lambda f: f.field_number or 0)
        assert [f.name for f in fields] == ["CUSTID", "AMOUNT", "RATE", "NAME"]
        assert fields[0].extras[BMS_EXTRAS_KEY]["position"] == {"row": 3, "column": 17}
        assert fields[0].extras[BMS_EXTRAS_KEY]["length"] == 10

    def test_types_follow_the_pictures(self) -> None:
        api = _import(ENQUIRY)
        assert _field(api, "TSTSET.TSTMAP", "CUSTID").type.name == "integer"
        assert _field(api, "TSTSET.TSTMAP", "RATE").type.name == "decimal"
        amount = _field(api, "TSTSET.TSTMAP", "AMOUNT")
        assert amount.type.name == "string" and amount.constraints.max_length == 12  # type: ignore[union-attr]
        name = _field(api, "TSTSET.TSTMAP", "NAME")
        assert name.type.name == "string" and name.constraints.max_length == 30  # type: ignore[union-attr]

    def test_attributes_are_declared_metadata(self) -> None:
        custid = _field(_import(ENQUIRY), "TSTSET.TSTMAP", "CUSTID").extras[BMS_EXTRAS_KEY]
        assert custid["attributes"] == {
            "protection": "unprotected",
            "numeric": True,
            "intensity": "normal",
            "initialCursor": True,
            "modifiedDataTag": False,
            "declared": ["UNPROT", "NUM", "IC"],
        }
        assert custid["picin"] == "9(10)" and custid["color"] == "GREEN"

    def test_attribute_defaults_are_autoskip_normal(self) -> None:
        name = _field(_import(ENQUIRY), "TSTSET.TSTMAP", "NAME").extras[BMS_EXTRAS_KEY]
        assert name["attributes"]["protection"] == "autoskip"
        assert name["attributes"]["intensity"] == "normal"

    def test_literals_stay_on_the_map(self) -> None:
        api = _import(ENQUIRY)
        literals = _type(api, "TSTSET.TSTMAP").extras[BMS_EXTRAS_KEY]["literals"]
        assert literals == [{"position": {"row": 1, "column": 1}, "length": 10, "initial": "ENQUIRY"}]
        assert _limits(api) == {"bms.literal_field": 1, "bms.edited_picture": 1}

    def test_occurs_is_a_list_of_exactly_n(self) -> None:
        api = _import(_mapset(_line("LINES", "DFHMDF", "POS=(5,1),LENGTH=12,OCCURS=8,PICOUT='X(12)'")))
        lines = _field(api, "TSTSET.TSTMAP", "LINES")
        assert lines.type.item is not None and lines.type.item.name == "string"
        assert (lines.constraints.min_items, lines.constraints.max_items) == (8, 8)  # type: ignore[union-attr]
        assert lines.constraints.extras["item_max_length"] == 12  # type: ignore[union-attr]
        assert _limits(api)["bms.occurs_layout"] == 1

    def test_mapset_defaults_are_inherited(self) -> None:
        api = _import(
            _mapset(_line("F1", "DFHMDF", "POS=(2,2),LENGTH=4"), mapset_operands="MODE=INOUT,COLOR=BLUE,HILIGHT=OFF")
        )
        assert _field(api, "TSTSET.TSTMAP", "F1").extras[BMS_EXTRAS_KEY]["inherited"] == {
            "color": "BLUE",
            "hilight": "OFF",
        }

    def test_group_and_initial(self) -> None:
        api = _import(_mapset(_line("DD", "DFHMDF", "POS=(6,22),LENGTH=2,GRPNAME=DATEGRP,INITIAL='01'")))
        metadata = _field(api, "TSTSET.TSTMAP", "DD").extras[BMS_EXTRAS_KEY]
        assert metadata["group"] == "DATEGRP" and metadata["initial"] == "01"

    def test_numeric_pos_is_an_offset(self) -> None:
        api = _import(_mapset(_line("F1", "DFHMDF", "POS=81,LENGTH=4")))
        assert _field(api, "TSTSET.TSTMAP", "F1").extras[BMS_EXTRAS_KEY]["position"] == {"row": 2, "column": 2}

    def test_length_defaults_to_initial(self) -> None:
        api = _import(_mapset(_line("F1", "DFHMDF", "POS=(2,2),INITIAL='ABCDE'")))
        assert _field(api, "TSTSET.TSTMAP", "F1").extras[BMS_EXTRAS_KEY]["length"] == 5

    def test_quoted_value_continues_on_the_next_line(self) -> None:
        first = _line("F1", "DFHMDF", "POS=(2,2),LENGTH=60,INITIAL='" + "A" * 40)
        first = f"{first:<71}X"
        text = _mapset(first, " " * 15 + "B" * 10 + "'")
        assert (
            _field(_import(text), "TSTSET.TSTMAP", "F1").extras[BMS_EXTRAS_KEY]["initial"].endswith("A" * 10 + "B" * 10)
        )

    def test_overlong_line_is_not_a_continuation(self) -> None:
        overlong = " " * 9 + "DFHMDF POS=(3,30),LENGTH=8,ATTRB=(PROT,NORM),INITIAL='QUANTITYXXXXXX'"
        assert len(overlong) > 72
        api = _import(_mapset(overlong, _line("F1", "DFHMDF", "POS=(5,1),LENGTH=4")))
        assert [f.name for f in _type(api, "TSTSET.TSTMAP").fields] == ["F1"]

    def test_unsized_map_assumes_24_by_80(self) -> None:
        text = "\n".join(
            [
                _line("S", "DFHMSD", "TYPE=MAP"),
                _line("M", "DFHMDI", "LINE=1"),
                _line("F", "DFHMDF", "POS=(1,2),LENGTH=3"),
                _line("", "DFHMSD", "TYPE=FINAL"),
            ]
        )
        metadata = _type(_import(text), "S.M").extras[BMS_EXTRAS_KEY]
        assert metadata["size"] == {"rows": 24, "columns": 80} and metadata["sizeDeclared"] is False


# ===========================================================================
# Symbolic maps
# ===========================================================================


SYMBOLIC = """      * generated symbolic map
       01  TSTMAPI.
           02  FILLER PIC X(12).
           02  CUSTIDL    COMP  PIC  S9(4).
           02  CUSTIDF    PICTURE X.
           02  FILLER REDEFINES CUSTIDF.
               03 CUSTIDA    PICTURE X.
           02  CUSTIDI  PIC X(10).
           02  AMOUNTL    COMP  PIC  S9(4).
           02  AMOUNTF    PICTURE X.
           02  FILLER REDEFINES AMOUNTF.
               03 AMOUNTA    PICTURE X.
           02  AMOUNTI  PIC X(12).
       01  TSTMAPO REDEFINES TSTMAPI.
           02  FILLER PIC X(12).
           02  FILLER PIC X(3).
           02  CUSTIDO  PIC X(10).
           02  FILLER PIC X(3).
           02  AMOUNTO  PIC ZZZ,ZZ9.99-.
"""


class TestSymbolicMap:
    def test_alone_gives_records_without_positions(self) -> None:
        api = _import(SYMBOLIC, "TSTMAP.cpy")
        record = _type(api, "TSTMAP")
        assert record.extras[BMS_EXTRAS_KEY]["symbolicMap"] == {
            "inputRecord": "TSTMAPI",
            "outputRecord": "TSTMAPO",
            "file": "TSTMAP.cpy",
        }
        amount = _field(api, "TSTMAP", "AMOUNT").extras[BMS_EXTRAS_KEY]["symbolic"]
        assert amount["entries"] == {"L": "AMOUNTL", "F": "AMOUNTF", "A": "AMOUNTA", "I": "AMOUNTI", "O": "AMOUNTO"}
        assert amount["outputPicture"] == "ZZZ,ZZ9.99-"
        assert _limits(api)["bms.symbolic_map_positions"] == 2

    def test_beside_its_mapset_names_each_field(self) -> None:
        adapter = _adapter()
        fileset = IntakeFileset.from_members({"TSTSET.bms": ENQUIRY, "TSTMAP.cpy": SYMBOLIC}, root="TSTSET.bms")
        api = adapter.normalize(adapter.parse_fileset(fileset))
        record = _type(api, "TSTSET.TSTMAP")
        assert record.extras[BMS_EXTRAS_KEY]["symbolicMap"]["inputRecord"] == "TSTMAPI"
        assert _field(api, "TSTSET.TSTMAP", "CUSTID").extras[BMS_EXTRAS_KEY]["symbolic"]["entries"]["I"] == "CUSTIDI"
        # RATE and NAME have no symbolic entries: the copybook is from another version of the mapset.
        assert _limits(api)["bms.symbolic_map_mismatch"] == 2

    def test_detected_over_the_copybook_adapter(self) -> None:
        payload = DetectionInput(text=SYMBOLIC, filename="TSTMAP.cpy")
        assert is_symbolic_map(SYMBOLIC)
        assert _adapter().detect(payload).confidence > CobolCopybookImportSource().detect(payload).confidence
        best = detect_import_source(payload)
        assert best is not None and best[0].key == "cics-bms"

    def test_ordinary_copybook_is_not_a_symbolic_map(self) -> None:
        copybook = "       01  CUSTOMER.\n           05  CUST-ID  PIC X(10).\n           05  CUST-AMT PIC 9(7)V99.\n"
        assert not is_symbolic_map(copybook)
        assert _code(copybook, "c.cpy") == "FORMAT_MISMATCH"


# ===========================================================================
# Refusals
# ===========================================================================


class TestRefusals:
    @pytest.mark.parametrize(
        ("text", "code"),
        [
            ("", "INPUT_EMPTY"),
            ("\x00" + ENQUIRY, "INPUT_ENCODING_INVALID"),
            ("DEFINE CLUSTER (NAME(A) INDEXED KEYS(1 0))", "FORMAT_MISMATCH"),
            # Trailing comma, no column-72 mark.
            (_mapset(_line("F", "DFHMDF", "POS=(1,2),LENGTH=3,")), "INPUT_MALFORMED"),
            # A continuation line written without the mark reads as an unknown operation.
            (_mapset(_line("F", "DFHMDF", "POS=(1,2),LENGTH=3"), _cont("COLOR=RED")), "INPUT_MALFORMED"),
            # The source ends on a continuation mark.
            (_line("S", "DFHMSD", "TYPE=MAP,", continued=True), "INPUT_TRUNCATED"),
            # The source ends inside a quoted value.
            (
                _line("S", "DFHMSD", "TYPE=MAP")
                + "\n"
                + _line("M", "DFHMDI", "SIZE=(24,80)")
                + "\n"
                + _line("F", "DFHMDF", "POS=(1,2),INITIAL='OPEN"),
                "INPUT_TRUNCATED",
            ),
            # A quoted value never closed before the next statement.
            (
                _mapset(_line("F", "DFHMDF", "POS=(1,2),INITIAL='OPEN"), _line("G", "DFHMDF", "POS=(3,2),LENGTH=1")),
                "INPUT_MALFORMED",
            ),
            # No DFHMSD TYPE=FINAL.
            (
                "\n".join(
                    [
                        _line("S", "DFHMSD", "TYPE=MAP"),
                        _line("M", "DFHMDI", "SIZE=(24,80)"),
                        _line("F", "DFHMDF", "POS=(1,2),LENGTH=3"),
                    ]
                ),
                "INPUT_TRUNCATED",
            ),
            (_line("M", "DFHMDI", "SIZE=(24,80)") + "\n" + _line("", "DFHMSD", "TYPE=FINAL"), "INPUT_MALFORMED"),
            (_line("S", "DFHMSD", "TYPE=MAP") + "\n" + _line("F", "DFHMDF", "POS=(1,2),LENGTH=3"), "INPUT_MALFORMED"),
            (_mapset(_line("F", "DFHMDF", "POS=(1,2),LENGTH=X")), "INPUT_MALFORMED"),
            (_mapset(_line("F", "DFHMDF", "POS=(1,2),LENGTH=3,ATTRB=(PROT")), "INPUT_MALFORMED"),
            (_mapset(_line("", "DFHMDF", "POS=(1,2),INITIAL='ONLY A LITERAL'")), "INPUT_SEMANTIC_INVALID"),
            (_mapset(_line("F", "DFHMDF", "LENGTH=3")), "INPUT_SEMANTIC_INVALID"),
            (_mapset(_line("F", "DFHMDF", "POS=(1,2)")), "INPUT_SEMANTIC_INVALID"),
            (
                _mapset(_line("F", "DFHMDF", "POS=(1,2),LENGTH=3"), _line("F", "DFHMDF", "POS=(3,2),LENGTH=3")),
                "INPUT_SEMANTIC_INVALID",
            ),
            (
                _mapset(_line("F", "DFHMDF", "POS=(1,2),LENGTH=10"), _line("G", "DFHMDF", "POS=(1,8),LENGTH=3")),
                "INPUT_SEMANTIC_INVALID",
            ),
            (_mapset(_line("F", "DFHMDF", "POS=(25,1),LENGTH=3")), "INPUT_SEMANTIC_INVALID"),
            (_mapset(_line("F", "DFHMDF", "POS=(24,79),LENGTH=5")), "INPUT_SEMANTIC_INVALID"),
            (
                "\n".join([_line("S", "DFHMSD", "TYPE=MAP"), _line("", "DFHMSD", "TYPE=FINAL")]),
                "INPUT_SEMANTIC_INVALID",
            ),
        ],
    )
    def test_codes(self, text: str, code: str) -> None:
        assert _code(text) == code

    def test_adjacent_fields_do_not_overlap(self) -> None:
        # The attribute byte sits at POS, the data after it: (6,22) length 2 ends at column 24.
        text = _mapset(
            _line("DD", "DFHMDF", "POS=(6,22),LENGTH=2"),
            _line("MM", "DFHMDF", "POS=(6,25),LENGTH=2"),
        )
        assert _code(text) is None


# ===========================================================================
# Detection and wiring
# ===========================================================================


class TestDetection:
    def test_macros(self) -> None:
        assert has_bms_macros(ENQUIRY)
        assert _adapter().detect(DetectionInput(text=ENQUIRY, filename="x.txt")).confidence >= 0.9

    def test_idcams_adapter_does_not_claim_bms(self) -> None:
        assert not VsamIdcamsImportSource().detect(DetectionInput(text=ENQUIRY, filename="x.bms")).matched

    def test_extension_alone_is_a_weak_claim(self) -> None:
        result = _adapter().detect(DetectionInput(text="hello", filename="x.bms"))
        assert result.matched and result.confidence < 0.6


class TestWiring:
    def test_registered(self) -> None:
        adapter = get_import_source("cics-bms")
        assert isinstance(adapter, CicsBmsImportSource)
        assert ".bms" in adapter.file_extensions

    def test_capability_seed_lists_every_limit(self) -> None:
        capability = capability_for("cics-bms")
        assert sorted(capability.canonical_projection.dropped_constructs) == sorted(BMS_LIMIT_DETAILS)

    def test_version_coverage(self) -> None:
        coverage = version_coverage_for("cics-bms")
        assert coverage.reads and not coverage.writes

    def test_schema_only_and_provenance_key(self) -> None:
        assert "cics-bms" in SCHEMA_ONLY_FORMATS
        assert BMS_EXTRAS_KEY in PROVENANCE_EXTRA_KEYS

    def test_ledger_rows(self) -> None:
        rows = {row.source_construct: row.coverage.value for row in _mainframe_misc_capability_rows(_import(ENQUIRY))}
        assert rows == {"bms.edited_picture": "partially-mapped", "bms.literal_field": "not-parsed-by-adapter"}

    def test_normalize_rejects_another_document(self) -> None:
        with pytest.raises(ImportSourceError):
            _adapter().normalize(object())
        assert parse_bms_text(ENQUIRY).mapsets[0].maps[0].name == "TSTMAP"


# ===========================================================================
# Corpus
# ===========================================================================


class TestCorpus:
    def test_order_entry_three_maps(self) -> None:
        path = EXAMPLES / "05-real-world-order-entry-mapset.bms"
        api = _import(path.read_text(encoding="utf-8"), path.name)
        assert sorted(t.key for t in api.types) == ["ORDRSET.ORDRCFM", "ORDRSET.ORDRDTL", "ORDRSET.ORDRHDR"]
        assert _type(api, "ORDRSET.ORDRCFM").extras[BMS_EXTRAS_KEY]["size"] == {"rows": 10, "columns": 60}
        assert _field(api, "ORDRSET.ORDRHDR", "HDELDT").type.name == "integer"
        assert _field(api, "ORDRSET.ORDRDTL", "DQTY").type.item.name == "decimal"  # type: ignore[union-attr]

    def test_stress_attributes(self) -> None:
        path = EXAMPLES / "04-stress-field-attributes.bms"
        api = _import(path.read_text(encoding="utf-8"), path.name)
        dark = _field(api, "STRSSET.STRSMAP1", "DARKFLD").extras[BMS_EXTRAS_KEY]["attributes"]
        assert dark["protection"] == "protected" and dark["intensity"] == "dark"
        assert _field(api, "STRSSET.STRSMAP1", "FSETFLD").extras[BMS_EXTRAS_KEY]["attributes"]["modifiedDataTag"]
        undr = _field(api, "STRSSET.STRSMAP1", "UNDRFLD").extras[BMS_EXTRAS_KEY]
        assert undr["validn"] == ["MUSTENTER", "MUSTFILL"] and undr["hilight"] == "UNDERLINE"

    def test_mapset_and_copybook_set(self) -> None:
        folder = EXAMPLES / "03-mapset-and-copybook-set"
        members = {path.name: path.read_text(encoding="utf-8") for path in folder.iterdir()}
        adapter = _adapter()
        api = adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root="ORDRSET.bms")))
        total = _field(api, "ORDRSET.ORDRMAP", "ORDTOT").extras[BMS_EXTRAS_KEY]["symbolic"]
        assert total["outputPicture"] == "Z,ZZZ,ZZ9.99"
        assert "bms.symbolic_map_mismatch" not in _limits(api)

    @pytest.mark.parametrize(
        ("name", "code"),
        [
            ("01-syntactic-missing-continuation.bms", "INPUT_MALFORMED"),
            ("02-semantic-map-without-fields.bms", "INPUT_SEMANTIC_INVALID"),
            ("03-truncated-mid-field.bms", "INPUT_TRUNCATED"),
            ("04-wrong-format-idcams.idcams", "FORMAT_MISMATCH"),
            ("06-semantic-overlapping-field-positions.bms", "INPUT_SEMANTIC_INVALID"),
        ],
    )
    def test_negatives(self, name: str, code: str) -> None:
        assert _code((EXAMPLES / "negative" / name).read_text(encoding="utf-8"), name) == code
