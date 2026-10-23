"""PL/I ``%INCLUDE`` structure import — FMT-11.1 (#5480).

Covers the reader (comments, strings, margins, labels, factored names, attributes and the language
defaults), ``%INCLUDE`` resolution across a fileset and the three outcomes of a missing member,
``LIKE`` expansion, the storage layout (alignment padding, packed bits, UNION overlays, arrays,
runtime extents, unsized items) and its stated assumptions, the canonical projection and the native
analysis, every refusal's taxonomy code, detection, and the registry / ledger wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import pytest

from app.canonical_model import ApiParadigm, CanonicalApi, CanonicalField, Type, TypeKind
from app.cobolcopybook_import_source import CobolCopybookImportSource
from app.data_contract_facts import SCHEMA_ONLY_FORMATS
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.format_version_coverage import version_coverage_for
from app.import_preview_manifest import PROVENANCE_EXTRA_KEYS, _pli_capability_rows
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    get_import_source,
    load_builtin_import_sources,
)
from app.pli_analysis import WARNING_INCLUDE_UNRESOLVED, WARNING_LAYOUT_ASSUMPTIONS
from app.pli_import_source import PliImportSource
from app.pli_layout import LAYOUT_ASSUMPTIONS, ItemLayout, compute_layout, picture_info
from app.pli_normalizer import PLI_EXTRAS_KEY, PLI_LIMIT_DETAILS, PLI_PARTIAL_LIMITS
from app.pli_parser import PliDocument, PliItem, has_pli_declarations, parse_pli_fileset, parse_pli_text

load_builtin_import_sources()

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "pli"


def _adapter() -> PliImportSource:
    return PliImportSource()


def _parse(text: str, name: str = "test.pli") -> PliDocument:
    return parse_pli_text(text, label=name)


def _import(text: str, name: str = "test.pli") -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse(text, source_label=name))


def _fileset(members: Dict[str, str], root: str) -> IntakeFileset:
    return IntakeFileset.from_members(members, root=root)


def _import_set(members: Dict[str, str], root: str) -> CanonicalApi:
    adapter = _adapter()
    return adapter.normalize(adapter.parse_fileset(_fileset(members, root)))


def _code(text: str, name: str = "test.pli") -> str:
    with pytest.raises(ImportSourceError) as caught:
        _adapter().parse(text, source_label=name)
    return caught.value.code or ""


def _type(api: CanonicalApi, name: str) -> Type:
    return next(t for t in api.types if t.name == name)


def _field(api: CanonicalApi, type_name: str, field_name: str) -> CanonicalField:
    return next(f for f in _type(api, type_name).fields if f.name == field_name)


def _pli(entity: object) -> Dict[str, object]:
    return entity.extras[PLI_EXTRAS_KEY]  # type: ignore[attr-defined]


def _limits(api: CanonicalApi) -> Dict[str, int]:
    return {limit["construct"]: limit["count"] for limit in api.extras[PLI_EXTRAS_KEY]["capability_limits"]}


def _layout(text: str, structure: int = 0) -> Dict[str, ItemLayout]:
    """``dotted path → layout`` of one structure (first occurrence of each path)."""
    root = _parse(text).structures[structure]
    layouts = compute_layout(root)
    out: Dict[str, ItemLayout] = {}

    def visit(item: PliItem, path: str) -> None:
        out.setdefault(path, layouts[id(item)])
        for child in item.children:
            visit(child, f"{path}.{child.name}")

    visit(root, root.name)
    return out


# ===========================================================================
# Reader
# ===========================================================================


class TestReader:
    def test_minimal_structure(self) -> None:
        document = _parse(" DCL 1 REC,\n       2 ID CHAR(16),\n       2 AT FIXED BIN(63);")
        (rec,) = document.structures
        assert [c.name for c in rec.children] == ["ID", "AT"]
        assert rec.children[0].data is not None and rec.children[0].data.length == 16
        assert rec.children[1].line == 3

    def test_comments_strings_and_labels_are_skipped(self) -> None:
        text = (
            "/* header ; with a semicolon */\n"
            "L1: DECLARE 1 REC, /* member */ 2 A CHAR(3) INIT('a;''b'), 2 B BIT(4) INIT('1010'B);"
        )
        (rec,) = _parse(text).structures
        assert [c.name for c in rec.children] == ["A", "B"]

    def test_sequence_numbers_in_columns_73_to_80_are_cut(self) -> None:
        lines = [" DCL 1 REC,", "       2 A CHAR(4),", "       2 B CHAR(2);"]
        text = "\n".join(f"{line:<72}{index:08d}" for index, line in enumerate(lines, start=1))
        (rec,) = _parse(text).structures
        assert [c.name for c in rec.children] == ["A", "B"]

    def test_process_lines_and_listing_directives_are_dropped(self) -> None:
        document = _parse("*PROCESS RULES(IBM);\n%PAGE;\n%SKIP(2);\n DCL 1 REC, 2 A CHAR(1);")
        assert document.structures[0].name == "REC" and not document.statements

    def test_level_numbers_need_not_be_consecutive(self) -> None:
        (rec,) = _parse("DCL 1 REC, 3 GRP, 7 A CHAR(1), 5 B CHAR(1), 3 C CHAR(1);").structures
        grp = rec.children[0]
        assert [c.name for c in grp.children] == ["A", "B"]
        assert [c.name for c in rec.children] == ["GRP", "C"]

    def test_factored_names_and_dim_attribute(self) -> None:
        (rec,) = _parse("DCL 1 REC, 2 (A, B) FIXED BIN(31), 2 T CHAR(2) DIM(1:4);").structures
        assert [c.name for c in rec.children] == ["A", "B", "T"]
        assert rec.children[2].dimensions[0].count == 4

    def test_scalars_and_statements_are_kept_aside(self) -> None:
        document = _parse("DCL P POINTER; DCL 1 REC BASED(P), 2 A CHAR(1), N FIXED BIN(31); X = 1;")
        assert [s.name for s in document.scalars] == ["P", "N"]
        assert document.structures[0].storage_class == "BASED" and document.structures[0].locator == "P"
        assert [s.keyword for s in document.statements] == ["X"]

    def test_level_one_without_members_is_a_scalar(self) -> None:
        document = _parse("DCL 1 FLAG BIT(1); DCL 1 REC, 2 A CHAR(1);")
        assert [s.name for s in document.scalars] == ["FLAG"]

    def test_unknown_attribute_is_kept_unread(self) -> None:
        (rec,) = _parse("DCL 1 REC, 2 A CHAR(4) WIBBLE(3) NONASSIGNABLE;").structures
        assert rec.children[0].unread == ["WIBBLE(3)"]

    def test_storage_class_scope_and_defined(self) -> None:
        document = _parse("DCL 1 REC STATIC EXTERNAL, 2 A CHAR(8), 2 B CHAR(2) DEFINED A POSITION(3);")
        rec = document.structures[0]
        assert (rec.storage_class, rec.scope) == ("STATIC", "EXTERNAL")
        assert (rec.children[1].defined, rec.children[1].position) == ("A", 3)


class TestDefaults:
    @pytest.mark.parametrize(
        ("attributes", "kind", "precision", "defaulted"),
        [
            ("", "fixed-binary", 15, ("all",)),  # name I..N
            ("FIXED", "fixed-decimal", 5, ("base", "precision")),
            ("BIN", "float-binary", 21, ("scale", "precision")),
            ("DEC(7,2)", "float-decimal", 7, ("scale",)),
            ("FLOAT", "float-decimal", 6, ("base", "precision")),
        ],
    )
    def test_arithmetic_defaults(self, attributes: str, kind: str, precision: int, defaulted: tuple) -> None:
        (rec,) = _parse(f"DCL 1 REC, 2 KOUNT {attributes};").structures
        data = rec.children[0].data
        assert data is not None
        assert (data.kind, data.precision, data.defaulted) == (kind, precision, defaulted)

    def test_name_outside_i_to_n_defaults_to_float_decimal(self) -> None:
        (rec,) = _parse("DCL 1 REC, 2 AMOUNT;").structures
        assert rec.children[0].data is not None and rec.children[0].data.kind == "float-decimal"

    def test_string_length_defaults_to_one(self) -> None:
        (rec,) = _parse("DCL 1 REC, 2 C CHAR, 2 B BIT;").structures
        assert [c.data.length for c in rec.children if c.data] == [1, 1]


# ===========================================================================
# Pictures and layout
# ===========================================================================


class TestPictures:
    @pytest.mark.parametrize(
        ("picture", "positions", "digits", "decimals", "edited", "character"),
        [
            ("999V99", 5, 5, 2, False, False),
            ("(5)9V(2)9", 7, 7, 2, False, False),
            ("S9(7)V99", 10, 9, 2, False, False),  # COBOL-style factors accepted; S is a position
            ("ZZZ,ZZ9.99", 10, 8, 0, True, False),
            ("$$$,$$9.99CR", 12, 3, 0, True, False),
            ("AAAXXX", 6, 0, 0, False, True),
        ],
    )
    def test_picture_info(
        self, picture: str, positions: int, digits: int, decimals: int, edited: bool, character: bool
    ) -> None:
        info = picture_info(picture)
        assert (info.positions, info.digits, info.decimals, info.edited, info.character) == (
            positions,
            digits,
            decimals,
            edited,
            character,
        )

    def test_unreadable_picture(self) -> None:
        assert picture_info("9Q9").positions is None


class TestLayout:
    def test_sizes_by_data_kind(self) -> None:
        layout = _layout(
            "DCL 1 R UNALIGNED, 2 C CHAR(10), 2 V CHAR(10) VARYING, 2 Z CHAR(10) VARYINGZ, 2 G GRAPHIC(3),"
            " 2 P FIXED DEC(9,2), 2 H FIXED BIN(15), 2 F FIXED BIN(31), 2 D FIXED BIN(63), 2 U FIXED BIN(8) UNSIGNED,"
            " 2 S FLOAT BIN(21), 2 L FLOAT DEC(16), 2 X FLOAT DEC(33), 2 Q FIXED DEC(5) COMPLEX,"
            " 2 PT POINTER, 2 AR AREA(100), 2 PC PIC'S999V99';"
        )
        lengths = {path.split(".")[-1]: lay.length for path, lay in layout.items() if path != "R"}
        assert lengths == {
            "C": 10,
            "V": 12,
            "Z": 11,
            "G": 6,
            "P": 5,
            "H": 2,
            "F": 4,
            "D": 8,
            "U": 1,
            "S": 4,
            "L": 8,
            "X": 16,
            "Q": 6,
            "PT": 4,
            "AR": 116,
            "PC": 6,
        }
        # UNALIGNED on the structure is inherited: no padding anywhere.
        assert layout["R"].length == sum(lengths.values())

    def test_aligned_items_are_padded_to_their_boundary(self) -> None:
        layout = _layout("DCL 1 R, 2 A CHAR(1), 2 H FIXED BIN(15), 2 B CHAR(1), 2 F FIXED BIN(31), 2 D FLOAT BIN(53);")
        assert (layout["R.H"].offset, layout["R.H"].padding_bits) == (3, 8)
        assert (layout["R.F"].offset, layout["R.F"].padding_bits) == (9, 24)
        assert (layout["R.D"].offset, layout["R.D"].padding_bits) == (17, 32)
        assert layout["R"].alignment == 8 and layout["R"].length == 24

    def test_explicit_unaligned_member_is_not_padded(self) -> None:
        layout = _layout("DCL 1 R, 2 A CHAR(1), 2 F FIXED BIN(31) UNALIGNED;")
        assert (layout["R.F"].offset, layout["R.F"].padding_bits) == (2, 0)

    def test_unaligned_bits_pack(self) -> None:
        layout = _layout("DCL 1 R, 2 A BIT(3), 2 B BIT(7), 2 C CHAR(1), 2 D BIT(8) ALIGNED;")
        assert (layout["R.A"].offset, layout["R.A"].bit_offset, layout["R.A"].bits) == (1, 0, 3)
        assert (layout["R.B"].offset, layout["R.B"].bit_offset) == (1, 3)
        assert (layout["R.C"].offset, layout["R.C"].padding_bits) == (3, 6)
        assert layout["R"].length == 4

    def test_union_members_share_storage(self) -> None:
        layout = _layout(
            "DCL 1 R, 2 K CHAR(2), 2 U UNION, 3 A CHAR(10), 3 B, 4 B1 CHAR(4), 4 B2 CHAR(8), 3 C CHAR(3), 2 T CHAR(1);"
        )
        assert {layout[p].offset for p in ("R.U.A", "R.U.B", "R.U.C", "R.U.B.B1")} == {3}
        assert layout["R.U"].length == 12
        assert (layout["R.U.B"].redefines, layout["R.U.C"].redefines, layout["R.U.A"].redefines) == ("A", "A", None)
        assert layout["R.U.C"].union == "U"
        assert layout["R.T"].offset == 15

    def test_array_of_aligned_structures_pads_each_element(self) -> None:
        layout = _layout("DCL 1 R, 2 E(3), 3 F FIXED BIN(31), 3 C CHAR(1), 2 Z CHAR(1);")
        assert (layout["R.E"].length, layout["R.E"].total_length, layout["R.E"].occurrences) == (5, 24, 3)
        assert layout["R.Z"].offset == 25

    def test_multi_dimension_and_bounds(self) -> None:
        layout = _layout("DCL 1 R UNALIGNED, 2 M(4,3) FIXED BIN(15), 2 B(-2:2) CHAR(2);")
        assert (layout["R.M"].occurrences, layout["R.M"].total_length) == (12, 24)
        assert (layout["R.B"].occurrences, layout["R.B"].offset) == (5, 25)

    def test_refer_extent_makes_later_offsets_variable(self) -> None:
        layout = _layout("DCL 1 R BASED, 2 N FIXED BIN(15), 2 T(N REFER(N)) CHAR(4), 2 Z CHAR(1);")
        assert layout["R.T"].variable and layout["R.T"].total_length is None
        assert layout["R.Z"].offset is None and layout["R.Z"].offset_variable
        assert layout["R"].length is None and layout["R"].reason

    def test_star_length_is_a_runtime_extent(self) -> None:
        layout = _layout("DCL 1 R, 2 S CHAR(*), 2 Z CHAR(1);")
        assert layout["R.S"].variable and layout["R.Z"].offset_variable

    def test_unsized_item_leaves_later_offsets_unknown_not_variable(self) -> None:
        layout = _layout("DCL 1 R, 2 E ENTRY, 2 Z CHAR(1);")
        assert layout["R.E"].length is None and "ENTRY" in (layout["R.E"].reason or "")
        assert layout["R.Z"].offset is None and not layout["R.Z"].offset_variable

    def test_assumptions_name_alignment_and_encoding(self) -> None:
        joined = " ".join(LAYOUT_ASSUMPTIONS)
        for phrase in ("single-byte", "VARYING", "ALIGNED", "doubleword", "RULES(IBM)"):
            assert phrase in joined


# ===========================================================================
# %INCLUDE and LIKE
# ===========================================================================

ADDRBLK = " DCL 1 ADDRESS_BLOCK,\n       2 LINE1 CHAR(35),\n       2 CITY CHAR(25);"
ORDER = " %INCLUDE ADDRBLK;\n DCL 1 ORDER_REC,\n       2 ID CHAR(10),\n       2 SHIP_TO LIKE ADDRESS_BLOCK;"


class TestInclude:
    def test_resolves_across_a_fileset(self) -> None:
        document = parse_pli_fileset(_fileset({"main.pli": ORDER, "ADDRBLK.inc": ADDRBLK}, "main.pli"))
        assert [s.name for s in document.structures] == ["ADDRESS_BLOCK", "ORDER_REC"]
        assert document.includes[0].resolved == "ADDRBLK.inc"
        ship = document.structures[1].children[1]
        assert [c.name for c in ship.children] == ["LINE1", "CITY"]
        # A spliced item keeps its own file and line.
        assert (document.structures[0].file, document.structures[0].line) == ("ADDRBLK.inc", 1)

    @pytest.mark.parametrize(
        "directive", ["%INCLUDE SYSLIB(ADDRBLK);", "%INCLUDE 'lib/addrblk.inc';", "% include addrblk ;"]
    )
    def test_directive_forms(self, directive: str) -> None:
        main = ORDER.replace("%INCLUDE ADDRBLK;", directive)
        document = parse_pli_fileset(_fileset({"main.pli": main, "lib/ADDRBLK.inc": ADDRBLK}, "main.pli"))
        assert document.includes[0].resolved == "lib/ADDRBLK.inc"

    def test_nested_includes_and_unreferenced_members(self) -> None:
        members = {
            "main.pli": "%INCLUDE OUTER; DCL 1 R, 2 X LIKE INNER_BLK;",
            "OUTER.inc": "%INCLUDE INNER;",
            "INNER.inc": "DCL 1 INNER_BLK, 2 A CHAR(1);",
            "SPARE.inc": "DCL 1 SPARE, 2 B CHAR(1);",
        }
        document = parse_pli_fileset(_fileset(members, "main.pli"))
        assert [i.member for i in document.includes] == ["OUTER", "INNER"]
        assert document.unreferenced == ["SPARE.inc"]

    def test_include_inside_a_declaration_is_spliced(self) -> None:
        members = {
            "main.pli": "DCL 1 R, 2 A CHAR(1), %INCLUDE FLDS; 2 Z CHAR(1);",
            "FLDS.inc": "2 B CHAR(2), 2 C CHAR(3),",
        }
        (rec,) = parse_pli_fileset(_fileset(members, "main.pli")).structures
        assert [c.name for c in rec.children] == ["A", "B", "C", "Z"]

    def test_include_cycle_is_semantic_invalid(self) -> None:
        members = {"main.pli": "%INCLUDE A; DCL 1 R, 2 X CHAR(1);", "A.inc": "%INCLUDE B;", "B.inc": "%INCLUDE A;"}
        with pytest.raises(ImportSourceError) as caught:
            _adapter().parse_fileset(_fileset(members, "main.pli"))
        assert caught.value.code == "INPUT_SEMANTIC_INVALID" and "cycle" in str(caught.value)

    def test_unresolved_include_needed_by_like_is_refused_naming_the_member(self) -> None:
        with pytest.raises(ImportSourceError) as caught:
            _adapter().parse(ORDER, source_label="main.pli")
        assert caught.value.code == "INPUT_REFERENCE_UNRESOLVED"
        assert "ADDRESS_BLOCK" in str(caught.value) and "%INCLUDE ADDRBLK" in str(caught.value)

    def test_unresolved_include_inside_a_structure_makes_it_partial(self) -> None:
        text = "DCL 1 R, 2 A CHAR(4), %INCLUDE MORE; 2 B FIXED BIN(31), 2 G, %INCLUDE GFLDS; 2 C CHAR(2);"
        api = _import(text)
        rec = _type(api, "R")
        partial = _pli(rec)["partial"]
        assert partial["missingIncludes"] == ["MORE"] and "MORE" in partial["reason"]  # type: ignore[index]
        assert _pli(_type(api, "R.G"))["partial"]["missingIncludes"] == ["GFLDS"]  # type: ignore[index]
        # Never a silently short layout: nothing after the gap has an offset or a record length.
        assert "offset" not in _pli(_field(api, "R", "B")) and "length" not in _pli(rec)
        assert _pli(_field(api, "R", "A"))["offset"] == 1
        assert [f.name for f in rec.fields] == ["A", "B", "C", "G"]
        assert _limits(api)["pli.unresolved_include"] == 2
        assert [i["inside"] for i in api.extras[PLI_EXTRAS_KEY]["includes"]] == ["R", "R"]
        assert "partial" in (rec.description or "")

    def test_unreferenced_unresolved_include_imports_whole(self) -> None:
        api = _import("%INCLUDE SPARE; DCL 1 R, 2 A CHAR(4);")
        assert "partial" not in _pli(_type(api, "R")) and _pli(_type(api, "R"))["length"] == 4
        assert api.extras[PLI_EXTRAS_KEY]["includes"][0] == {
            "member": "SPARE",
            "file": "test.pli",
            "line": 1,
            "resolved": None,
        }
        assert _limits(api) == {"pli.unresolved_include": 1}

    def test_nothing_but_unresolved_includes_is_refused(self) -> None:
        assert _code("%INCLUDE A; %INCLUDE B;") == "INPUT_REFERENCE_UNRESOLVED"


class TestLike:
    def test_like_copies_members_and_records_their_origin(self) -> None:
        document = _parse("DCL 1 BLK, 2 A CHAR(2), 2 G, 3 B CHAR(1); DCL 1 R, 2 X LIKE BLK, 2 Y(2) LIKE BLK.G;")
        x, y = document.structures[1].children
        assert [c.name for c in x.children] == ["A", "G"] and x.children[1].level == 3
        assert x.children[1].children[0].level == 4
        assert x.children[0].cloned_from == "BLK"
        assert [c.name for c in y.children] == ["B"] and y.children[0].level == 3

    def test_forward_and_nested_like(self) -> None:
        document = _parse(
            "DCL 1 S, 2 C LIKE CUST; DCL 1 CUST, 2 ID CHAR(4), 2 ADDR LIKE ADDR_BLK; DCL 1 ADDR_BLK, 2 CITY CHAR(9);"
        )
        assert [c.name for c in document.structures[0].children[0].children[1].children] == ["CITY"]

    def test_like_field_references_the_target_record(self) -> None:
        api = _import("DCL 1 BLK, 2 A CHAR(2); DCL 1 R, 2 X LIKE BLK, 2 Y(3) LIKE BLK;")
        assert _field(api, "R", "X").type.name == "pli.BLK"
        y = _field(api, "R", "Y")
        assert y.type.item is not None and y.type.item.name == "pli.BLK"
        assert y.constraints is not None and y.constraints.max_items == 3
        assert {t.name for t in api.types} == {"BLK", "R"}

    def test_like_cycle(self) -> None:
        assert _code("DCL 1 A, 2 X LIKE B; DCL 1 B, 2 Y LIKE A;") == "INPUT_SEMANTIC_INVALID"

    def test_like_of_an_element_is_semantic_invalid(self) -> None:
        assert _code("DCL 1 A, 2 X CHAR(1), 2 Y LIKE X;") == "INPUT_SEMANTIC_INVALID"

    def test_like_of_nothing_is_unresolved(self) -> None:
        assert _code("DCL 1 A, 2 Y LIKE NOWHERE;") == "INPUT_REFERENCE_UNRESOLVED"


# ===========================================================================
# Refusals
# ===========================================================================


class TestRefusals:
    @pytest.mark.parametrize(
        ("text", "code"),
        [
            ("", "INPUT_EMPTY"),
            ("   \n  ", "INPUT_EMPTY"),
            ("/* only a comment */", "INPUT_EMPTY"),
            ("﻿DCL 1 R, 2 A CHAR(1);", "INPUT_ENCODING_INVALID"),
            ("D\x00C\x00L\x00", "INPUT_ENCODING_INVALID"),
            ("       01  REC.\n           05  A  PIC X(10).", "FORMAT_MISMATCH"),
            ("DCL 1 R, 2 A CHAR(1); /* never closed", "INPUT_TRUNCATED"),
            ("DCL 1 R, 2 A CHAR(1) INIT('open", "INPUT_TRUNCATED"),
            ("DCL 1 R, 2 A FIXED DEC(13,", "INPUT_TRUNCATED"),
            ("DCL 1 R, 2 A CHAR(1)", "INPUT_TRUNCATED"),
            ("DCL 1 R, 2 A CHAR(1)\nDCL 1 S, 2 B CHAR(1);", "INPUT_MALFORMED"),
            ("DCL 1 R, 2 A CHAR(1));", "INPUT_MALFORMED"),
            ("DCL 1 R 2 A CHAR(1);", "INPUT_MALFORMED"),
            ("DCL 1 R, , 2 A CHAR(1);", "INPUT_MALFORMED"),
            ("DCL;", "INPUT_MALFORMED"),
            ("DCL 1 R, 2 A PIC;", "INPUT_MALFORMED"),
            ("%INCLUDE ;", "INPUT_MALFORMED"),
            ("DCL 2 ORPHAN CHAR(1);", "INPUT_SEMANTIC_INVALID"),
            ("DCL 1 R, 2 A CHAR(1), 3 B CHAR(1);", "INPUT_SEMANTIC_INVALID"),
            ("DCL 1 R, 2 A CHAR(1); DCL 1 R, 2 B CHAR(1);", "INPUT_SEMANTIC_INVALID"),
            ("DCL P POINTER;", "INPUT_SEMANTIC_INVALID"),
            ("DCL 1 R, 2 A CHAR(4) DEFINED ELSEWHERE;", "INPUT_REFERENCE_UNRESOLVED"),
        ],
    )
    def test_codes(self, text: str, code: str) -> None:
        assert _code(text) == code

    def test_missing_semicolon_names_the_item(self) -> None:
        with pytest.raises(ImportSourceError) as caught:
            _adapter().parse("DCL 1 R, 2 A CHAR(1)\n DCL 1 S, 2 B CHAR(1);")
        assert "the ';' before it is missing" in str(caught.value) and "line 2" in str(caught.value)

    def test_normalize_rejects_another_document(self) -> None:
        with pytest.raises(ImportSourceError):
            _adapter().normalize(object())
        with pytest.raises(ImportSourceError):
            _adapter().analyze(object())


# ===========================================================================
# Canonical projection
# ===========================================================================

SCALARS = (
    "DCL 1 R, 2 C CHAR(8), 2 V CHAR(20) VARYING, 2 FLAG BIT(1), 2 BITS BIT(12), 2 N FIXED DEC(7),"
    " 2 D FIXED DEC(9,2), 2 I FIXED BIN(31), 2 S FLOAT BIN(21), 2 L FLOAT DEC(16), 2 PN PIC'999',"
    " 2 PD PIC'99V99', 2 PE PIC'ZZ9.99', 2 PX PIC'XXXX', 2 P POINTER, 2 E ENTRY, 2 M(4,3) CHAR(2), 2 * CHAR(5);"
)


class TestProjection:
    def test_record_and_paradigm(self) -> None:
        api = _import(SCALARS)
        assert api.paradigm == ApiParadigm.DATA_SCHEMA and api.format == "pli"
        record = _type(api, "R")
        assert record.kind == TypeKind.RECORD and record.namespace == "pli" and record.key == "pli.R"

    @pytest.mark.parametrize(
        ("name", "scalar", "max_length"),
        [
            ("C", "string", 8),
            ("V", "string", 20),
            ("FLAG", "boolean", None),
            ("BITS", "bytes", None),
            ("N", "integer", None),
            ("D", "decimal", None),
            ("I", "integer", None),
            ("S", "float", None),
            ("L", "double", None),
            ("PN", "integer", None),
            ("PD", "decimal", None),
            ("PE", "string", 6),
            ("PX", "string", 4),
            ("P", "bytes", None),
            ("E", "any", None),
        ],
    )
    def test_scalars(self, name: str, scalar: str, max_length: Optional[int]) -> None:
        item = _field(_import(SCALARS), "R", name)
        assert item.type.name == scalar
        assert (item.constraints.max_length if item.constraints else None) == max_length

    def test_dimensions_nest_lists_and_filler_is_named(self) -> None:
        api = _import(SCALARS)
        matrix = _field(api, "R", "M")
        assert matrix.type.item is not None and matrix.type.item.item is not None
        assert matrix.type.item.item.name == "string"
        assert matrix.constraints is not None and (matrix.constraints.min_items, matrix.constraints.max_items) == (4, 4)
        assert matrix.constraints.extras == {"item_max_length": 2}
        filler = _field(api, "R", "FILLER_1")
        assert _pli(filler)["filler"] is True

    def test_field_numbers_follow_declaration_order(self) -> None:
        record = _type(_import(SCALARS), "R")
        ordered = sorted(record.fields, key=lambda f: f.field_number or 0)
        assert [f.name for f in ordered][:3] == ["C", "V", "FLAG"]

    def test_limits(self) -> None:
        assert _limits(_import(SCALARS)) == {
            "pli.edited_picture": 1,
            "pli.locator_item": 1,
            "pli.program_control_item": 1,
        }
        assert _limits(_import("DCL 1 R, 2 KOUNT, 2 A CHAR(1) ODDITY; DCL Q POINTER; Q = 1;")) == {
            "pli.default_attributes": 1,
            "pli.non_declare_statement": 1,
            "pli.scalar_declaration": 1,
            "pli.unread_attribute": 1,
        }

    def test_nested_structures_are_records_with_relative_offsets(self) -> None:
        api = _import("DCL 1 R, 2 ID CHAR(4), 2 ADDR, 3 LINE CHAR(10), 3 CITY CHAR(6);")
        addr = _field(api, "R", "ADDR")
        assert addr.type.name == "pli.R.ADDR"
        assert (_pli(addr)["offset"], _pli(addr)["length"]) == (5, 16)
        # Offsets on the nested record's fields are relative to that record.
        assert _pli(_field(api, "R.ADDR", "CITY"))["offset"] == 11
        assert "at offset 11, 6 bytes" in (_field(api, "R.ADDR", "CITY").description or "")

    def test_union_presents_like_redefines(self) -> None:
        api = _import(EXAMPLES.joinpath("06-typical-union-record.pli").read_text(encoding="utf-8"))
        body = _type(api, "TRANSACTION_REC.TXN_BODY")
        assert _pli(body)["union"] is True
        offsets = {f.name: _pli(f)["offset"] for f in body.fields}
        assert set(offsets.values()) == {1}
        assert _pli(_field(api, "TRANSACTION_REC.TXN_BODY", "RAW_VIEW"))["redefines"] == "DEBIT_VIEW"
        assert "shares storage with DEBIT_VIEW" in (
            _field(api, "TRANSACTION_REC.TXN_BODY", "CREDIT_VIEW").description or ""
        )
        assert _limits(api) == {"pli.union_storage": 1}

    def test_storage_map_and_assumptions(self) -> None:
        api = _import("DCL 1 BLK, 2 A CHAR(3); DCL 1 R, 2 X FIXED BIN(31), 2 Y LIKE BLK;")
        rows = _pli(_type(api, "R"))["storageMap"]
        assert [(row["path"], row.get("offset")) for row in rows] == [("R", 1), ("R.X", 1), ("R.Y", 5), ("R.Y.A", 5)]  # type: ignore[union-attr]
        assert api.extras[PLI_EXTRAS_KEY]["layoutAssumptions"] == list(LAYOUT_ASSUMPTIONS)
        assert api.extras[PLI_EXTRAS_KEY]["structures"][1] == {"name": "R", "type": "pli.R", "length": 7}

    def test_raw_keeps_every_file(self) -> None:
        api = _import_set({"main.pli": ORDER, "ADDRBLK.inc": ADDRBLK}, "main.pli")
        assert [f["path"] for f in api.raw["files"]] == ["ADDRBLK.inc", "main.pli"]  # type: ignore[index]
        assert api.extras[PLI_EXTRAS_KEY]["input"] == "fileset"


# ===========================================================================
# Native analysis
# ===========================================================================


class TestAnalysis:
    def test_available_with_assumptions_stated(self) -> None:
        adapter = _adapter()
        analysis = adapter.analyze(adapter.parse("DCL 1 R, 2 A CHAR(2), 2 B FIXED BIN(31);"))
        assert analysis.status == "available"
        codes = [w.code for w in analysis.warnings]
        assert codes == [WARNING_LAYOUT_ASSUMPTIONS]
        root = analysis.tree[0]
        assert root.kind == "record" and root.attributes["length"] == 8
        assert root.children[1].attributes["paddingBits"] == 16

    def test_unresolved_include_makes_the_record_partial(self) -> None:
        adapter = _adapter()
        analysis = adapter.analyze(adapter.parse("DCL 1 R, 2 A CHAR(2), %INCLUDE MORE; 2 B CHAR(1);"))
        assert analysis.status == "partial"
        assert WARNING_INCLUDE_UNRESOLVED in [w.code for w in analysis.warnings]
        include = analysis.tree[0].children[1]
        assert include.kind == "include" and include.attributes["member"] == "MORE"


# ===========================================================================
# Detection and wiring
# ===========================================================================


class TestDetection:
    def test_structure_is_claimed_strongly(self) -> None:
        result = _adapter().detect(DetectionInput(text="DCL 1 R, 2 A CHAR(1);", filename="x.txt"))
        assert result.matched and result.confidence >= 0.9

    def test_include_only_member_is_claimed(self) -> None:
        assert has_pli_declarations("%INCLUDE ADDRBLK;")
        assert 0.8 <= _adapter().detect(DetectionInput(text="%INCLUDE ADDRBLK;", filename="x")).confidence < 0.9

    def test_copybook_is_not_claimed_and_does_not_claim_pli(self) -> None:
        copybook = (EXAMPLES / "negative" / "04-wrong-format-cobol-copybook.cpy").read_text(encoding="utf-8")
        assert not _adapter().detect(DetectionInput(text=copybook, filename="x.cpy")).matched
        pli = (EXAMPLES / "02-typical-customer-record.pli").read_text(encoding="utf-8")
        assert not CobolCopybookImportSource().detect(DetectionInput(text=pli, filename="x.pli")).matched

    def test_dcl_in_a_comment_is_not_a_declaration(self) -> None:
        assert not has_pli_declarations("/* DCL 1 X */ 01 REC.")

    def test_extension_alone_is_a_weak_claim(self) -> None:
        result = _adapter().detect(DetectionInput(text="hello", filename="x.pli"))
        assert result.matched and result.confidence < 0.6


class TestWiring:
    def test_registered(self) -> None:
        adapter = get_import_source("pli")
        assert isinstance(adapter, PliImportSource)
        assert {".pli", ".pl1", ".inc"} <= set(adapter.file_extensions)

    def test_capability_seed_lists_every_limit(self) -> None:
        capability = capability_for("pli")
        assert sorted(capability.canonical_projection.dropped_constructs) == sorted(PLI_LIMIT_DETAILS)
        assert PLI_PARTIAL_LIMITS < set(PLI_LIMIT_DETAILS)

    def test_version_coverage(self) -> None:
        coverage = version_coverage_for("pli")
        assert coverage.reads and not coverage.writes

    def test_schema_only_and_provenance_key(self) -> None:
        assert "pli" in SCHEMA_ONLY_FORMATS
        assert PLI_EXTRAS_KEY in PROVENANCE_EXTRA_KEYS

    def test_ledger_rows(self) -> None:
        api = _import("%INCLUDE SPARE; DCL Q POINTER; DCL 1 R, 2 U UNION, 3 A CHAR(1), 3 B CHAR(1);")
        rows = {row.source_construct: row.coverage.value for row in _pli_capability_rows(api)}
        assert rows == {
            "pli.scalar_declaration": "not-parsed-by-adapter",
            "pli.union_storage": "partially-mapped",
            "pli.unresolved_include": "partially-mapped",
        }


# ===========================================================================
# Corpus
# ===========================================================================


class TestCorpus:
    def test_customer_record_byte_layout(self) -> None:
        api = _import((EXAMPLES / "02-typical-customer-record.pli").read_text(encoding="utf-8"))
        record = _type(api, "CUSTOMER_REC")
        assert _pli(record)["length"] == 514
        contacts = _field(api, "CUSTOMER_REC", "CUST_CONTACTS")
        assert (_pli(contacts)["offset"], _pli(contacts)["length"], _pli(contacts)["totalLength"]) == (185, 62, 310)
        assert _field(api, "CUSTOMER_REC", "CUST_BALANCE").type.name == "decimal"

    def test_includes_set(self) -> None:
        folder = EXAMPLES / "03-includes-set"
        members = {path.name: path.read_text(encoding="utf-8") for path in folder.iterdir()}
        api = _import_set(members, "main.pli")
        assert {t.name for t in api.types} == {"ADDRESS_BLOCK", "MONEY_BLOCK", "ORDER_REC", "ORDER_REC.ORDER_LINES"}
        assert _field(api, "ORDER_REC", "BILL_TO").type.name == "pli.ADDRESS_BLOCK"
        assert _pli(_type(api, "ORDER_REC"))["length"] == 1066
        assert not _limits(api)

    def test_composition(self) -> None:
        api = _import((EXAMPLES / "07-composition-like-and-nesting.pli").read_text(encoding="utf-8"))
        assert _field(api, "STATEMENT_REC", "STMT_CUSTOMER").type.name == "pli.CUSTOMER_REC"
        rows = [row["path"] for row in _pli(_type(api, "STATEMENT_REC"))["storageMap"]]  # type: ignore[union-attr]
        assert "STATEMENT_REC.STMT_CUSTOMER.CUST_BILL_TO.CITY" in rows

    def test_stress_coverage(self) -> None:
        api = _import((EXAMPLES / "04-stress-attribute-coverage.pli").read_text(encoding="utf-8"))
        assert _limits(api) == {
            "pli.edited_picture": 1,
            "pli.locator_item": 3,
            "pli.refer_extent": 1,
            "pli.scalar_declaration": 1,
            "pli.union_storage": 1,
        }
        payload = _field(api, "COVERAGE_REC", "PAYLOAD")
        assert _pli(payload)["offsetVariable"] is True and "offset" not in _pli(payload)
        assert _pli(_type(api, "COVERAGE_REC"))["storageClass"] == "BASED"

    @pytest.mark.parametrize(
        ("name", "code"),
        [
            ("01-syntactic-missing-semicolon.pli", "INPUT_MALFORMED"),
            ("02-semantic-level-number-gap.pli", "INPUT_SEMANTIC_INVALID"),
            ("03-truncated-mid-declare.pli", "INPUT_TRUNCATED"),
            ("04-wrong-format-cobol-copybook.cpy", "FORMAT_MISMATCH"),
            ("06-unresolvable-include.pli", "INPUT_REFERENCE_UNRESOLVED"),
        ],
    )
    def test_negatives(self, name: str, code: str) -> None:
        assert _code((EXAMPLES / "negative" / name).read_text(encoding="utf-8"), name) == code

    def test_utf16_negative(self) -> None:
        raw = (EXAMPLES / "negative" / "05-encoding-utf16.pli").read_bytes()
        assert _code(raw.decode("utf-8", errors="replace")) == "INPUT_ENCODING_INVALID"
