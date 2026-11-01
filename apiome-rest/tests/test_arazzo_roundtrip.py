"""Arazzo emitter validate + round-trip — MFX-10.3 (#3872).

Covers :mod:`app.arazzo_roundtrip`, the ``arazzo`` export gate and the emitter changes that make a
rebuilt document schema-valid:

* **invalid output fails** — every Arazzo schema violation is one finding with its JSON pointer (capped,
  then counted); not YAML; a document that does not import; an empty export; and an export job whose
  rebuilt output breaks the schema fails with ``EMITTED_ARTIFACT_INVALID``;
* **the schema follows the declared version** — a 1.1-only construct passes 1.1 and fails 1.0;
* **pass-through** — an Arazzo import is the user's own document: its schema violations are reported,
  never blocking, and every corpus workflow round-trips lossless;
* **rebuilt exports are valid** — every other corpus source exports to a schema-valid, importable
  document (placeholder ``sourceDescriptions``, ``info.version`` fallback, both ``SYNTH``); a source with
  nothing to sequence is refused (422). Measurements are pinned in
  ``fixtures/arazzo_roundtrip/measurements.json`` (regenerate with ``APIOME_REGEN_ARAZZO_ROUNDTRIP=1``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
import yaml

from app.arazzo_emitter import (
    DEFAULT_INFO_VERSION,
    ArazzoEmitter,
    is_workflow_source,
    synthesized_source_description,
)
from app.arazzo_roundtrip import (
    MAX_SCHEMA_PROBLEMS,
    RoundTripStatus,
    arazzo_schema_violations,
    check_emitted_arazzo,
    reimport_arazzo,
    round_trip_arazzo,
)
from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, Operation, OperationKind, Service
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, EmitResult, EmittedFile
from app.export_dispatch import dispatch_from_source
from app.export_job_engine import ExportJobStartRequest, schedule_export_job
from app.export_service import ExportError
from app.export_source import ExportSource
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import ImportSourceError
from app.lossiness import LossinessKind

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "arazzo_roundtrip" / "measurements.json"
_ARAZZO_CORPUS = sorted((_EXAMPLES / "arazzo").glob("*.yaml"))
#: Sources whose import needs no external toolchain, so the fixture is reproducible everywhere.
_OTHER_CORPUS = [
    (_EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml", "openapi"),
    (_EXAMPLES / "graphql" / "06-union-types.graphql", "graphql"),
    (_EXAMPLES / "thrift" / "01-user-service.thrift", "thrift"),
    (_EXAMPLES / "wsdl" / "02-order-service.wsdl", "wsdl"),
    (_EXAMPLES / "raml" / "01-simple-api.raml", "raml"),
]


def _api(path: Path, fmt: str = "arazzo") -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _rest_api(**overrides: Any) -> CanonicalApi:
    """A plain REST model with one operation and no workflow, version or source description."""
    fields: Dict[str, Any] = dict(
        paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="Shop"), title="Shop Orders",
        services=[Service(key="orders", name="Orders", operations=[
            Operation(key="GET /orders", name="listOrders", kind=OperationKind.REQUEST_RESPONSE,
                      http_method="GET", http_path="/orders", extras={"operationId": "listOrders"}),
        ])],
    )
    fields.update(overrides)
    return CanonicalApi(**fields)


def _document(**overrides: Any) -> Dict[str, Any]:
    document: Dict[str, Any] = {
        "arazzo": "1.0.1",
        "info": {"title": "Orders", "version": "1.0.0"},
        "sourceDescriptions": [{"name": "orders", "url": "./orders.openapi.yaml", "type": "openapi"}],
        "workflows": [{"workflowId": "list", "steps": [{"stepId": "list", "operationId": "listOrders"}]}],
    }
    document.update(overrides)
    return document


def _export(document: Any, path: str = "orders.arazzo.yaml") -> EmitResult:
    text = document if isinstance(document, str) else yaml.safe_dump(document, sort_keys=False)
    return EmitResult(files=[EmittedFile(path=path, content=text, media_type="application/yaml")],
                      media_type="application/yaml")


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
# Invalid output fails
# ===========================================================================


def test_a_valid_document_passes() -> None:
    assert check_emitted_arazzo(_export(_document())) == []


def test_each_schema_violation_is_one_problem_with_its_pointer() -> None:
    problems = check_emitted_arazzo(_export(_document(sourceDescriptions=[])))
    assert _rules(problems) == ["arazzo.schema"]
    assert problems[0]["path"] == "/sourceDescriptions" and problems[0]["file"] == "orders.arazzo.yaml"


def test_schema_problems_are_capped_with_a_count() -> None:
    steps = [{"stepId": f"s{i}", "operationId": "x", "unknown": i} for i in range(MAX_SCHEMA_PROBLEMS + 5)]
    problems = check_emitted_arazzo(_export(_document(workflows=[{"workflowId": "w", "steps": steps}])))
    assert len(problems) == MAX_SCHEMA_PROBLEMS + 1
    assert problems[-1]["message"].endswith("more schema violations.")


def test_not_yaml_is_caught() -> None:
    assert _rules(check_emitted_arazzo(_export("arazzo: [unclosed"))) == ["arazzo.yaml"]


def test_an_unreadable_version_is_one_violation() -> None:
    assert arazzo_schema_violations(_document(arazzo="2.0.0"))[0][0] == "/arazzo"


def test_a_document_that_does_not_import_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(result):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.arazzo_roundtrip.reimport_arazzo", failing)
    problems = check_emitted_arazzo(_export(_document()))
    assert _rules(problems) == ["arazzo.reimport"] and "cannot normalize" in problems[0]["message"]


def test_an_empty_export_is_refused() -> None:
    with pytest.raises(ValueError):
        check_emitted_arazzo(EmitResult(files=[], media_type="application/yaml"))


def test_reimport_raises_import_errors() -> None:
    with pytest.raises(ImportSourceError):
        reimport_arazzo(_export("[1, 2]"))


async def test_gate_reports_the_rule_and_pointer_for_a_rebuilt_document() -> None:
    verdict = await validate_emitted_artifact("arazzo", _export(_document(info={"title": "Orders"})), api=_rest_api())
    assert verdict.failed
    assert (verdict.findings[0].keyword, verdict.findings[0].path) == ("arazzo.schema", "/info")


async def test_invalid_output_fails_the_job() -> None:
    """MFX-10.3 acceptance: invalid output fails the export job, with detail, before delivery."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _source, _wait_terminal

    def _emit_broken(*args, **kwargs):
        return _export(_document(sourceDescriptions=[]), "widgets.arazzo.yaml")

    request = ExportJobStartRequest(artifact="artifact-1", target="arazzo", confirm=True)
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(
        "app.export_job_engine.emit_canonical", side_effect=_emit_broken
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    findings = status["error"]["context"]["findings"]
    assert findings and all(f["keyword"] == "arazzo.schema" for f in findings)
    assert findings[0]["path"] == "/sourceDescriptions" and findings[0]["file"] == "widgets.arazzo.yaml"


# ===========================================================================
# The schema follows the declared version
# ===========================================================================


def test_an_asyncapi_source_is_valid_in_1_1_and_not_in_1_0() -> None:
    sources = [{"name": "events", "url": "./events.asyncapi.yaml", "type": "asyncapi"}]
    assert arazzo_schema_violations(_document(arazzo="1.1.0", sourceDescriptions=sources)) == []
    assert any(pointer == "/sourceDescriptions/0/type"
               for pointer, _ in arazzo_schema_violations(_document(arazzo="1.0.1", sourceDescriptions=sources)))


# ===========================================================================
# Pass-through: the user's own Arazzo document
# ===========================================================================


@pytest.mark.parametrize("path", _ARAZZO_CORPUS, ids=lambda p: p.name)
def test_arazzo_corpus_round_trips_lossless_and_the_report_agrees(path: Path) -> None:
    report = round_trip_arazzo(_api(path))
    assert report.passthrough
    assert report.status is RoundTripStatus.LOSSLESS and report.explained and not report.diverges


def test_a_passthrough_document_reports_but_does_not_block_its_schema_violations() -> None:
    api = _api(_EXAMPLES / "arazzo" / "simple-workflow.yaml")  # spells workflows with `name`
    assert is_workflow_source(api)
    report = round_trip_arazzo(api)
    assert report.valid and report.problems == []
    assert report.schema_violations and {v["rule"] for v in report.schema_violations} == {"arazzo.schema"}
    assert check_emitted_arazzo(ArazzoEmitter().emit(api), passthrough=True) == []
    assert _rules(check_emitted_arazzo(ArazzoEmitter().emit(api)))[0] == "arazzo.schema"


async def test_gate_passes_a_passthrough_document() -> None:
    api = _api(_EXAMPLES / "arazzo" / "simple-workflow.yaml")
    verdict = await validate_emitted_artifact("arazzo", ArazzoEmitter().emit(api), api=api)
    assert verdict.applicable and verdict.validated and verdict.valid


# ===========================================================================
# Rebuilt exports are valid
# ===========================================================================


@pytest.mark.parametrize(("path", "fmt"), _OTHER_CORPUS, ids=lambda v: str(v))
def test_every_other_source_exports_a_valid_document(path: Path, fmt: str) -> None:
    report = round_trip_arazzo(_api(path, fmt))
    assert not report.passthrough
    assert report.valid, report.problems or report.import_error
    assert report.schema_violations == []


async def test_gate_passes_a_rebuilt_export() -> None:
    api = _api(*_OTHER_CORPUS[0])
    verdict = await validate_emitted_artifact("arazzo", ArazzoEmitter().emit(api), api=api)
    assert verdict.applicable and verdict.validated and verdict.valid


def test_a_rebuilt_document_carries_a_placeholder_source_and_a_version() -> None:
    api = _rest_api()
    result = ArazzoEmitter().emit(api)
    document = yaml.safe_load(result.files[0].content)
    assert document["sourceDescriptions"] == [synthesized_source_description(api)]
    assert document["sourceDescriptions"][0] == {
        "name": "Shop-Orders", "url": "./shop-orders.openapi.yaml", "type": "openapi"
    }
    assert document["info"]["version"] == DEFAULT_INFO_VERSION
    assert {"source-description-placeholder", "info-version-default"} <= {loss.subject for loss in result.losses}


def test_the_report_names_the_synthesized_source_and_version() -> None:
    root = [i for i in compute_lossiness_for_emitter(_rest_api(), ArazzoEmitter()).items if i.construct_key == ""]
    mappings = {i.target_mapping: i.kind for i in root}
    assert mappings["source API → placeholder sourceDescriptions entry"] is LossinessKind.SYNTH
    assert mappings[f"no version → {DEFAULT_INFO_VERSION}"] is LossinessKind.SYNTH


def test_a_source_with_its_own_version_and_sources_synthesizes_neither() -> None:
    sources = [{"name": "shop", "url": "https://example.com/shop.yaml", "type": "openapi"}]
    api = _rest_api(version="2.3.0", extras={"sourceDescriptions": sources})
    result = ArazzoEmitter().emit(api)
    document = yaml.safe_load(result.files[0].content)
    assert document["sourceDescriptions"] == sources and document["info"]["version"] == "2.3.0"
    assert not {"source-description-placeholder", "info-version-default"} & {loss.subject for loss in result.losses}
    root = [i for i in compute_lossiness_for_emitter(api, ArazzoEmitter()).items if i.construct_key == ""]
    assert not any("placeholder" in (i.target_mapping or "") or "no version" in (i.target_mapping or "")
                   for i in root)


def test_a_source_with_nothing_to_sequence_is_refused_with_a_422() -> None:
    api = _rest_api(services=[])
    assert ArazzoEmitter.source_unsupported_reason(api)
    with pytest.raises(EmitPreconditionError):
        ArazzoEmitter().emit(api)
    source = ExportSource(api=api, artifact_id="artifact-1", version_record_id="rev-1")
    with pytest.raises(ExportError) as raised:
        dispatch_from_source(source, "arazzo", confirm=True)
    assert raised.value.status_code == 422


def test_an_arazzo_import_is_never_refused() -> None:
    api = _rest_api(format="arazzo", services=[])
    assert ArazzoEmitter.source_unsupported_reason(api) is None


def test_failure_verdicts(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api(*_OTHER_CORPUS[0])
    empty = round_trip_arazzo(api, emit_result=EmitResult(files=[], media_type="application/yaml"))
    assert empty.status is RoundTripStatus.INVALID
    broken = round_trip_arazzo(api, emit_result=_export("arazzo: [unclosed"))
    assert broken.status is RoundTripStatus.INVALID and not broken.diverges

    def failing(result):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.arazzo_roundtrip.reimport_arazzo", failing)
    report = round_trip_arazzo(api)
    assert report.status is RoundTripStatus.UNPARSEABLE and report.import_error == "cannot normalize"


def test_measurements_match_the_fixture() -> None:
    measurements = {path.name: _summary(round_trip_arazzo(_api(path, fmt))) for path, fmt in _OTHER_CORPUS}
    if os.environ.get("APIOME_REGEN_ARAZZO_ROUNDTRIP"):
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
    assert measurements == json.loads(_GOLDEN.read_text(encoding="utf-8"))
