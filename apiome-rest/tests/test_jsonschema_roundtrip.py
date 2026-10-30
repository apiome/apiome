"""JSON Schema emitter validate + round-trip — MFX-21.4 (#4129).

Covers :mod:`app.jsonschema_roundtrip` and the ``json-schema`` export gate:

* **valid output passes** — every corpus source exports, under every draft, packaging, ``id_base``
  and the JTD mode, to documents that pass their metaschema, whose references all resolve, and that
  import again;
* **broken output fails** — a metaschema violation, a dangling ``#/$defs`` pointer, a per-type file
  that references a missing file, a relative reference that leaves the export, an invalid JTD
  document and a document that does not import are each caught with the rule that caught them — and
  fail the export job (``EMITTED_ARTIFACT_INVALID``) before delivery;
* the reference walker — nested ``$id`` bases, draft-04 ``id``, names under ``properties`` and data
  under ``enum`` / ``examples`` are not read as references, absolute references outside the export
  are left alone;
* **round trip** — every JSON Schema corpus file round-trips lossless with the fidelity report
  agreeing; the pinned fixture ``fixtures/jsonschema_roundtrip/measurements.json`` records what the
  draft-07 rebuild and other sources measure (regenerate with ``APIOME_REGEN_JSONSCHEMA_ROUNDTRIP=1``).
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
from app.jsonschema_emitter import JsonSchemaEmitOptions, JsonSchemaEmitter
from app.jsonschema_roundtrip import (
    RoundTripStatus,
    check_emitted_jsonschema,
    reimport_document,
    round_trip_jsonschema,
    unresolved_references,
)

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "jsonschema_roundtrip" / "measurements.json"
_SCHEMA_2020 = "https://json-schema.org/draft/2020-12/schema"
_JSON_SCHEMA_CORPUS = sorted((_EXAMPLES / "json-schema").glob("*.json"))
_OTHER_CORPUS = [
    _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml",
    _EXAMPLES / "openapi" / "22-advanced-oneof-polymorphism.yaml",
    _EXAMPLES / "protobuf" / "02-grpc-service.proto",
    _EXAMPLES / "avro" / "01-user-record.avsc",
    _EXAMPLES / "graphql" / "06-union-types.graphql",
]
_OPTION_SETS = [
    {},
    {"draft": "draft-07"},
    {"draft": "draft-04"},
    {"packaging": "per-type"},
    {"packaging": "per-type", "id_base": "https://schemas.example.com/shop"},
    {"draft": "draft-04", "id_base": "https://schemas.example.com/shop"},
    {"mode": "jtd"},
]


def _corpus_api(path: Path):
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    fmt = {".json": "json-schema", ".yaml": "openapi", ".proto": "protobuf", ".graphql": "graphql",
           ".avsc": "avro"}[path.suffix]
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _files(**documents: Any) -> EmitResult:
    """An export of hand-written documents, keyed by file name (``a_b`` → ``a.b``)."""
    files = [
        EmittedFile(path=name.replace("__", "."), content=json.dumps(doc), media_type="application/schema+json")
        for name, doc in documents.items()
    ]
    return EmitResult(files=files, media_type="application/schema+json")


def _rules(problems: List[Dict[str, Any]]) -> List[str]:
    return [p["rule"] for p in problems]


def _summary(report) -> Dict[str, Any]:
    return {
        "status": report.status.value,
        "diff": [[e.entity, e.key, e.change.value] for e in report.diff.entries] if report.diff else None,
        "unexplained": [[e.entity, e.key, e.change.value] for e in report.unexplained],
        "overclaims": sorted(report.overclaims),
    }


# ===========================================================================
# Valid output passes
# ===========================================================================


@pytest.mark.parametrize("options", _OPTION_SETS, ids=lambda o: ",".join(f"{k}={v}" for k, v in o.items()) or "default")
@pytest.mark.parametrize("path", [*_JSON_SCHEMA_CORPUS, *_OTHER_CORPUS], ids=lambda p: p.name)
def test_every_export_is_valid_and_imports(path: Path, options: Dict[str, str]) -> None:
    api = _corpus_api(path)
    opts = JsonSchemaEmitOptions(**options)
    report = round_trip_jsonschema(api, opts=opts)
    assert report.valid, report.problems or report.import_error
    # A JTD document, or a per-type export of several files, is validated and re-parsed but not diffed.
    if options.get("mode") == "jtd" or len(JsonSchemaEmitter().emit(api, opts=opts).files) > 1:
        assert report.status is RoundTripStatus.VALID and report.diff is None
    else:
        assert report.diff is not None


async def test_gate_passes_a_valid_export() -> None:
    api = _corpus_api(_OTHER_CORPUS[0])
    result = JsonSchemaEmitter().emit(api, opts=JsonSchemaEmitOptions(packaging="per-type"))
    verdict = await validate_emitted_artifact("json-schema", result, api=api)
    assert verdict.applicable and verdict.validated and verdict.valid


# ===========================================================================
# Broken output fails
# ===========================================================================


def test_a_metaschema_violation_is_caught() -> None:
    problems = check_emitted_jsonschema(_files(a__schema__json={"$schema": _SCHEMA_2020, "type": 5}))
    assert _rules(problems) == ["jsonschema.metaschema"]
    assert problems[0]["file"] == "a.schema.json"


def test_a_dangling_defs_pointer_is_caught_with_its_location() -> None:
    document = {"$schema": _SCHEMA_2020, "$defs": {"Pet": {"type": "object", "properties": {
        "owner": {"$ref": "#/$defs/Owner"}}}}}
    problems = check_emitted_jsonschema(_files(a__schema__json=document))
    assert _rules(problems) == ["jsonschema.unresolved-ref"]
    assert problems[0]["path"] == "/$defs/Pet/properties/owner/$ref"


def test_a_per_type_reference_to_a_missing_file_is_caught() -> None:
    order = {"$schema": _SCHEMA_2020, "title": "Order", "type": "object",
             "properties": {"pet": {"$ref": "Pet.schema.json"}, "owner": {"$ref": "Owner.schema.json"}}}
    pet = {"$schema": _SCHEMA_2020, "title": "Pet", "type": "object"}
    problems = check_emitted_jsonschema(_files(Order__schema__json=order, Pet__schema__json=pet))
    assert [(p["rule"], p["file"], p["path"]) for p in problems] == [
        ("jsonschema.unresolved-ref", "Order.schema.json", "/properties/owner/$ref")
    ]


def test_per_type_references_resolve_under_an_id_base() -> None:
    base = "https://schemas.example.com/shop"
    order = {"$schema": _SCHEMA_2020, "$id": f"{base}/Order.schema.json",
             "properties": {"pet": {"$ref": "Pet.schema.json"}, "abs": {"$ref": f"{base}/Pet.schema.json#/title"}}}
    pet = {"$schema": _SCHEMA_2020, "$id": f"{base}/Pet.schema.json", "title": "Pet"}
    assert unresolved_references({"Order.schema.json": order, "Pet.schema.json": pet}) == []
    order["properties"]["bad"] = {"$ref": f"{base}/Pet.schema.json#/$defs/Nope"}
    assert _rules(unresolved_references({"Order.schema.json": order, "Pet.schema.json": pet})) == [
        "jsonschema.unresolved-ref"
    ]


def test_a_relative_reference_that_leaves_the_export_is_caught() -> None:
    document = {"$schema": _SCHEMA_2020, "properties": {"x": {"$ref": "../other.schema.json"}}}
    assert _rules(check_emitted_jsonschema(_files(a__schema__json=document))) == ["jsonschema.unresolved-ref"]


def test_an_absolute_reference_outside_the_export_is_left_alone() -> None:
    document = {"$schema": _SCHEMA_2020, "properties": {"geo": {"$ref": "https://geojson.org/schema/Point.json"}}}
    assert check_emitted_jsonschema(_files(a__schema__json=document)) == []


def test_names_and_data_are_not_read_as_references() -> None:
    document = {
        "$schema": _SCHEMA_2020,
        "properties": {"$ref": {"type": "string"}},
        "enum": [{"$ref": "#/nowhere"}],
        "examples": [{"$ref": "#/nowhere"}],
        "default": {"$ref": "#/nowhere"},
    }
    assert unresolved_references({"a.json": document}) == []


def test_a_nested_id_moves_the_base_and_draft_04_uses_id() -> None:
    nested = {"$schema": _SCHEMA_2020, "$defs": {"inner": {"$id": "https://x.example/inner.json",
                                                            "$defs": {"leaf": {"type": "string"}},
                                                            "properties": {"l": {"$ref": "#/$defs/leaf"}}}}}
    assert unresolved_references({"a.json": nested}) == []
    draft4 = {"$schema": "http://json-schema.org/draft-04/schema#", "id": "https://x.example/a.json",
              "definitions": {"A": {"type": "string"}}, "properties": {"a": {"$ref": "#/definitions/A"}}}
    assert unresolved_references({"a.json": draft4}) == []


def test_an_invalid_jtd_document_is_caught() -> None:
    problems = check_emitted_jsonschema(_files(a__jtd__json={"definitions": {"A": {"type": "nonsense"}}, "ref": "A"}))
    assert _rules(problems) == ["jsonschema.jtd"]


def test_malformed_json_is_caught() -> None:
    result = EmitResult(files=[EmittedFile(path="a.json", content="{nope", media_type="application/json")],
                        media_type="application/json")
    assert _rules(check_emitted_jsonschema(result)) == ["jsonschema.metaschema"]


def test_an_empty_export_is_rejected() -> None:
    with pytest.raises(ValueError):
        check_emitted_jsonschema(EmitResult(files=[], media_type="application/json"))
    report = round_trip_jsonschema(_corpus_api(_JSON_SCHEMA_CORPUS[0]),
                                   emit_result=EmitResult(files=[], media_type="application/json"))
    assert report.status is RoundTripStatus.INVALID


def test_reimport_failure_is_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(text, **kw):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.jsonschema_roundtrip.reimport_document", failing)
    report = round_trip_jsonschema(_corpus_api(_JSON_SCHEMA_CORPUS[0]))
    assert report.status is RoundTripStatus.UNPARSEABLE and report.import_error == "cannot normalize"


def test_reimport_document_raises_import_errors() -> None:
    with pytest.raises(ImportSourceError):
        reimport_document("[1, 2]")


async def test_gate_rejects_each_broken_output_with_its_rule() -> None:
    api = _corpus_api(_JSON_SCHEMA_CORPUS[0])
    dangling = _files(a__schema__json={"$schema": _SCHEMA_2020, "$ref": "#/$defs/Missing"})
    verdict = await validate_emitted_artifact("json-schema", dangling, api=api)
    assert verdict.failed and [f.keyword for f in verdict.findings] == ["jsonschema.unresolved-ref"]
    assert verdict.findings[0].file == "a.schema.json" and verdict.findings[0].path == "/$ref"


async def test_gate_rejects_a_document_that_does_not_import(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(text, **kw):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.jsonschema_roundtrip.reimport_document", failing)
    api = _corpus_api(_JSON_SCHEMA_CORPUS[0])
    verdict = await validate_emitted_artifact("json-schema", JsonSchemaEmitter().emit(api), api=api)
    assert verdict.failed and verdict.findings[0].keyword == "jsonschema.reimport"


async def test_a_broken_export_fails_the_job_with_detail() -> None:
    """MFX-21.4 acceptance: deliberately broken output fails the export job, with detail, before delivery."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _source, _wait_terminal

    def _emit_broken(*args, **kwargs):
        return _files(widgets__schema__json={"$schema": _SCHEMA_2020, "$ref": "#/$defs/Missing"})

    request = ExportJobStartRequest(artifact="artifact-1", target="json-schema")
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(
        "app.export_job_engine.emit_canonical", side_effect=_emit_broken
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    findings = status["error"]["context"]["findings"]
    assert findings[0]["keyword"] == "jsonschema.unresolved-ref" and findings[0]["path"] == "/$ref"


# ===========================================================================
# Round trip
# ===========================================================================


@pytest.mark.parametrize("path", _JSON_SCHEMA_CORPUS, ids=lambda p: p.name)
def test_json_schema_corpus_round_trips_lossless_and_the_report_agrees(path: Path) -> None:
    report = round_trip_jsonschema(_corpus_api(path))
    assert report.status is RoundTripStatus.LOSSLESS
    assert report.explained and not report.diverges


def test_draft_07_rebuilds_match_the_report_where_measured() -> None:
    """Every draft-07 rebuild whose round trip changes nothing is predicted lossless-or-reported."""
    for path in _JSON_SCHEMA_CORPUS:
        report = round_trip_jsonschema(_corpus_api(path), opts=JsonSchemaEmitOptions(draft="draft-07"))
        assert report.valid
        if report.empirically_lossless:
            assert report.explained


def test_measurements_match_the_fixture() -> None:
    measurements = {}
    for path in _JSON_SCHEMA_CORPUS:
        report = round_trip_jsonschema(_corpus_api(path), opts=JsonSchemaEmitOptions(draft="draft-07"))
        measurements[f"{path.name} draft-07"] = _summary(report)
    for path in _OTHER_CORPUS:
        measurements[path.name] = _summary(round_trip_jsonschema(_corpus_api(path)))
    if os.environ.get("APIOME_REGEN_JSONSCHEMA_ROUNDTRIP"):
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
    assert measurements == json.loads(_GOLDEN.read_text(encoding="utf-8"))


def test_the_report_is_computed_for_the_export_options() -> None:
    """A draft downgrade's losses are predicted, so they explain what the downgrade changed."""
    api = _corpus_api(_JSON_SCHEMA_CORPUS[4])  # 05-allof-inheritance: rewritten for draft-07
    report = round_trip_jsonschema(api, opts=JsonSchemaEmitOptions(draft="draft-07"))
    assert report.predicted_losses and report.valid
