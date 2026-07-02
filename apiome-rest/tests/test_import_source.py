"""Unit tests for the ImportSource SPI + registry (MFI-1.1, #3733).

Covers the adapter contract, the by-key registry and its descriptor enumeration
(the "source list"), the shared canonical fingerprint and diff defaults, and the
auto-detection primitive — independently of any concrete adapter where possible,
and asserting the built-in adapters register and appear in the source list.
"""

from __future__ import annotations

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
)
from app.import_source import (
    NO_MATCH,
    CanonicalDiff,
    DetectionInput,
    DetectionResult,
    DiffChangeKind,
    ImportSource,
    ImportSourceDescriptor,
    ImportSourceError,
    InputKind,
    LintReport,
    available_import_sources,
    canonical_diff,
    canonical_fingerprint,
    describe_import_sources,
    detect_import_source,
    get_import_source,
    load_builtin_import_sources,
    register_import_source,
)

# ===========================================================================
# Registry / SPI contract
# ===========================================================================


def test_builtin_sources_register_and_appear_in_source_list() -> None:
    load_builtin_import_sources()
    keys = available_import_sources()
    assert "openapi" in keys
    # The acceptance criterion: the no-op sample adapter appears in the source list.
    assert "sample" in keys

    descriptors = {d.key: d for d in describe_import_sources()}
    assert set(descriptors) == set(keys)
    sample = descriptors["sample"]
    assert isinstance(sample, ImportSourceDescriptor)
    assert sample.label == "Sample (no-op)"
    assert sample.paradigm is ApiParadigm.DATA_SCHEMA
    assert sample.input_kinds == [InputKind.PASTE]
    assert sample.supports_live_discovery is False


def test_get_import_source_returns_instance_or_none() -> None:
    assert isinstance(get_import_source("openapi"), ImportSource)
    assert get_import_source("does-not-exist") is None


def test_describe_import_sources_is_sorted_by_key() -> None:
    descriptors = describe_import_sources()
    keys = [d.key for d in descriptors]
    assert keys == sorted(keys)


def test_register_rejects_empty_key() -> None:
    class _NoKey(ImportSource):
        paradigm = ApiParadigm.REST

        def detect(self, payload):  # pragma: no cover - never reached
            return NO_MATCH

        def parse(self, raw, *, source_label=None):  # pragma: no cover
            return {}

        def normalize(self, native_ast, *, include_raw=True):  # pragma: no cover
            raise NotImplementedError

    with pytest.raises(ValueError, match="non-empty `key`"):
        register_import_source(_NoKey)


def test_register_is_idempotent_for_same_class_but_rejects_collisions() -> None:
    class _Reusable(ImportSource):
        key = "test-reusable-key"
        paradigm = ApiParadigm.REST

        def detect(self, payload):  # pragma: no cover
            return NO_MATCH

        def parse(self, raw, *, source_label=None):  # pragma: no cover
            return {}

        def normalize(self, native_ast, *, include_raw=True):  # pragma: no cover
            raise NotImplementedError

    register_import_source(_Reusable)
    # Re-registering the *same* class is a no-op (safe under module re-import).
    register_import_source(_Reusable)

    class _Collision(ImportSource):
        key = "test-reusable-key"
        paradigm = ApiParadigm.REST

        def detect(self, payload):  # pragma: no cover
            return NO_MATCH

        def parse(self, raw, *, source_label=None):  # pragma: no cover
            return {}

        def normalize(self, native_ast, *, include_raw=True):  # pragma: no cover
            raise NotImplementedError

    with pytest.raises(ValueError, match="already registered"):
        register_import_source(_Collision)


def test_register_true_flag_self_registers() -> None:
    class _AutoReg(ImportSource, register=True):
        key = "test-auto-register"
        paradigm = ApiParadigm.GRAPH

        def detect(self, payload):  # pragma: no cover
            return NO_MATCH

        def parse(self, raw, *, source_label=None):  # pragma: no cover
            return {}

        def normalize(self, native_ast, *, include_raw=True):  # pragma: no cover
            raise NotImplementedError

    assert "test-auto-register" in available_import_sources()


# ===========================================================================
# Detection
# ===========================================================================


def test_detection_result_clamps_confidence() -> None:
    assert DetectionResult(confidence=5.0).confidence == 1.0
    assert DetectionResult(confidence=-1.0).confidence == 0.0
    assert NO_MATCH.matched is False
    assert DetectionResult(confidence=0.5).matched is True


def test_detect_import_source_picks_highest_confidence() -> None:
    payload = DetectionInput(document={"openapi": "3.1.0", "info": {}, "paths": {}})
    match = detect_import_source(payload)
    assert match is not None
    adapter, result = match
    assert adapter.key == "openapi"
    assert result.format == "openapi-3.1"


def test_detect_import_source_returns_none_when_unrecognized() -> None:
    assert detect_import_source(DetectionInput(document={"not": "a spec"})) is None


# ===========================================================================
# Default normalize delegation
# ===========================================================================


def test_normalize_via_registry_raises_for_unknown_format() -> None:
    class _NoNormalizer(ImportSource):
        key = "test-no-normalizer"
        paradigm = ApiParadigm.RPC

        def detect(self, payload):  # pragma: no cover
            return NO_MATCH

        def parse(self, raw, *, source_label=None):  # pragma: no cover
            return {}

        def normalize(self, native_ast, *, include_raw=True):
            return self._normalize_via_registry("totally-unknown-format", native_ast)

    with pytest.raises(ImportSourceError, match="No normalizer registered"):
        _NoNormalizer().normalize({})


