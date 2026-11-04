"""FIX Orchestra export validation — MFX-37.3 (#4325).

The export gate checks every FIX Orchestra export (:func:`app.export_validation.validate_emitted_artifact`,
target ``fix-orchestra``) against the official FIX Orchestra 1.0 repository XSD and then round-trips it
through the FIX Orchestra importer (:func:`app.fix_orchestra_emitter.check_emitted_fix_orchestra`).

Acceptance: **invalid output fails the job with detail** — a repository the XSD refuses, one that does not
parse, or one whose messages do not read back is rejected with one finding per problem (its rule as
``keyword``, its path, the file), and the delivery gate then blocks the job.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, List

import pytest

from app import import_export_quality_policy as qp
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitResult, EmittedFile, load_builtin_emitters
from app.export_delivery_gate import DeliveryDecision, evaluate_delivery
from app.export_validation import EmittedArtifactValidation, validate_emitted_artifact
from app.export_validation_gate import build_validation_report
from app.fix_orchestra_emitter import FixOrchestraEmitter, check_emitted_fix_orchestra
from app.import_source import load_builtin_import_sources

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_TARGET = "fix-orchestra"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


@pytest.fixture
def _no_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(qp.db, "get_latest_import_export_quality_policy", lambda _tenant: None)
    monkeypatch.setattr(qp.db, "list_active_import_export_quality_waivers", lambda _tenant, **_kw: [])


def _imported(fmt: str, relative: str) -> Any:
    text = (_EXAMPLES / relative).read_text(encoding="utf-8")
    return build_conversion_source({"id": "i", "name": Path(relative).stem, "source_format": fmt,
                                    "format_metadata": {"sourceContent": text}}).api


def _validate(result: EmitResult, api: Any) -> EmittedArtifactValidation:
    return asyncio.run(validate_emitted_artifact(_TARGET, result, api=api))


def _repository(content: str, path: str = "Broken.orchestra.xml") -> EmitResult:
    return EmitResult(files=[EmittedFile(path=path, content=content, media_type="application/xml")],
                      media_type="application/xml")


def _valid() -> str:
    return FixOrchestraEmitter().emit(_imported("fix-orchestra", "fix-orchestra/02-typical-order-repository.xml")) \
        .files[0].content


SOURCES: List[tuple[str, str]] = [
    ("fix-orchestra", "fix-orchestra/02-typical-order-repository.xml"),
    ("fix-orchestra", "fix-orchestra/06-typical-actors-and-state-machine.xml"),
    ("openapi", "openapi/30-openapi-3.0-petstore.yaml"),
    ("json-schema", "json-schema/03-multiple-defs.json"),
]


# ===========================================================================
# The gate passes every export
# ===========================================================================


@pytest.mark.parametrize(("fmt", "path"), SOURCES)
def test_the_gate_passes_every_export(fmt: str, path: str) -> None:
    api = _imported(fmt, path)
    verdict = _validate(FixOrchestraEmitter().emit(api), api)
    assert verdict.applicable and verdict.validated and verdict.valid, verdict


# ===========================================================================
# Invalid output fails with detail
# ===========================================================================


def test_a_repository_the_xsd_refuses_fails_with_one_finding_per_violation() -> None:
    api = _imported("fix-orchestra", "fix-orchestra/02-typical-order-repository.xml")
    broken = _valid().replace('version="FIX.4.4"', 'version="v4"').replace("<fixr:metadata>", "<fixr:metadata>", 1)
    broken = broken.replace('msgType="D"', 'msgType="TOOLONG"')
    verdict = _validate(_repository(broken), api)
    assert verdict.validated and not verdict.valid and verdict.failed
    keywords = {f.keyword for f in verdict.findings}
    assert keywords == {"orchestra.xsd"}
    assert len(verdict.findings) >= 2
    for finding in verdict.findings:
        assert finding.file == "Broken.orchestra.xml" and finding.path and finding.message
    messages = " ".join(f.message for f in verdict.findings)
    assert "v4" in messages and "TOOLONG" in messages


def test_a_missing_required_element_is_named() -> None:
    broken = _valid()
    start, end = broken.index("<fixr:metadata"), broken.index("</fixr:metadata>") + len("</fixr:metadata>")
    findings = check_emitted_fix_orchestra(_repository(broken[:start] + broken[end:]))
    assert findings and findings[0]["rule"] == "orchestra.xsd" and "metadata" in findings[0]["message"]


def test_unparseable_xml_fails_as_xml() -> None:
    [finding] = check_emitted_fix_orchestra(_repository("<fixr:repository"))
    assert finding["rule"] == "xml"


def test_a_message_that_does_not_read_back_fails_the_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import import_source

    real = import_source.get_import_source("fix-orchestra")

    class _Lossy:
        """The importer, minus every message — what a broken round trip looks like."""

        def parse(self, text: str, **kwargs: Any) -> Any:
            return real.parse(text, **kwargs)

        def normalize(self, native: Any, **kwargs: Any) -> Any:
            api = real.normalize(native, **kwargs)
            api.types = [t for t in api.types if (t.extras or {}).get("fix_kind") != "message"]
            return api

    monkeypatch.setattr(import_source, "get_import_source", lambda key: _Lossy() if key == "fix-orchestra" else None)
    problems = check_emitted_fix_orchestra(_repository(_valid(), "ExampleEquities.orchestra.xml"))
    assert problems and {p["rule"] for p in problems} == {"reimport"}
    assert any("NewOrderSingle" in p["message"] for p in problems)


def test_a_repository_the_importer_refuses_fails_the_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import import_source
    from app.import_source import ImportSourceError

    class _Refusing:
        def parse(self, text: str, **kwargs: Any) -> Any:
            raise ImportSourceError("unresolved fieldRef 99999", code="INPUT_SEMANTIC_INVALID")

        def normalize(self, native: Any, **kwargs: Any) -> Any:  # pragma: no cover - parse refuses first
            return native

    monkeypatch.setattr(import_source, "get_import_source", lambda key: _Refusing())
    [problem] = check_emitted_fix_orchestra(_repository(_valid()))
    assert problem["rule"] == "reimport" and "unresolved fieldRef 99999" in problem["message"]


def test_an_export_with_no_repository_fails() -> None:
    api = _imported("fix-orchestra", "fix-orchestra/02-typical-order-repository.xml")
    assert not _validate(EmitResult(files=[], media_type="application/xml"), api).valid
    assert check_emitted_fix_orchestra(_repository("x", "notes.txt"))[0]["rule"] == "orchestra.file"


# ===========================================================================
# …and the job
# ===========================================================================


def _decision(result: EmitResult, api: Any) -> DeliveryDecision:
    report = evaluate_delivery(tenant_id="t1", tenant_slug="acme", target_format=_TARGET, target_key=_TARGET,
                               version_record_id="rev-1", validation=build_validation_report(_validate(result, api)),
                               preserved_percent=100)
    return report.decision


def test_invalid_output_fails_the_job(_no_policy: None) -> None:
    api = _imported("fix-orchestra", "fix-orchestra/02-typical-order-repository.xml")
    broken = _repository(_valid().replace('version="FIX.4.4"', 'version="v4"'))
    assert _decision(broken, api) is DeliveryDecision.BLOCK


def test_valid_output_is_not_blocked(_no_policy: None) -> None:
    api = _imported("fix-orchestra", "fix-orchestra/02-typical-order-repository.xml")
    assert _decision(FixOrchestraEmitter().emit(api), api) is not DeliveryDecision.BLOCK


def test_the_validation_report_carries_the_findings() -> None:
    api = _imported("fix-orchestra", "fix-orchestra/02-typical-order-repository.xml")
    report = build_validation_report(_validate(_repository(_valid().replace('version="FIX.4.4"', 'version="v4"')),
                                               api))
    dumped = report.model_dump(mode="json")
    assert "orchestra.xsd" in str(dumped) and "v4" in str(dumped)
