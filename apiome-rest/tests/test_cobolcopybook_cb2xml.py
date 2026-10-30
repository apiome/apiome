"""cb2xml validation of emitted COBOL copybooks — MFX-23.4 (#4142).

cb2xml is a JVM tool the CI runtime does not install, so most of these tests stand it in: either a fake
``cb2xml`` executable on the toolchain runner (it writes cb2xml's XML, or its fatal-error text), or a
stand-in :func:`app.cobolcopybook_cb2xml.run_cb2xml` that reads the copybook text it is given and writes
the layout in cb2xml's XML spellings. The tests marked ``_needs_cb2xml`` run the real tool when the
runtime has it (``APIOME_CB2XML_BIN`` or ``cb2xml`` on ``PATH``). Covers:

* **running the tool** — arguments, the XML read back, a fatal parse error (exit code 0) or a crash
  turned into its message, line and column; the tool missing;
* **reading cb2xml's layout** and **comparing it with the emit plan** — equivalent spellings agree
  (``X(3)`` / ``XXX``, ``COMP`` / ``BINARY``, ``COMP-3`` / ``PACKED-DECIMAL``, quoted values, inherited
  usage); each real difference is one problem at its item path;
* **free format** laid out in fixed format for cb2xml, reading the same entries;
* **the export gate** — the emit plan follows the export's options; cb2xml's error and every layout
  difference reject the export; without cb2xml, or when it goes missing mid-run, the re-parse decides;
  broken emitter output fails the export job with the cb2xml error;
* **fixtures** — every example copybook and a converted model, in both formats, parse to the emit plan.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path
from typing import List
from unittest.mock import patch
from xml.sax.saxutils import quoteattr

import pytest
from test_cobolcopybook_emitter import _EXAMPLES, _api, _copybook_item, _emit, _field, _record, _shop, _text

from app.canonical_model import CanonicalApi, Constraints, EnumValue, Type, TypeKind, TypeRef
from app.cobolcopybook_cb2xml import (
    Cb2xmlError,
    LayoutItem,
    _error_from,
    cb2xml_available,
    check_with_cb2xml,
    fixed_format_text,
    layout_differences,
    parse_cb2xml_layout,
    plan_layout,
    run_cb2xml,
)
from app.cobolcopybook_emitter import CobolCopybookEmitOptions, copybook_emit_options, copybook_emit_plan
from app.cobolcopybook_parser import _parse_flat_fields
from app.emitter import EmitResult, EmittedFile
from app.export_job_engine import ExportJobStartRequest, schedule_export_job
from app.export_validation import validate_emitted_artifact

_needs_cb2xml = pytest.mark.skipif(
    not cb2xml_available(), reason="cb2xml is not installed here (set APIOME_CB2XML_BIN or put cb2xml on PATH)"
)

#: cb2xml's spelling of each USAGE the emitter writes.
_CB2XML_USAGE = {"COMP": "computational", "COMP-1": "computational-1", "COMP-2": "computational-2",
                 "COMP-3": "computational-3", "BINARY": "binary", "PACKED-DECIMAL": "packed-decimal"}


# ===========================================================================
# Helpers
# ===========================================================================


def _cb2xml_xml(items: List[LayoutItem]) -> str:
    """``items`` as cb2xml (2017 format) writes them: quoted 88 values, its usage names, occurs-min for ODO."""

    def item(i: LayoutItem) -> str:
        attrs = {"level": f"{i.level:02d}", "name": i.name}
        if i.occurs:
            attrs["occurs"] = str(i.occurs[1])
            if i.depending_on:
                attrs["occurs-min"] = str(i.occurs[0])
                attrs["depending-on"] = i.depending_on
        if i.picture:
            attrs["picture"] = i.picture
        if i.usage:
            attrs["usage"] = _CB2XML_USAGE.get(i.usage.upper(), i.usage.lower())
        attrs["position"] = "1"
        if i.redefines:
            attrs["redefines"] = i.redefines
        rendered = " ".join(f"{k}={quoteattr(v)}" for k, v in attrs.items())
        conditions = "".join(
            f"<condition name={quoteattr(name)} value={quoteattr(_quoted(value))}/>" for name, value in i.conditions
        )
        return f"<item {rendered}>{conditions}{''.join(item(c) for c in i.children)}</item>"

    body = "".join(item(i) for i in items)
    header = '<?xml version="1.0" ?><copybook filename="x.cpy" dialect="Mainframe" cb2xml-format="2017">'
    return f"{header}{body}</copybook>"


def _quoted(value: str) -> str:
    """An 88 value as cb2xml writes it: a number bare, else the literal's text (quotes inside still doubled,
    as the copybook reader leaves them) back in its quotes."""
    if value.lstrip("-").isdigit():
        return value
    return f"'{value}'"


def _read_back(text: str) -> List[LayoutItem]:
    """The records a fixed-format copybook declares, read independently of the plan (one per ``01``)."""
    records: List[LayoutItem] = []
    stack: List[tuple] = []  # (level, attrs dict, children list)

    def close(until: int) -> None:
        while stack and stack[-1][0] >= until:
            level, attrs, children = stack.pop()
            built = LayoutItem(children=tuple(children), **attrs)
            (stack[-1][2] if stack else records).append(built)

    for f in _parse_flat_fields(text):
        close(f.level)
        occurs = (f.occurs_min, f.occurs_max) if f.occurs_max is not None else None
        stack.append((f.level, dict(level=f.level, name=f.name, picture=f.picture, usage=f.usage, occurs=occurs,
                                    depending_on=f.depending_on, redefines=f.redefines,
                                    conditions=tuple((c.name, c.value) for c in f.conditions)), []))
    close(0)
    return records


def _stand_in(text: str) -> str:
    """A cb2xml stand-in: the layout the copybook text declares, in cb2xml's XML."""
    return _cb2xml_xml(_read_back(text))