# ===========================================================================
# Canonical fingerprint
# ===========================================================================


def _api(*, title: str = "Pets", services=None, types=None) -> CanonicalApi:
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name=title),
        title=title,
        services=services or [],
        types=types or [],
    )


def test_fingerprint_is_stable_and_ignores_raw() -> None:
    a = _api()
    b = _api()
    b.raw = {"some": "native ast", "openapi": "3.1.0"}
    # The fidelity bag is excluded — fingerprint is over the normalized shape only.
    assert canonical_fingerprint(a) == canonical_fingerprint(b)
    assert canonical_fingerprint(a).startswith("sha256:")


def test_fingerprint_changes_with_content() -> None:
    a = _api(title="Pets")
    b = _api(title="Orders")
    assert canonical_fingerprint(a) != canonical_fingerprint(b)


def test_default_fingerprint_method_matches_helper() -> None:
    source = get_import_source("sample")
    model = _api()
    assert source.fingerprint(model) == canonical_fingerprint(model)


# ===========================================================================
# Canonical diff
# ===========================================================================


def _service_with_op(op_key: str, *, summary: str = "") -> Service:
    return Service(
        key="pets",
        name="pets",
        operations=[
            Operation(
                key=op_key,
                name=op_key,
                kind=OperationKind.REQUEST_RESPONSE,
                description=summary or None,
            )
        ],
    )


def test_diff_identical_models_is_empty() -> None:
    a = _api(services=[_service_with_op("GET /pets")])
    b = _api(services=[_service_with_op("GET /pets")])
    diff = canonical_diff(a, b)
    assert isinstance(diff, CanonicalDiff)
    assert diff.is_empty


def test_diff_detects_added_removed_changed() -> None:
    a = _api(
        services=[_service_with_op("GET /pets", summary="old")],
        types=[Type(key="Pet", name="Pet", kind=TypeKind.RECORD)],
    )
    b = _api(
        services=[_service_with_op("GET /pets", summary="new")],
        types=[Type(key="Order", name="Order", kind=TypeKind.RECORD)],
    )
    diff = canonical_diff(a, b)

    changed = {(e.entity, e.key) for e in diff.of_kind(DiffChangeKind.CHANGED)}
    added = {(e.entity, e.key) for e in diff.of_kind(DiffChangeKind.ADDED)}
    removed = {(e.entity, e.key) for e in diff.of_kind(DiffChangeKind.REMOVED)}

    assert ("operation", "GET /pets") in changed
    assert ("type", "Order") in added
    assert ("type", "Pet") in removed


def test_diff_is_by_key_not_position() -> None:
    # Re-ordering services/types must not register as a diff.
    a = _api(
        types=[
            Type(key="Pet", name="Pet", kind=TypeKind.RECORD),
            Type(key="Order", name="Order", kind=TypeKind.RECORD),
        ]
    )
    b = _api(
        types=[
            Type(key="Order", name="Order", kind=TypeKind.RECORD),
            Type(key="Pet", name="Pet", kind=TypeKind.RECORD),
        ]
    )
    assert canonical_diff(a, b).is_empty


def test_default_diff_method_matches_helper() -> None:
    source = get_import_source("sample")
    a = _api(title="A")
    b = _api(title="B")
    assert source.diff(a, b) == canonical_diff(a, b)


# ===========================================================================
# Default lint
# ===========================================================================


def test_base_lint_rolls_up_canonical_model() -> None:
    # MFI-4.2: the SPI default lints the canonical model through the paradigm-agnostic engine
    # and rolls findings up to a deterministic score / grade / fingerprint (no longer empty).
    source = get_import_source("sample")
    report = source.lint(_api())
    assert isinstance(report, LintReport)
    assert isinstance(report.score, int)
    assert 0 <= report.score <= 100
    assert report.grade in {"A", "B", "C", "D", "F"}
    assert report.report_fingerprint
    # The per-severity tally is consistent with the findings the score was computed from.
    assert sum(report.severity_counts.values()) == len(report.findings)


def test_lint_report_from_lint_result_copies_the_roll_up() -> None:
    # MFI-4.2: the SPI report mirrors an engine LintResult (score/grade/fingerprint/tallies),
    # mapping each engine finding onto the SPI finding shape.
    from app.schema_lint import assemble_lint_result
    from app.schema_lint import LintFinding as EngineFinding

    result = assemble_lint_result(
        [
            EngineFinding(
                path="$.a",
                category="documentation",
                rule="documentation.schema-missing-description",
                severity="warning",
                message="missing",
            )
        ]
    )
    report = LintReport.from_lint_result(result)
    assert report.score == result.score
    assert report.grade == result.grade
    assert report.report_fingerprint == result.report_fingerprint
    assert report.rule_hits == dict(result.rule_hits)
    assert report.severity_counts == dict(result.severity_counts)
    assert [f.rule for f in report.findings] == [f.rule for f in result.findings]


def test_base_lint_is_deterministic() -> None:
    # The same fixed model always yields the same roll-up (acceptance criterion).
    source = get_import_source("sample")
    first = source.lint(_api())
    second = source.lint(_api())
    assert (first.score, first.grade, first.report_fingerprint) == (
        second.score,
        second.grade,
        second.report_fingerprint,
    )
