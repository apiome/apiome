"""Standalone XSD emitter validate + round-trip — MFX-22.5 (#4136).

Covers :mod:`app.xsd_roundtrip` and the ``xsd`` export gate:

* **valid output passes 1.0 and 1.1 modes** — every corpus source exports, as XSD 1.0 (built by the
  1.0 *and* 1.1 processors) and as XSD 1.1 (built by the 1.1 processor), to a valid schema that imports
  again; a multi-namespace export is checked as one set;
* **invalid output fails the job with detail** — unsafe or malformed XML, an ``xs:import`` that is not
  packaged, an unknown type, and a 1.1-only construct in a 1.0 schema are each caught with their rule,
  file and processor; an export job fails with ``EMITTED_ARTIFACT_INVALID`` before delivery;
* **round trip** — XSD sources round-trip through the XSD import, WSDL sources through the WSDL import
  path (the export spliced into the item's WSDL bundle); the pinned fixture
  ``fixtures/xsd_roundtrip/measurements.json`` records every measurement (regenerate with
  ``APIOME_REGEN_XSD_ROUNDTRIP=1``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, CanonicalField, Type, TypeKind, TypeRef
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitResult, EmittedFile
from app.export_job_engine import ExportJobStartRequest, schedule_export_job
from app.export_validation import validate_emitted_artifact
from app.import_source import ImportSourceError
from app.xsd_emitter import XsdEmitOptions, XsdEmitter
from app.xsd_roundtrip import RoundTripStatus, check_emitted_xsd, reimport_xsd, round_trip_xsd

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "xsd_roundtrip" / "measurements.json"
_XSD_CORPUS = sorted((_EXAMPLES / "xsd").glob("*.xsd"))
_WSDL_CORPUS = sorted((_EXAMPLES / "wsdl").glob("*.wsdl"))
_OTHER_CORPUS = [
    _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml",
    _EXAMPLES / "openapi" / "22-advanced-oneof-polymorphism.yaml",
    _EXAMPLES / "protobuf" / "02-grpc-service.proto",
    _EXAMPLES / "json-schema" / "10-comprehensive-ecommerce.json",
]
_NS = "http://example.com/pets"
_COMMON = "http://example.com/common"
_XS = 'xmlns:xs="http://www.w3.org/2001/XMLSchema"'


def _corpus_api(path: Path) -> CanonicalApi:
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    fmt = {".xsd": "xsd", ".wsdl": "wsdl", ".yaml": "openapi", ".proto": "protobuf", ".json": "json-schema"}
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt[path.suffix],
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _two_namespace_api() -> CanonicalApi:
    address = Type(key="Address", name="Address", kind=TypeKind.RECORD, namespace=_COMMON,
                   fields=[CanonicalField(key="Address.city", name="city", type=TypeRef(name="string"))])
    order = Type(key="Order", name="Order", kind=TypeKind.RECORD, namespace=_NS, fields=[
        CanonicalField(key="Order.id", name="id", type=TypeRef(name="string")),
        CanonicalField(key="Order.shipTo", name="shipTo", type=TypeRef(name="Address")),
    ])
    return CanonicalApi(paradigm=ApiParadigm.REST, format="openapi", identity=ApiIdentity(name="Orders", namespace=_NS),
                        types=[order, address])


def _documents(**docs: str) -> EmitResult:
    """An export of hand-written documents, keyed by file name (``a__xsd`` → ``a.xsd``)."""
    return EmitResult(
        files=[
            EmittedFile(path=n.replace("__", "."), content=t, media_type="application/xml") for n, t in docs.items()
        ],
        media_type="application/xml",
    )


def _rules(problems: List[Dict[str, Any]]) -> List[str]:
    return [p["rule"] for p in problems]


def _summary(report) -> Dict[str, Any]:
    return {
        "status": report.status.value,
        "import_path": report.import_path,
        "diff": [[e.entity, e.key, e.change.value] for e in report.diff.entries],
        "unexplained": [[e.entity, e.key, e.change.value] for e in report.unexplained],
        "overclaims": sorted(report.overclaims),
    }


# ===========================================================================
# Valid output passes 1.0 and 1.1 modes
# ===========================================================================


@pytest.mark.parametrize("version", ["1.0", "1.1"])
@pytest.mark.parametrize("path", [*_XSD_CORPUS, *_WSDL_CORPUS, *_OTHER_CORPUS], ids=lambda p: p.name)
def test_every_export_is_a_valid_schema_that_imports(path: Path, version: str) -> None:
    report = round_trip_xsd(_corpus_api(path), opts=XsdEmitOptions(xsd_version=version))
    assert report.valid, report.problems or report.import_error


@pytest.mark.parametrize("version", ["1.0", "1.1"])
def test_a_multi_namespace_export_is_checked_as_one_set(version: str) -> None:
    result = XsdEmitter().emit(_two_namespace_api(), opts=XsdEmitOptions(xsd_version=version))
    assert len(result.files) == 2
    assert check_emitted_xsd(result) == []
    assert round_trip_xsd(_two_namespace_api(), emit_result=result, opts=XsdEmitOptions(xsd_version=version)).valid


async def test_gate_passes_a_valid_export() -> None:
    api = _two_namespace_api()
    verdict = await validate_emitted_artifact("xsd", XsdEmitter().emit(api), api=api)
    assert verdict.applicable and verdict.validated and verdict.valid


# ===========================================================================
# Invalid output fails with detail
# ===========================================================================


def test_malformed_and_unsafe_xml_are_caught() -> None:
    assert _rules(check_emitted_xsd(_documents(a__xsd="<xs:schema"))) == ["xsd.xml"]
    doctype = f'<!DOCTYPE x [<!ENTITY e "boom">]><xs:schema {_XS}/>'
    problems = check_emitted_xsd(_documents(a__xsd=doctype))
    assert _rules(problems) == ["xsd.xml"] and problems[0]["file"] == "a.xsd"


@pytest.mark.parametrize("location", ["missing.xsd", "../common.xsd", "http://example.com/common.xsd"])
def test_an_import_that_is_not_packaged_is_caught(location: str) -> None:
    main = (f'<xs:schema {_XS} targetNamespace="urn:a"><xs:import namespace="urn:b" '
            f'schemaLocation="{location}"/></xs:schema>')
    problems = check_emitted_xsd(_documents(a__xsd=main))
    assert _rules(problems) == ["xsd.bundle-reference"]
    assert (problems[0]["file"], problems[0]["path"]) == ("a.xsd", location)


def test_an_unknown_type_fails_both_processors_with_the_file_named() -> None:
    result = XsdEmitter().emit(_two_namespace_api())
    common = result.files[1]
    broken = EmitResult(files=[result.files[0], EmittedFile(
        path=common.path, content=common.content.replace('type="xsd:string"', 'type="xsd:strang"'),
        media_type="application/xml")], media_type="application/xml")
    problems = check_emitted_xsd(broken)
    assert _rules(problems) == ["xsd.schema-1.0", "xsd.schema-1.1"]
    assert all("strang" in p["message"] for p in problems)
    assert {p["file"] for p in problems} == {common.path}
    assert all("xsd-export-" not in p["message"] for p in problems)  # the temporary folder is not leaked


def test_a_1_1_construct_in_a_1_0_schema_fails_the_1_0_processor() -> None:
    schema = (f'<xs:schema {_XS} targetNamespace="urn:a"><xs:complexType name="T"><xs:sequence/>'
              '<xs:assert test="true()"/></xs:complexType></xs:schema>')
    assert _rules(check_emitted_xsd(_documents(a__xsd=schema))) == ["xsd.schema-1.0"]
    marked = schema.replace("<xs:schema ", '<xs:schema xmlns:vc="http://www.w3.org/2007/XMLSchema-versioning" '
                                           'vc:minVersion="1.1" ')
    assert check_emitted_xsd(_documents(a__xsd=marked)) == []


def test_an_empty_export_is_invalid() -> None:
    with pytest.raises(ValueError):
        check_emitted_xsd(EmitResult(files=[], media_type="application/xml"))
    report = round_trip_xsd(_two_namespace_api(), emit_result=EmitResult(files=[], media_type="application/xml"))
    assert report.status is RoundTripStatus.INVALID


def test_reimport_raises_import_errors() -> None:
    with pytest.raises(ImportSourceError):
        reimport_xsd(_documents(a__xsd="<root/>"))


def test_a_reimport_failure_is_unparseable(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(_result):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.xsd_roundtrip.reimport_xsd", failing)
    report = round_trip_xsd(_two_namespace_api())
    assert report.status is RoundTripStatus.UNPARSEABLE and report.import_error == "cannot normalize"


async def test_gate_rejects_with_rule_file_and_path() -> None:
    api = _two_namespace_api()
    main = f'<xs:schema {_XS}><xs:import namespace="urn:b" schemaLocation="gone.xsd"/></xs:schema>'
    verdict = await validate_emitted_artifact("xsd", _documents(Orders__xsd=main), api=api)
    assert verdict.failed
    finding = verdict.findings[0]
    assert (finding.keyword, finding.file, finding.path) == ("xsd.bundle-reference", "Orders.xsd", "gone.xsd")


async def test_gate_rejects_an_export_that_does_not_import(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(_result):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.xsd_roundtrip.reimport_xsd", failing)
    api = _two_namespace_api()
    verdict = await validate_emitted_artifact("xsd", XsdEmitter().emit(api), api=api)
    assert verdict.failed and verdict.findings[0].keyword == "xsd.reimport"


async def test_invalid_output_fails_the_job_with_detail() -> None:
    """MFX-22.5 acceptance: invalid emitter output fails the export job, with detail, before delivery."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _source, _wait_terminal

    def _emit_broken(*args, **kwargs):
        return _documents(widgets__xsd=f'<xs:schema {_XS}><xs:element name="w" type="xs:strang"/></xs:schema>')

    request = ExportJobStartRequest(artifact="artifact-1", target="xsd")
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(
        "app.export_job_engine.emit_canonical", side_effect=_emit_broken
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    findings = status["error"]["context"]["findings"]
    assert [f["keyword"] for f in findings] == ["xsd.schema-1.0", "xsd.schema-1.1"]
    assert findings[0]["file"] == "widgets.xsd" and "strang" in findings[0]["message"]


# ===========================================================================
# Round trip
# ===========================================================================


@pytest.mark.parametrize("path", _XSD_CORPUS, ids=lambda p: p.name)
def test_xsd_sources_round_trip_through_the_xsd_import(path: Path) -> None:
    report = round_trip_xsd(_corpus_api(path))
    assert report.import_path == "xsd" and report.valid


@pytest.mark.parametrize("path", _WSDL_CORPUS, ids=lambda p: p.name)
def test_wsdl_sources_round_trip_through_the_wsdl_import_path(path: Path) -> None:
    report = round_trip_xsd(_corpus_api(path))
    assert report.import_path == "wsdl" and report.valid
    if path.name != "04-kitchen-sink.wsdl":  # its rpc multi-part messages measure as changed (fixture)
        assert report.status is RoundTripStatus.LOSSLESS and not report.diverges


def test_measurements_match_the_fixture() -> None:
    measurements = {path.name: _summary(round_trip_xsd(_corpus_api(path)))
                    for path in [*_XSD_CORPUS, *_WSDL_CORPUS, *_OTHER_CORPUS]}
    if os.environ.get("APIOME_REGEN_XSD_ROUNDTRIP"):
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
    assert measurements == json.loads(_GOLDEN.read_text(encoding="utf-8"))
