"""Cross-format compatibility golden corpus — XPC-4.6 (#5750).

The corpus is ``tests/golden/compatibility`` (see :mod:`compatibility_corpus` for the layout). The
acceptance criteria are: Apiome's verdict under every mode matches the golden; each reference tool's
verdict matches its recording when the tool is available live; a reference disagreement fails unless
a documented waiver covers it; the Avro and JSON Schema sets reproduce the Confluent documentation
tables; the Protobuf set covers every Buf rule the baseline claims; and the README and the docs
page's waiver table are generated.

Regenerate with ``uv run pytest tests/test_compatibility_corpus_golden.py --update-golden``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import compatibility_corpus as corpus
import pytest
from compatibility_corpus import (
    CORPUS_ROOT,
    DEFAULT_MODE,
    FORMATS,
    Case,
    Finding,
    ReferenceUnavailableError,
    Side,
)

from app.compatibility_rule_catalogue import catalogue

_CASES: List[Case] = corpus.load_cases()
_CASE_IDS = [c.id for c in _CASES]
_CASE_TOOLS = [(c, t) for c in _CASES for t in FORMATS[c.format].references]


@pytest.fixture(scope="module", autouse=True)
def _regenerate(request: pytest.FixtureRequest) -> None:
    """Under ``--update-golden``: prune orphans, re-grade and re-record, rewrite README and docs."""
    if not corpus.should_update(request):
        return
    corpus.prune_orphans()
    for case in corpus.load_cases():
        try:
            live, _ = corpus.live_references(case)
            expected = corpus.build_expected(case, corpus.read_expected(case), live)
        except ReferenceUnavailableError:
            continue  # a Protobuf case without buf keeps its golden
        corpus.write_json(case.expected_path, expected)
    waivers = corpus.load_waivers()
    corpus.README_PATH.write_text(corpus.render_readme(corpus.load_cases(), waivers), encoding="utf-8")
    page = corpus.DOCS_PAGE.read_text(encoding="utf-8")
    corpus.DOCS_PAGE.write_text(corpus.replace_docs_section(page, waivers), encoding="utf-8")


def _verdicts_or_skip(case: Case) -> Dict[str, Dict[str, Any]]:
    """Apiome's verdicts, skipping a Protobuf case when ``buf`` cannot compile it."""
    try:
        return corpus.apiome_verdicts(case)
    except ReferenceUnavailableError as exc:
        if corpus.is_strict("buf"):
            pytest.fail(f"{case.id}: {exc}")
        pytest.skip(str(exc))


# ===========================================================================
# Shape
# ===========================================================================


def test_every_format_has_cases() -> None:
    assert {c.format for c in _CASES} == set(FORMATS)


def test_no_orphan_case_directories() -> None:
    assert corpus.orphan_dirs() == [], "a case lacks a side: restore it or run --update-golden to prune it"


def test_no_unknown_format_directories() -> None:
    present = {p.name for p in CORPUS_ROOT.iterdir() if p.is_dir()}
    assert present <= set(FORMATS)


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_case_is_described(case: Case) -> None:
    expected = corpus.read_expected(case)
    assert expected.get("case") == case.id
    assert expected.get("description", "").strip(), f"{case.expected_path}: write a description"
    assert expected.get("source", "").strip(), f"{case.expected_path}: name the case's source"


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_case_carries_every_required_reference(case: Case) -> None:
    references = corpus.read_expected(case).get("references", {})
    for tool in FORMATS[case.format].references:
        if not tool.required:
            continue
        assert tool.id in references, f"{case.id}: no {tool.id} recording; run --update-golden with it installed"
        assert set(references[tool.id]["verdicts"]) == set(tool.modes)


# ===========================================================================
# Apiome's verdicts
# ===========================================================================


@pytest.mark.parametrize("case", _CASES, ids=_CASE_IDS)
def test_verdicts_match_golden(case: Case) -> None:
    expected = corpus.read_expected(case).get("verdicts")
    actual = _verdicts_or_skip(case)
    assert actual == expected, (
        f"{case.id}: Apiome's verdicts moved. If intended, regenerate with "
        "`uv run pytest tests/test_compatibility_corpus_golden.py --update-golden` and review the diff."
    )


