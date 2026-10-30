"""Smithy emitter validate + round-trip (Smithy CLI) — MFX-20.3 (#3916).

The Smithy CLI is a JVM tool the CI runtime does not install, so the CLI paths replay ``smithy validate
--format csv`` output recorded from the real CLI 1.53.0 (``tests/fixtures/smithy_lint/recordings``, the
recordings the lint tests use): ``model`` carries six ``WARNING`` events (style lints, which pass),
``error`` one ``ERROR`` (``Target.UnresolvedShape``). ``smithy ast`` is reported unavailable to the
replay, so the built model is read by the built-in reader. Covers:

* :func:`app.smithy_ast.validate_smithy_members` ``strict`` mode — never "found nothing" for "did not run";
* :func:`app.smithy_roundtrip.validate_emitted_smithy` — ``ERROR`` / ``DANGER`` block, warnings pass,
  each emitted file validated alone, the reader without the CLI, the CLI going missing mid-run;
* :func:`app.smithy_roundtrip.round_trip_smithy` — the four verdicts and the reconciliation;
* the export gate — blocking events and a built model that does not import both reject it;
* the round-trip fixture ``fixtures/smithy_roundtrip/openapi-petstore.json`` (regenerate with
  ``APIOME_REGEN_SMITHY_ROUNDTRIP=1``); with the real CLI, every corpus export validates and imports.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest
from smithy_reference import SMITHY
from test_smithy_emitter import _EXAMPLES, _SMITHY_CORPUS, _VALIDATE_CORPUS, _corpus_api, _emit, _rest_api

from app import smithy_ast
from app.emitter import EmitResult, EmittedFile
from app.export_validation import validate_emitted_artifact
from app.import_source import ImportSourceError
from app.smithy_roundtrip import (
    RoundTripStatus,
    reimport_built_model,
    round_trip_smithy,
    validate_emitted_smithy,
)
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError, ToolRunResult, ToolTimeoutError

_RECORDINGS = Path(__file__).resolve().parent / "fixtures" / "smithy_lint" / "recordings"
_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "smithy_roundtrip" / "openapi-petstore.json"
_PETSTORE = _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml"
_PLACEHOLDER = "/__STAGING__"

needs_smithy = pytest.mark.skipif(SMITHY is None, reason="the Smithy CLI is not installed here")


@pytest.fixture(autouse=True)
def reader_import(monkeypatch: pytest.MonkeyPatch, request) -> None:
    """The import source's own CLI paths are not under test; keep them on the reader (except live tests)."""
    if "live" not in request.node.name:
        monkeypatch.setattr("app.smithy_import_source.smithy_cli_available", lambda: False)


@pytest.fixture
def no_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(smithy_ast, "smithy_cli_available", lambda: False)