def _fake_tool(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, xml: str = "", stderr: str = "",
               exit_code: int = 0) -> Path:
    """Put a fake ``cb2xml`` on the toolchain runner: it records its args, writes ``xml`` to ``-xml``."""
    log = tmp_path / "args.txt"
    script = tmp_path / "cb2xml"
    script.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        f"open({str(log)!r}, 'w').write('\\n'.join(sys.argv[1:]))\n"
        "args = sys.argv[1:]\n"
        f"xml = {xml!r}\n"
        "if xml:\n"
        "    open(args[args.index('-xml') + 1], 'w').write(xml)\n"
        f"sys.stderr.write({stderr!r})\n"
        f"sys.exit({exit_code})\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("APIOME_CB2XML_BIN", str(script))
    return log


@pytest.fixture
def stand_in(monkeypatch: pytest.MonkeyPatch):
    """Report cb2xml present and stand it in with :func:`_stand_in`; record the text it was given."""
    seen: List[str] = []

    def fake(text: str, *, name: str = "copybook.cpy") -> str:
        seen.append(text)
        return _stand_in(text)

    monkeypatch.setattr("app.cobolcopybook_cb2xml.cb2xml_available", lambda: True)
    monkeypatch.setattr("app.cobolcopybook_cb2xml.run_cb2xml", fake)
    return seen


def _export(text: str, path: str = "Shop.cpy") -> EmitResult:
    return EmitResult(files=[EmittedFile(path=path, content=text, media_type="text/plain")], media_type="text/plain")


def _small() -> CanonicalApi:
    o = "Order"
    return _api(_record(o, _field(o, "id", TypeRef(name="i32")),
                        _field(o, "note", TypeRef(name="string")),
                        _field(o, "lines", TypeRef(item=TypeRef(name="string")),
                               constraints=Constraints(max_length=8))))


# ===========================================================================
# Running the tool
# ===========================================================================


def test_run_cb2xml_passes_the_copybook_and_reads_the_xml(tmp_path, monkeypatch) -> None:
    xml = _cb2xml_xml([LayoutItem(level=1, name="REC", children=(LayoutItem(level=5, name="A", picture="X(2)"),))])
    log = _fake_tool(tmp_path, monkeypatch, xml=xml)
    assert run_cb2xml("       01  REC.\n           05  A PIC X(2).\n", name="dir/Rec.cpy") == xml
    args = log.read_text().splitlines()
    assert args[0] == "-cobol" and args[1].endswith("/Rec.cpy") and args[2] == "-xml"