@pytest.mark.parametrize("case", [c for c in _CASES if c.format != "graphql"], ids=lambda c: c.id)
def test_none_mode_never_breaks(case: Case) -> None:
    verdicts = corpus.read_expected(case)["verdicts"]
    if "NONE" in verdicts:
        assert verdicts["NONE"]["compatible"] is True


# ===========================================================================
# Reference tools
# ===========================================================================


@pytest.mark.parametrize("case,tool", _CASE_TOOLS, ids=[f"{c.id}::{t.id}" for c, t in _CASE_TOOLS])
def test_live_reference_matches_recording(case: Case, tool: corpus.ReferenceTool) -> None:
    try:
        _, live = tool.run(case)
    except ReferenceUnavailableError as exc:
        if corpus.is_strict(tool.id):
            pytest.fail(f"{tool.id} must be available ({corpus.STRICT_ENV}): {exc}")
        pytest.skip(str(exc))
    recorded = corpus.read_expected(case).get("references", {}).get(tool.id)
    assert recorded is not None, f"{case.id}: no {tool.id} recording; run --update-golden"
    assert corpus.comparable({"verdicts": live}) == corpus.comparable(
        recorded
    ), f"{case.id}: {tool.id} now answers differently from its recording; re-record with --update-golden"


def test_no_unwaived_reference_disagreements(record_property: Any) -> None:
    waivers = corpus.load_waivers()
    findings: List[Finding] = []
    for case in _CASES:
        expected = corpus.read_expected(case)
        findings += corpus.disagreements(case, expected["verdicts"], expected.get("references", {}), waivers)
    report = [f.as_dict() for f in findings]
    record_property(corpus.REFERENCE_DISAGREEMENT, json.dumps(report))
    target = os.environ.get(corpus.REPORT_ENV, "").strip()
    if target:
        Path(target).write_text(json.dumps({"findings": report}, indent=2) + "\n", encoding="utf-8")
    unwaived = [f.as_dict() for f in findings if f.waiver is None]
    assert not unwaived, (
        "reference_disagreement: Apiome and a reference tool disagree. Fix the classifier, or document "
        "the difference in tests/golden/compatibility/waivers.json:\n" + json.dumps(unwaived, indent=2)
    )
    used = {(f.case, f.tool, f.mode) for f in findings}
    stale = [
        (w["case"], w["tool"], mode) for w in waivers for mode in w["modes"] if (w["case"], w["tool"], mode) not in used
    ]
    assert not stale, f"waivers that cover no disagreement (remove them): {stale}"


def test_waivers_are_documented() -> None:
    known_tools = {t.id: t for spec in FORMATS.values() for t in spec.references}
    for waiver in corpus.load_waivers():
        assert set(waiver) == {"case", "tool", "modes", "reason"}, waiver
        assert waiver["reason"].strip() and len(waiver["reason"].split()) >= 5, waiver
        assert waiver["case"] in _CASE_IDS, waiver
        assert waiver["tool"] in known_tools, waiver
        assert waiver["modes"] and set(waiver["modes"]) <= set(known_tools[waiver["tool"]].modes), waiver


# ===========================================================================
# Coverage the roadmap names
# ===========================================================================

#: The Confluent "compatibility types" table, read against the Avro field rows it names: which
#: change each mode allows. (BACKWARD: delete fields, add optional fields; FORWARD: add fields,
#: delete optional fields; FULL: add and delete optional fields; NONE: all changes.)
_CONFLUENT_AVRO_TABLE = {
    "avro/add-field-with-default": {"BACKWARD": True, "FORWARD": True, "FULL": True, "NONE": True},
    "avro/add-field-without-default": {"BACKWARD": False, "FORWARD": True, "FULL": False, "NONE": True},
    "avro/remove-field-with-default": {"BACKWARD": True, "FORWARD": True, "FULL": True, "NONE": True},
    "avro/remove-field-without-default": {"BACKWARD": True, "FORWARD": False, "FULL": False, "NONE": True},
}

