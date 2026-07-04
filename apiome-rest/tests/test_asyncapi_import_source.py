"""End-to-end tests for the AsyncAPI import source (MFI-8.5, #3763).

Exercises the adapter through the full SPI: detect → parse → normalize →
fingerprint/lint. The parse step drives the Node ``@asyncapi/parser`` via a
worker-thread loop; tests that need real parsing are gated on the bundled tool
being resolvable (mirroring ``test_asyncapi_parser.py``), while the detect /
normalize / lint paths are covered without it using dereferenced inline documents
and a monkeypatched parser for the bridge + error mapping.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict

import pytest

from app.asyncapi_import_source import AsyncApiImportSource
from app.asyncapi_parser import (
    ASYNCAPI_PARSER_TOOL_KEY,
    AsyncApiDiagnostic,
    AsyncApiIdentity,
    AsyncApiParseError,
    AsyncApiParseResult,
)
from app.canonical_model import ApiParadigm, CanonicalApi
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    InputKind,
    LintReport,
)
from app.toolchain_packaging import probe_tool

_FIXTURES = Path(__file__).parent / "fixtures" / "asyncapi"


def _v3_doc() -> Dict[str, Any]:
    """A small, dereferenced AsyncAPI 3.0 document (``$ref``s already inlined)."""
    channel = {
        "address": "user/signedup",
        "messages": {
            "UserSignedUp": {
                "name": "UserSignedUp",
                "payload": {
                    "type": "object",
                    "properties": {"userId": {"type": "string"}},
                },
            }
        },
    }
    return {
        "asyncapi": "3.0.0",
        "id": "urn:com:example:user-service",
        "info": {"title": "User Service", "version": "1.2.3", "description": "Events."},
        "defaultContentType": "application/json",
        "servers": {"production": {"host": "broker.example.com", "protocol": "kafka"}},
        "channels": {"userSignedUp": channel},
        "operations": {
            "onUserSignedUp": {"action": "receive", "channel": copy.deepcopy(channel)}
        },
    }


def _v2_doc() -> Dict[str, Any]:
    """A small, dereferenced AsyncAPI 2.6 document."""
    return {
        "asyncapi": "2.6.0",
        "id": "urn:com:example:streetlights",
        "info": {"title": "Streetlights API", "version": "1.0.0"},
        "defaultContentType": "application/json",
        "servers": {"production": {"url": "mqtt://broker.example.com", "protocol": "mqtt"}},
        "channels": {
            "light/measured": {
                "publish": {
                    "operationId": "onLightMeasured",
                    "message": {
                        "name": "LightMeasured",
                        "payload": {
                            "type": "object",
                            "properties": {"lumens": {"type": "integer", "minimum": 0}},
                        },
                    },
                }
            }
        },
    }


def _valid_result(document: Dict[str, Any]) -> AsyncApiParseResult:
    """A successful parse result wrapping ``document`` (no error diagnostics)."""
    info = document.get("info", {})
    return AsyncApiParseResult(
        ok=True,
        asyncapi_version=document["asyncapi"],
        identity=AsyncApiIdentity(title=info.get("title"), version=info.get("version")),
        document=document,
        diagnostics=[
            AsyncApiDiagnostic(severity="warning", code="asyncapi-id", message="hygiene")
        ],
    )


@pytest.fixture()
def adapter() -> AsyncApiImportSource:
    return AsyncApiImportSource()


# ===========================================================================
# Descriptor
# ===========================================================================


def test_descriptor_metadata(adapter: AsyncApiImportSource) -> None:
    d = adapter.descriptor()
    assert d.key == "asyncapi"
    assert d.label == "AsyncAPI"
    assert d.icon == "radio"
    assert d.paradigm is ApiParadigm.EVENT
    assert set(d.input_kinds) == {InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.FILESET}
    assert d.formats == ["asyncapi-2", "asyncapi-3"]
    assert d.supports_live_discovery is False


def test_descriptor_reports_availability_from_parser_toolchain(adapter, monkeypatch) -> None:
    # MFI-5.2: AsyncAPI parse hard-requires the Node `asyncapi-parser`; the descriptor reflects
    # whether it can run in this runtime so the UI disables it instead of failing at parse.
    monkeypatch.setattr("app.toolchain_runner.is_tool_available", lambda key: key != "asyncapi-parser")
    d = adapter.descriptor()
    assert d.available is False
    assert d.unavailable_reason and "asyncapi-parser" in d.unavailable_reason

    monkeypatch.setattr("app.toolchain_runner.is_tool_available", lambda key: True)
    assert adapter.descriptor().available is True


def test_registered_in_import_source_registry() -> None:
    # Registering the adapter is all the UI source card / CLI dispatch need: it must
    # surface from the public registry enumeration.
    from app.import_source import available_import_sources, get_import_source

    assert "asyncapi" in available_import_sources()
    assert isinstance(get_import_source("asyncapi"), AsyncApiImportSource)


# ===========================================================================
# Detection
# ===========================================================================


def test_detect_v3_from_document(adapter: AsyncApiImportSource) -> None:
    result = adapter.detect(DetectionInput(document=_v3_doc()))
    assert result.format == "asyncapi-3"
    assert result.confidence > 0.9


def test_detect_v2_from_yaml_text(adapter: AsyncApiImportSource) -> None:
    result = adapter.detect(DetectionInput(text="asyncapi: '2.6.0'\ninfo:\n  title: X\n"))
    assert result.format == "asyncapi-2"
    assert result.matched


def test_detect_non_asyncapi_is_no_match(adapter: AsyncApiImportSource) -> None:
    assert adapter.detect(DetectionInput(document={"openapi": "3.1.0"})).matched is False
    # An out-of-range AsyncAPI family is not a match either.
    assert adapter.detect(DetectionInput(document={"asyncapi": "1.0.0"})).matched is False
    # Malformed text must not raise, just fail to match.
    assert adapter.detect(DetectionInput(text="{not yaml or json: [")).matched is False


# ===========================================================================
# Normalize (dereferenced inline documents — no Node tool needed)
# ===========================================================================


def test_normalize_v3_produces_event_model(adapter: AsyncApiImportSource) -> None:
    model = adapter.normalize(_v3_doc())
    assert isinstance(model, CanonicalApi)
    assert model.paradigm is ApiParadigm.EVENT
    assert model.format == "asyncapi-3"
    assert model.identity.name == "User Service"
    assert model.version == "1.2.3"
    assert any(ch.key for ch in model.channels)


def test_normalize_v2_produces_event_model(adapter: AsyncApiImportSource) -> None:
    model = adapter.normalize(_v2_doc())
    assert model.format == "asyncapi-2"
    assert model.protocol == "mqtt"


def test_normalize_accepts_parse_result(adapter: AsyncApiImportSource) -> None:
    # The pipeline passes the AsyncApiParseResult parse() returns straight to normalize().
    model = adapter.normalize(_valid_result(_v3_doc()))
    assert model.format == "asyncapi-3"


def test_normalize_is_deterministic(adapter: AsyncApiImportSource) -> None:
    a = adapter.normalize(_v3_doc())
    b = adapter.normalize(_v3_doc())
    assert adapter.fingerprint(a) == adapter.fingerprint(b)


def test_normalize_non_dict_raises(adapter: AsyncApiImportSource) -> None:
    with pytest.raises(ImportSourceError, match="parsed mapping"):
        adapter.normalize("not a dict")


def test_normalize_non_asyncapi_raises(adapter: AsyncApiImportSource) -> None:
    with pytest.raises(ImportSourceError, match="version marker"):
        adapter.normalize({"openapi": "3.1.0"})


def test_normalize_unsupported_version_raises(adapter: AsyncApiImportSource) -> None:
    with pytest.raises(ImportSourceError, match="Unsupported AsyncAPI version"):
        adapter.normalize({"asyncapi": "1.0.0", "info": {"title": "x"}})


def test_normalize_without_raw_omits_fidelity_bag(adapter: AsyncApiImportSource) -> None:
    model = adapter.normalize(_v3_doc(), include_raw=False)
    assert model.raw is None


# ===========================================================================
# Lint
# ===========================================================================


def test_lint_without_parse_result_uses_engine_default(
    adapter: AsyncApiImportSource,
) -> None:
    # With no stashed parse result the adapter degrades to the engine default (common +
    # native AsyncAPI packs) so the revision still rolls up to a deterministic score.
    model = adapter.normalize(_v3_doc())
    report = adapter.lint(model)
    assert isinstance(report, LintReport)
    assert isinstance(report.score, int)
    assert 0 <= report.score <= 100
    assert report.grade in {"A", "B", "C", "D", "F"}
    assert report.report_fingerprint


def test_lint_folds_spectral_when_parse_result_present(
    adapter: AsyncApiImportSource,
) -> None:
    # When parse() stashed the parse result, its spectral:asyncapi diagnostics flow into the
    # report (MFI-8.3), so a finding referencing the Spectral namespace appears.
    model = adapter.normalize(_v3_doc())
    adapter._parse_result = AsyncApiParseResult(
        ok=True,
        asyncapi_version="3.0.0",
        diagnostics=[
            AsyncApiDiagnostic(
                severity="warning",
                code="asyncapi-servers",
                message="server hygiene",
                path="servers",
            )
        ],
    )
    report = adapter.lint(model)
    assert isinstance(report.score, int)
    assert any("spectral" in f.rule for f in report.findings)


# ===========================================================================
# Parse bridge + error mapping (monkeypatched parser — no Node tool needed)
# ===========================================================================


def test_parse_returns_and_stashes_result(
    adapter: AsyncApiImportSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _valid_result(_v3_doc())

    async def _fake_parse(raw: str, **_kw: Any) -> AsyncApiParseResult:
        return expected

    monkeypatch.setattr("app.asyncapi_parser.parse_asyncapi", _fake_parse)
    result = adapter.parse("asyncapi: '3.0.0'\n")
    assert result is expected
    # The result is stashed so a subsequent lint() can fold Spectral findings.
    assert adapter._parse_result is expected
    # And it round-trips through normalize().
    assert adapter.normalize(result).format == "asyncapi-3"


def test_parse_invalid_document_raises_import_source_error(
    adapter: AsyncApiImportSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid = AsyncApiParseResult(
        ok=False,
        asyncapi_version="3.0.0",
        diagnostics=[
            AsyncApiDiagnostic(severity="error", code="bad", message="missing channels")
        ],
    )

    async def _fake_parse(raw: str, **_kw: Any) -> AsyncApiParseResult:
        return invalid

    monkeypatch.setattr("app.asyncapi_parser.parse_asyncapi", _fake_parse)
    with pytest.raises(ImportSourceError, match="missing channels"):
        adapter.parse("asyncapi: '3.0.0'\n")


def test_parse_tool_failure_raises_import_source_error(
    adapter: AsyncApiImportSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_parse(raw: str, **_kw: Any) -> AsyncApiParseResult:
        raise AsyncApiParseError("parser tool is not available")

    monkeypatch.setattr("app.asyncapi_parser.parse_asyncapi", _fake_parse)
    with pytest.raises(ImportSourceError, match="not available"):
        adapter.parse("asyncapi: '3.0.0'\n")


# ===========================================================================
# End-to-end: the real Node parser over the committed fixtures (gated)
# ===========================================================================

_PARSER_AVAILABLE = bool(getattr(probe_tool(ASYNCAPI_PARSER_TOOL_KEY), "available", False))


@pytest.mark.skipif(
    not _PARSER_AVAILABLE,
    reason="asyncapi-parser tool is not resolvable in this environment "
    "(bundled only in the image / via APIOME_ASYNCAPI_PARSER_BIN)",
)
class TestRealParser:
    """Drives parse → normalize → lint over the real 2.6/3.0/3.1 fixtures."""

    @pytest.mark.parametrize(
        "fixture, fmt, title",
        [
            ("streetlights_2.6.yaml", "asyncapi-2", "Streetlights API"),
            ("user_events_3.0.yaml", "asyncapi-3", "User Service"),
            ("account_3.1.yaml", "asyncapi-3", "Account Service"),
        ],
    )
    def test_fixture_imports_end_to_end(self, fixture: str, fmt: str, title: str) -> None:
        adapter = AsyncApiImportSource()
        raw = (_FIXTURES / fixture).read_text()

        parse_result = adapter.parse(raw, source_label=fixture)
        assert parse_result.ok is True

        model = adapter.normalize(parse_result)
        assert model.paradigm is ApiParadigm.EVENT
        assert model.format == fmt
        assert model.identity.name == title
        assert model.channels

        report = adapter.lint(model)
        assert isinstance(report.score, int)
        assert report.grade in {"A", "B", "C", "D", "F"}
        assert report.report_fingerprint

        # Fingerprint is stable across a second import of the same source.
        again = adapter.normalize(adapter.parse(raw))
        assert adapter.fingerprint(model) == adapter.fingerprint(again)

    def test_invalid_fixture_raises(self) -> None:
        adapter = AsyncApiImportSource()
        raw = (_FIXTURES / "invalid_missing_version_3.0.yaml").read_text()
        with pytest.raises(ImportSourceError):
            adapter.parse(raw)

    def test_non_asyncapi_document_raises(self) -> None:
        adapter = AsyncApiImportSource()
        raw = (_FIXTURES / "not_asyncapi.json").read_text()
        with pytest.raises(ImportSourceError):
            adapter.parse(raw)
