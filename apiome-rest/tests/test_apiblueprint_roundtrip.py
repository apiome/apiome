"""API Blueprint emitter validate + round-trip (drafter) — MFX-18.3 (#3907).

drafter is a native tool the CI runtime does not build, so the drafter paths replay output recorded
from the real drafter 4.0.0 (``tests/fixtures/apiblueprint_drafter/recordings``, the recordings the
lint tests use): ``warnings`` carries four warnings, ``error`` one error (exit code 4). ``clean`` is
the ``warnings`` parse result with its annotations taken out — what drafter prints for a blueprint
with nothing to say. Covers:

* :func:`app.apiblueprint_roundtrip.validate_emitted_apiblueprint` — **zero warnings**: errors and
  warnings both block; the reader without drafter; drafter going missing mid-run falls back; drafter
  that gives no answer is a problem, never a silent pass (``run_drafter(strict=True)``);
* :func:`app.apiblueprint_roundtrip.round_trip_apiblueprint` — the four verdicts and the reconciliation;
* the export gate — warnings, errors and a document that does not import all reject it;
* the round-trip fixture ``fixtures/apiblueprint_roundtrip/openapi-petstore.json`` (regenerate with
  ``APIOME_REGEN_APIB_ROUNDTRIP=1``) and every API Blueprint corpus file round-tripping unchanged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest
from test_apiblueprint_emitter import _APIB_CORPUS, _CORPUS, _EXAMPLES, _corpus_api, _emit, _pets_api

from app import apiblueprint_drafter
from app import apiblueprint_import_source as import_source_module
from app.apiblueprint_roundtrip import (
    RoundTripStatus,
    reimport_with_reader,
    round_trip_apiblueprint,
    validate_emitted_apiblueprint,
)
from app.emitter import EmitResult, EmittedFile
from app.export_validation import validate_emitted_artifact
from app.import_source import ImportSourceError
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError, ToolRunResult, ToolTimeoutError

_RECORDINGS = Path(__file__).resolve().parent / "fixtures" / "apiblueprint_drafter" / "recordings"
_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "apiblueprint_roundtrip" / "openapi-petstore.json"
_PETSTORE = _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml"


def _recording(name: str) -> Dict[str, Any]:
    if name == "clean":
        recorded = _recording("warnings")
        result = json.loads(recorded["stdout"])
        result["content"] = [e for e in result["content"] if e.get("element") != "annotation"]
        return {**recorded, "stdout": json.dumps(result)}
    return json.loads((_RECORDINGS / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def reader_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """The import source's own drafter lint is not under test; keep it off."""
    monkeypatch.setattr(import_source_module, "drafter_available", lambda: False)


@pytest.fixture
def no_drafter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(apiblueprint_drafter, "drafter_available", lambda: False)


