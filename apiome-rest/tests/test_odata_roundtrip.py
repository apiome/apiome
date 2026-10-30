"""OData emitter validate + round-trip (OASIS schema) — MFX-16.3 (#3899).

Covers :mod:`app.odata_roundtrip`, the ``odata`` export gate and the emitter fix the new checks surfaced:

* **checks** — every OASIS CSDL JSON schema and EDMX / EDM XML schema violation is one finding with its
  JSON pointer; a ``$Type`` that names nothing and a ``$Key`` property that does not exist are caught by
  reference and key resolution (which no schema can see); unparseable text; ``output: both`` documents
  that describe different models;
* **the emitter fix** — an OData source's own type names are re-qualified into the one namespace the
  export writes (``Example.Sales.InvoiceLine`` → ``Example.Core.InvoiceLine``), and a name the item does
  not declare (a TypeDefinition the import did not keep) falls back to the canonical type, reported on the
  type it is in;
* **job** — invalid output fails the export job with ``EMITTED_ARTIFACT_INVALID`` and its findings;
* **round trip** — every OData corpus document round-trips with the fidelity report agreeing, under every
  output; other sources are pinned in ``fixtures/odata_roundtrip/measurements.json`` (regenerate with
  ``APIOME_REGEN_ODATA_ROUNDTRIP=1``).
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
from app.odata_emitter import ODataEmitOptions, ODataEmitter
from app.odata_roundtrip import RoundTripStatus, check_emitted_odata, round_trip_odata

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "odata_roundtrip" / "measurements.json"
_ODATA_CORPUS = sorted(p for p in (_EXAMPLES / "odata").glob("*.*") if p.suffix in (".edmx", ".json"))
_OTHER_CORPUS = [
    (_EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml", "openapi"),
    (_EXAMPLES / "openapi" / "22-advanced-oneof-polymorphism.yaml", "openapi"),
    (_EXAMPLES / "protobuf" / "02-grpc-service.proto", "protobuf"),
    (_EXAMPLES / "graphql" / "06-union-types.graphql", "graphql"),
    (_EXAMPLES / "json-schema" / "10-comprehensive-ecommerce.json", "json-schema"),
]


def _api(path: Path, fmt: str = "odata"):
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _csdl(**product: Any) -> Dict[str, Any]:
    entity = {"$Kind": "EntityType", "$Key": ["ID"], "ID": {"$Type": "Edm.Int32"}, "Name": {"$Nullable": True}}
    entity.update(product)
    return {
        "$Version": "4.01",
        "$EntityContainer": "Demo.Service",
        "Demo": {"Product": entity, "Service": {"$Kind": "EntityContainer",
                                                "Products": {"$Collection": True, "$Type": "Demo.Product"}}},
    }


def _export(*files: tuple) -> EmitResult:
    return EmitResult(
        files=[EmittedFile(path=p, content=c if isinstance(c, str) else json.dumps(c), media_type="application/json")
               for p, c in files],
        media_type="application/json",
    )


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
# Checks
# ===========================================================================


def test_a_valid_document_passes() -> None:
    assert check_emitted_odata(_export(("Demo.csdl.json", _csdl()))) == []


def test_each_csdl_json_schema_violation_is_one_finding_with_its_pointer() -> None:
    document = _csdl(Name={"$MaxLength": "x"})
    document["Demo"]["Order"] = {"$Kind": "ComplexType", "Total": {"$Precision": "x"}}
    problems = check_emitted_odata(_export(("Demo.csdl.json", document)))
    # The OASIS schema names the most specific violation in each type, so two types give two findings.
    assert _rules(problems) == ["odata.csdl-schema", "odata.csdl-schema"]
    assert {p["path"] for p in problems} == {"/Demo/Product/Name/$MaxLength", "/Demo/Order/Total/$Precision"}
    assert all(p["file"] == "Demo.csdl.json" for p in problems)


def test_a_dangling_type_is_caught_by_resolution() -> None:
    problems = check_emitted_odata(_export(("Demo.csdl.json", _csdl(Owner={"$Type": "Demo.Missing"}))))
    assert _rules(problems) == ["odata.unresolved-reference"]
    assert problems[0]["path"] == "/Demo/Product/Owner/$Type" and "Demo.Missing" in problems[0]["message"]


def test_a_key_property_that_does_not_exist_is_caught() -> None:
    problems = check_emitted_odata(_export(("Demo.csdl.json", _csdl(**{"$Key": ["Nope"]}))))
    assert _rules(problems) == ["odata.key"]


def test_a_csdl_xml_schema_violation_is_caught() -> None:
    xml = ODataEmitter().emit(_api(_ODATA_CORPUS[2]), opts=ODataEmitOptions(output="xml")).files[0]
    broken = xml.content.replace("<EntityType ", '<EntityType Bogus="1" ', 1)
    problems = check_emitted_odata(_export((xml.path, broken)))
    assert "odata.csdl-xml-schema" in _rules(problems)
    assert all(p["file"] == xml.path for p in problems)


def test_unparseable_text_is_caught() -> None:
    assert _rules(check_emitted_odata(_export(("Demo.csdl.json", "{nope")))) == ["odata.parse"]


def test_two_outputs_that_disagree_are_caught() -> None:
    result = ODataEmitter().emit(_api(_ODATA_CORPUS[2]), opts=ODataEmitOptions(output="both"))
    json_file = next(f for f in result.files if f.path.endswith(".json"))
    other = _csdl()
    problems = check_emitted_odata(_export((json_file.path, other), *[(f.path, f.content) for f in result.files
                                                                       if f is not json_file]))
    assert _rules(problems) == ["odata.outputs-disagree"]


def test_an_empty_export_is_refused() -> None:
    with pytest.raises(ValueError):
        check_emitted_odata(EmitResult(files=[], media_type="application/json"))
    report = round_trip_odata(_api(_ODATA_CORPUS[0]), emit_result=EmitResult(files=[], media_type="application/json"))
    assert report.status is RoundTripStatus.INVALID


def test_a_document_that_does_not_import_is_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(document):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.odata_roundtrip._normalize", failing)
    report = round_trip_odata(_api(_ODATA_CORPUS[0]))
    assert report.status is RoundTripStatus.UNPARSEABLE and "cannot normalize" in report.import_error
    assert _rules(check_emitted_odata(ODataEmitter().emit(_api(_ODATA_CORPUS[0])))) == ["odata.reimport"]


# ===========================================================================
# The emitter fix
# ===========================================================================


def test_names_from_another_source_namespace_are_requalified() -> None:
    api = _api(_EXAMPLES / "odata" / "04-inheritance-two-schemas.edmx")
    text = ODataEmitter().emit(api).files[0].content
    assert "Example.Sales." not in text
    assert check_emitted_odata(ODataEmitter().emit(api)) == []


def test_an_undeclared_stored_type_falls_back_and_is_reported_on_its_type() -> None:
    api = _api(_EXAMPLES / "odata" / "05-stress-service-surface.edmx")
    result = ODataEmitter().emit(api)
    assert "Example.Warehouse.Sku" not in result.files[0].content
    losses = [loss for loss in result.losses if loss.subject == "stored-type-undeclared"]
    assert [loss.pointer for loss in losses] == ["Example.Warehouse.Bin"]
    assert check_emitted_odata(result) == []


# ===========================================================================
# Gate and job
# ===========================================================================


async def test_gate_passes_valid_output_and_rejects_with_pointer() -> None:
    api = _api(_ODATA_CORPUS[0])
    assert (await validate_emitted_artifact("odata", ODataEmitter().emit(api), api=api)).valid
    broken = _export(("Demo.csdl.json", _csdl(Owner={"$Type": "Demo.Missing"})))
    verdict = await validate_emitted_artifact("odata", broken, api=api)
    assert verdict.failed
    assert (verdict.findings[0].keyword, verdict.findings[0].path) == ("odata.unresolved-reference",
                                                                       "/Demo/Product/Owner/$Type")


async def test_invalid_output_fails_the_job_with_detail() -> None:
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _source, _wait_terminal

    def _emit_broken(*args, **kwargs):
        return _export(("widgets.csdl.json", _csdl(Owner={"$Type": "Demo.Missing"})))

    request = ExportJobStartRequest(artifact="artifact-1", target="odata", confirm=True)
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(
        "app.export_job_engine.emit_canonical", side_effect=_emit_broken
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    finding = status["error"]["context"]["findings"][0]
    assert (finding["keyword"], finding["path"], finding["file"]) == (
        "odata.unresolved-reference", "/Demo/Product/Owner/$Type", "widgets.csdl.json")


# ===========================================================================
# Round trip
# ===========================================================================


@pytest.mark.parametrize("output", ["json", "xml", "both"])
@pytest.mark.parametrize("path", _ODATA_CORPUS, ids=lambda p: p.name)
def test_odata_corpus_round_trips_and_the_report_agrees(path: Path, output: str) -> None:
    report = round_trip_odata(_api(path), opts=ODataEmitOptions(output=output))
    assert report.valid, report.problems or report.import_error
    assert report.explained and not report.diverges, (report.unexplained, report.overclaims)


@pytest.mark.parametrize(("path", "fmt"), _OTHER_CORPUS, ids=lambda v: str(v))
def test_every_other_source_exports_valid_metadata(path: Path, fmt: str) -> None:
    for output in ("json", "xml", "both"):
        report = round_trip_odata(_api(path, fmt), opts=ODataEmitOptions(output=output))
        assert report.valid, (output, report.problems or report.import_error)


def test_measurements_match_the_fixture() -> None:
    measurements = {path.name: _summary(round_trip_odata(_api(path, fmt))) for path, fmt in _OTHER_CORPUS}
    if os.environ.get("APIOME_REGEN_ODATA_ROUNDTRIP"):
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
    assert measurements == json.loads(_GOLDEN.read_text(encoding="utf-8"))
