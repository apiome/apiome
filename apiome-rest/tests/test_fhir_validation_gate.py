"""FHIR export validation gate — MFX-26.4 (#4160).

The official HL7 FHIR validator gates FHIR export delivery (wired in MFX-26.1). It is a JVM tool the CI
runtime does not install, so its runs are stood in for by a fake ``validate_with_fhir_validator`` (the
OperationOutcome reader itself is covered in ``test_fhir_emitter.py``). Covers:

* **the validator decides** — it is called with the version the export declares (``4.0.1`` for R4,
  ``5.0.0`` for R5) over every emitted file, bundle or per-type; each issue it returns is a finding;
* **invalid artifacts fail the export job with validator output** — end to end through the export job:
  ``EMITTED_ARTIFACT_INVALID`` carrying the validator's message, file, location and code;
* **the fallback without the validator** (:func:`app.fhir_validation.structural_problems`) — one finding
  per broken structural rule with its resource path (it joined them into one message before), not-JSON,
  a file the FHIR reader cannot read back; and a validator that goes missing mid-run falls back to it;
* **fixtures pass R4 and R5** — every corpus export passes the gate in both versions and both packagings.
"""

from __future__ import annotations

import json
from typing import Dict, List
from unittest.mock import patch

import pytest
from test_fhir_emitter import _CORPUS, _EXAMPLES, _corpus_api, _emit, _pets_api

from app.emitter import EmitResult, EmittedFile
from app.export_job_engine import ExportJobStartRequest, schedule_export_job
from app.export_validation import validate_emitted_artifact
from app.fhir_validation import FhirValidationIssue, structural_problems
from app.import_source import ImportSourceError


@pytest.fixture
def validator(monkeypatch: pytest.MonkeyPatch):
    """Report the validator present; record each call and return the issues set on ``validator.issues``."""

    class _Fake:
        calls: List[tuple] = []
        issues: List[FhirValidationIssue] = []

        def __call__(self, members: Dict[str, str], version: str) -> List[FhirValidationIssue]:
            self.calls.append((sorted(members), version))
            return list(self.issues)

    fake = _Fake()
    fake.calls, fake.issues = [], []
    monkeypatch.setattr("app.fhir_validation.fhir_validator_available", lambda: True)
    monkeypatch.setattr("app.fhir_validation.validate_with_fhir_validator", fake)
    return fake


@pytest.fixture
def no_validator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.fhir_validation.fhir_validator_available", lambda: False)


def _broken_bundle() -> str:
    """The pets export with two structural defects in its first StructureDefinition."""
    bundle = json.loads(_emit(_pets_api()).files[0].content)
    definition = next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == "StructureDefinition")
    definition["status"] = "bogus"
    definition["name"] = "not computable"
    return json.dumps(bundle)


def _export(path: str, text: str) -> EmitResult:
    return EmitResult(files=[EmittedFile(path=path, content=text, media_type="application/fhir+json")],
                      media_type="application/fhir+json")


# ===========================================================================
# The validator decides
# ===========================================================================


@pytest.mark.parametrize(("version", "declared"), [("R4", "4.0.1"), ("R5", "5.0.0")])
@pytest.mark.parametrize("packaging", ["bundle", "per-type"])
async def test_the_validator_runs_at_the_declared_version_over_every_file(validator, version: str, declared: str,
                                                                         packaging: str) -> None:
    api = _pets_api()
    result = _emit(api, fhir_version=version, packaging=packaging)
    verdict = await validate_emitted_artifact("fhir", result, api=api)
    assert verdict.validated and verdict.valid
    assert validator.calls == [(sorted(f.path for f in result.files), declared)]


async def test_each_validator_issue_is_a_finding(validator) -> None:
    validator.issues = [
        FhirValidationIssue(message="Element is not allowed", file="Pets.bundle.json",
                            location="Bundle.entry[0].resource.differential.element[2]", code="structure"),
        FhirValidationIssue(message="Constraint failed: sdf-0", file="Pets.bundle.json",
                            location="Bundle.entry[1].resource", code="invariant"),
    ]
    api = _pets_api()
    verdict = await validate_emitted_artifact("fhir", _emit(api), api=api)
    assert verdict.failed
    assert [(f.message, f.path, f.keyword) for f in verdict.findings] == [
        ("Element is not allowed", "Bundle.entry[0].resource.differential.element[2]", "structure"),
        ("Constraint failed: sdf-0", "Bundle.entry[1].resource", "invariant"),
    ]