def _replay(monkeypatch: pytest.MonkeyPatch, name: str) -> List[List[str]]:
    """Report the CLI present; ``smithy validate`` replays ``name``, ``smithy ast`` is unavailable."""
    recorded = json.loads((_RECORDINGS / f"{name}.json").read_text(encoding="utf-8"))
    staged: List[List[str]] = []

    def _fake(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        if args[0] != "validate":
            raise ToolNotAvailableError(key, "smithy")
        staged.append([Path(a).name for a in args if a.endswith((".smithy", ".json"))])
        stdout = recorded["stdout"].replace(_PLACEHOLDER, str(Path(args[-1]).parent))
        if recorded["exit_code"]:
            raise ToolExecutionError(key, recorded["exit_code"], stdout, "")
        return ToolRunResult(key=key, argv=[key, *args], exit_code=0, stdout=stdout, stderr="", duration_ms=1)

    monkeypatch.setattr(smithy_ast, "smithy_cli_available", lambda: True)
    monkeypatch.setattr(smithy_ast, "run_tool_blocking", _fake)
    return staged


def _raising(monkeypatch: pytest.MonkeyPatch, exc: Exception) -> None:
    def _fake(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        raise exc

    monkeypatch.setattr(smithy_ast, "smithy_cli_available", lambda: True)
    monkeypatch.setattr(smithy_ast, "run_tool_blocking", _fake)


def _events(monkeypatch: pytest.MonkeyPatch, events: List[Dict[str, Any]]) -> None:
    monkeypatch.setattr(smithy_ast, "smithy_cli_available", lambda: True)
    monkeypatch.setattr(smithy_ast, "validate_smithy_members", lambda members, strict=False: events)


def _model(text: str, path: str = "Shop.smithy") -> EmitResult:
    return EmitResult(files=[EmittedFile(path=path, content=text, media_type="text/x-smithy")],
                      media_type="text/x-smithy")


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
# validate_smithy_members strict mode
# ===========================================================================


def test_strict_validate_raises_when_the_cli_gives_no_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    _raising(monkeypatch, ToolTimeoutError("smithy", 120.0))
    members = {"model.smithy": "$version: \"2\"\nnamespace a.b\n"}
    assert smithy_ast.validate_smithy_members(members) == []  # the import stays best effort
    with pytest.raises(ToolTimeoutError):
        smithy_ast.validate_smithy_members(members, strict=True)


def test_strict_validate_raises_without_an_events_table(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(key, args, **kwargs):
        return ToolRunResult(key=key, argv=[key], exit_code=0, stdout="nonsense", stderr="", duration_ms=1)

    monkeypatch.setattr(smithy_ast, "run_tool_blocking", _fake)
    with pytest.raises(ValueError):
        smithy_ast.validate_smithy_members({"model.smithy": "namespace a"}, strict=True)
    with pytest.raises(ValueError):
        smithy_ast.validate_smithy_members({"readme.md": "x"}, strict=True)


# ===========================================================================
# Validation
# ===========================================================================


def test_warnings_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "model")
    assert validate_emitted_smithy(_emit(_rest_api())) == ("smithy", [])


def test_an_error_event_blocks_with_its_location(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "error")
    validator, problems = validate_emitted_smithy(_emit(_rest_api()))
    assert validator == "smithy"
    assert [(p["severity"], p["id"]) for p in problems] == [("ERROR", "Target.UnresolvedShape")]
    assert problems[0]["file"] == "PetService.smithy" and problems[0]["line"]


def test_a_danger_event_blocks_and_a_note_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    _events(monkeypatch, [
        {"severity": "DANGER", "id": "HttpMethodSemantics", "shape": "a#Get", "line": 3, "column": 1, "message": "x"},
        {"severity": "NOTE", "id": "Hint", "shape": None, "line": None, "column": None, "message": "y"},
    ])
    _validator, problems = validate_emitted_smithy(_emit(_rest_api()))
    assert [p["id"] for p in problems] == ["HttpMethodSemantics"]


def test_each_output_file_is_validated_on_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    staged = _replay(monkeypatch, "model")
    validate_emitted_smithy(_emit(_rest_api(), output="both"))
    assert staged == [["PetService.smithy"], ["PetService.json"]]


def test_without_the_cli_the_reader_validates(no_cli) -> None:
    assert validate_emitted_smithy(_emit(_rest_api())) == ("reader", [])
    assert validate_emitted_smithy(_emit(_rest_api(), output="json-ast")) == ("reader", [])
    validator, problems = validate_emitted_smithy(_model("{ not json", path="Shop.json"))
    assert validator == "reader" and problems[0]["file"] == "Shop.json"


def test_the_cli_going_missing_falls_back_to_the_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    _raising(monkeypatch, ToolNotAvailableError("smithy", "smithy"))
    assert validate_emitted_smithy(_emit(_rest_api())) == ("reader", [])


def test_a_cli_that_fails_to_run_is_a_problem_not_a_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    _raising(monkeypatch, ToolTimeoutError("smithy", 120.0))
    validator, problems = validate_emitted_smithy(_emit(_rest_api()))
    assert validator == "smithy" and "could not validate" in problems[0]["message"]


def test_an_empty_export_cannot_be_validated() -> None:
    with pytest.raises(ValueError):
        validate_emitted_smithy(EmitResult(files=[], media_type="text/x-smithy"))


def test_reimport_raises_import_errors(no_cli) -> None:
    with pytest.raises(ImportSourceError):
        reimport_built_model(_model("{ not json", path="Shop.json"))


# ===========================================================================
# Round trip
# ===========================================================================


@pytest.mark.parametrize("path", _SMITHY_CORPUS, ids=lambda p: p.name)
def test_smithy_corpus_round_trips_and_every_difference_is_explained(path: Path, no_cli) -> None:
    report = round_trip_smithy(_corpus_api(path, "smithy"))
    assert report.valid and report.validator == "reader"
    if path.name == "04-grammar-corners.smithy":
        # Measured: @length / @range / @pattern imported by name only are not written back (reported as
        # trait-value-unknown by the writer), but the fidelity report still calls the input preserved.
        assert report.overclaims == ["example.payments.SubmitPaymentInput"] and report.diverges
    else:
        assert report.explained, (report.unexplained, report.overclaims)


def test_a_cli_validated_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "model")
    report = round_trip_smithy(_corpus_api(_SMITHY_CORPUS[0], "smithy"))
    assert report.validator == "smithy" and report.valid


def test_an_error_event_makes_the_round_trip_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "error")
    report = round_trip_smithy(_rest_api())
    assert report.status is RoundTripStatus.INVALID
    assert not report.valid and report.diff is None and not report.diverges


