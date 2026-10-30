"""RAML emitter validate + round-trip (AMF) — MFX-17.3 (#3903).

AMF is a JVM tool the CI runtime does not install, so the AMF paths replay ``amf validate`` output
recorded from the real ``amf`` 5.7.1 CLI (``tests/fixtures/raml_amf/recordings``, the same recordings
:mod:`tests.test_raml_amf` uses): ``petstore-validate`` conforms, ``lint-validate`` carries two
``example-validation-error`` violations. Covers:

* :func:`app.raml_roundtrip.validate_emitted_raml` — AMF when present (violations reject, the
  recorded report is read), the reader without it, the reader when AMF goes missing mid-run;
* :func:`app.raml_roundtrip.round_trip_raml` — ``invalid`` / ``unparseable`` / ``lossy`` /
  ``lossless`` and the reconciliation against the fidelity report;
* the export gate — AMF violations and a document that does not import both reject it;
* the round-trip fixture: ``fixtures/raml_roundtrip/openapi-petstore.json`` pins the measured round
  trip of the OpenAPI petstore (regenerate with ``APIOME_REGEN_RAML_ROUNDTRIP=1``);
* every RAML corpus document round-trips with no difference.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest
from test_raml_emitter import _CORPUS, _EXAMPLES, _RAML_CORPUS, _corpus_api, _emit

from app import raml_amf
from app import raml_import_source as raml_import_source_module
from app.emitter import EmitResult, EmittedFile
from app.export_validation import validate_emitted_artifact
from app.import_source import ImportSourceError
from app.raml_roundtrip import (
    RoundTripStatus,
    reimport_with_reader,
    round_trip_raml,
    validate_emitted_raml,
)
from app.toolchain_runner import ToolRunResult

_RECORDINGS = Path(__file__).resolve().parent / "fixtures" / "raml_amf" / "recordings"
_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "raml_roundtrip" / "openapi-petstore.json"
_PETSTORE = _EXAMPLES / "openapi" / "30-openapi-3.0-petstore.yaml"
_SIMPLE = _EXAMPLES / "raml" / "01-simple-api.raml"


def _document(text: str) -> EmitResult:
    return EmitResult(
        files=[EmittedFile(path="api.raml", content=text, media_type="application/raml+yaml")],
        media_type="application/raml+yaml",
    )


@pytest.fixture(autouse=True)
def reader_import(monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-import through the reader: a recorded ``amf parse`` describes another document."""
    monkeypatch.setattr(raml_import_source_module, "amf_available", lambda: False)


