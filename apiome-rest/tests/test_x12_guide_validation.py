"""Validation of emitted X12 implementation guides — MFX-24.4 (#4148).

Covers :mod:`app.x12_guide_validation` and the ``x12-guide`` export gate:

* **fixtures pass** — the pinned guides in ``fixtures/x12_guide_validation/`` (a typed REST source and an
  imported X12 834, regenerate with ``APIOME_REGEN_X12_GUIDE_VALIDATION=1``), and every corpus source's
  guide for X12 005010 and 004010, pass every check, including the pyx12 dictionary spot-check;
* **broken guides fail** — each rule (schema, segment IDs, element refs, types, lengths, usage, code
  sets, envelope, referential integrity, positions, the CSV / Markdown agreeing with the JSON, the
  dictionary) is caught with its keyword, file and JSON Pointer, and every problem is reported, not
  only the first;
* the **dictionary spot-check** — read from pyx12's maps, skipped (with the reason) when pyx12 or the
  version's maps are missing;
* **the gate** — :func:`app.export_validation.validate_emitted_artifact` passes a good guide and rejects a
  broken one, and a broken guide fails the export job (``EMITTED_ARTIFACT_INVALID``) with detail;
* the emitter fixes the checks found: an ``004010`` guide's ``ST`` has no ``ST03``, and a guide with
  more than 98 segment uses keeps four-digit positions.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List
from unittest.mock import patch

import pytest

from app import x12_guide_validation as validation
from app.canonical_model import CanonicalApi, CanonicalField, Type, TypeKind, TypeRef
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, EmitResult, EmittedFile, coerce_emit_options, load_builtin_emitters
from app.export_job_engine import ExportJobStartRequest, schedule_export_job
from app.export_validation import validate_emitted_artifact
from app.x12_guide_emitter import X12GuideEmitter, _csv, _markdown
from app.x12_guide_validation import (
    GUIDE_SCHEMA,
    check_guide_files,
    dictionary_problems,
    guide_problems,
    load_x12_dictionary,
)

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "x12_guide_validation"
_REGEN = bool(os.environ.get("APIOME_REGEN_X12_GUIDE_VALIDATION"))

#: The pinned fixtures: a typed REST source (made-up segments) and an imported X12 834 (standard segments).
FIXTURE_SOURCES: Dict[str, tuple[str, str]] = {
    "petstore": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "benefit-enrollment-834": ("edi-x12/06-834-benefit-enrollment.edi", "edix12"),
}

_needs_pyx12 = pytest.mark.skipif(validation._pyx12_map_dir() is None, reason="pyx12 is not installed")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


def _source(path: str, fmt: str) -> CanonicalApi:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _emit(api: CanonicalApi, **options: Any) -> EmitResult:
    return X12GuideEmitter().emit(api, opts=coerce_emit_options(X12GuideEmitter, options))


def _files(result: EmitResult) -> Dict[str, str]:
    return {emitted.path: str(emitted.content) for emitted in result.files}


def _orders() -> CanonicalApi:
    """The guide emitter suite's typed model: a purchase order with a party, coded fields and repeating lines."""
    from test_x12_guide_emitter import _orders as orders

    return orders()


def _guide() -> Dict[str, Any]:
    return json.loads(_emit(_orders()).files[0].content)


def _rules(problems: List[Any]) -> List[str]:
    return [problem.rule for problem in problems]


# ===========================================================================
# Fixtures pass
# ===========================================================================


def test_the_pinned_guides_match_the_fixtures_and_pass() -> None:
    for name, ref in FIXTURE_SOURCES.items():
        files = _files(_emit(_source(*ref)))
        folder = _GOLDEN / name
        if _REGEN:
            folder.mkdir(parents=True, exist_ok=True)
            for path, text in files.items():
                (folder / path).write_text(text, encoding="utf-8")
        on_disk = {path.name: path.read_text(encoding="utf-8") for path in sorted(folder.iterdir())}
        assert on_disk == files, name
        check = check_guide_files(on_disk)
        assert check.problems == [], name


def test_every_corpus_source_gives_a_guide_that_passes_every_check() -> None:
    from corpus_roundtrip import representatives_by_format
    from export_conformance import _import_entry

    failures = []
    for family, entry in sorted(representatives_by_format().items()):
        if entry is None:
            continue
        try:
            api = _import_entry(entry)
        except Exception:  # noqa: BLE001 - the import matrix owns import failures
            continue
        for version in ("005010", "004010"):
            try:
                result = _emit(api, version=version)
            except EmitPreconditionError:
                break
            check = check_guide_files(_files(result))
            failures += [f"{family} {version}: {p.rule}: {p.message}" for p in check.problems]
    assert not failures, "\n".join(failures)


