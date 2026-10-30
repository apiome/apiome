"""Collection export validate + round-trip — MFX-31.4 (#4292).

Covers :mod:`app.postman_roundtrip` and the ``postman`` export gate:

* **flavors** — a file is checked for what it is: a Postman collection by the v2.1.0 schema, an Insomnia
  export or a Bruno folder (the MFX-31.3 output modes, exercised here with real corpus files) by its
  import adapter; an unknown file and a mix of flavors are refused;
* **broken output is caught and fails the export job with detail** — every schema violation is one
  finding with its JSON path; not-JSON, a collection that does not import, and a job whose export breaks
  the schema (``EMITTED_ARTIFACT_INVALID``);
* **round trip** — every Postman corpus collection round-trips lossless with the fidelity report
  agreeing; other sources are pinned in ``fixtures/postman_roundtrip/measurements.json`` (regenerate with
  ``APIOME_REGEN_POSTMAN_ROUNDTRIP=1``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.catalog_conversion import build_conversion_source
from app.emitter import EmitResult, EmittedFile
from app.export_job_engine import ExportJobStartRequest, schedule_export_job
from app.export_validation import validate_emitted_artifact
from app.import_source import ImportSourceError
from app.postman_emitter import PostmanEmitOptions, PostmanEmitter
from app.postman_roundtrip import (
    MAX_SCHEMA_PROBLEMS,
    RoundTripStatus,
    check_emitted_collection,
    collection_flavor,
    postman_schema_problems,
    reimport_collection,
    round_trip_collection,
)

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "postman_roundtrip" / "measurements.json"
_POSTMAN_CORPUS = sorted((_EXAMPLES / "postman").glob("*.json"))
_OTHER_CORPUS = [
    (_EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml", "openapi"),
    (_EXAMPLES / "openapi" / "31-paths-comprehensive.yaml", "openapi"),
    (_EXAMPLES / "openapi" / "22-advanced-oneof-polymorphism.yaml", "openapi"),
    (_EXAMPLES / "raml" / "03-orders-service.raml", "raml"),
    (_EXAMPLES / "api-blueprint" / "01-simple-api.apib", "apiblueprint"),
]
_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


def _api(path: Path, fmt: str = "postman"):
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _export(*files: tuple) -> EmitResult:
    return EmitResult(files=[EmittedFile(path=p, content=c, media_type="application/json") for p, c in files],
                      media_type="application/json")


def _collection(**overrides: Any) -> str:
    document = {"info": {"name": "Shop", "schema": _SCHEMA},
                "item": [{"name": "List", "request": {"method": "GET", "url": "https://api.example.com/items"}}]}
    document.update(overrides)
    return json.dumps(document)


def _rules(problems: List[Dict[str, Any]]) -> List[str]:
    return [p["rule"] for p in problems]


def _summary(report) -> Dict[str, Any]:
    return {
        "status": report.status.value,
        "diff": [[e.entity, e.key, e.change.value] for e in report.diff.entries],
        "unexplained": [[e.entity, e.key, e.change.value] for e in report.unexplained],
        "overclaims": sorted(report.overclaims),
    }


# ===========================================================================
# Flavors
# ===========================================================================


def test_flavors_are_read_from_each_file() -> None:
    assert collection_flavor("a.postman_collection.json", "{}") == "postman"
    assert collection_flavor("a.json", _collection()) == "postman"
    insomnia = (_EXAMPLES / "insomnia" / "05-real-world-v4-payments-export.json").read_text(encoding="utf-8")
    assert collection_flavor("export.json", insomnia) == "insomnia"
    assert collection_flavor("orders/get-order.bru", "meta {\n}\n") == "bruno"
    assert collection_flavor("bruno.json", "{}") == "bruno"
    assert collection_flavor("notes.txt", "hello") is None
    assert collection_flavor("a.json", '{"info": {"schema": "https://example.com"}}') is None


def test_an_insomnia_export_is_checked_by_the_insomnia_adapter() -> None:
    path = _EXAMPLES / "insomnia" / "05-real-world-v4-payments-export.json"
    flavor, problems = check_emitted_collection(_export(("export.json", path.read_text(encoding="utf-8"))))
    assert (flavor, problems) == ("insomnia", [])


def test_a_bruno_folder_is_checked_by_the_bruno_adapter_as_one_upload() -> None:
    folder = _EXAMPLES / "bruno" / "07-flat-orders-collection"
    files = tuple((f"orders/{p.name}", p.read_text(encoding="utf-8")) for p in sorted(folder.iterdir()))
    flavor, problems = check_emitted_collection(_export(*files))
    assert (flavor, problems) == ("bruno", [])
    model = reimport_collection(_export(*files), "bruno")
    assert {op.key for op in model.operations()}


def test_a_broken_insomnia_export_is_caught_by_its_adapter() -> None:
    _flavor, problems = check_emitted_collection(_export(("export.json", '{"_type": "export", "resources": []}')))
    assert _rules(problems) == ["insomnia.reimport"]


def test_an_unknown_file_and_mixed_flavors_are_refused() -> None:
    assert _rules(check_emitted_collection(_export(("notes.txt", "hello")))[1]) == ["collection.unknown-file"]
    mixed = _export(("a.postman_collection.json", _collection()), ("b.bru", "meta {\n}\n"))
    assert _rules(check_emitted_collection(mixed)[1]) == ["collection.mixed-flavors"]


# ===========================================================================
# Broken output is caught
# ===========================================================================


@pytest.mark.parametrize("path", _POSTMAN_CORPUS, ids=lambda p: p.name)
def test_every_postman_export_passes_the_schema_and_imports(path: Path) -> None:
    assert check_emitted_collection(PostmanEmitter().emit(_api(path))) == ("postman", [])


def test_each_schema_violation_is_one_problem_with_its_json_path() -> None:
    broken = _collection(item=[{"name": "List", "request": {"method": 5, "url": "x"}}, {"name": 7}])
    problems = postman_schema_problems("Shop.postman_collection.json", broken)
    assert problems and set(_rules(problems)) == {"postman.schema"}
    assert all(p["path"].startswith("/item") for p in problems)
    assert all(p["file"] == "Shop.postman_collection.json" for p in problems)


def test_schema_problems_are_capped_with_a_count() -> None:
    items = [{"name": n} for n in range(MAX_SCHEMA_PROBLEMS + 10)]
    problems = postman_schema_problems("a.json", _collection(item=[{"request": {"method": 1}} for _ in items]))
    assert len(problems) == MAX_SCHEMA_PROBLEMS + 1 and "more schema violations" in problems[-1]["message"]


def test_not_json_is_caught() -> None:
    assert _rules(postman_schema_problems("a.postman_collection.json", "{nope")) == ["postman.json"]


def test_a_collection_that_does_not_import_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(result, flavor):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.postman_roundtrip.reimport_collection", failing)
    _flavor, problems = check_emitted_collection(_export(("a.postman_collection.json", _collection())))
    assert _rules(problems) == ["postman.reimport"]


def test_an_empty_export_is_refused() -> None:
    with pytest.raises(ValueError):
        check_emitted_collection(EmitResult(files=[], media_type="application/json"))


async def test_gate_reports_every_violation_with_its_path() -> None:
    api = _api(_POSTMAN_CORPUS[0])
    broken = _export(("Shop.postman_collection.json", _collection(info={"schema": _SCHEMA})))
    verdict = await validate_emitted_artifact("postman", broken, api=api)
    assert verdict.failed
    assert verdict.findings[0].keyword == "postman.schema" and verdict.findings[0].path == "/info"


async def test_gate_passes_a_valid_export() -> None:
    api = _api(_OTHER_CORPUS[0][0], "openapi")
    verdict = await validate_emitted_artifact("postman", PostmanEmitter().emit(api), api=api)
    assert verdict.applicable and verdict.validated and verdict.valid


async def test_broken_output_fails_the_job_with_detail() -> None:
    """MFX-31.4 acceptance: broken output is caught and fails the export job with detail."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _source, _wait_terminal

    def _emit_broken(*args, **kwargs):
        return _export(("widgets.postman_collection.json", _collection(item=[{"request": {"method": 5}}])))

    # `confirm`: a REST model → Postman conversion reports losses that need the caller's confirmation.
    request = ExportJobStartRequest(artifact="artifact-1", target="postman", confirm=True)
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(
        "app.export_job_engine.emit_canonical", side_effect=_emit_broken
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    findings = status["error"]["context"]["findings"]
    assert findings and all(f["keyword"] == "postman.schema" for f in findings)
    assert findings[0]["path"].startswith("/item/0") and findings[0]["file"] == "widgets.postman_collection.json"


# ===========================================================================
# Round trip
# ===========================================================================


@pytest.mark.parametrize("path", _POSTMAN_CORPUS, ids=lambda p: p.name)
def test_postman_corpus_round_trips_lossless_and_the_report_agrees(path: Path) -> None:
    report = round_trip_collection(_api(path))
    assert report.flavor == "postman"
    assert report.status is RoundTripStatus.LOSSLESS and report.explained and not report.diverges


@pytest.mark.parametrize("options", [{}, {"folder_strategy": "flat"}, {"variable_style": "inline"},
                                     {"example_depth": "full"}], ids=str)
def test_every_option_writes_a_valid_collection(options: Dict[str, str]) -> None:
    for path, fmt in _OTHER_CORPUS:
        report = round_trip_collection(_api(path, fmt), opts=PostmanEmitOptions(**options))
        assert report.valid, report.problems or report.import_error


def test_failure_verdicts() -> None:
    api = _api(_POSTMAN_CORPUS[0])
    empty = round_trip_collection(api, emit_result=EmitResult(files=[], media_type="application/json"))
    assert empty.status is RoundTripStatus.INVALID
    broken = round_trip_collection(api, emit_result=_export(("a.postman_collection.json", "{nope")))
    assert broken.status is RoundTripStatus.INVALID and not broken.diverges


def test_a_reimport_failure_is_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(result, flavor):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.postman_roundtrip.reimport_collection", failing)
    report = round_trip_collection(_api(_POSTMAN_CORPUS[0]))
    assert report.status is RoundTripStatus.UNPARSEABLE and report.import_error == "cannot normalize"


def test_measurements_match_the_fixture() -> None:
    measurements = {path.name: _summary(round_trip_collection(_api(path, fmt))) for path, fmt in _OTHER_CORPUS}
    if os.environ.get("APIOME_REGEN_POSTMAN_ROUNDTRIP"):
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
    assert measurements == json.loads(_GOLDEN.read_text(encoding="utf-8"))
