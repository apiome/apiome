"""IMS DBD and PSB import — FMT-11.2 (#5482).

Covers the macro-statement reader (labels, comments, column-72 continuations and their tolerated
departures), the DBD reader (PARENT hierarchy independent of file order, FIELD / LCHILD / XDFLD,
variable-length and logical segments, LOGICAL databases), the PSB reader (PCB / SENSEG / SENFLD,
PROCOPT decoding), filesets that resolve a PSB against its DBD, the canonical projection (nested
records, byte-accurate fields, the declared access profile, layout assumptions, declared limits),
every refusal's taxonomy code, detection, and the registry / ledger wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import pytest

from app.canonical_model import ApiParadigm, CanonicalApi, CanonicalField, Type, TypeKind
from app.data_contract_facts import SCHEMA_ONLY_FORMATS
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.format_version_coverage import version_coverage_for
from app.import_preview_manifest import PROVENANCE_EXTRA_KEYS, _ims_capability_rows
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.ims_import_source import ImsImportSource
from app.ims_normalizer import IMS_EXTRAS_KEY, IMS_LIMIT_DETAILS, LAYOUT_ASSUMPTIONS
from app.ims_parser import decode_procopt, has_ims_statements, parse_ims_text

load_builtin_import_sources()

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "ims"

#: Operands start in column 16; the continuation mark sits in column 72.
COL = " " * 9


def _stmt(operation: str, operands: str, *, label: str = "") -> str:
    """One statement line: label in column 1, operation in column 10, operands after it."""
    return f"{label:<9}{operation:<6}{operands}\n" if len(operation) < 6 else f"{label:<9}{operation} {operands}\n"


def _continued(first: str, rest: str) -> str:
    """A statement whose first line carries ``X`` in column 72 and a continuation in column 16."""
    return f"{first:<71}X\n{' ' * 15}{rest}\n"


DBD = (
    _stmt("DBD", "NAME=TESTDB,ACCESS=(HDAM,OSAM)")
    + _stmt("DATASET", "DD1=TESTDD,DEVICE=3390")
    + _stmt("SEGM", "NAME=ROOT,BYTES=40,PARENT=0")
    + _stmt("FIELD", "NAME=(ROOTKEY,SEQ,U),BYTES=8,START=1,TYPE=C")
    + _stmt("FIELD", "NAME=ROOTAMT,BYTES=5,START=9,TYPE=P")
    + _stmt("SEGM", "NAME=KID,BYTES=20,PARENT=ROOT")
    + _stmt("FIELD", "NAME=(KIDSEQ,SEQ,M),BYTES=4,START=1")
    + _stmt("DBDGEN", "")
    + _stmt("FINISH", "")
    + _stmt("END", "")
)

PSB = (
    _stmt("PCB", "TYPE=DB,DBDNAME=TESTDB,PROCOPT=G,KEYLEN=12")
    + _stmt("SENSEG", "NAME=ROOT,PARENT=0")
    + _stmt("SENFLD", "NAME=ROOTKEY,START=1")
    + _stmt("SENSEG", "NAME=KID,PARENT=ROOT,PROCOPT=AP")
    + _stmt("PSBGEN", "LANG=COBOL,PSBNAME=TESTPSB")
    + _stmt("END", "")
)


def _adapter() -> ImsImportSource:
    return ImsImportSource()


def _import(text: str, name: str = "test.dbd") -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse(text, source_label=name))


def _import_fileset(members: Dict[str, str], root: str) -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root=root)))


def _code(text: str, name: str = "test.dbd") -> Optional[str]:
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
    return {limit["construct"]: limit["count"] for limit in api.extras[IMS_EXTRAS_KEY]["capability_limits"]}


def _example(name: str) -> CanonicalApi:
    return _import((EXAMPLES / name).read_text(encoding="utf-8"), name)


# ===========================================================================
# Statement reader
# ===========================================================================


class TestStatements:
    def test_comments_labels_and_housekeeping_are_skipped(self) -> None:
        text = "* a comment\n" + _stmt("PRINT", "NOGEN") + DBD.replace("DBD   NAME", "DBD   NAME", 1)
        api = _import(text)
        assert {t.name for t in api.types} == {"TESTDB.ROOT", "TESTDB.KID"}

    def test_column_72_continuation_joins_operands(self) -> None:
        text = DBD.replace(
            _stmt("DBD", "NAME=TESTDB,ACCESS=(HDAM,OSAM)"),
            _continued(f"{COL}DBD   NAME=TESTDB,", "ACCESS=(HDAM,OSAM),RMNAME=(DFSHDC40,1,10)"),
        )
        document = parse_ims_text(text)
        assert document.dbds[0].access == ("HDAM", "OSAM")
        assert document.dbds[0].operands["RMNAME"] == ("DFSHDC40", "1", "10")

    def test_mark_one_column_late_is_still_a_mark(self) -> None:
        first = f"{COL}DBD   NAME=TESTDB,"
        late = f"{first:<72}X\n{' ' * 15}ACCESS=(HDAM,OSAM)\n"
        text = DBD.replace(_stmt("DBD", "NAME=TESTDB,ACCESS=(HDAM,OSAM)"), late)
        assert parse_ims_text(text).dbds[0].access == ("HDAM", "OSAM")

    def test_sequence_numbers_in_columns_73_to_80_are_not_a_mark(self) -> None:
        line = f"{COL}SEGM  NAME=ROOT,BYTES=40,PARENT=0"
        text = DBD.replace(_stmt("SEGM", "NAME=ROOT,BYTES=40,PARENT=0"), f"{line:<72}00000030\n")
        assert parse_ims_text(text).dbds[0].segments[0].max_bytes == 40

    def test_over_long_operand_is_one_line(self) -> None:
        operands = "NAME=ROOT,BYTES=40,PARENT=0,POINTER=(TWINBWD,LTWIN),COMPRTN=(XYZRTN,DATA)"
        line = f"{COL}SEGM  {operands}"
        assert len(line) > 72
        text = DBD.replace(_stmt("SEGM", "NAME=ROOT,BYTES=40,PARENT=0"), line + "\n")
        assert parse_ims_text(text).dbds[0].segments[0].operands["POINTER"] == ("TWINBWD", "LTWIN")

    def test_continuation_that_does_not_start_in_column_16_is_malformed(self) -> None:
        first = f"{COL}DBD   NAME=TESTDB,"
        text = DBD.replace(_stmt("DBD", "NAME=TESTDB,ACCESS=(HDAM,OSAM)"), f"{first:<71}X\n")
        assert _code(text) == "INPUT_MALFORMED"

    def test_source_ending_on_a_continuation_mark_is_truncated(self) -> None:
        first = f"{COL}DBD   NAME=TESTDB,"
        assert _code(f"{first:<71}X\n") == "INPUT_TRUNCATED"

    def test_trailing_comma_without_mark_is_malformed_mid_file(self) -> None:
        text = DBD.replace("ACCESS=(HDAM,OSAM)", "ACCESS=(HDAM,OSAM),")
        assert _code(text) == "INPUT_MALFORMED"

    def test_trailing_comma_at_the_end_is_truncated(self) -> None:
        assert _code(_stmt("DBD", "NAME=TESTDB,ACCESS=(HDAM,OSAM),")) == "INPUT_TRUNCATED"

    def test_operand_without_equals_is_malformed(self) -> None:
        assert _code(DBD.replace("TYPE=P", "TYPE")) == "INPUT_MALFORMED"

    def test_operand_written_twice_is_malformed(self) -> None:
        assert _code(DBD.replace("BYTES=5,", "BYTES=5,BYTES=6,")) == "INPUT_MALFORMED"

    def test_unbalanced_parentheses_are_malformed(self) -> None:
        assert _code(DBD.replace("ACCESS=(HDAM,OSAM)", "ACCESS=(HDAM,OSAM")) == "INPUT_MALFORMED"

    def test_deeply_nested_operand_is_malformed(self) -> None:
        deep = "(" * 2000 + "A" + ")" * 2000
        assert _code(DBD.replace("ACCESS=(HDAM,OSAM)", f"ACCESS={deep}")) == "INPUT_MALFORMED"

    def test_unknown_operation_is_malformed(self) -> None:
        assert _code(DBD.replace(_stmt("DATASET", "DD1=TESTDD,DEVICE=3390"), _stmt("DATSET", "DD1=X"))) == (
            "INPUT_MALFORMED"
        )


# ===========================================================================
# DBD reader
# ===========================================================================


class TestDbd:
    def test_hierarchy_comes_from_parent_not_file_order(self) -> None:
        child_first = (
            _stmt("DBD", "NAME=ORDERED,ACCESS=HIDAM")
            + _stmt("SEGM", "NAME=GRAND,BYTES=10,PARENT=KID")
            + _stmt("FIELD", "NAME=G1,BYTES=10,START=1")
            + _stmt("SEGM", "NAME=KID,BYTES=10,PARENT=ROOT")
            + _stmt("SEGM", "NAME=ROOT,BYTES=10")
            + _stmt("DBDGEN", "")
        )
        api = _import(child_first)
        levels = {row["segment"]: row["level"] for row in api.extras[IMS_EXTRAS_KEY]["dbds"][0]["hierarchy"]}
        assert levels == {"GRAND": 3, "KID": 2, "ROOT": 1}
        assert api.extras[IMS_EXTRAS_KEY]["dbds"][0]["root"] == "ROOT"
        kid = _field(api, "ims.ORDERED.ROOT", "KID")
        assert kid.type.item is not None and kid.type.item.name == "ims.ORDERED.KID"

    def test_dangling_parent_is_unresolved(self) -> None:
        assert _code(DBD.replace("PARENT=ROOT", "PARENT=NOWHERE")) == "INPUT_REFERENCE_UNRESOLVED"

    def test_two_roots_are_semantic(self) -> None:
        assert _code(DBD.replace("PARENT=ROOT", "PARENT=0")) == "INPUT_SEMANTIC_INVALID"

    def test_parent_cycle_is_semantic(self) -> None:
        text = DBD.replace(
            _stmt("DBDGEN", ""),
            _stmt("SEGM", "NAME=A,BYTES=4,PARENT=B") + _stmt("SEGM", "NAME=B,BYTES=4,PARENT=A") + _stmt("DBDGEN", ""),
        )
        assert _code(text) == "INPUT_SEMANTIC_INVALID"

    def test_no_segments_is_semantic(self) -> None:
        text = _stmt("DBD", "NAME=EMPTY,ACCESS=HDAM") + _stmt("DBDGEN", "")
        assert _code(text) == "INPUT_SEMANTIC_INVALID"

    def test_duplicate_segment_and_field_names_are_semantic(self) -> None:
        assert _code(DBD.replace("NAME=KID,", "NAME=ROOT,").replace("PARENT=ROOT", "PARENT=0")) == (
            "INPUT_SEMANTIC_INVALID"
        )
        assert _code(DBD.replace("NAME=ROOTAMT", "NAME=ROOTKEY")) == "INPUT_SEMANTIC_INVALID"

    def test_field_past_the_segment_is_semantic(self) -> None:
        assert _code(DBD.replace("BYTES=5,START=9", "BYTES=5,START=37")) == "INPUT_SEMANTIC_INVALID"

    def test_unknown_field_type_is_semantic(self) -> None:
        assert _code(DBD.replace("TYPE=P", "TYPE=Q")) == "INPUT_SEMANTIC_INVALID"

    def test_two_sequence_fields_are_semantic(self) -> None:
        assert _code(DBD.replace("NAME=ROOTAMT", "NAME=(ROOTAMT,SEQ,U)")) == "INPUT_SEMANTIC_INVALID"

    def test_non_numeric_bytes_is_malformed(self) -> None:
        assert _code(DBD.replace("BYTES=40", "BYTES=FORTY")) == "INPUT_MALFORMED"

    def test_field_before_any_segment_is_malformed(self) -> None:
        text = _stmt("DBD", "NAME=X,ACCESS=HDAM") + _stmt("FIELD", "NAME=F,BYTES=1,START=1") + DBD.split("\n", 1)[1]
        assert _code(text) == "INPUT_MALFORMED"

    def test_missing_dbdgen_is_truncated(self) -> None:
        assert _code(DBD.split(_stmt("DBDGEN", ""))[0]) == "INPUT_TRUNCATED"

    def test_variable_length_minimum_above_maximum_is_semantic(self) -> None:
        assert _code(DBD.replace("BYTES=20,PARENT=ROOT", "BYTES=(20,40),PARENT=ROOT")) == "INPUT_SEMANTIC_INVALID"

    def test_xdfld_rules(self) -> None:
        index = _stmt("LCHILD", "NAME=(IXSEG,IXDBD),POINTER=INDX")
        good = _stmt("XDFLD", "NAME=XAMT,SRCH=(ROOTAMT),SUBSEQ=(ROOTKEY)")
        anchor = _stmt("SEGM", "NAME=KID,BYTES=20,PARENT=ROOT")
        assert _code(DBD.replace(anchor, index + good + anchor)) is None
        assert _code(DBD.replace(anchor, good + anchor)) == "INPUT_MALFORMED"
        unknown_field = _stmt("XDFLD", "NAME=XAMT,SRCH=(NOPE)")
        assert _code(DBD.replace(anchor, index + unknown_field + anchor)) == "INPUT_REFERENCE_UNRESOLVED"
        unknown_segment = _stmt("XDFLD", "NAME=XAMT,SEGMENT=NOPE,SRCH=(ROOTAMT)")
        assert _code(DBD.replace(anchor, index + unknown_segment + anchor)) == "INPUT_REFERENCE_UNRESOLVED"

    def test_logical_segment_needs_a_source(self) -> None:
        text = _stmt("DBD", "NAME=LDB,ACCESS=LOGICAL") + _stmt("SEGM", "NAME=L1,PARENT=0") + _stmt("DBDGEN", "")
        assert _code(text) == "INPUT_SEMANTIC_INVALID"


# ===========================================================================
# PSB reader
# ===========================================================================


class TestPsb:
    def test_reads_pcbs_sensegs_and_senflds(self) -> None:
        psb = parse_ims_text(PSB, label="TESTPSB.psb").psbs[0]
        assert psb.name == "TESTPSB" and psb.language == "COBOL"
        pcb = psb.pcbs[0]
        assert (pcb.name, pcb.dbd_name, pcb.procopt, pcb.key_length) == ("PCB1", "TESTDB", "G", 12)
        assert [s.name for s in pcb.sensegs] == ["ROOT", "KID"]
        assert pcb.sensegs[0].fields[0].name == "ROOTKEY"
        assert pcb.sensegs[1].procopt == "AP"

    def test_psbname_defaults_to_the_file_stem(self) -> None:
        text = PSB.replace("LANG=COBOL,PSBNAME=TESTPSB", "LANG=PLI")
        assert parse_ims_text(text, label="dir/payroll.psb").psbs[0].name == "PAYROLL"

    def test_label_names_the_pcb(self) -> None:
        text = PSB.replace(
            _stmt("PCB", "TYPE=DB,DBDNAME=TESTDB,PROCOPT=G,KEYLEN=12"),
            _stmt("PCB", "TYPE=DB,DBDNAME=TESTDB", label="CUSTPCB"),
        )
        assert parse_ims_text(text).psbs[0].pcbs[0].name == "CUSTPCB"

    @pytest.mark.parametrize(
        ("change", "code"),
        [
            # SENSEG outside a PCB.
            (lambda t: _stmt("SENSEG", "NAME=ROOT,PARENT=0") + t, "INPUT_MALFORMED"),
            # A database PCB with no DBDNAME.
            (lambda t: t.replace("DBDNAME=TESTDB,", ""), "INPUT_MALFORMED"),
            # SENFLD before any SENSEG.
            (
                lambda t: t.replace(_stmt("SENSEG", "NAME=ROOT,PARENT=0"), _stmt("SENFLD", "NAME=X,START=1")),
                "INPUT_MALFORMED",
            ),
            # A SENSEG whose parent the PCB is not sensitive to.
            (lambda t: t.replace("PARENT=ROOT", "PARENT=GHOST"), "INPUT_REFERENCE_UNRESOLVED"),
            # Two root SENSEGs.
            (lambda t: t.replace("PARENT=ROOT", "PARENT=0"), "INPUT_SEMANTIC_INVALID"),
            # No PSBGEN.
            (lambda t: t.split(_stmt("PSBGEN", "LANG=COBOL,PSBNAME=TESTPSB"))[0], "INPUT_TRUNCATED"),
            # A DBD statement inside an open PSB.
            (
                lambda t: t.replace(_stmt("PSBGEN", "LANG=COBOL,PSBNAME=TESTPSB"), _stmt("SEGM", "NAME=X,BYTES=1")),
                "INPUT_MALFORMED",
            ),
        ],
    )
    def test_refusals(self, change, code: str) -> None:  # type: ignore[no-untyped-def]
        assert _code(change(PSB), "test.psb") == code

    def test_tp_pcb_cannot_hold_sensitive_segments(self) -> None:
        text = _stmt("PCB", "TYPE=TP,MODIFY=YES") + _stmt("SENSEG", "NAME=ROOT,PARENT=0") + _stmt("PSBGEN", "PSBNAME=X")
        assert _code(text, "x.psb") == "INPUT_MALFORMED"

    def test_database_pcb_without_sensegs_is_semantic(self) -> None:
        text = _stmt("PCB", "TYPE=DB,DBDNAME=TESTDB") + _stmt("PSBGEN", "PSBNAME=X")
        assert _code(text, "x.psb") == "INPUT_SEMANTIC_INVALID"

    def test_decode_procopt(self) -> None:
        everything = decode_procopt("A")
        assert all(everything[k] for k in ("get", "insert", "replace", "delete")) and not everything["path"]
        get_insert_path = decode_procopt("GIP")
        assert get_insert_path["intents"] == ["get", "insert", "path"]
        assert get_insert_path["replace"] is False
        assert decode_procopt("LS")["insert"] is True
        assert decode_procopt("GQ")["unrecognised"] == ["Q"]
        assert "unrecognised" not in decode_procopt("G")


# ===========================================================================
# Filesets
# ===========================================================================


class TestFileset:
    def test_psb_resolves_against_its_dbd(self) -> None:
        api = _import_fileset({"TESTDB.dbd": DBD, "TESTPSB.psb": PSB}, root="TESTDB.dbd")
        view = _field(api, "ims.TESTPSB.PCB1.ROOT", "ROOTKEY")
        assert view.type.name == "string" and view.constraints is not None and view.constraints.max_length == 8
        assert view.extras[IMS_EXTRAS_KEY]["segmentStart"] == 1
        # A SENSEG with no SENFLD sees every field, typed from the DBD.
        assert [f.name for f in _type(api, "ims.TESTPSB.PCB1.KID").fields] == ["KIDSEQ"]
        access = _type(api, "ims.TESTDB.KID").extras[IMS_EXTRAS_KEY]["access"]
        assert access == [
            {"psb": "TESTPSB", "pcb": "PCB1", "procopt": decode_procopt("AP"), "fields": "all"},
        ]
        assert "ims.unresolved_dbd" not in _limits(api)
        assert api.extras[IMS_EXTRAS_KEY]["psbs"][0]["pcbs"][0]["dbdResolved"] is True

    def test_unknown_senseg_or_senfld_is_unresolved(self) -> None:
        assert _fileset_code({"a.dbd": DBD, "b.psb": PSB.replace("NAME=KID,", "NAME=GHOST,")}, root="a.dbd") == (
            "INPUT_REFERENCE_UNRESOLVED"
        )
        assert _fileset_code({"a.dbd": DBD, "b.psb": PSB.replace("NAME=ROOTKEY,", "NAME=GHOST,")}, root="a.dbd") == (
            "INPUT_REFERENCE_UNRESOLVED"
        )

    def test_senseg_parent_contradicting_the_dbd_is_semantic(self) -> None:
        dbd = DBD.replace(_stmt("DBDGEN", ""), _stmt("SEGM", "NAME=OTHER,BYTES=4,PARENT=ROOT") + _stmt("DBDGEN", ""))
        psb = PSB.replace(
            _stmt("PSBGEN", "LANG=COBOL,PSBNAME=TESTPSB"),
            _stmt("SENSEG", "NAME=OTHER,PARENT=KID") + _stmt("PSBGEN", "LANG=COBOL,PSBNAME=TESTPSB"),
        )
        assert _fileset_code({"a.dbd": dbd, "b.psb": psb}, root="a.dbd") == "INPUT_SEMANTIC_INVALID"

    def test_duplicate_dbd_across_members_is_semantic(self) -> None:
        assert _fileset_code({"a.dbd": DBD, "b.dbd": DBD}, root="a.dbd") == "INPUT_SEMANTIC_INVALID"

    def test_non_ims_root_is_a_format_mismatch_and_other_members_are_skipped(self) -> None:
        assert _fileset_code({"a.txt": "hello\n", "b.dbd": DBD}, root="a.txt") == "FORMAT_MISMATCH"
        api = _import_fileset({"a.dbd": DBD, "notes.md": "not read"}, root="a.dbd")
        assert api.extras[IMS_EXTRAS_KEY]["files"] == ["a.dbd"]

    def test_logical_database_names_resolved_source_records(self) -> None:
        members = {
            name: (EXAMPLES / name).read_text(encoding="utf-8")
            for name in (
                "02-typical-hdam-dbd.dbd",
                "04-stress-secondary-indexes.dbd",
                "07-composition-logical-database.dbd",
            )
        }
        api = _import_fileset(members, root="07-composition-logical-database.dbd")
        sources = _type(api, "ims.CUSTORDL.LORDER").extras[IMS_EXTRAS_KEY]["sources"]
        assert [s["type"] for s in sources] == ["ims.CUSTDB.ORDER", "ims.ORDERDB.ORDER"]
        logical_parent = _type(api, "ims.ORDERDB.CUSTLINK").extras[IMS_EXTRAS_KEY]["logicalParent"]
        assert logical_parent == {
            "segment": "CUSTOMER",
            "storage": "PHYSICAL",
            "dbd": "CUSTDB",
            "type": "ims.CUSTDB.CUSTOMER",
        }


# ===========================================================================
# Projection
# ===========================================================================


class TestProjection:
    def test_document_shape(self) -> None:
        api = _import(DBD)
        assert api.paradigm is ApiParadigm.DATA_SCHEMA and api.format == "ims"
        assert api.identity.name == "TESTDB" and api.identity.namespace == "ims"
        assert all(t.kind is TypeKind.RECORD and t.namespace == "ims" for t in api.types)
        assert api.extras[IMS_EXTRAS_KEY]["layoutAssumptions"] == list(LAYOUT_ASSUMPTIONS)
        assert api.raw is not None and api.raw["files"][0]["path"] == "test.dbd"
        assert _adapter().normalize(_adapter().parse(DBD), include_raw=False).raw is None

    def test_field_types_offsets_and_sequence(self) -> None:
        text = DBD.replace(
            _stmt("SEGM", "NAME=KID,BYTES=20,PARENT=ROOT"),
            _stmt("FIELD", "NAME=ROOTHEX,BYTES=2,START=14,TYPE=X")
            + _stmt("FIELD", "NAME=ROOTH,BYTES=2,START=16,TYPE=H")
            + _stmt("FIELD", "NAME=ROOTF,BYTES=4,START=18,TYPE=F")
            + _stmt("FIELD", "NAME=ROOTZ,BYTES=3,START=22,TYPE=Z")
            + _stmt("SEGM", "NAME=KID,BYTES=20,PARENT=ROOT"),
        )
        api = _import(text)
        key = _field(api, "ims.TESTDB.ROOT", "ROOTKEY")
        assert key.type.name == "string" and key.constraints is not None and key.constraints.max_length == 8
        assert key.extras[IMS_EXTRAS_KEY]["sequence"] == {"unique": True}
        assert (key.extras[IMS_EXTRAS_KEY]["offset"], key.extras[IMS_EXTRAS_KEY]["start"]) == (0, 1)
        amount = _field(api, "ims.TESTDB.ROOT", "ROOTAMT")
        assert amount.type.name == "decimal" and amount.extras[IMS_EXTRAS_KEY]["digits"] == 9
        assert amount.extras[IMS_EXTRAS_KEY]["offset"] == 8
        hexa = _field(api, "ims.TESTDB.ROOT", "ROOTHEX")
        assert hexa.type.name == "bytes" and hexa.constraints is not None
        assert (hexa.constraints.min_length, hexa.constraints.max_length) == (2, 2)
        assert _field(api, "ims.TESTDB.ROOT", "ROOTH").type.name == "integer"
        assert _field(api, "ims.TESTDB.ROOT", "ROOTF").type.name == "integer"
        assert _field(api, "ims.TESTDB.ROOT", "ROOTZ").extras[IMS_EXTRAS_KEY]["digits"] == 3
        non_unique = _field(api, "ims.TESTDB.KID", "KIDSEQ")
        assert non_unique.extras[IMS_EXTRAS_KEY]["sequence"] == {"unique": False}
        assert non_unique.extras[IMS_EXTRAS_KEY]["type"] == "C"  # the TYPE default

    def test_parent_holds_a_list_per_child_segment(self) -> None:
        api = _import(DBD)
        kid = _field(api, "ims.TESTDB.ROOT", "KID")
        assert kid.type.item is not None and kid.type.item.name == "ims.TESTDB.KID"
        assert kid.extras[IMS_EXTRAS_KEY] == {"role": "child-segment", "segment": "ims.TESTDB.KID"}

    def test_child_name_clash_gets_a_suffix(self) -> None:
        api = _import(DBD.replace("NAME=ROOTAMT", "NAME=KID"))
        names = [f.name for f in _type(api, "ims.TESTDB.ROOT").fields]
        assert "KID" in names and "KID_SEGMENTS" in names

    def test_undescribed_bytes_are_a_partial_limit(self) -> None:
        api = _import(DBD)
        root = _type(api, "ims.TESTDB.ROOT").extras[IMS_EXTRAS_KEY]
        assert root["undescribed"] == [{"start": 14, "end": 40}]
        assert root["sequenceField"] == "ROOTKEY" and root["level"] == 1 and root["root"] is True
        assert _limits(api)["ims.segment_layout"] == 2

    def test_overlapping_fields_name_each_other(self) -> None:
        api = _import(DBD.replace("BYTES=5,START=9", "BYTES=5,START=6"))
        assert _field(api, "ims.TESTDB.ROOT", "ROOTAMT").extras[IMS_EXTRAS_KEY]["overlaps"] == ["ROOTKEY"]
        assert _field(api, "ims.TESTDB.ROOT", "ROOTKEY").extras[IMS_EXTRAS_KEY]["overlaps"] == ["ROOTAMT"]
        assert _limits(api)["ims.overlapping_fields"] == 1

    def test_variable_length_and_system_fields(self) -> None:
        text = DBD.replace("BYTES=20,PARENT=ROOT", "BYTES=(20,6),PARENT=ROOT").replace(
            _stmt("DBDGEN", ""), _stmt("FIELD", "NAME=/SX1") + _stmt("DBDGEN", "")
        )
        api = _import(text)
        kid = _type(api, "ims.TESTDB.KID")
        assert kid.extras[IMS_EXTRAS_KEY]["variableLength"] == {"maximum": 20, "minimum": 6}
        assert kid.extras[IMS_EXTRAS_KEY]["systemFields"] == [{"name": "/SX1"}]
        assert [f.name for f in kid.fields] == ["KIDSEQ"]
        assert _limits(api)["ims.variable_length_segment"] == 1
        assert _limits(api)["ims.system_related_field"] == 1

    def test_psb_alone_keeps_its_program_view_by_name(self) -> None:
        api = _import(PSB + "", "TESTPSB.psb")
        root = _type(api, "ims.TESTPSB.PCB1.ROOT")
        assert root.extras[IMS_EXTRAS_KEY]["procopt"]["code"] == "G"
        assert root.extras[IMS_EXTRAS_KEY]["procoptSource"] == "pcb"
        assert root.extras[IMS_EXTRAS_KEY]["dbdResolved"] is False
        rootkey = _field(api, "ims.TESTPSB.PCB1.ROOT", "ROOTKEY")
        assert rootkey.type.name == "bytes" and rootkey.extras[IMS_EXTRAS_KEY]["offset"] == 0
        kid = _type(api, "ims.TESTPSB.PCB1.KID").extras[IMS_EXTRAS_KEY]
        assert kid["procopt"]["replace"] is True and kid["procopt"]["path"] is True
        assert kid["procoptSource"] == "senseg"
        assert _limits(api) == {"ims.unresolved_dbd": 1}

    def test_tp_pcb_is_listed_not_modelled(self) -> None:
        text = PSB.replace(
            _stmt("PSBGEN", "LANG=COBOL,PSBNAME=TESTPSB"),
            _stmt("PCB", "TYPE=TP,MODIFY=YES") + _stmt("PSBGEN", "LANG=COBOL,PSBNAME=TESTPSB"),
        )
        api = _import(text, "x.psb")
        pcbs = api.extras[IMS_EXTRAS_KEY]["psbs"][0]["pcbs"]
        assert [(p["name"], p["type"]) for p in pcbs] == [("PCB1", "DB"), ("PCB2", "TP")]
        assert _limits(api)["ims.non_database_pcb"] == 1


# ===========================================================================
# Detection
# ===========================================================================


class TestDetection:
    def test_dbd_and_psb_are_claimed(self) -> None:
        assert _adapter().detect(DetectionInput(text=DBD)).confidence == 0.95
        assert _adapter().detect(DetectionInput(text=PSB)).confidence == 0.95
        opening_only = _stmt("DBD", "NAME=X,ACCESS=HDAM") + _stmt("DBDGEN", "")
        assert _adapter().detect(DetectionInput(text=opening_only)).confidence == 0.9

    def test_suffix_alone_is_weak_and_other_text_is_not_claimed(self) -> None:
        assert _adapter().detect(DetectionInput(text="garbage", filename="x.dbd")).confidence == 0.5
        copybook = (EXAMPLES / "negative" / "04-wrong-format-cobol-copybook.cpy").read_text(encoding="utf-8")
        assert _adapter().detect(DetectionInput(text=copybook)).confidence == 0.0
        bms = _stmt("DFHMSD", "TYPE=MAP,LANG=COBOL", label="CUSTSET")
        assert _adapter().detect(DetectionInput(text=bms)).confidence == 0.0
        assert _adapter().detect(DetectionInput(data=b"\x00")).confidence == 0.0

    def test_has_ims_statements(self) -> None:
        assert has_ims_statements(DBD) == (True, True)
        assert has_ims_statements("DBD NAME=X") == (False, False)


# ===========================================================================
# Registry wiring
# ===========================================================================


class TestRegistry:
    def test_adapter_is_registered(self) -> None:
        adapter = get_import_source("ims")
        assert isinstance(adapter, ImsImportSource)
        assert adapter.paradigm is ApiParadigm.DATA_SCHEMA

    def test_capability_seed_lists_every_limit(self) -> None:
        capability = capability_for("ims")
        assert sorted(capability.canonical_projection.dropped_constructs) == sorted(IMS_LIMIT_DETAILS)

    def test_version_coverage(self) -> None:
        coverage = version_coverage_for("ims")
        assert coverage.reads and not coverage.writes

    def test_schema_only_and_provenance_key(self) -> None:
        assert "ims" in SCHEMA_ONLY_FORMATS
        assert IMS_EXTRAS_KEY in PROVENANCE_EXTRA_KEYS

    def test_ledger_rows(self) -> None:
        text = DBD.replace(
            _stmt("SEGM", "NAME=KID,BYTES=20,PARENT=ROOT"),
            _stmt("LCHILD", "NAME=(IXSEG,IXDBD),POINTER=INDX") + _stmt("SEGM", "NAME=KID,BYTES=20,PARENT=ROOT"),
        )
        rows = {row.source_construct: row.coverage.value for row in _ims_capability_rows(_import(text))}
        assert rows == {"ims.index_database": "not-parsed-by-adapter", "ims.segment_layout": "partially-mapped"}

    def test_normalize_rejects_a_foreign_document(self) -> None:
        with pytest.raises(ImportSourceError):
            _adapter().normalize(object())

    def test_empty_and_encoding(self) -> None:
        assert _code("   \n") == "INPUT_EMPTY"
        assert _code("﻿" + DBD) == "INPUT_ENCODING_INVALID"


# ===========================================================================
# Corpus
# ===========================================================================


class TestCorpus:
    def test_hdam_dbd(self) -> None:
        api = _example("02-typical-hdam-dbd.dbd")
        dbd = api.extras[IMS_EXTRAS_KEY]["dbds"][0]
        assert dbd["access"] == ["HDAM", "OSAM"]
        assert dbd["operands"]["rmname"] == ["DFSHDC40", "10", "500", "824"]
        assert [f.name for f in _type(api, "ims.CUSTDB.CUSTOMER").fields if f.type.item] == ["ADDRESS", "ORDER"]

    def test_secondary_indexes(self) -> None:
        api = _example("04-stress-secondary-indexes.dbd")
        order = _type(api, "ims.ORDERDB.ORDER").extras[IMS_EXTRAS_KEY]
        assert [lc["kind"] for lc in order["lchildren"]] == ["index", "index"]
        assert order["secondaryIndexes"] == [
            {
                "name": "XCUSTDT",
                "indexSegment": "CUSTDATE",
                "indexDbd": "ORDXDB2",
                "sourceSegment": "ORDER",
                "search": ["ORDCUST", "ORDDATE"],
                "subsequence": ["ORDERID"],
                "duplicateData": ["ORDSTAT"],
                "nullValue": "BLANK",
            }
        ]
        # The root SEGM's operand runs into column 73: an over-long line, not a continuation.
        assert order["operands"]["pointer"] == ["TWINBWD", "LTWIN"]
        assert _limits(api)["ims.secondary_index_field"] == 1

    def test_four_level_hierarchy(self) -> None:
        api = _example("05-real-world-policy-dbd.dbd")
        levels = {row["segment"]: row["level"] for row in api.extras[IMS_EXTRAS_KEY]["dbds"][0]["hierarchy"]}
        assert levels == {"POLICY": 1, "INSURED": 2, "COVERAGE": 2, "CLAIM": 3, "CLMNOTE": 4}

    def test_psb_access_profile(self) -> None:
        api = _example("06-typical-psb.psb")
        pcbs = api.extras[IMS_EXTRAS_KEY]["psbs"][0]["pcbs"]
        assert [p.get("procopt", {}).get("code") for p in pcbs] == ["G", "AP", None]
        assert pcbs[0]["processingSequence"] == "CUSTIDX"
        note = _type(api, "ims.CUSTINQ.PCB2.ORDNOTE").extras[IMS_EXTRAS_KEY]["procopt"]
        assert note["intents"] == ["get", "insert"]

    def test_logical_database_alone(self) -> None:
        api = _example("07-composition-logical-database.dbd")
        assert _limits(api)["ims.logical_database"] == 5
        sources = _type(api, "ims.CUSTORDL.LORDER").extras[IMS_EXTRAS_KEY]["sources"]
        assert sources == [
            {"segment": "ORDER", "mode": "DATA", "dbd": "CUSTDB"},
            {"segment": "ORDER", "mode": "DATA", "dbd": "ORDERDB"},
        ]

    @pytest.mark.parametrize(
        ("name", "code"),
        [
            ("01-syntactic-unterminated-continuation.dbd", "INPUT_MALFORMED"),
            ("02-semantic-no-segments.dbd", "INPUT_SEMANTIC_INVALID"),
            ("03-truncated-mid-field.dbd", "INPUT_TRUNCATED"),
            ("04-wrong-format-cobol-copybook.cpy", "FORMAT_MISMATCH"),
            ("06-unresolvable-parent-reference.dbd", "INPUT_REFERENCE_UNRESOLVED"),
        ],
    )
    def test_negatives(self, name: str, code: str) -> None:
        assert _code((EXAMPLES / "negative" / name).read_text(encoding="utf-8"), name) == code