def test_a_fatal_parse_error_is_an_error_though_cb2xml_exits_0(tmp_path, monkeypatch) -> None:
    stderr = ("*** fatal parse error ***\n[3,20] expecting: '.', blank when zero\n"
              "=== buffer dump start ===\n05 A PIC\n=== buffer dump end ===\n")
    _fake_tool(tmp_path, monkeypatch, stderr=stderr)
    with pytest.raises(Cb2xmlError) as caught:
        run_cb2xml("       01  REC.\n")
    assert caught.value.message == "[3,20] expecting: '.', blank when zero"
    assert (caught.value.line, caught.value.column, caught.value.unavailable) == (3, 20, False)


def test_a_crash_or_no_output_is_an_error(tmp_path, monkeypatch) -> None:
    _fake_tool(tmp_path, monkeypatch, stderr="java.lang.NullPointerException\n\tat net.sf.cb2xml.Cb2Xml", exit_code=1)
    with pytest.raises(Cb2xmlError, match="NullPointerException"):
        run_cb2xml("       01  REC.\n")
    _fake_tool(tmp_path, monkeypatch)
    with pytest.raises(Cb2xmlError, match="wrote no layout"):
        run_cb2xml("       01  REC.\n")


def test_a_missing_tool_is_unavailable(monkeypatch) -> None:
    monkeypatch.setenv("APIOME_CB2XML_BIN", "/definitely/not/here/cb2xml")
    with patch("app.toolchain_runner.resolve_executable", return_value=None):
        with pytest.raises(Cb2xmlError) as caught:
            run_cb2xml("       01  REC.\n")
    assert caught.value.unavailable


def test_error_text_without_a_position() -> None:
    error = _error_from("*** fatal parse error ***\nUnexpected end of file\n")
    assert (error.message, error.line, error.column) == ("Unexpected end of file", None, None)


# ===========================================================================
# Reading and comparing layouts
# ===========================================================================


def test_cb2xml_xml_is_read_into_records_items_and_conditions() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<copybook filename="Shop.cpy" dialect="Mainframe" cb2xml-format="2017">
  <item level="01" name="REC" position="1" storage-length="20" display-length="20">
    <item level="05" name="GIFT" picture="X" position="1" storage-length="1" display-length="1">
      <condition name="GIFT-TRUE" value="'Y'"/>
    </item>
    <item level="05" name="N-COUNT" picture="S9(4)" usage="computational" position="2" numeric="COBOL_NUMERIC"/>
    <item level="05" name="N" occurs="5" occurs-min="0" depending-on="N-COUNT" position="4">
      <item level="10" name="AMT" picture="S9(5)V99" usage="computational-3" inherited-usage="true"/>
    </item>
  </item>
  <item level="01" name="OTHER" picture="X(3)" position="1"/>
