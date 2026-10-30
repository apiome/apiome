"""TypeSpec emitter validate + round-trip (``tsp compile``) — MFX-15.3 (#3895).

Covers :mod:`app.typespec_roundtrip` and the ``typespec`` export gate:

* the round-trip verdicts — ``skipped`` without a compiler, ``invalid`` on a compile error,
  ``unparseable`` when the emitted OpenAPI does not import, ``lossy`` / ``lossless`` against the
  direct-OpenAPI baseline — and the ``valid`` / ``diverges`` flags;
* the round-trip fixture: ``fixtures/typespec_roundtrip/pets.openapi.json`` is what ``tsp`` 0.65
  emits for the pets export; the tsp-free tests stand it in for the compiler, and a live test proves
  the compiler still emits it;
* the gate: a compile error, and an emitted OpenAPI that does not import, both reject the export;
* with ``tsp`` installed, every corpus export compiles, imports, and is measured.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_typespec_emitter import _COMPILE_CORPUS, _EXAMPLES, _corpus_api, _emit, _pets_api, needs_tsp

from app.emitter import EmitResult
from app.export_validation import validate_emitted_artifact
from app.import_source import ImportSourceError
from app.typespec_compile import TypeSpecCompiled, openapi_sha256
from app.typespec_roundtrip import (
    RoundTripStatus,
    compile_emitted_typespec,
    compile_error_diagnostics,
    import_compiled_openapi,
    round_trip_typespec,
)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "typespec_roundtrip" / "pets.openapi.json"


def _pets_openapi() -> dict:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _compiler_returning(document: dict):
    """A stand-in for ``compile_typespec_set`` that 'compiles' to ``document``."""

    def compile_set(members, root, **_kw):
        return TypeSpecCompiled(
            openapi=document,
            root_text=members[root],
            source_files=(root,),
            namespaces=(),
            openapi_sha256=openapi_sha256(document),
        )

    return compile_set


def _compiler_raising(message: str, code: str):
    def compile_set(members, root, **_kw):
        raise ImportSourceError(message, code=code)

    return compile_set


@pytest.fixture
def fixture_compiler(monkeypatch):
    """Compile every TypeSpec export to the recorded pets OpenAPI."""
    monkeypatch.setattr("app.typespec_compile.compile_typespec_set", _compiler_returning(_pets_openapi()))


# ===========================================================================
# Round-trip verdicts
# ===========================================================================


def test_pets_round_trip_measures_the_typespec_hop(fixture_compiler) -> None:
    report = round_trip_typespec(_pets_api())
    assert report.status is RoundTripStatus.LOSSY
    assert report.valid and report.compiled and report.reimported
    assert report.openapi["openapi"] == "3.0.0"
    changed = {(change.key, tuple(f.field for f in change.fields)) for change in report.diff.changes}
    # @typespec/openapi3 names operations <Interface>_<op> and adds int32 to a plain integer.
    assert ("GET /pets", ("extras", "name", "parameters")) in changed
    assert ("Error.code", ("constraints",)) in changed
    assert not report.diverges  # the emitter predicted a loss, and one was measured


def test_identical_documents_round_trip_lossless(monkeypatch) -> None:
    api = import_compiled_openapi(_pets_openapi())
    monkeypatch.setattr("app.typespec_roundtrip._baseline", lambda _api: api)
    monkeypatch.setattr("app.typespec_compile.compile_typespec_set", _compiler_returning(_pets_openapi()))
    report = round_trip_typespec(_pets_api())
    assert report.status is RoundTripStatus.LOSSLESS
    assert report.empirically_lossless
    assert report.diverges is not report.predicted_lossless  # predicted 1 loss, measured none


def test_no_compiler_is_skipped_not_invalid(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.typespec_compile.compile_typespec_set", _compiler_raising("tsp is not installed", "ADAPTER_UNAVAILABLE")
    )
    report = round_trip_typespec(_pets_api())
    assert report.status is RoundTripStatus.SKIPPED
    assert not report.valid and report.diff is None and not report.diverges


def test_compile_error_is_invalid_with_its_diagnostics(monkeypatch) -> None:
    line = "Pet_Store.tsp:3:7 - error unknown-identifier: Unknown identifier Pett"
    monkeypatch.setattr(
        "app.typespec_compile.compile_typespec_set",
        _compiler_raising(f"TypeSpec compile failed: {line}", "INPUT_SEMANTIC_INVALID"),
    )
    report = round_trip_typespec(_pets_api())
    assert report.status is RoundTripStatus.INVALID
    assert report.compile_errors[0]["code"] == "unknown-identifier"
    assert report.compile_errors[0]["line"] == 3


def test_compile_error_without_diagnostic_lines_keeps_the_message() -> None:
    rows = compile_error_diagnostics(ImportSourceError("timed out", code="INPUT_TIME_LIMIT"), "a.tsp")
    assert rows == [{"code": "INPUT_TIME_LIMIT", "message": "timed out", "file": "a.tsp", "line": None, "column": None}]


@pytest.mark.parametrize(
    "document",
    [{"info": {"title": "x"}}, {"openapi": "3.0.0", "info": {"title": "x", "version": "1"}, "paths": "nope"}],
    ids=["no-version-marker", "paths-not-a-mapping"],
)
def test_openapi_that_does_not_import_is_unparseable(monkeypatch, document) -> None:
    monkeypatch.setattr("app.typespec_compile.compile_typespec_set", _compiler_returning(document))
    report = round_trip_typespec(_pets_api())
    assert report.status is RoundTripStatus.UNPARSEABLE
    assert report.compiled and not report.reimported and report.import_error


def test_an_empty_export_is_invalid() -> None:
    report = round_trip_typespec(_pets_api(), emit_result=EmitResult(files=[], media_type="text/plain"))
    assert report.status is RoundTripStatus.INVALID
    with pytest.raises(ValueError):
        compile_emitted_typespec(EmitResult(files=[], media_type="text/plain"))


def test_a_given_emission_is_used_as_is(fixture_compiler) -> None:
    result = _emit(_pets_api())
    report = round_trip_typespec(_pets_api(), emit_result=result)
    assert report.predicted_losses == list(result.losses)


# ===========================================================================
# The export gate
# ===========================================================================


async def test_gate_passes_when_the_compiled_openapi_imports(fixture_compiler) -> None:
    api = _pets_api()
    verdict = await validate_emitted_artifact("typespec", _emit(api), api=api)
    assert verdict.applicable and verdict.validated and verdict.valid


async def test_gate_rejects_compiled_openapi_that_does_not_import(monkeypatch) -> None:
    monkeypatch.setattr("app.typespec_compile.compile_typespec_set", _compiler_returning({"info": {"title": "x"}}))
    api = _pets_api()
    verdict = await validate_emitted_artifact("typespec", _emit(api), api=api)
    assert verdict.failed
    assert verdict.findings[0].keyword == "typespec.openapi-import"
    assert verdict.findings[0].file == "Pet_Store.tsp"


async def test_gate_rejects_a_compile_error_with_its_location(monkeypatch) -> None:
    line = "Pet_Store.tsp:3:7 - error unknown-identifier: Unknown identifier Pett"
    monkeypatch.setattr(
        "app.typespec_compile.compile_typespec_set",
        _compiler_raising(f"TypeSpec compile failed: {line}", "INPUT_SEMANTIC_INVALID"),
    )
    api = _pets_api()
    verdict = await validate_emitted_artifact("typespec", _emit(api), api=api)
    assert verdict.failed
    finding = verdict.findings[0]
    assert (finding.keyword, finding.line, finding.column) == ("unknown-identifier", 3, 7)


# ===========================================================================
# Live compiler
# ===========================================================================


@needs_tsp
def test_the_fixture_is_what_tsp_emits_for_the_pets_export() -> None:
    assert compile_emitted_typespec(_emit(_pets_api())) == _pets_openapi()


@needs_tsp
@pytest.mark.parametrize(("path", "fmt"), _COMPILE_CORPUS, ids=lambda v: str(v))
def test_every_corpus_export_compiles_imports_and_is_measured(path: str, fmt: str) -> None:
    report = round_trip_typespec(_corpus_api(_EXAMPLES / path, fmt))
    assert report.valid, report.compile_errors or report.import_error
    assert report.status in (RoundTripStatus.LOSSY, RoundTripStatus.LOSSLESS)
    assert report.diff is not None