def _replay(monkeypatch: pytest.MonkeyPatch, name: str) -> List[str]:
    """Report drafter present and make every run replay ``name`` (a non-zero exit raises, as the runner does)."""
    recorded = _recording(name)
    calls: List[str] = []

    def _fake(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        calls.append(kwargs.get("stdin", ""))
        if recorded["exit_code"]:
            raise ToolExecutionError(key, recorded["exit_code"], recorded["stdout"], recorded["stderr"])
        return ToolRunResult(key=key, argv=[key, *args], exit_code=0, stdout=recorded["stdout"],
                             stderr=recorded["stderr"], duration_ms=1)

    monkeypatch.setattr(apiblueprint_drafter, "drafter_available", lambda: True)
    monkeypatch.setattr(apiblueprint_drafter, "run_tool_blocking", _fake)
    return calls


def _raising(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    def _fake(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        raise exc

    monkeypatch.setattr(apiblueprint_drafter, "drafter_available", lambda: True)
    monkeypatch.setattr(apiblueprint_drafter, "run_tool_blocking", _fake)


def _document(text: str) -> EmitResult:
    return EmitResult(files=[EmittedFile(path="api.apib", content=text, media_type="text/vnd.apiblueprint")],
                      media_type="text/vnd.apiblueprint")


def _summary(report) -> Dict[str, Any]:
    return {
        "status": report.status.value,
        "validator": report.validator,
        "diff": [[e.entity, e.key, e.change.value] for e in report.diff.entries],
        "unexplained": [[e.entity, e.key, e.change.value] for e in report.unexplained],
        "overclaims": sorted(report.overclaims),
        "predicted_losses": len(report.predicted_losses),
        "diverges": report.diverges,
    }


# ===========================================================================
# drafter strict mode
# ===========================================================================


def test_strict_run_raises_when_drafter_gives_no_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    _raising(monkeypatch, ToolTimeoutError("drafter", 30.0))
    assert apiblueprint_drafter.run_drafter("FORMAT: 1A\n") == []  # the import stays best effort
    with pytest.raises(ToolTimeoutError):
        apiblueprint_drafter.run_drafter("FORMAT: 1A\n", strict=True)


def test_strict_run_raises_on_output_that_is_not_a_parse_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(key, args, **kwargs):
        return ToolRunResult(key=key, argv=[key], exit_code=0, stdout="nonsense", stderr="", duration_ms=1)

    monkeypatch.setattr(apiblueprint_drafter, "run_tool_blocking", _fake)
    assert apiblueprint_drafter.run_drafter("FORMAT: 1A\n") == []
    with pytest.raises(ValueError):
        apiblueprint_drafter.run_drafter("FORMAT: 1A\n", strict=True)


# ===========================================================================
# Validation
# ===========================================================================


def test_a_clean_drafter_parse_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _replay(monkeypatch, "clean")
    result = _emit(_pets_api())
    assert validate_emitted_apiblueprint(result) == ("drafter", [])
    assert calls == [result.files[0].content]


def test_drafter_warnings_block(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "warnings")
    validator, problems = validate_emitted_apiblueprint(_emit(_pets_api()))
    assert validator == "drafter"
    assert [(p["severity"], p["code"], p["line"]) for p in problems] == [
        ("warning", 8, 9), ("warning", 6, 23), ("warning", 6, 29), ("warning", 2, 27)
    ]
    assert {p["file"] for p in problems} == {"Pets.apib"}


def test_drafter_errors_block(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "error")
    _validator, problems = validate_emitted_apiblueprint(_emit(_pets_api()))
    assert [(p["severity"], p["code"]) for p in problems] == [("error", 4)]


def test_without_drafter_the_reader_validates(no_drafter) -> None:
    assert validate_emitted_apiblueprint(_emit(_pets_api())) == ("reader", [])
    validator, problems = validate_emitted_apiblueprint(_document("not a blueprint"))
    assert validator == "reader" and problems and problems[0]["file"] == "api.apib"


def test_drafter_going_missing_falls_back_to_the_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    _raising(monkeypatch, ToolNotAvailableError("drafter", "not on PATH"))
    assert validate_emitted_apiblueprint(_emit(_pets_api())) == ("reader", [])


def test_drafter_that_fails_to_run_is_a_problem_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _raising(monkeypatch, ToolTimeoutError("drafter", 30.0))
    validator, problems = validate_emitted_apiblueprint(_emit(_pets_api()))
    assert validator == "drafter"
    assert "drafter could not parse the document" in problems[0]["message"]


def test_an_empty_export_cannot_be_validated() -> None:
    with pytest.raises(ValueError):
        validate_emitted_apiblueprint(EmitResult(files=[], media_type="text/vnd.apiblueprint"))


def test_reimport_with_reader_raises_import_errors() -> None:
    with pytest.raises(ImportSourceError):
        reimport_with_reader(_document("not a blueprint"))


# ===========================================================================
# Round trip
# ===========================================================================


@pytest.mark.parametrize("path", _APIB_CORPUS, ids=lambda p: p.name)
def test_api_blueprint_corpus_round_trips_unchanged(path: Path, no_drafter) -> None:
    report = round_trip_apiblueprint(_corpus_api(path))
    assert report.status is RoundTripStatus.LOSSLESS, report.diff
    assert report.valid and report.explained and not report.diverges


def test_drafter_validated_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "clean")
    report = round_trip_apiblueprint(_corpus_api(_APIB_CORPUS[0]))
    assert (report.validator, report.status) == ("drafter", RoundTripStatus.LOSSLESS)


def test_drafter_warnings_make_the_round_trip_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "warnings")
    report = round_trip_apiblueprint(_pets_api())
    assert report.status is RoundTripStatus.INVALID
    assert not report.valid and report.diff is None and not report.diverges


def test_a_document_that_does_not_import_is_unparseable(monkeypatch: pytest.MonkeyPatch, no_drafter) -> None:
    def failing(*_args, **_kw):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.apiblueprint_roundtrip.reimport_emitted", failing)
    report = round_trip_apiblueprint(_pets_api())
    assert report.status is RoundTripStatus.UNPARSEABLE and report.import_error == "cannot normalize"


def test_an_empty_emission_is_invalid() -> None:
    report = round_trip_apiblueprint(_pets_api(), emit_result=EmitResult(files=[], media_type="text/plain"))
    assert report.status is RoundTripStatus.INVALID


def test_openapi_petstore_round_trip_matches_the_fixture(no_drafter) -> None:
    report = round_trip_apiblueprint(_corpus_api(_PETSTORE))
    assert report.valid
    summary = _summary(report)
    if os.environ.get("APIOME_REGEN_APIB_ROUNDTRIP"):
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    assert summary == json.loads(_GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", _CORPUS, ids=lambda p: p.name)
def test_every_other_source_exports_a_valid_blueprint(path: Path, no_drafter) -> None:
    report = round_trip_apiblueprint(_corpus_api(path))
    assert report.valid, report.problems or report.import_error
    assert report.status in (RoundTripStatus.LOSSY, RoundTripStatus.LOSSLESS)


# ===========================================================================
# The export gate
# ===========================================================================


async def test_gate_rejects_drafter_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "warnings")
    api = _pets_api()
    verdict = await validate_emitted_artifact("apiblueprint", _emit(api), api=api)
    assert verdict.failed
    assert [f.keyword for f in verdict.findings] == ["8", "6", "6", "2"]
    assert verdict.findings[0].line == 9 and verdict.findings[0].file == "Pets.apib"


async def test_gate_passes_a_clean_drafter_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "clean")
    api = _pets_api()
    verdict = await validate_emitted_artifact("apiblueprint", _emit(api), api=api)
    assert verdict.validated and verdict.valid


async def test_gate_rejects_a_document_that_does_not_import(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "clean")

    def failing(_result):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.apiblueprint_roundtrip.reimport_with_reader", failing)
    api = _pets_api()
    verdict = await validate_emitted_artifact("apiblueprint", _emit(api), api=api)
    assert verdict.failed and verdict.findings[0].keyword == "apiblueprint.reimport"


async def test_gate_rejects_drafter_that_fails_to_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _raising(monkeypatch, ToolTimeoutError("drafter", 30.0))
    api = _pets_api()
    verdict = await validate_emitted_artifact("apiblueprint", _emit(api), api=api)
    assert verdict.failed