#: Confluent's JSON Schema content-model rules: a closed model may gain a property backward and
#: lose one forward; an open model the reverse; a partially open model may gain a property its
#: ``additionalProperties`` schema already admits both ways.
_CONFLUENT_JSON_SCHEMA_TABLE = {
    "json-schema/closed-property-added": {"BACKWARD": True, "FORWARD": False, "FULL": False, "NONE": True},
    "json-schema/closed-property-removed": {"BACKWARD": False, "FORWARD": True, "FULL": False, "NONE": True},
    "json-schema/open-property-added": {"BACKWARD": False, "FORWARD": True, "FULL": False, "NONE": True},
    "json-schema/open-property-removed": {"BACKWARD": True, "FORWARD": False, "FULL": False, "NONE": True},
    "json-schema/partially-open-property-added-covered": {
        "BACKWARD": True,
        "FORWARD": True,
        "FULL": True,
        "NONE": True,
    },
}


@pytest.mark.parametrize("case_id,row", sorted({**_CONFLUENT_AVRO_TABLE, **_CONFLUENT_JSON_SCHEMA_TABLE}.items()))
def test_reproduces_the_confluent_documentation_tables(case_id: str, row: Dict[str, bool]) -> None:
    expected = json.loads((CORPUS_ROOT / case_id / "expected.json").read_text())
    assert {mode: v["compatible"] for mode, v in expected["verdicts"].items()} == row
    assert "Confluent" in expected["source"]


def test_protobuf_covers_every_buf_rule_the_baseline_claims() -> None:
    # The structural ``protobuf.<category>.<rule>`` ids; the ``buf`` overlay ids and families
    # (``protobuf.buf-breaking.*``, ``buf-breaking.wire-compatible``) are buf's own output.
    claimed = {
        e.rule_id
        for e in catalogue()
        if e.family == "protobuf" and e.rule_id.count(".") == 2 and not e.rule_id.startswith("protobuf.buf-breaking.")
    }
    assert len(claimed) == 16
    fired = {
        rule
        for case in _CASES
        if case.format == "protobuf"
        for verdict in corpus.read_expected(case)["verdicts"].values()
        for rule in verdict["rule_ids"]
    }
    assert claimed - fired == set(), f"no Protobuf corpus case fires {sorted(claimed - fired)}"


def test_graphql_is_graded_under_the_default_mode_only() -> None:
    assert FORMATS["graphql"].modes == (DEFAULT_MODE,)


# ===========================================================================
# Generated pages
# ===========================================================================


def test_readme_is_generated() -> None:
    assert corpus.README_PATH.read_text(encoding="utf-8") == corpus.render_readme(
        _CASES, corpus.load_waivers()
    ), "tests/golden/compatibility/README.md is stale; run --update-golden"


def test_docs_list_the_waivers() -> None:
    page = corpus.DOCS_PAGE.read_text(encoding="utf-8")
    assert (
        corpus.replace_docs_section(page, corpus.load_waivers()) == page
    ), "the docs page's known-differences table is stale; run --update-golden"
    assert "## Known differences from reference tools" in page


# ===========================================================================
# Machinery
# ===========================================================================


def _case(fmt: str = "avro") -> Case:
    side = Side(files={"base.avsc": "{}"}, label="base.avsc")
    return Case(format=fmt, name="x", path=CORPUS_ROOT / fmt / "x", base=side, head=side)