async def test_a_validator_that_fails_to_run_rejects_and_one_that_goes_missing_falls_back(monkeypatch) -> None:
    api = _pets_api()
    monkeypatch.setattr("app.fhir_validation.fhir_validator_available", lambda: True)

    def timed_out(members, version):
        raise ImportSourceError("The FHIR validator took too long", code="INPUT_TIME_LIMIT")

    monkeypatch.setattr("app.fhir_validation.validate_with_fhir_validator", timed_out)
    verdict = await validate_emitted_artifact("fhir", _emit(api), api=api)
    assert verdict.failed and "took too long" in verdict.findings[0].message

    def missing(members, version):
        raise ImportSourceError("not installed", code="ADAPTER_UNAVAILABLE")

    monkeypatch.setattr("app.fhir_validation.validate_with_fhir_validator", missing)
    broken = _export("Pets.bundle.json", _broken_bundle())
    verdict = await validate_emitted_artifact("fhir", broken, api=api)
    assert verdict.failed and {f.keyword for f in verdict.findings} == {"fhir.structure"}


async def test_invalid_artifacts_fail_the_export_job_with_validator_output(validator) -> None:
    """MFX-26.4 acceptance: an artifact the validator rejects fails the job, carrying the validator's output."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _source, _wait_terminal

    validator.issues = [FhirValidationIssue(message="Unknown code 'sold' in ValueSet", file="widgets.bundle.json",
                                            location="Bundle.entry[0].resource.compose", code="code-invalid")]

    def _emit_fhir(*args, **kwargs):
        return _emit(_pets_api())

    request = ExportJobStartRequest(artifact="artifact-1", target="fhir", confirm=True)
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(
        "app.export_job_engine.emit_canonical", side_effect=_emit_fhir
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    finding = status["error"]["context"]["findings"][0]
    assert (finding["message"], finding["file"], finding["path"], finding["keyword"]) == (
        "Unknown code 'sold' in ValueSet", "widgets.bundle.json", "Bundle.entry[0].resource.compose", "code-invalid")


# ===========================================================================
# The fallback without the validator
# ===========================================================================


def test_each_structural_issue_is_one_problem_with_its_path() -> None:
    problems = structural_problems("Pets.bundle.json", _broken_bundle())
    assert {p["rule"] for p in problems} == {"fhir.structure"} and len(problems) == 2
    paths = sorted(p["path"] for p in problems)
    assert paths[0].endswith("StructureDefinition/name") and paths[1].endswith("StructureDefinition/status")
    assert all(p["path"].startswith("Bundle/entry[") for p in problems)


def test_not_json_and_an_unreadable_file_are_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    assert [p["rule"] for p in structural_problems("a.json", "{nope")] == ["fhir.json"]

    def unreadable(text, **kw):
        raise ValueError("no resources")

    monkeypatch.setattr("app.fhir_parser.parse_fhir", unreadable)
    assert [p["rule"] for p in structural_problems("a.json", _emit(_pets_api()).files[0].content)] == ["fhir.reimport"]


async def test_the_fallback_gate_names_every_issue(no_validator) -> None:
    api = _pets_api()
    verdict = await validate_emitted_artifact("fhir", _export("Pets.bundle.json", _broken_bundle()), api=api)
    assert verdict.failed and len(verdict.findings) == 2
    assert all(f.keyword == "fhir.structure" and f.file == "Pets.bundle.json" and f.path for f in verdict.findings)


# ===========================================================================
# Fixtures pass R4 and R5
# ===========================================================================


@pytest.mark.parametrize("packaging", ["bundle", "per-type"])
@pytest.mark.parametrize("version", ["R4", "R5"])
@pytest.mark.parametrize(("path", "fmt"), _CORPUS, ids=lambda v: str(v))
async def test_every_corpus_export_passes_the_gate(path: str, fmt: str, version: str, packaging: str,
                                                   no_validator) -> None:
    api = _corpus_api(_EXAMPLES / path, fmt)
    verdict = await validate_emitted_artifact("fhir", _emit(api, fhir_version=version, packaging=packaging), api=api)
    assert verdict.validated and verdict.valid, verdict.errors