@pytest.fixture
def no_amf(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(raml_amf, "amf_available", lambda: False)


def _replay_validate(monkeypatch: pytest.MonkeyPatch, name: str) -> List[Dict[str, Any]]:
    """Report AMF present and make ``amf validate`` replay the recording ``name``."""
    calls: List[Dict[str, Any]] = []
    recorded = json.loads((_RECORDINGS / f"{name}.json").read_text(encoding="utf-8"))

    def _fake(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        calls.append({"key": key, "args": list(args)})
        assert args[0] == "validate"
        stdout = recorded["stdout"].replace("/__STAGING__", kwargs["cwd"])
        return ToolRunResult(key=key, argv=[key, *args], exit_code=0, stdout=stdout, stderr="", duration_ms=1)

    monkeypatch.setattr(raml_amf, "amf_available", lambda: True)
    monkeypatch.setattr(raml_amf, "run_tool_blocking", _fake)
    return calls


def _summary(report) -> Dict[str, Any]:
    """The parts of a round-trip report the golden fixture pins."""
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
# Validation
# ===========================================================================


def test_amf_conforming_report_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _replay_validate(monkeypatch, "petstore-validate")
    assert validate_emitted_raml(_emit(_corpus_api(_SIMPLE))) == ("amf", [])
    assert calls and calls[0]["key"] == raml_amf.AMF_TOOL_KEY


def test_amf_violations_are_returned_with_their_location(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay_validate(monkeypatch, "lint-validate")
    validator, violations = validate_emitted_raml(_emit(_corpus_api(_SIMPLE)))
    assert validator == "amf"
    assert [(v["constraint"], v["line"]) for v in violations] == [
        ("example-validation-error", 21),
        ("example-validation-error", 29),
    ]
    assert all(v["file"] for v in violations)


def test_without_amf_the_reader_validates(no_amf) -> None:
    assert validate_emitted_raml(_emit(_corpus_api(_SIMPLE))) == ("reader", [])
    validator, violations = validate_emitted_raml(_document("#%RAML 1.0\ntitle: [x\n"))
    assert validator == "reader" and "Malformed YAML" in violations[0]["message"]


def test_amf_going_missing_falls_back_to_the_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(members, root):
        raise ImportSourceError("amf is not installed", code="ADAPTER_UNAVAILABLE")

    monkeypatch.setattr(raml_amf, "amf_available", lambda: True)
    monkeypatch.setattr(raml_amf, "validate_raml_set_with_amf", unavailable)
    assert validate_emitted_raml(_emit(_corpus_api(_SIMPLE))) == ("reader", [])


def test_an_amf_failure_is_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    def timed_out(members, root):
        raise ImportSourceError("AMF took too long", code="INPUT_TIME_LIMIT")

    monkeypatch.setattr(raml_amf, "amf_available", lambda: True)
    monkeypatch.setattr(raml_amf, "validate_raml_set_with_amf", timed_out)
    with pytest.raises(ImportSourceError):
        validate_emitted_raml(_emit(_corpus_api(_SIMPLE)))


def test_an_empty_export_cannot_be_validated() -> None:
    with pytest.raises(ValueError):
        validate_emitted_raml(EmitResult(files=[], media_type="application/raml+yaml"))


@pytest.mark.parametrize("text", ["#%RAML 1.0\ntitle: x\n", "hello"], ids=["no-resources", "not-raml"])
def test_reimport_with_reader_raises_import_errors(text: str) -> None:
    with pytest.raises(ImportSourceError):
        reimport_with_reader(_document(text))


# ===========================================================================
# Round trip
# ===========================================================================


@pytest.mark.parametrize("path", _RAML_CORPUS, ids=lambda p: p.name)
def test_raml_corpus_round_trips_and_every_difference_is_explained(path: Path, no_amf) -> None:
    report = round_trip_raml(_corpus_api(path))
    assert report.valid and report.validator == "reader"
    assert report.explained, (report.unexplained, report.overclaims)
    if "resource-types-and-traits" in path.name:
        assert report.status is RoundTripStatus.LOSSY  # the flattened type / trait names (reported)
        assert not report.diverges
    else:
        assert report.status is RoundTripStatus.LOSSLESS and not report.diverges


def test_amf_validated_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay_validate(monkeypatch, "petstore-validate")
    report = round_trip_raml(_corpus_api(_SIMPLE))
    assert (report.validator, report.status) == ("amf", RoundTripStatus.LOSSLESS)


def test_amf_violations_make_the_round_trip_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay_validate(monkeypatch, "lint-validate")
    report = round_trip_raml(_corpus_api(_SIMPLE))
    assert report.status is RoundTripStatus.INVALID
    assert not report.valid and report.diff is None and not report.diverges


def test_an_amf_failure_makes_the_round_trip_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    def timed_out(members, root):
        raise ImportSourceError("AMF took too long", code="INPUT_TIME_LIMIT")

    monkeypatch.setattr(raml_amf, "amf_available", lambda: True)
    monkeypatch.setattr(raml_amf, "validate_raml_set_with_amf", timed_out)
    report = round_trip_raml(_corpus_api(_SIMPLE))
    assert report.status is RoundTripStatus.INVALID
    assert report.violations[0]["message"] == "AMF took too long"


def test_a_document_that_does_not_import_is_unparseable(monkeypatch: pytest.MonkeyPatch, no_amf) -> None:
    def failing(*_args, **_kw):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.raml_roundtrip.reimport_emitted", failing)
    report = round_trip_raml(_corpus_api(_SIMPLE))
    assert report.status is RoundTripStatus.UNPARSEABLE
    assert report.import_error == "cannot normalize"


def test_a_given_emission_is_used_as_is(no_amf) -> None:
    api = _corpus_api(_PETSTORE)
    result = _emit(api)
    assert round_trip_raml(api, emit_result=result).predicted_losses == list(result.losses)


def test_openapi_petstore_round_trip_matches_the_fixture(no_amf) -> None:
    report = round_trip_raml(_corpus_api(_PETSTORE))
    assert report.status is RoundTripStatus.LOSSY and report.valid
    summary = _summary(report)
    if os.environ.get("APIOME_REGEN_RAML_ROUNDTRIP"):
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    assert summary == json.loads(_GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", _CORPUS, ids=lambda p: p.name)
def test_every_other_source_exports_valid_raml(path: Path, no_amf) -> None:
    report = round_trip_raml(_corpus_api(path))
    assert report.valid, report.violations or report.import_error
    assert report.status in (RoundTripStatus.LOSSY, RoundTripStatus.LOSSLESS)


# ===========================================================================
# The export gate
# ===========================================================================


async def test_gate_rejects_amf_violations_with_their_constraint(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay_validate(monkeypatch, "lint-validate")
    api = _corpus_api(_SIMPLE)
    verdict = await validate_emitted_artifact("raml", _emit(api), api=api)
    assert verdict.failed
    assert [f.keyword for f in verdict.findings] == ["example-validation-error"] * 2


async def test_gate_passes_a_conforming_document(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay_validate(monkeypatch, "petstore-validate")
    api = _corpus_api(_PETSTORE)
    verdict = await validate_emitted_artifact("raml", _emit(api), api=api)
    assert verdict.validated and verdict.valid


async def test_gate_rejects_a_document_that_does_not_import(monkeypatch: pytest.MonkeyPatch) -> None:
    _replay_validate(monkeypatch, "petstore-validate")

    def failing(_result):
        raise ImportSourceError("cannot normalize")

    monkeypatch.setattr("app.raml_roundtrip.reimport_with_reader", failing)
    api = _corpus_api(_SIMPLE)
    verdict = await validate_emitted_artifact("raml", _emit(api), api=api)
    assert verdict.failed
    assert verdict.findings[0].keyword == "raml.reimport"


async def test_gate_rejects_an_amf_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def timed_out(members, root):
        raise ImportSourceError("AMF took too long", code="INPUT_TIME_LIMIT")

    monkeypatch.setattr(raml_amf, "amf_available", lambda: True)
    monkeypatch.setattr(raml_amf, "validate_raml_set_with_amf", timed_out)
    api = _corpus_api(_SIMPLE)
    verdict = await validate_emitted_artifact("raml", _emit(api), api=api)
    assert verdict.failed and verdict.findings[0].message == "AMF took too long"