def test_disagreements_report_waived_and_unwaived() -> None:
    verdicts = {"BACKWARD": {"compatible": True}, "FORWARD": {"compatible": False}}
    references = {
        "apicurio-registry": {"verdicts": {"BACKWARD": {"compatible": False}, "FORWARD": {"compatible": False}}},
        "asyncapi-diff": {"verdicts": {"BACKWARD": {"compatible": None}}},
    }
    waivers = [{"case": "avro/x", "tool": "apicurio-registry", "modes": ["BACKWARD"], "reason": "because of a reason"}]
    (finding,) = corpus.disagreements(_case(), verdicts, references, waivers)
    assert (finding.tool, finding.mode, finding.waiver) == ("apicurio-registry", "BACKWARD", "because of a reason")
    assert finding.as_dict()["kind"] == "reference_disagreement"
    assert finding.as_dict()["apiome"] == "compatible" and finding.as_dict()["reference"] == "incompatible"
    assert corpus.disagreements(_case(), verdicts, references, [])[0].waiver is None


def test_build_expected_keeps_hand_written_fields_and_offline_recordings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(corpus, "apiome_verdicts", lambda case: {"BACKWARD": {"compatible": True}})
    previous = {
        "description": "d",
        "source": "s",
        "verdicts": {"OLD": {}},
        "references": {
            "confluent-schema-registry": {"version": "7", "verdicts": {}},
            "apicurio-registry": {"version": "1"},
        },
    }
    built = corpus.build_expected(_case(), previous, {"apicurio-registry": {"version": "2", "verdicts": {}}})
    assert built["description"] == "d" and built["source"] == "s"
    assert built["verdicts"] == {"BACKWARD": {"compatible": True}}
    assert built["references"]["confluent-schema-registry"]["version"] == "7"
    assert built["references"]["apicurio-registry"]["version"] == "2"


def test_prune_orphans_removes_incomplete_cases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(corpus, "CORPUS_ROOT", tmp_path)
    complete, orphan = tmp_path / "avro" / "complete", tmp_path / "avro" / "orphan"
    for directory in (complete, orphan):
        directory.mkdir(parents=True)
        (directory / "expected.json").write_text("{}")
    (complete / "base.avsc").write_text("{}")
    (complete / "head.avsc").write_text("{}")
    (orphan / "base.avsc").write_text("{}")
    assert corpus.prune_orphans() == [orphan]
    assert complete.is_dir() and not orphan.exists()
    assert [c.id for c in corpus.load_cases()] == ["avro/complete"]


def test_registry_detail_reads_error_types() -> None:
    messages = [
        "{errorType:'READER_FIELD_MISSING_DEFAULT_VALUE', description:'x'}",
        "{oldSchemaVersion: 1}",
        "{errorType:'READER_FIELD_MISSING_DEFAULT_VALUE', description:'y'}",
    ]
    assert corpus._registry_detail(messages) == ["READER_FIELD_MISSING_DEFAULT_VALUE"]


def test_registry_reference_needs_a_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(corpus.APICURIO_URL_ENV, raising=False)
    with pytest.raises(ReferenceUnavailableError):
        FORMATS["avro"].references[0].run(_case())


def test_strict_reads_one_or_a_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(corpus.STRICT_ENV, "buf, asyncapi-diff")
    assert corpus.is_strict("buf") and corpus.is_strict("asyncapi-diff") and not corpus.is_strict("graphql-inspector")
    monkeypatch.setenv(corpus.STRICT_ENV, "1")
    assert corpus.is_strict("graphql-inspector")
    monkeypatch.delenv(corpus.STRICT_ENV)
    assert not corpus.is_strict("buf")


def test_waiver_table_and_docs_section() -> None:
    assert "No known differences" in corpus.render_waiver_table([])
    table = corpus.render_waiver_table(
        [{"case": "protobuf/x", "tool": "buf", "modes": ["WIRE"], "reason": "a documented reason here"}]
    )
    assert "| `protobuf/x` | `buf breaking` | `WIRE` | a documented reason here |" in table
    page = f"intro\n{corpus.DOCS_START}\nold\n{corpus.DOCS_END}\noutro\n"
    assert corpus.replace_docs_section(page, []).startswith(f"intro\n{corpus.DOCS_START}\n\nNo known differences")
    with pytest.raises(ValueError):
        corpus.replace_docs_section("no markers", [])