def test_a_model_that_does_not_import_is_unparseable(monkeypatch: pytest.MonkeyPatch, no_cli) -> None:
    def failing(_result):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.smithy_roundtrip.reimport_built_model", failing)
    report = round_trip_smithy(_rest_api())
    assert report.status is RoundTripStatus.UNPARSEABLE and report.import_error == "cannot normalize"


def test_an_empty_emission_is_invalid() -> None:
    report = round_trip_smithy(_rest_api(), emit_result=EmitResult(files=[], media_type="text/x-smithy"))
    assert report.status is RoundTripStatus.INVALID


def test_openapi_petstore_round_trip_matches_the_fixture(no_cli) -> None:
    report = round_trip_smithy(_corpus_api(_PETSTORE, "openapi"))
    assert report.valid
    summary = _summary(report)
    if os.environ.get("APIOME_REGEN_SMITHY_ROUNDTRIP"):
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    assert summary == json.loads(_GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize(("path", "fmt"), _VALIDATE_CORPUS, ids=lambda v: str(v))
def test_every_corpus_export_is_valid_with_the_reader(path: str, fmt: str, no_cli) -> None:
    report = round_trip_smithy(_corpus_api(_EXAMPLES / path, fmt))
    assert report.valid, report.problems or report.import_error


@needs_smithy
@pytest.mark.parametrize(("path", "fmt"), _VALIDATE_CORPUS, ids=lambda v: str(v))
def test_live_every_corpus_export_validates_and_imports(path: str, fmt: str) -> None:
    report = round_trip_smithy(_corpus_api(_EXAMPLES / path, fmt))
    assert report.validator == "smithy"
    assert report.valid, report.problems or report.import_error


# ===========================================================================
# The export gate
# ===========================================================================


async def test_gate_rejects_an_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "error")
    api = _rest_api()
    verdict = await validate_emitted_artifact("smithy", _emit(api), api=api)
    assert verdict.failed
    finding = verdict.findings[0]
    assert (finding.keyword, finding.file) == ("Target.UnresolvedShape", "PetService.smithy")
    assert finding.path and finding.line


async def test_gate_passes_warnings(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay(monkeypatch, "model")
    api = _rest_api()
    verdict = await validate_emitted_artifact("smithy", _emit(api), api=api)
    assert verdict.applicable and verdict.validated and verdict.valid


async def test_gate_rejects_a_model_that_does_not_import(monkeypatch: pytest.MonkeyPatch, no_cli) -> None:
    def failing(_result):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.smithy_roundtrip.reimport_built_model", failing)
    api = _rest_api()
    verdict = await validate_emitted_artifact("smithy", _emit(api), api=api)
    assert verdict.failed and verdict.findings[0].keyword == "smithy.reimport"


async def test_gate_without_the_cli_reparses(no_cli) -> None:
    api = _rest_api()
    verdict = await validate_emitted_artifact("smithy", _emit(api, output="both"), api=api)
    assert verdict.validated and verdict.valid