def test_the_schema_describes_the_emitted_guide() -> None:
    from jsonschema import Draft202012Validator

    Draft202012Validator.check_schema(GUIDE_SCHEMA)
    assert list(Draft202012Validator(GUIDE_SCHEMA).iter_errors(_guide())) == []


# ===========================================================================
# Broken guides fail, with the rule, the file and the pointer
# ===========================================================================


def _segment(guide: Dict[str, Any], seg_id: str) -> Dict[str, Any]:
    return next(s for s in guide["segments"] if s["id"] == seg_id)


def _coded(guide: Dict[str, Any]) -> Dict[str, Any]:
    """The first ID (coded) element made from the source."""
    return next(e for s in guide["segments"][1:-1] for e in s["elements"] if e["type"] == "ID")


BREAKS: List[tuple[str, Callable[[Dict[str, Any]], None], str]] = [
    ("schema", lambda g: g.pop("structure"), "'structure' is a required property"),
    ("schema", lambda g: g["segments"][1]["elements"][0].update(minLength="1"), "is not of type 'integer'"),
    ("transaction-set", lambda g: g["transactionSet"].update(id="85"), "3-digit"),
    ("version", lambda g: g.update(version="5010"), "6-digit"),
    ("segment-id", lambda g: g["segments"][1].update(id="order"), "not 2-3"),
    ("duplicate-segment", lambda g: g["segments"].insert(2, copy.deepcopy(g["segments"][1])), "defined twice"),
    ("element-ref", lambda g: g["segments"][1]["elements"][0].update(ref="ZZ09"), "must be"),
    ("element-type", lambda g: g["segments"][1]["elements"][0].update(type="XX"), "not an X12 element type"),
    ("lengths", lambda g: g["segments"][1]["elements"][0].update(minLength=5, maxLength=2), "minLength"),
    ("usage", lambda g: g["segments"][1]["elements"][0].update(usage="R"), "usage must be M, O or X"),
    ("codes", lambda g: _coded(g).pop("codes"), "needs a code list"),
    ("codes", lambda g: _coded(g).update(codes=["TOOLONGCODE"]), "characters"),
    ("codes", lambda g: _coded(g).update(codes=[_coded(g)["codes"][0]] * 2), "more than once"),
    ("codes", lambda g: g["segments"][1]["elements"][0].update(type="AN", codes=["X"]), "only an ID"),
    ("codes", lambda g: _coded(g).update(codeValues={"NOPE": "x"}), "codeValues"),
    ("codes", lambda g: _segment(g, "ST")["elements"][0].update(codes=["810"]), "ST01 must list"),
    ("envelope", lambda g: g["structure"].pop(0), "start with the ST"),
    ("undefined-segment", lambda g: g["structure"].insert(1, {"type": "segment", "position": "0150",
                                                              "segment": "ZZZ", "usage": "M", "maxUse": 1}),
     "not defined"),
    ("unused-segment", lambda g: g["segments"].insert(1, {"id": "ZZZ", "name": "Z", "elements": [
        {"ref": "ZZZ01", "name": "z", "type": "AN", "minLength": 1, "maxLength": 2, "usage": "O"}]}),
     "never uses it"),
    ("loop", lambda g: next(n for n in g["structure"] if n["type"] == "loop").update(loopId="XXX"),
     "start with its own segment"),
    ("position", lambda g: g["structure"][1].update(position="9999"), "not after"),
    ("position", lambda g: g["structure"][1].update(position="10000"), "four digits"),
    ("max-use", lambda g: g["structure"][1].update(maxUse=0), "maxUse"),
]


@pytest.mark.parametrize(("rule", "mutate", "message"), BREAKS, ids=[f"{r}-{m}" for r, _, m in BREAKS])
def test_each_rule_catches_its_break(rule: str, mutate: Callable[[Dict[str, Any]], None], message: str) -> None:
    guide = _guide()
    mutate(guide)
    problems = [p for p in guide_problems(guide) if p.rule == f"x12-guide.{rule}"]
    assert problems and any(message in p.message for p in problems), guide_problems(guide)
    assert all(p.path and p.path.startswith("/") for p in problems)


