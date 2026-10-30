"""OpenRPC emitter validate + round-trip — MFX-33.3 (#4303).

Covers :mod:`app.openrpc_roundtrip` and the ``openrpc`` export gate:

* **invalid output fails** — every meta-schema violation is one finding with its JSON pointer (capped,
  then counted); not-JSON; a dangling ``#/components/…`` reference the meta-schema cannot see; a
  document that does not import; and an export job whose output breaks the meta-schema fails with
  ``EMITTED_ARTIFACT_INVALID``;
* **valid output passes** — every corpus source exports to a valid, importable document;
* **round trip** — every OpenRPC corpus file round-trips lossless with the fidelity report agreeing;
  other sources are pinned in ``fixtures/openrpc_roundtrip/measurements.json`` (regenerate with
  ``APIOME_REGEN_OPENRPC_ROUNDTRIP=1``).
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
from app.openrpc_emitter import OpenRpcEmitter, meta_schema_errors, meta_schema_violations
from app.openrpc_roundtrip import (
    MAX_META_SCHEMA_PROBLEMS,
    RoundTripStatus,
    check_emitted_openrpc,
    reimport_openrpc,
    round_trip_openrpc,
)

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "openrpc_roundtrip" / "measurements.json"
_OPENRPC_CORPUS = sorted((_EXAMPLES / "openrpc").glob("*.json"))
_OTHER_CORPUS = [
    (_EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml", "openapi"),
    (_EXAMPLES / "protobuf" / "02-grpc-service.proto", "protobuf"),
    (_EXAMPLES / "graphql" / "06-union-types.graphql", "graphql"),
    (_EXAMPLES / "thrift" / "01-user-service.thrift", "thrift"),
    (_EXAMPLES / "wsdl" / "02-order-service.wsdl", "wsdl"),
    (_EXAMPLES / "avro" / "01-user-record.avsc", "avro"),
]


def _api(path: Path, fmt: str = "openrpc"):
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _document(**overrides: Any) -> Dict[str, Any]:
    document = {
        "openrpc": "1.2.6",
        "info": {"title": "Wallet", "version": "1.0.0"},
        "methods": [{"name": "getBalance", "params": [],
                     "result": {"name": "balance", "schema": {"$ref": "#/components/schemas/Balance"}}}],
        "components": {"schemas": {"Balance": {"type": "integer"}}},
    }
    document.update(overrides)
    return document


def _export(document: Any, path: str = "Wallet.openrpc.json") -> EmitResult:
    text = document if isinstance(document, str) else json.dumps(document)
    return EmitResult(files=[EmittedFile(path=path, content=text, media_type="application/json")],
                      media_type="application/json")


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
    assert check_emitted_openrpc(_export(_document())) == []


def test_each_meta_schema_violation_is_one_problem_with_its_pointer() -> None:
    broken = _document(methods=[{"name": 5, "params": "x"}])
    problems = check_emitted_openrpc(_export(broken))
    assert problems and set(_rules(problems)) == {"openrpc.meta-schema"}
    assert all(p["path"].startswith("/methods") for p in problems)
    assert all(p["file"] == "Wallet.openrpc.json" for p in problems)


def test_meta_schema_problems_are_capped_with_a_count() -> None:
    broken = _document(methods=[{"name": n} for n in range(MAX_META_SCHEMA_PROBLEMS + 10)])
    problems = check_emitted_openrpc(_export(broken))
    assert len(problems) == MAX_META_SCHEMA_PROBLEMS + 1 and "more meta-schema" in problems[-1]["message"]


def test_the_string_helper_keeps_its_format() -> None:
    assert meta_schema_violations(_document()) == []
    assert meta_schema_errors({"openrpc": "1.2.6"}) == ["(root): 'info' is a required property",
                                                         "(root): 'methods' is a required property"]


def test_not_json_is_caught() -> None:
    assert _rules(check_emitted_openrpc(_export("{nope"))) == ["openrpc.json"]


def test_a_dangling_component_reference_is_caught() -> None:
    dangling = _document(components={"schemas": {}})
    problems = check_emitted_openrpc(_export(dangling))
    assert _rules(problems) == ["openrpc.unresolved-ref"]
    assert problems[0]["path"] == "/methods/0/result/schema/$ref"


def test_a_document_that_does_not_import_is_caught(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing(result):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.openrpc_roundtrip.reimport_openrpc", failing)
    assert _rules(check_emitted_openrpc(_export(_document()))) == ["openrpc.reimport"]


def test_an_empty_export_is_refused() -> None:
    with pytest.raises(ValueError):
        check_emitted_openrpc(EmitResult(files=[], media_type="application/json"))


def test_reimport_raises_import_errors() -> None:
    with pytest.raises(ImportSourceError):
        reimport_openrpc(_export("[1, 2]"))


async def test_gate_reports_the_rule_and_pointer() -> None:
    api = _api(_OPENRPC_CORPUS[0])
    verdict = await validate_emitted_artifact("openrpc", _export(_document(components={"schemas": {}})), api=api)
    assert verdict.failed
    assert (verdict.findings[0].keyword, verdict.findings[0].path) == (
        "openrpc.unresolved-ref", "/methods/0/result/schema/$ref"
    )


async def test_invalid_output_fails_the_job() -> None:
    """MFX-33.3 acceptance: invalid output fails the export job, with detail, before delivery."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _source, _wait_terminal

    def _emit_broken(*args, **kwargs):
        return _export(_document(methods=[{"name": "listWidgets", "params": "nope"}]), "widgets.openrpc.json")

    request = ExportJobStartRequest(artifact="artifact-1", target="openrpc", confirm=True)
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(
        "app.export_job_engine.emit_canonical", side_effect=_emit_broken
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    findings = status["error"]["context"]["findings"]
    assert findings and all(f["keyword"] == "openrpc.meta-schema" for f in findings)
    assert findings[0]["path"].startswith("/methods/0") and findings[0]["file"] == "widgets.openrpc.json"


# ===========================================================================
# Valid output passes, and the round trip
# ===========================================================================


@pytest.mark.parametrize("path", _OPENRPC_CORPUS, ids=lambda p: p.name)
def test_openrpc_corpus_round_trips_lossless_and_the_report_agrees(path: Path) -> None:
    report = round_trip_openrpc(_api(path))
    assert report.status is RoundTripStatus.LOSSLESS and report.explained and not report.diverges


@pytest.mark.parametrize(("path", "fmt"), _OTHER_CORPUS, ids=lambda v: str(v))
def test_every_other_source_exports_a_valid_document(path: Path, fmt: str) -> None:
    report = round_trip_openrpc(_api(path, fmt))
    assert report.valid, report.problems or report.import_error


async def test_gate_passes_a_valid_export() -> None:
    api = _api(_OTHER_CORPUS[0][0], "openapi")
    verdict = await validate_emitted_artifact("openrpc", OpenRpcEmitter().emit(api), api=api)
    assert verdict.applicable and verdict.validated and verdict.valid


def test_failure_verdicts(monkeypatch: pytest.MonkeyPatch) -> None:
    api = _api(_OPENRPC_CORPUS[0])
    empty = round_trip_openrpc(api, emit_result=EmitResult(files=[], media_type="application/json"))
    assert empty.status is RoundTripStatus.INVALID
    broken = round_trip_openrpc(api, emit_result=_export("{nope"))
    assert broken.status is RoundTripStatus.INVALID and not broken.diverges

    def failing(result):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.openrpc_roundtrip.reimport_openrpc", failing)
    report = round_trip_openrpc(api)
    assert report.status is RoundTripStatus.UNPARSEABLE and report.import_error == "cannot normalize"


def test_measurements_match_the_fixture() -> None:
    measurements = {path.name: _summary(round_trip_openrpc(_api(path, fmt))) for path, fmt in _OTHER_CORPUS}
    if os.environ.get("APIOME_REGEN_OPENRPC_ROUNDTRIP"):
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
    assert measurements == json.loads(_GOLDEN.read_text(encoding="utf-8"))
