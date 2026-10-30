"""Thrift emitter validate + round-trip — MFX-25.4 (#4154).

The Apache Thrift compiler is not installed in CI (the image builds it; MFX-25.1), so the compiler
path is driven through :func:`app.thrift_compile.compile_thrift_idl` stood in for by a fake that raises
the compiler's own ``[ERROR:file:line]`` lines; thriftpy2 (a pure-Python dependency) always runs.
Covers:

* :func:`app.thrift_roundtrip.compile_problems` — compiler errors become findings with the compiler's
  detail; no compiler and ``include`` exports are reported, not failed;
* :func:`app.thrift_roundtrip.spot_check_thrift` — thriftpy2 parses every corpus export and agrees with
  the Thrift reader; an undefined type / enum value is caught; a disagreement is reported; includes
  resolve only inside the export;
* :func:`app.thrift_roundtrip.round_trip_thrift` — every Thrift corpus file round-trips lossless with
  the fidelity report agreeing; other sources are measured into the fixture
  ``fixtures/thrift_roundtrip/measurements.json`` (regenerate with ``APIOME_REGEN_THRIFT_ROUNDTRIP=1``);
* the gate and the export job — non-compiling output fails the job with the compiler's detail.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app import thrift_compile
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitResult, EmittedFile
from app.export_job_engine import ExportJobStartRequest, schedule_export_job
from app.export_validation import validate_emitted_artifact
from app.import_source import ImportSourceError
from app.thrift_emitter import ThriftEmitter
from app.thrift_parser import ThriftDocument, ThriftEnum, ThriftField, ThriftService, ThriftServiceMethod, ThriftStruct
from app.thrift_roundtrip import (
    RoundTripStatus,
    _reader_disagreements,
    compile_problems,
    reimport_thrift,
    round_trip_thrift,
    spot_check_thrift,
)

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "thrift_roundtrip" / "measurements.json"
_THRIFT_CORPUS = sorted((_EXAMPLES / "thrift").glob("*.thrift"))
_OTHER_CORPUS = [
    _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml",
    _EXAMPLES / "openapi" / "22-advanced-oneof-polymorphism.yaml",
    _EXAMPLES / "protobuf" / "02-grpc-service.proto",
    _EXAMPLES / "graphql" / "06-union-types.graphql",
    _EXAMPLES / "avro" / "01-user-record.avsc",
    _EXAMPLES / "wsdl" / "02-order-service.wsdl",
]
_COMPILER_ERROR = "[ERROR:Shop.thrift:3] (last token was 'Missing')\nType \"Missing\" has not been defined."


def _corpus_api(path: Path):
    if not path.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    fmt = {".thrift": "thrift", ".yaml": "openapi", ".proto": "protobuf", ".graphql": "graphql", ".avsc": "avro",
           ".wsdl": "wsdl"}[path.suffix]
    return build_conversion_source(
        {"id": "item-1", "name": path.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}
    ).api


def _idl(**files: str) -> EmitResult:
    """An export of hand-written files, keyed by name (``Shop__thrift`` → ``Shop.thrift``)."""
    return EmitResult(
        files=[EmittedFile(path=n.replace("__", "."), content=t, media_type="text/x-thrift") for n, t in files.items()],
        media_type="text/x-thrift",
    )


@pytest.fixture
def compiler(monkeypatch: pytest.MonkeyPatch):
    """Report the compiler present; it rejects any file containing ``Missing`` with its own error lines."""
    calls: List[str] = []

    async def _compile(path: str, content: str, **kwargs: Any) -> None:
        calls.append(path)
        if "Missing" in content:
            raise thrift_compile.ThriftCompileError("rejected", diagnostics=_COMPILER_ERROR.splitlines())

    monkeypatch.setattr(thrift_compile, "thrift_available", lambda: True)
    monkeypatch.setattr(thrift_compile, "compile_thrift_idl", _compile)
    return calls


@pytest.fixture
def no_compiler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(thrift_compile, "thrift_available", lambda: False)


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
# Compile
# ===========================================================================


async def test_compiler_errors_become_problems_with_the_compiler_detail(compiler) -> None:
    verdict, problems = await compile_problems(_idl(Shop__thrift="struct A { 1: Missing m }\n"))
    assert verdict == "thrift" and compiler == ["Shop.thrift"]
    assert [p["message"] for p in problems] == _COMPILER_ERROR.splitlines()
    assert {p["rule"] for p in problems} == {"thrift.compile"}


async def test_no_compiler_and_include_exports_are_reported_not_failed(no_compiler, monkeypatch) -> None:
    assert await compile_problems(_idl(Shop__thrift="struct A {}\n")) == ("unavailable", [])
    monkeypatch.setattr(thrift_compile, "thrift_available", lambda: True)
    assert await compile_problems(_idl(Shop__thrift='include "shared.thrift"\nstruct A {}\n')) == ("includes", [])


async def test_a_compiler_that_goes_missing_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _compile(path, content, **kwargs):
        raise thrift_compile.ThriftCompileError("not installed", unavailable=True)

    monkeypatch.setattr(thrift_compile, "thrift_available", lambda: True)
    monkeypatch.setattr(thrift_compile, "compile_thrift_idl", _compile)
    assert await compile_problems(_idl(Shop__thrift="struct A {}\n")) == ("unavailable", [])


# ===========================================================================
# thriftpy2 spot-check
# ===========================================================================


@pytest.mark.parametrize("path", [*_THRIFT_CORPUS, *_OTHER_CORPUS], ids=lambda p: p.name)
def test_thriftpy2_parses_every_export_and_agrees_with_the_reader(path: Path) -> None:
    result = ThriftEmitter().emit(_corpus_api(path))
    assert spot_check_thrift({f.path: f.content for f in result.files}) == []


def test_an_undefined_type_is_caught_by_thriftpy2() -> None:
    problems = spot_check_thrift({"Shop.thrift": "struct A { 1: optional Nope n }\n"})
    assert _rules(problems) == ["thrift.thriftpy2-parse"]
    assert problems[0]["file"] == "Shop.thrift" and "apiome-thriftpy2-" not in problems[0]["message"]


def test_an_enum_value_used_before_its_enum_is_caught() -> None:
    idl = "struct A { 1: optional E e = E.X }\nenum E { X = 1 }\n"
    assert _rules(spot_check_thrift({"Shop.thrift": idl})) == ["thrift.thriftpy2-parse"]


def test_the_emitter_declares_enums_before_the_structs_that_use_their_values() -> None:
    """MFX-25.4: the spot-check caught a field default naming an enum declared after it (04-telemetry)."""
    text = ThriftEmitter().emit(_corpus_api(_EXAMPLES / "thrift" / "04-telemetry-stress.thrift")).files[0].content
    assert text.index("enum Severity") < text.index("Severity severity = Severity.INFO")


def test_includes_resolve_only_inside_the_export() -> None:
    shared = "struct Money { 1: optional i64 cents }\n"
    order = 'include "shared.thrift"\nstruct Order { 1: optional shared.Money total }\n'
    assert spot_check_thrift({"orders.thrift": order, "shared.thrift": shared}) == []
    # An include of something the export does not carry is skipped, never looked up elsewhere.
    for target in ("missing.thrift", "../shared.thrift", "/etc/shared.thrift", "http://example.com/x.thrift"):
        idl = f'include "{target}"\nstruct Order {{ 1: optional i32 total }}\n'
        assert spot_check_thrift({"orders.thrift": idl}) == []


def test_a_parser_disagreement_is_reported() -> None:
    document = ThriftDocument(
        namespaces={}, includes=(), typedefs={},
        enums=(ThriftEnum(name="E", values=(("A", 1), ("B", 2))),),
        structs=(ThriftStruct(name="S", kind="struct", fields=(ThriftField(id=1, name="x", required=True,
                                                                           type_expr="string"),)),),
        services=(ThriftService(name="Svc", methods=(ThriftServiceMethod(name="get", return_type="S",
                                                                         parameters=(), throws=()),)),),
        raw="",
    )
    agreeing = {"enums": {"E": ["A", "B"]}, "structs": {"S": ("struct", {1: "x"})}, "services": {"Svc": {"get"}}}
    assert _reader_disagreements("a.thrift", document, agreeing) == []
    disagreeing = {"enums": {"E": ["A"]}, "structs": {"S": ("union", {2: "x"})}, "services": {}}
    problems = _reader_disagreements("a.thrift", document, disagreeing)
    assert _rules(problems) == ["thrift.parser-disagreement"] * 3
    assert "members" in problems[0]["message"] and "fields" in problems[1]["message"]


def test_reimport_raises_import_errors() -> None:
    with pytest.raises(ImportSourceError):
        reimport_thrift(_idl(Shop__thrift="not thrift at all {"))


# ===========================================================================
# Round trip
# ===========================================================================


@pytest.mark.parametrize("path", _THRIFT_CORPUS, ids=lambda p: p.name)
async def test_thrift_corpus_round_trips_lossless_and_the_report_agrees(path: Path, no_compiler) -> None:
    report = await round_trip_thrift(_corpus_api(path))
    assert report.status is RoundTripStatus.LOSSLESS and report.explained
    assert report.compiler == ("includes" if "includes" in path.name else "unavailable")


async def test_a_compiled_round_trip(compiler) -> None:
    report = await round_trip_thrift(_corpus_api(_THRIFT_CORPUS[0]))
    assert report.compiler == "thrift" and report.status is RoundTripStatus.LOSSLESS


async def test_compiler_rejection_makes_the_round_trip_invalid(compiler) -> None:
    broken = _idl(Shop__thrift="struct A {}\n// Missing\n")
    report = await round_trip_thrift(_corpus_api(_THRIFT_CORPUS[0]), emit_result=broken)
    assert report.status is RoundTripStatus.INVALID and not report.diverges


async def test_an_empty_export_and_a_failed_reimport(no_compiler, monkeypatch: pytest.MonkeyPatch) -> None:
    api = _corpus_api(_THRIFT_CORPUS[0])
    empty = await round_trip_thrift(api, emit_result=EmitResult(files=[], media_type="text/x-thrift"))
    assert empty.status is RoundTripStatus.INVALID

    def failing(_result):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.thrift_roundtrip.reimport_thrift", failing)
    report = await round_trip_thrift(api)
    assert report.status is RoundTripStatus.UNPARSEABLE and report.import_error == "cannot normalize"


async def test_measurements_match_the_fixture(no_compiler) -> None:
    measurements = {path.name: _summary(await round_trip_thrift(_corpus_api(path)))
                    for path in [*_THRIFT_CORPUS, *_OTHER_CORPUS]}
    if os.environ.get("APIOME_REGEN_THRIFT_ROUNDTRIP"):
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(measurements, indent=2) + "\n", encoding="utf-8")
    assert measurements == json.loads(_GOLDEN.read_text(encoding="utf-8"))


# ===========================================================================
# The gate and the export job
# ===========================================================================


async def test_gate_passes_valid_output_with_and_without_the_compiler(compiler, monkeypatch) -> None:
    api = _corpus_api(_OTHER_CORPUS[0])
    result = ThriftEmitter().emit(api)
    assert (await validate_emitted_artifact("thrift", result, api=api)).valid
    monkeypatch.setattr(thrift_compile, "thrift_available", lambda: False)
    assert (await validate_emitted_artifact("thrift", result, api=api)).valid


async def test_gate_rejects_a_thriftpy2_failure_without_the_compiler(no_compiler) -> None:
    api = _corpus_api(_THRIFT_CORPUS[0])
    verdict = await validate_emitted_artifact("thrift", _idl(Shop__thrift="struct A { 1: optional Nope n }\n"), api=api)
    assert verdict.failed and verdict.findings[0].keyword == "thrift.thriftpy2-parse"


async def test_gate_rejects_an_export_that_does_not_import(no_compiler, monkeypatch) -> None:
    def failing(_result):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.thrift_roundtrip.reimport_thrift", failing)
    api = _corpus_api(_THRIFT_CORPUS[0])
    verdict = await validate_emitted_artifact("thrift", ThriftEmitter().emit(api), api=api)
    assert verdict.failed and verdict.findings[0].keyword == "thrift.reimport"


async def test_non_compiling_output_fails_the_job_with_compiler_detail(compiler) -> None:
    """MFX-25.4 acceptance: non-compiling output fails the export job with the compiler's detail."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _source, _wait_terminal

    def _emit_broken(*args, **kwargs):
        return _idl(Shop__thrift="struct Widget {\n  1: optional string id,\n  2: optional Missing m,\n}\n")

    request = ExportJobStartRequest(artifact="artifact-1", target="thrift")
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(
        "app.export_job_engine.emit_canonical", side_effect=_emit_broken
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    findings = status["error"]["context"]["findings"]
    compile_findings = [f for f in findings if f["keyword"] == "thrift.compile"]
    assert [f["message"] for f in compile_findings] == _COMPILER_ERROR.splitlines()
    assert all(f["file"] == "Shop.thrift" for f in compile_findings)