def test_every_problem_is_reported_not_only_the_first() -> None:
    guide = _guide()
    guide["transactionSet"]["id"] = "85"
    guide["segments"][1]["elements"][0]["usage"] = "R"
    guide["structure"][1]["maxUse"] = 0
    assert {"x12-guide.transaction-set", "x12-guide.usage", "x12-guide.max-use"} <= set(_rules(guide_problems(guide)))


def test_a_guide_of_the_wrong_shape_reports_only_its_schema_problems() -> None:
    guide = _guide()
    guide["segments"] = "none"
    assert set(_rules(guide_problems(guide))) == {"x12-guide.schema"}


def test_the_csv_and_markdown_must_say_what_the_json_says() -> None:
    files = _files(_emit(_orders()))
    csv_path = next(p for p in files if p.endswith(".csv"))
    md_path = next(p for p in files if p.endswith(".md"))
    files[csv_path] += "ZZZ,Extra,ZZZ01,extra,AN,1,2,O,,,\n"
    files[md_path] += "\nAn extra line.\n"
    problems = check_guide_files(files).problems
    assert [(p.rule, p.file) for p in problems] == [("x12-guide.files", csv_path), ("x12-guide.files", md_path)]


def test_a_missing_file_or_non_json_guide_is_reported() -> None:
    files = _files(_emit(_orders()))
    json_path = next(p for p in files if p.endswith(".json"))
    without_csv = {p: t for p, t in files.items() if not p.endswith(".csv")}
    assert [p.message for p in check_guide_files(without_csv).problems] == ["the export has no .x12-segments.csv file"]
    broken = {**files, json_path: "ST*850"}
    problem = check_guide_files(broken).problems[0]
    assert (problem.rule, problem.file) == ("x12-guide.schema", json_path) and "Not a JSON guide" in problem.message


# ===========================================================================
# The pyx12 dictionary spot-check
# ===========================================================================


@_needs_pyx12
def test_the_dictionary_is_read_from_pyx12s_maps() -> None:
    dictionary = load_x12_dictionary("005010")
    assert dictionary is not None and dictionary.version == "5010"
    assert dictionary.element_counts["ST"] == 3 and dictionary.element_counts["SE"] == 2
    assert dictionary.elements[("ST", 2)] == ("AN", 4, 9)
    assert load_x12_dictionary("004010").element_counts["ST"] == 2


@_needs_pyx12
def test_the_envelope_must_match_the_dictionary() -> None:
    guide = _guide()
    _segment(guide, "SE")["elements"][1]["maxLength"] = 12
    problems = dictionary_problems(guide, load_x12_dictionary("005010"))
    assert _rules(problems) == ["x12-guide.dictionary"] and "SE02" in problems[0].message
    assert problems[0].path.startswith("/segments/")


@_needs_pyx12
def test_a_carried_x12_segment_must_not_outgrow_the_standard() -> None:
    guide = json.loads(_emit(_source(*FIXTURE_SOURCES["benefit-enrollment-834"])).files[0].content)
    bgn = _segment(guide, "BGN")
    standard = load_x12_dictionary(guide["version"]).element_counts["BGN"]
    bgn["elements"] += [
        {"ref": f"BGN{n:02d}", "name": f"BGN{n:02d}", "type": "AN", "minLength": 1, "maxLength": 80, "usage": "O"}
        for n in range(len(bgn["elements"]) + 1, standard + 2)
    ]
    problems = dictionary_problems(guide, load_x12_dictionary(guide["version"]))
    assert any(f"segment BGN has {standard + 1} elements" in p.message for p in problems)


@_needs_pyx12
def test_a_segment_made_from_a_type_is_not_held_to_a_standard_segment_of_the_same_id() -> None:
    guide = _guide()
    segment = guide["segments"][1]
    segment["elements"] = [dict(segment["elements"][0], ref=f"{segment['id']}{n:02d}") for n in range(1, 30)]
    assert dictionary_problems(guide, load_x12_dictionary("005010")) == []


def test_the_spot_check_is_skipped_with_the_reason_without_pyx12(monkeypatch: pytest.MonkeyPatch) -> None:
    load_x12_dictionary.cache_clear()
    monkeypatch.setattr(validation, "_pyx12_map_dir", lambda: None)
    try:
        check = check_guide_files(_files(_emit(_orders())))
    finally:
        load_x12_dictionary.cache_clear()
    assert check.problems == [] and not check.dictionary_checked
    assert check.skipped_reason == "pyx12 is not installed"


