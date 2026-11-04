"""PL/I include structure output mode of the copybook export — MFX-23.3 (#4141).

Covers the acceptance criteria:

* **syntactically valid PL/I declares for the fixture set** — every copybook in the corpus
  (``apiome-ui/examples/cobol-copybook/*.cpy``), the converted model the copybook tests use and the copybook
  target's OpenAPI case, under both numeric usages and both formats, are written as PL/I that Apiome's PL/I
  reader parses with no attribute it does not know, that describes the copybook layout item for item and
  byte for byte (:func:`app.cobolcopybook_pli.layout_problems`), that passes the export gate and that imports
  again as a PL/I item;
* **the same fidelity reporting as the copybook mode** — every loss the copybook plan records is reported
  with the same subject, construct and verdict, in PL/I terms; what only PL/I changes is reported besides.

Also: the attribute mapping, names, overlays (``UNION``), variable tables (``REFER``), condition names,
margins, the option and the written fixtures (``fixtures/copybook_target/pli/``, regenerate with
``APIOME_REGEN_COPYBOOK_PLI=1``).
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

import pytest
from pydantic import ValidationError
from test_cobolcopybook_emitter import _EXAMPLES, _api, _copybook_item, _field, _record, _shop

from app.canonical_model import Constraints, EnumValue, Service, Type, TypeKind, TypeRef
from app.cobolcopybook_emitter import CobolCopybookEmitOptions, CobolCopybookEmitter, copybook_emit_plan
from app.cobolcopybook_pli import PliNamer, _attributes, _zoned_picture, layout_problems, pli_name
from app.emitter import EmittedFile
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import get_import_source, load_builtin_import_sources
from app.lossiness import LossinessKind, LossinessSeverity
from app.pli_import_source import PliImportSource
from app.pli_parser import parse_pli_text

_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "copybook_target"
_PLI_GOLDEN = _GOLDEN / "pli"
_REGEN = bool(os.environ.get("APIOME_REGEN_COPYBOOK_PLI"))
_COPYBOOKS = sorted(p.name for p in _EXAMPLES.glob("*.cpy"))
#: The restated messages must not name a COBOL clause; these are the ones the copybook messages use.
_COBOL_TERMS = re.compile(r"PIC X\(|OCCURS \d|DEPENDING ON|REDEFINES [A-Z]|COBOL picture|COBOL type|a copybook")


# ===========================================================================
# Helpers
# ===========================================================================


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_import_sources()


def _emit(api, **opts):
    return CobolCopybookEmitter().emit(api, opts=CobolCopybookEmitOptions(**opts))


def _pli(api, **opts):
    return _emit(api, mode="pli", **opts)


def _text(api, **opts) -> str:
    return _pli(api, **opts).files[0].content


def _openapi() -> Any:
    adapter = get_import_source("openapi")
    text = (_GOLDEN / "source.openapi.yaml").read_text(encoding="utf-8")
    return adapter.normalize(adapter.parse(text, source_label="source.openapi.yaml"))


def _fixture(name: str) -> Any:
    if name == "converted-shop":
        return _shop()
    if name == "openapi-order":
        return _openapi()
    return _copybook_item(_EXAMPLES / name)


_FIXTURE_SET = [*_COPYBOOKS, "converted-shop", "openapi-order"]
_VARIANTS = {
    "comp-fixed": {},
    "display-free": {"numeric_usage": "display", "fixed_format": False},
}


def _decl(text: str, name: str) -> str:
    """The declaration of ``name`` (one line, without the trailing comma)."""
    joined = re.sub(r"\s*\n\s+(?!/\*)(?=[A-Z(])", " ", text)
    for line in joined.splitlines():
        if re.search(rf"\b\d+ {re.escape(name)}\b", line):
            return line.strip().rstrip(",;")
    raise AssertionError(f"{name} not declared in:\n{text}")


def _losses(result, subject: str) -> List[str]:
    return sorted(loss.pointer or "" for loss in result.losses if loss.subject == subject)


def _report(api, **opts):
    return compute_lossiness_for_emitter(api, CobolCopybookEmitter(), options={"mode": "pli", **opts})


# ===========================================================================
# The option
# ===========================================================================


def test_the_mode_defaults_to_copybook() -> None:
    assert CobolCopybookEmitOptions().mode == "copybook"
    with pytest.raises(ValidationError):
        CobolCopybookEmitOptions(mode="pl1")


def test_the_pli_member_is_named_after_the_record() -> None:
    result = _pli(_shop())
    assert [(f.path, f.media_type) for f in result.files] == [("Shop.pli", "text/plain")]
    assert _pli(_copybook_item(_EXAMPLES / "03-payment-redefines.cpy")).files[0].path == "PAYMENT-RECORD.pli"


def test_the_copybook_mode_is_unchanged() -> None:
    api = _shop()
    assert _emit(api).files[0].content == _emit(api, mode="copybook").files[0].content
    assert _emit(api).files[0].path == "Shop.cpy"


# ===========================================================================
# AC 1 — syntactically valid PL/I declares for the fixture set
# ===========================================================================


@pytest.mark.parametrize("variant", _VARIANTS)
@pytest.mark.parametrize("name", _FIXTURE_SET)
def test_every_fixture_is_valid_pli_with_the_copybook_layout(name: str, variant: str) -> None:
    api = _fixture(name)
    options = {"mode": "pli", **_VARIANTS[variant]}
    result = _emit(api, **_VARIANTS[variant], mode="pli")
    text = result.files[0].content
    document = parse_pli_text(text, label=result.files[0].path)
    plan = copybook_emit_plan(api, CobolCopybookEmitOptions(**options))
    assert len(document.structures) == len(plan)
    assert layout_problems(text, plan) == []


@pytest.mark.parametrize("variant", _VARIANTS)
@pytest.mark.parametrize("name", _FIXTURE_SET)
def test_every_fixture_passes_the_export_gate(name: str, variant: str) -> None:
    api = _fixture(name)
    options = {"mode": "pli", **_VARIANTS[variant]}
    verdict = asyncio.run(validate_emitted_artifact("cobolcopybook", _emit(api, **options), api=api,
                                                    options=options))
    assert verdict.valid, [f.message for f in verdict.findings]


@pytest.mark.parametrize("name", _FIXTURE_SET)
def test_every_fixture_imports_again_as_a_pli_item(name: str) -> None:
    result = _pli(_fixture(name))
    adapter = PliImportSource()
    back = adapter.normalize(adapter.parse(result.files[0].content, source_label=result.files[0].path))
    assert back.format == "pli"
    assert any(t.kind is TypeKind.RECORD for t in back.types)


@pytest.mark.parametrize("name", _FIXTURE_SET)
def test_fixed_format_stays_inside_the_pli_margins(name: str) -> None:
    for line in _text(_fixture(name)).splitlines():
        assert len(line) <= 72, line
        assert not line or line[0] == " ", line  # column 1 is outside PL/I's default margins


def test_free_format_never_wraps_a_declaration() -> None:
    deep = _api(_record("L6", _field("L6", "customerLoyaltyProgramMembershipNumber", TypeRef(name="string"),
                                     constraints=Constraints(max_length=99999))))
    for depth in reversed(range(6)):
        deep = _api(_record(f"L{depth}", _field(f"L{depth}", "customerLoyaltyProgramMembershipNumber",
                                                TypeRef(name=f"L{depth + 1}"))), *deep.types)
    text = _text(deep, fixed_format=False)
    # Every line is a comment or a whole declaration (``DCL 1 …`` / ``n NAME …``), however long.
    assert all(re.match(r"^\s+(/\*|DCL 1 |\d+ )", line) for line in text.splitlines() if line.strip())
    assert layout_problems(text, copybook_emit_plan(deep, CobolCopybookEmitOptions())) == []


def test_a_long_declaration_wraps_between_words() -> None:
    api = _api(_record("R", _field("R", "lines", TypeRef(item=TypeRef(name="string")),
                                   constraints=Constraints(max_length=12))))
    deep = api
    for depth in range(7):
        deep = _api(_record(f"L{depth}", _field(f"L{depth}", "customerLoyaltyProgramMembershipNumber",
                                                TypeRef(name="L" + str(depth + 1) if depth < 6 else "string"),
                                                constraints=Constraints(max_length=99999))),
                    *deep.types)
    for line in _text(deep).splitlines():
        assert len(line) <= 72, line
    assert layout_problems(_text(deep), copybook_emit_plan(deep, CobolCopybookEmitOptions())) == []


def test_the_written_members_match_the_fixtures() -> None:
    cases = {"nested-array-long-name": _openapi(),
             "decimal-redefines": _copybook_item(_EXAMPLES / "03-payment-redefines.cpy"),
             "decimal-occurs-depending": _copybook_item(_EXAMPLES / "04-warehouse-stress.cpy")}
    files: Dict[str, str] = {}
    for case, api in cases.items():
        for variant, options in _VARIANTS.items():
            emitted = _emit(api, mode="pli", **options).files[0]
            files[f"{case}/{variant}/{emitted.path}"] = emitted.content
    if _REGEN:
        shutil.rmtree(_PLI_GOLDEN, ignore_errors=True)
        for name, text in files.items():
            (_PLI_GOLDEN / name).parent.mkdir(parents=True, exist_ok=True)
            (_PLI_GOLDEN / name).write_text(text, encoding="utf-8")
    on_disk = {str(p.relative_to(_PLI_GOLDEN)): p.read_text(encoding="utf-8")
               for p in sorted(_PLI_GOLDEN.rglob("*.pli"))}
    assert on_disk == files


# ===========================================================================
# What each item becomes
# ===========================================================================


@pytest.mark.parametrize(
    ("picture", "usage", "expected"),
    [
        ("X(10)", None, "CHAR(10)"),
        ("X", None, "CHAR(1)"),
        ("A(5)", None, "CHAR(5)"),
        ("N(20)", None, "WIDECHAR(20)"),
        ("S9(9)V99", "COMP-3", "FIXED DEC(11,2)"),
        ("9(5)", "PACKED-DECIMAL", "FIXED DEC(5)"),
        ("S9(4)", "COMP", "FIXED BIN(15)"),
        ("9(9)", "BINARY", "FIXED BIN(31)"),
        ("S9(18)", "COMP-5", "FIXED BIN(63)"),
        ("9(8)", None, "PIC'(8)9'"),
        ("S9(5)", None, "PIC'(4)9T'"),
        ("S9(9)V99", "DISPLAY", "PIC'(9)9V9T'"),
        ("9(8)V99", None, "PIC'(8)9V99'"),
        ("S9V9", None, "PIC'9VT'"),
        (None, "COMP-1", "FLOAT DEC(6)"),
        (None, "COMP-2", "FLOAT DEC(16)"),
        (None, "POINTER", "POINTER"),
        (None, "INDEX", "FIXED BIN(31)"),
    ],
)
def test_each_picture_and_usage_has_its_pli_attributes(picture, usage, expected) -> None:
    attributes, subject, _detail = _attributes({"picture": picture, "usage": usage})
    assert (attributes, subject) == (expected, None)


@pytest.mark.parametrize(
    ("picture", "usage", "expected", "subject"),
    [
        ("Z(5)9.99", None, "CHAR(9)", "picture-as-char"),
        ("X(3)9(2)", None, "CHAR(5)", "picture-as-char"),
        ("S9(5)V99", "COMP", "FIXED BIN(31)", "binary-scale-as-comment"),
        ("9(20)", "COMP", "CHAR(20)", "picture-as-char"),
    ],
)
def test_a_picture_pli_cannot_say_exactly_is_reported(picture, usage, expected, subject) -> None:
    attributes, found, detail = _attributes({"picture": picture, "usage": usage})
    assert (attributes, found) == (expected, subject)
    assert picture in detail


def test_zoned_pictures_overpunch_the_sign_on_the_last_digit() -> None:
    assert _zoned_picture(5, 0, False) == "(5)9"
    assert _zoned_picture(5, 0, True) == "(4)9T"
    assert _zoned_picture(11, 2, True) == "(9)9V9T"
    assert _zoned_picture(2, 0, False) == "99"


@pytest.mark.parametrize(
    ("cobol", "pli"),
    [("CUST-ID", "CUST_ID"), ("FILLER", "*"), ("2FA-CODE", "X_2FA_CODE"), ("ORDER", "ORDER"), ("", "*")],
)
def test_pli_names(cobol: str, pli: str) -> None:
    assert pli_name(cobol) == pli


def test_the_namer_is_stable_and_unique() -> None:
    namer = PliNamer()
    assert namer.name("A-B") == "A_B"
    assert namer.name("A-B") == "A_B"
    assert namer.name("A_B") == "A_B_2"
    assert namer.fresh("A_B") == "A_B_3"
    assert namer.name("FILLER") == "*"


def test_a_converted_model_is_one_unaligned_structure_by_depth() -> None:
    text = _text(_shop())
    assert re.search(r"^ DCL 1 PURCHASE UNALIGNED BASED,$", text, re.M)
    assert _decl(text, "ORDER_ID") == "2 ORDER_ID FIXED BIN(63)"
    assert _decl(text, "CUSTOMER_NAME") == "2 CUSTOMER_NAME CHAR(40)"
    assert _decl(text, "TOTAL") == "2 TOTAL FIXED DEC(18,3)"
    assert _decl(text, "RATIO") == "2 RATIO FLOAT DEC(16)"
    assert _decl(text, "STREET") == "3 STREET CHAR(30)"
    assert text.rstrip().endswith(";")


def test_display_usage_writes_zoned_pictures() -> None:
    text = _text(_shop(), numeric_usage="display")
    assert _decl(text, "ORDER_ID") == "2 ORDER_ID PIC'(17)9T'"
    assert _decl(text, "QTY") == "2 QTY PIC'(9)9'"


def test_a_variable_table_refers_to_its_counter_in_a_based_structure() -> None:
    text = _text(_shop())
    # LINES is a COBOL reserved word, so the shared plan names the field LINES-X.
    assert _decl(text, "LINES_X_COUNT") == "2 LINES_X_COUNT FIXED BIN(15)"
    assert _decl(text, "LINES_X") == "2 LINES_X(50 REFER(LINES_X_COUNT))"
    assert text.index("LINES_X_COUNT FIXED") < text.index("REFER(LINES_X_COUNT)")
    assert _decl(text, "CODES") == "2 CODES(3) CHAR(4)"


def test_a_structure_with_no_variable_table_is_not_based() -> None:
    api = _api(_record("R", _field("R", "id", TypeRef(name="i32"))))
    assert re.search(r"^ DCL 1 R UNALIGNED,$", _text(api), re.M)


def test_a_union_the_plan_lays_out_is_a_union_group() -> None:
    text = _text(_shop())
    assert _decl(text, "PAYMENT") == "2 PAYMENT UNION"
    assert "REDEFINES" not in text
    assert _losses(_pli(_shop()), "overlay-union-synthesized") == []


def test_an_overlay_beside_other_items_gets_a_union_group() -> None:
    api = _copybook_item(_EXAMPLES / "03-payment-redefines.cpy")
    result = _pli(api)
    text = result.files[0].content
    assert _decl(text, "PAYMENT_DETAIL_UNION") == "2 PAYMENT_DETAIL_UNION UNION"
    assert _decl(text, "PAYMENT_DETAIL") == "3 PAYMENT_DETAIL CHAR(30)"
    assert _decl(text, "CARD_DETAIL") == "3 CARD_DETAIL"
    assert _decl(text, "PAYMENT_POSTED_DATE") == "2 PAYMENT_POSTED_DATE PIC'(8)9'"
    [item] = [i for i in _report(api).items if i.target_mapping == "overlay-union-synthesized"]
    assert item.kind is LossinessKind.SYNTH
    assert "PAYMENT_DETAIL_UNION" in item.message


def test_a_redefines_of_nothing_is_written_as_its_own_item() -> None:
    result = _pli(_copybook_item(_EXAMPLES / "08-overlay-warnings.cpy"))
    assert _decl(result.files[0].content, "SNAP_ORPHAN") == "2 SNAP_ORPHAN"
    assert len(_losses(result, "redefines-unresolved")) == 1


def test_condition_names_are_a_comment_above_the_item() -> None:
    result = _pli(_shop())
    text = result.files[0].content
    assert "/* values: GIFT_TRUE = 'Y', GIFT_FALSE = 'N' */" in text
    assert text.index("GIFT_TRUE") < text.index("2 GIFT CHAR(1)")
    assert "Purchase.gift" in _losses(result, "conditions-as-comment")
    item = next(i for i in _report(_shop()).items
                if i.construct_key == "Purchase.gift" and i.target_mapping == "conditions-as-comment")
    assert (item.kind, item.severity) == (LossinessKind.APPROX, LossinessSeverity.INFO)


def test_a_renames_item_is_dropped_and_reported() -> None:
    api = _copybook_item(_EXAMPLES / "07-ledger-unmodelled.cpy")
    result = _pli(api)
    assert "LEDGER_STAMP" not in result.files[0].content
    assert _decl(result.files[0].content, "LEDGER_STATUS") == "2 LEDGER_STATUS CHAR(1)"
    assert len(_losses(result, "renames-dropped")) == 1
    assert any(i.kind is LossinessKind.DROP and i.target_mapping == "renames-dropped" for i in _report(api).items)


def test_a_comment_cannot_end_early() -> None:
    api = _api(_record("R", _field("R", "code", TypeRef(name="string"),
                                   constraints=Constraints(max_length=4, pattern="^a*/b$"))))
    text = _text(api)
    assert "* /b" in text
    assert layout_problems(text, copybook_emit_plan(api, CobolCopybookEmitOptions())) == []


def test_the_banner_is_optional() -> None:
    assert _text(_shop()).startswith(" /* Generated PL/I include structure for Shop */")
    assert _text(_shop(), include_comments=False).startswith(" DCL 1 PURCHASE")


# ===========================================================================
# AC 2 — the same fidelity reporting as the copybook mode
# ===========================================================================


@pytest.mark.parametrize("name", ["converted-shop", "openapi-order"])
@pytest.mark.parametrize("usage", ["comp", "display"])
def test_every_copybook_loss_is_reported_with_the_same_subject_and_construct(name: str, usage: str) -> None:
    api = _fixture(name)
    copybook = {(loss.subject, loss.pointer) for loss in _emit(api, numeric_usage=usage).losses}
    pli = {(loss.subject, loss.pointer) for loss in _pli(api, numeric_usage=usage).losses}
    # A respelling is dropped where PL/I keeps the source's own name (an underscore COBOL had to change).
    assert {entry for entry in copybook if entry[0] != "name-mangled"} <= pli
    assert {entry for entry in pli if entry[0] == "name-mangled"} <= copybook


@pytest.mark.parametrize("name", ["converted-shop", "openapi-order"])
def test_the_report_grades_each_shared_entry_as_the_copybook_mode_does(name: str) -> None:
    api = _fixture(name)
    graded = lambda report: {(i.construct_key, i.target_mapping, i.kind, i.severity) for i in report.items  # noqa: E731
                             if i.target_mapping and "→" not in i.target_mapping}
    copybook = graded(compute_lossiness_for_emitter(api, CobolCopybookEmitter(), options={}))
    pli = graded(_report(api))
    assert {entry for entry in copybook if entry[1] != "name-mangled"} <= pli


@pytest.mark.parametrize("name", ["converted-shop", "openapi-order"])
def test_the_messages_are_in_pli_terms(name: str) -> None:
    restated = {"length-synthesized", "counter-synthesized", "occurs-fixed", "union-as-redefines", "union-dropped",
                "pattern-as-comment", "format-as-comment", "float-as-decimal", "unmapped-scalar", "map-dropped",
                "recursion-cut", "name-mangled"}
    for usage in ("comp", "display"):
        for loss in _pli(_fixture(name), numeric_usage=usage).losses:
            if loss.subject in restated:
                assert not _COBOL_TERMS.search(loss.detail), loss.detail
                assert "-COUNT" not in loss.detail, loss.detail


def test_restated_messages_name_the_pli_declaration() -> None:
    details = {loss.subject: loss.detail for loss in _pli(_shop()).losses}
    assert "it is written CHAR(255) (the default length)" in details["length-synthesized"]
    assert "(50 REFER(LINES_X_COUNT))" in details["counter-synthesized"]
    assert "is written as a UNION of its members" in details["union-as-redefines"]
    assert "A PL/I structure has no map" in details["map-dropped"]


def test_a_respelling_pli_does_not_need_is_not_reported() -> None:
    result = _pli(_shop())
    # customer_name → CUSTOMER-NAME in COBOL, but CUSTOMER_NAME in PL/I is the source name upper-cased.
    copybook = {loss.pointer for loss in _emit(_shop()).losses if loss.subject == "name-mangled"}
    assert "Purchase.customer_name" in copybook
    assert "Purchase.customer_name" not in _losses(result, "name-mangled")
    # orderId → ORDER_ID is still a respelling.
    assert "Purchase.orderId" in _losses(result, "name-mangled")


def test_a_copybook_item_reports_its_names_once() -> None:
    result = _pli(_copybook_item(_EXAMPLES / "01-customer-record.cpy"))
    assert _losses(result, "names-respelled") == [""]
    assert _losses(result, "name-mangled") == []


def test_the_root_note_names_pli() -> None:
    for api in (_shop(), _copybook_item(_EXAMPLES / "02-order-line.cpy")):
        notes = [i for i in _report(api).items if i.target_mapping == "document → PL/I include structure"]
        assert len(notes) == 1 and notes[0].kind is LossinessKind.APPROX


def test_the_types_only_advisory_names_pli() -> None:
    api = _shop().model_copy(update={"services": [Service(key="S", name="S")]})
    assert any("PL/I include structure" in loss.detail for loss in _pli(api).losses
               if loss.subject == "services-dropped")


def test_an_enum_value_list_is_a_comment() -> None:
    api = _api(_record("R", _field("R", "state", TypeRef(name="State"))),
               Type(key="State", name="State", kind=TypeKind.ENUM,
                    enum_values=[EnumValue(key="State.a", name="a", value="A")]))
    assert "/* values: STATE_A = 'A' */" in _text(api)


# ===========================================================================
# The gate
# ===========================================================================


def _tampered(result, old: str, new: str):
    emitted = result.files[0]
    files = [EmittedFile(path=emitted.path, content=emitted.content.replace(old, new, 1),
                         media_type=emitted.media_type)]
    return result.model_copy(update={"files": files})


def test_the_gate_rejects_an_item_of_another_size() -> None:
    api = _shop()
    result = _tampered(_pli(api), "CHAR(40)", "CHAR(39)")
    verdict = asyncio.run(validate_emitted_artifact("cobolcopybook", result, api=api, options={"mode": "pli"}))
    assert not verdict.valid
    assert [f.keyword for f in verdict.findings] == ["pli.layout"]
    assert "CUSTOMER_NAME takes 39 byte(s)" in verdict.findings[0].message


def test_the_gate_rejects_a_member_that_does_not_parse() -> None:
    api = _shop()
    result = _tampered(_pli(api), ";", "")
    verdict = asyncio.run(validate_emitted_artifact("cobolcopybook", result, api=api, options={"mode": "pli"}))
    assert not verdict.valid


def test_the_gate_rejects_an_attribute_the_reader_does_not_know() -> None:
    api = _api(_record("R", _field("R", "id", TypeRef(name="i32"))))
    problems = layout_problems(_text(api).replace("FIXED BIN(31)", "FIXED BIN(31) WOBBLY"),
                               copybook_emit_plan(api, CobolCopybookEmitOptions()))
    assert any("WOBBLY" in p for p in problems)


def test_the_plan_carries_each_construct_key() -> None:
    [tree] = copybook_emit_plan(_shop(), CobolCopybookEmitOptions())
    assert tree["key"] == "Purchase"
    keys = {child.get("key") for child in tree["children"]}
    assert {"Purchase.orderId", "Purchase.lines"} <= keys
    counter = next(c for c in tree["children"] if c["name"] == "LINES-X-COUNT")
    assert "key" not in counter  # the synthesized counter belongs to no field of its own