</copybook>"""
    records = parse_cb2xml_layout(xml)
    assert [r.name for r in records] == ["REC", "OTHER"]
    gift, count, table = records[0].children
    assert gift.conditions == (("GIFT-TRUE", "'Y'"),)
    assert (count.picture, count.usage) == ("S9(4)", "computational")
    assert (table.occurs, table.depending_on) == ((0, 5), "N-COUNT")
    assert table.children[0].usage is None  # inherited from a group: not the item's own


@pytest.mark.parametrize("xml", ["not xml", "<layout/>", '<!DOCTYPE x [<!ENTITY a "b">]><copybook/>'])
def test_output_that_is_not_cb2xml_xml_is_an_error(xml: str) -> None:
    with pytest.raises(Cb2xmlError):
        parse_cb2xml_layout(xml)


def test_equivalent_spellings_agree() -> None:
    planned = [LayoutItem(level=1, name="rec", children=(
        LayoutItem(level=5, name="A", picture="X(3)"),
        LayoutItem(level=5, name="B", picture="S9(4)", usage="COMP"),
        LayoutItem(level=5, name="C", picture="S9(5)V9(2)", usage="COMP-3"),
        LayoutItem(level=5, name="D", usage="COMP-2"),
        LayoutItem(level=5, name="E", picture="X(4)", conditions=(("E-A", "it''s"), ("E-B", "1"))),
        LayoutItem(level=5, name="F", picture="X", usage="DISPLAY"),
    ))]
    read = [LayoutItem(level=1, name="REC", children=(
        LayoutItem(level=5, name="a", picture="xxx"),
        LayoutItem(level=5, name="B", picture="S9999", usage="binary"),
        LayoutItem(level=5, name="C", picture="S9(5)V99", usage="packed-decimal"),
        LayoutItem(level=5, name="D", usage="computational-2"),
        LayoutItem(level=5, name="E", picture="XXXX", conditions=(("e-a", "'it''''s'"), ("E-B", "1"))),
        LayoutItem(level=5, name="F", picture="X(1)"),
    ))]
    assert layout_differences(planned, read) == []


def test_each_difference_is_one_problem_at_its_path() -> None:
    planned = [LayoutItem(level=1, name="REC", children=(
        LayoutItem(level=5, name="A", picture="X(10)"),
        LayoutItem(level=5, name="B", picture="S9(4)", usage="COMP"),
        LayoutItem(level=5, name="T", occurs=(0, 5), depending_on="B", children=(
            LayoutItem(level=10, name="X", picture="X"),)),
        LayoutItem(level=5, name="R", redefines="A", picture="9(10)"),
        LayoutItem(level=5, name="S", picture="X", conditions=(("S-Y", "Y"),)),
        LayoutItem(level=5, name="M", picture="X"),
    ))]
    read = [LayoutItem(level=1, name="REC", children=(
        LayoutItem(level=5, name="A", picture="X(1)"),
        LayoutItem(level=5, name="B", picture="S9(4)", usage="computational-3"),
        LayoutItem(level=5, name="T", occurs=(5, 5), children=(LayoutItem(level=15, name="X", picture="X"),)),
        LayoutItem(level=5, name="R", picture="9(10)"),
        LayoutItem(level=5, name="S", picture="X", conditions=(("S-Y", "'N'"),)),
        LayoutItem(level=5, name="WRONG", picture="X"),
        LayoutItem(level=5, name="EXTRA", picture="X"),
    ))]
    assert layout_differences(planned, read) == [
        ("REC.A", "PICTURE: the emit plan has X(10); cb2xml read X(1)."),
        ("REC.B", "USAGE: the emit plan has COMP; cb2xml read computational-3."),
        ("REC.T", "OCCURS: the emit plan has OCCURS 0 TO 5 DEPENDING ON B; cb2xml read OCCURS 5."),
        ("REC.T.X", "Level: the emit plan has 10; cb2xml read 15."),
        ("REC.R", "REDEFINES: the emit plan has A; cb2xml read none."),
        ("REC.S", "88 levels: the emit plan has S-Y Y; cb2xml read S-Y 'N'."),
        ("REC.M", "The emit plan has M here; cb2xml read WRONG."),
        ("REC.EXTRA", "cb2xml read EXTRA, which the emit plan does not have."),
    ]
    assert layout_differences(planned, []) == [("REC", "cb2xml did not read REC, which the emit plan has.")]


def test_the_plan_is_read_the_way_the_emitter_writes_it() -> None:
    plan = copybook_emit_plan(_shop(), CobolCopybookEmitOptions())
    items = {i.name: i for i in plan_layout(plan)[0].children}
    assert items["LINES-X"].occurs == (0, 50) and items["LINES-X"].depending_on == "LINES-X-COUNT"
    assert items["CODES"].occurs == (3, 3)  # a fixed table: `OCCURS 3 TIMES`
    assert items["GIFT"].conditions == (("GIFT-TRUE", "Y"), ("GIFT-FALSE", "N"))
    # A variable table with no minimum is written `OCCURS 1 TO n`.
    assert plan_layout([{"level": 1, "name": "R", "children": [
        {"level": 5, "name": "T", "occurs_max": 4, "depending_on": "N", "picture": "X"}]}])[0].children[0].occurs == (
        1, 4)


# ===========================================================================
# Free format
# ===========================================================================


def test_free_format_is_laid_out_in_the_code_area_with_the_same_entries() -> None:
    e = Type(key="E", name="E", kind=TypeKind.ENUM, enum_values=[
        EnumValue(key="E.a", name="a", value="a value with  two spaces and a long tail of words"),
        EnumValue(key="E.b", name="b", value="it's")])
    api = _api(*_shop().types, e)
    api.types[0].fields.append(_field("Purchase", "kind", TypeRef(name="E")))
    fixed, free = _text(api), _text(api, fixed_format=False)
    laid_out = fixed_format_text(free)
    assert all(len(line) <= 72 for line in laid_out.splitlines())
    assert "a value with  two spaces and a long tail of words'" in laid_out  # a literal is never split
    assert _read_back(laid_out) == _read_back(fixed)
    assert laid_out.splitlines()[0] == "      * Generated COBOL copybook for Shop"


# ===========================================================================
# The export gate
# ===========================================================================


def test_the_emit_plan_follows_the_export_options() -> None:
    assert copybook_emit_options({"default_string_length": 80}).default_string_length == 80
    assert copybook_emit_options({"default_string_length": 0}) == CobolCopybookEmitOptions()  # invalid → defaults
    assert copybook_emit_options(None) == CobolCopybookEmitOptions()
    plan = copybook_emit_plan(_small(), copybook_emit_options({"default_string_length": 80, "default_occurs": 3}))
    note, lines = plan[0]["children"][1], plan[0]["children"][3]
    assert note["picture"] == "X(80)" and lines["occurs_max"] == 3


@pytest.mark.parametrize("fixed_format", [True, False])
async def test_a_sound_export_passes_with_the_options_it_was_emitted_with(stand_in, fixed_format: bool) -> None:
    options = {"default_string_length": 80, "default_occurs": 3, "fixed_format": fixed_format}
    verdict = await validate_emitted_artifact("cobolcopybook", _emit(_small(), **options), api=_small(),
                                              options=options)
    assert verdict.valid and verdict.validated, verdict.findings
    assert len(stand_in) == 1 and all(len(line) <= 72 for line in stand_in[0].splitlines())
    # Checked against the defaults instead, the same copybook differs from the plan.
    verdict = await validate_emitted_artifact("cobolcopybook", _emit(_small(), **options), api=_small())
    assert verdict.failed
    assert {(f.keyword, f.path) for f in verdict.findings} == {("cb2xml.layout", "ORDER-X.NOTE"),
                                                               ("cb2xml.layout", "ORDER-X.LINES-X")}


async def test_cb2xml_parse_errors_reject_the_export_with_cb2xml_output(monkeypatch) -> None:
    def broken(text: str, *, name: str = "copybook.cpy") -> str:
        raise Cb2xmlError("[5,24] expecting: '.'", line=5, column=24)

    monkeypatch.setattr("app.cobolcopybook_cb2xml.cb2xml_available", lambda: True)
    monkeypatch.setattr("app.cobolcopybook_cb2xml.run_cb2xml", broken)
    verdict = await validate_emitted_artifact("cobolcopybook", _emit(_small()), api=_small())
    assert verdict.failed
    (finding,) = verdict.findings
    assert (finding.keyword, finding.file, finding.line, finding.column) == ("cb2xml.parse", "Shop.cpy", 5, 24)
    assert finding.message == "cb2xml cannot parse the copybook: [5,24] expecting: '.'"
    # A free-format export is laid out again for cb2xml, so its line numbers are not the file's.
    verdict = await validate_emitted_artifact("cobolcopybook", _emit(_small(), fixed_format=False), api=_small(),
                                              options={"fixed_format": False})
    assert (verdict.findings[0].line, verdict.findings[0].column) == (None, None)


async def test_a_copybook_that_does_not_match_its_plan_is_rejected(stand_in) -> None:
    text = _text(_small()).replace("PIC X(255)", "PIC X(25)")
    verdict = await validate_emitted_artifact("cobolcopybook", _export(text), api=_small())
    assert verdict.failed
    assert [(f.keyword, f.path, f.message) for f in verdict.findings] == [
        ("cb2xml.layout", "ORDER-X.NOTE", "PICTURE: the emit plan has X(255); cb2xml read X(25).")]


async def test_without_cb2xml_the_re_parse_decides(monkeypatch) -> None:
    monkeypatch.setattr("app.cobolcopybook_cb2xml.cb2xml_available", lambda: False)
    ran = []
    monkeypatch.setattr("app.cobolcopybook_cb2xml.run_cb2xml", lambda *a, **k: ran.append(1))
    assert (await validate_emitted_artifact("cobolcopybook", _emit(_small()), api=_small())).valid
    verdict = await validate_emitted_artifact("cobolcopybook", _export("not a copybook"), api=_small())
    assert verdict.failed and not ran


async def test_cb2xml_that_goes_missing_mid_run_falls_back_to_the_re_parse(monkeypatch) -> None:
    def missing(text: str, *, name: str = "copybook.cpy") -> str:
        raise Cb2xmlError("cb2xml is not installed on this server.", unavailable=True)

    monkeypatch.setattr("app.cobolcopybook_cb2xml.cb2xml_available", lambda: True)
    monkeypatch.setattr("app.cobolcopybook_cb2xml.run_cb2xml", missing)
    assert (await validate_emitted_artifact("cobolcopybook", _emit(_small()), api=_small())).valid


async def test_the_gate_runs_the_real_runner_path_with_a_fake_tool(tmp_path, monkeypatch) -> None:
    text = _text(_small())
    _fake_tool(tmp_path, monkeypatch, xml=_stand_in(text))
    assert cb2xml_available()
    assert (await validate_emitted_artifact("cobolcopybook", _export(text), api=_small())).valid
    _fake_tool(tmp_path, monkeypatch, stderr="*** fatal parse error ***\n[2,12] expecting: number\n")
    verdict = await validate_emitted_artifact("cobolcopybook", _export(text), api=_small())
    assert [(f.keyword, f.line) for f in verdict.findings] == [("cb2xml.parse", 2)]


async def test_broken_emitter_output_fails_the_export_job_with_the_cb2xml_error(monkeypatch) -> None:
    """MFX-23.4 acceptance: a copybook cb2xml rejects fails the job, carrying cb2xml's error."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _source, _wait_terminal

    def broken(text: str, *, name: str = "copybook.cpy") -> str:
        raise Cb2xmlError("[9,30] expecting: 'times'", line=9, column=30)

    monkeypatch.setattr("app.cobolcopybook_cb2xml.cb2xml_available", lambda: True)
    monkeypatch.setattr("app.cobolcopybook_cb2xml.run_cb2xml", broken)
    request = ExportJobStartRequest(artifact="artifact-1", target="cobolcopybook", confirm=True)
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(
        "app.export_job_engine.emit_canonical", side_effect=lambda *a, **k: _emit(_small())
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    finding = status["error"]["context"]["findings"][0]
    assert (finding["message"], finding["keyword"], finding["line"]) == (
        "cb2xml cannot parse the copybook: [9,30] expecting: 'times'", "cb2xml.parse", 9)


# ===========================================================================
# Fixtures
# ===========================================================================

_FIXTURES = sorted(p.name for p in _EXAMPLES.glob("*.cpy"))


def _fixture_cases() -> List[tuple]:
    return [(name, fixed) for name in [*_FIXTURES, "converted-shop"] for fixed in (True, False)]


def _fixture_api(name: str) -> CanonicalApi:
    return _shop() if name == "converted-shop" else _copybook_item(_EXAMPLES / name)


@pytest.mark.parametrize(("name", "fixed_format"), _fixture_cases())
async def test_every_fixture_parses_to_its_emit_plan(stand_in, name: str, fixed_format: bool) -> None:
    api = _fixture_api(name)
    options = {"fixed_format": fixed_format}
    verdict = await validate_emitted_artifact("cobolcopybook", _emit(api, **options), api=api, options=options)
    assert verdict.valid, [f.message for f in verdict.findings]


@_needs_cb2xml
@pytest.mark.parametrize(("name", "fixed_format"), _fixture_cases())
def test_cb2xml_parses_every_fixture_to_its_emit_plan(name: str, fixed_format: bool) -> None:
    api = _fixture_api(name)
    options = CobolCopybookEmitOptions(fixed_format=fixed_format)
    emitted = _emit(api, fixed_format=fixed_format).files[0]
    assert check_with_cb2xml(emitted.path, emitted.content, copybook_emit_plan(api, options),
                             fixed_format=fixed_format) == []


@_needs_cb2xml
def test_cb2xml_rejects_a_broken_copybook() -> None:
    (problem,) = check_with_cb2xml("Bad.cpy", "       01  REC.\n           05  A PIC X(2) OCCURS.\n",
                                   [{"level": 1, "name": "REC", "children": []}])
    assert problem.rule == "cb2xml.parse" and problem.message.startswith("cb2xml cannot parse the copybook: ")