@_needs_pyx12
def test_the_spot_check_is_skipped_for_a_version_pyx12_has_no_maps_for() -> None:
    check = check_guide_files(_files(_emit(_orders(), version="003040")))
    assert check.problems == [] and check.skipped_reason == "pyx12 ships no segment dictionary for X12 003040"


# ===========================================================================
# The export gate
# ===========================================================================


async def test_the_gate_passes_a_good_guide() -> None:
    api = _orders()
    verdict = await validate_emitted_artifact("x12-guide", _emit(api), api=api)
    assert verdict.applicable and verdict.validated and verdict.valid


async def test_the_gate_rejects_a_broken_guide_with_findings() -> None:
    api = _orders()
    result = _emit(api)
    guide = json.loads(result.files[0].content)
    guide["structure"].insert(1, {"type": "segment", "position": "0150", "segment": "ZZZ", "usage": "M", "maxUse": 1})
    files = [EmittedFile(path=result.files[0].path, content=json.dumps(guide), media_type="application/json"),
             *result.files[1:]]
    verdict = await validate_emitted_artifact("x12-guide", EmitResult(files=files, media_type="application/json"),
                                              api=api)
    assert verdict.failed
    finding = verdict.findings[0]
    assert (finding.keyword, finding.file, finding.path) == (
        "x12-guide.undefined-segment", result.files[0].path, "/structure/1/segment")


async def test_the_gate_says_when_the_spot_check_did_not_run(monkeypatch: pytest.MonkeyPatch) -> None:
    load_x12_dictionary.cache_clear()
    monkeypatch.setattr(validation, "_pyx12_map_dir", lambda: None)
    api = _orders()
    try:
        verdict = await validate_emitted_artifact("x12-guide", _emit(api), api=api)
    finally:
        load_x12_dictionary.cache_clear()
    assert verdict.valid and verdict.detail == (
        "The X12 segment-dictionary spot-check did not run: pyx12 is not installed.")


async def test_a_broken_guide_fails_the_export_job_with_detail() -> None:
    """MFX-24.4 acceptance: a broken guide fails the export job, with detail, before delivery."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _wait_terminal
    from test_export_job_engine import _source as job_source

    good = _emit(_orders())
    broken_guide = json.loads(good.files[0].content)
    broken_guide["version"] = "5010"

    def _emit_broken(*args: Any, **kwargs: Any) -> EmitResult:
        files = [EmittedFile(path=good.files[0].path, content=json.dumps(broken_guide), media_type="application/json"),
                 *good.files[1:]]
        return EmitResult(files=files, media_type="application/json")

    request = ExportJobStartRequest(artifact="artifact-1", target="x12-guide")
    with patch("app.export_job_engine.load_export_source", return_value=job_source()), patch(
        "app.export_job_engine.emit_canonical", side_effect=_emit_broken
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    assert "6-digit" in json.dumps(status["error"])


# ===========================================================================
# What the checks found in the emitter
# ===========================================================================


def test_an_004010_guide_has_no_st03() -> None:
    guide = json.loads(_emit(_orders(), version="004010").files[0].content)
    assert [e["ref"] for e in _segment(guide, "ST")["elements"]] == ["ST01", "ST02"]
    assert "ST03" in [e["ref"] for e in _segment(_guide(), "ST")["elements"]]


def test_a_guide_with_many_segments_keeps_four_digit_positions() -> None:
    def record(n: int) -> Type:
        return Type(key=f"R{n}", name=f"Record{n:03d}", kind=TypeKind.RECORD,
                    fields=[CanonicalField(key=f"R{n}.v", name="v", type=TypeRef(name="string"))])

    holder = Type(key="Holder", name="Holder", kind=TypeKind.RECORD, fields=[
        CanonicalField(key=f"Holder.r{n}", name=f"r{n}", type=TypeRef(name=f"R{n}")) for n in range(150)])
    from test_x12_guide_emitter import _api

    api = _api(holder, *(record(n) for n in range(150)))
    result = _emit(api)
    assert check_guide_files(_files(result)).problems == []
    positions = [n["position"] for n in json.loads(result.files[0].content)["structure"] if "position" in n]
    assert all(len(p) == 4 for p in positions) and positions == sorted(positions)


def test_the_renderers_are_the_ones_the_check_compares_with() -> None:
    files = _files(_emit(_orders()))
    guide = json.loads(next(t for p, t in files.items() if p.endswith(".json")))
    assert next(t for p, t in files.items() if p.endswith(".csv")) == _csv(guide)
    assert next(t for p, t in files.items() if p.endswith(".md")) == _markdown(guide)
