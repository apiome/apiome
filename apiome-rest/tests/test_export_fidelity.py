"""Tests for fidelity report surfacing — tiers, preserved-% and envelopes — MFX-2.5 (#3842).

Covers the pure presentation layer (:mod:`app.export_fidelity`) the REST surface sits on:

* :func:`~app.export_fidelity.preserved_percent` — the OK÷total estimate, incl. the empty case;
* :func:`~app.export_fidelity.classify_tier` — lossless vs types-only vs lossy, driven by the
  report and the target's capability profile;
* :func:`~app.export_fidelity.build_target_fidelity` — the cheap per-target badge;
* :func:`~app.export_fidelity.build_export_fidelity` — the full envelope (report + advisory +
  summary), including that a preview and a re-run are byte-identical (determinism).
"""

from __future__ import annotations

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import CapabilityProfile, EmitResult, Emitter
from app.export_fidelity import (
    ExportFidelityTier,
    build_export_fidelity,
    build_target_fidelity,
    classify_tier,
    preserved_percent,
)
from app.lossiness import (
    LossinessKind,
    LossinessReport,
    LossinessReportBuilder,
    LossinessSeverity,
)
from app.openapi_emitter import OpenApiEmitter
from app.sample_emitter import SampleEmitter


# ---------------------------------------------------------------------------
# Model builders
# ---------------------------------------------------------------------------
def _rest_api_with_operation() -> CanonicalApi:
    """A REST API with one operation + one clean record type (2 constructs)."""
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))],
    )
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    service = Service(key="widgets", name="widgets", operations=[op])
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        services=[service],
        types=[widget],
    )


def _types_only_api() -> CanonicalApi:
    """A source with only a type and no operations/channels."""
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        types=[widget],
    )


def _api_with_constrained_field() -> CanonicalApi:
    """A record whose one field carries a length constraint (an APPROX on a no-constraints target)."""
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(
                key="Widget.code",
                name="code",
                type=TypeRef(name="string", nullable=True),
                constraints=Constraints(max_length=10),
            )
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        types=[widget],
    )


class _OpsNoConstraintsEmitter(Emitter):
    """Test emitter: carries operations/events but cannot enforce constraints (a lossy, not types-only, target)."""

    key = "opsnc"
    format = "opsnc-1"
    label = "OpsNC"
    paradigm = ApiParadigm.REST

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=True,
            unions=True,
            nullability=True,
            constraints=False,
            field_identity=True,
        )

    def emit(self, api: CanonicalApi, *, opts=None) -> EmitResult:  # pragma: no cover - never emitted
        raise NotImplementedError


def _report(*kinds: LossinessKind) -> LossinessReport:
    """Build a report with one item per given kind (severity info, distinct construct keys)."""
    builder = LossinessReportBuilder()
    for index, kind in enumerate(kinds):
        builder.add(
            f"C{index}",
            kind,
            LossinessSeverity.INFO if kind is LossinessKind.OK else LossinessSeverity.WARN,
            f"item {index}",
        )
    return builder.build()


# ---------------------------------------------------------------------------
# preserved_percent
# ---------------------------------------------------------------------------
def test_preserved_percent_empty_report_is_full():
    """A source with no constructs is fully preserved (nothing to lose)."""
    assert preserved_percent(LossinessReport()) == 100


def test_preserved_percent_all_ok_is_100():
    assert preserved_percent(_report(LossinessKind.OK, LossinessKind.OK)) == 100


def test_preserved_percent_is_ok_over_total_rounded():
    """3 of 4 OK → 75%; 1 of 3 OK → rounds to 33."""
    assert preserved_percent(
        _report(LossinessKind.OK, LossinessKind.OK, LossinessKind.OK, LossinessKind.DROP)
    ) == 75
    assert preserved_percent(
        _report(LossinessKind.OK, LossinessKind.DROP, LossinessKind.APPROX)
    ) == 33


# ---------------------------------------------------------------------------
# classify_tier
# ---------------------------------------------------------------------------
def test_classify_tier_lossless_when_all_ok():
    """An all-OK report is lossless regardless of the target profile."""
    schema_only = CapabilityProfile(operations=False, events=False)
    assert classify_tier(_report(LossinessKind.OK), schema_only) is ExportFidelityTier.LOSSLESS


def test_classify_tier_types_only_for_schema_only_target():
    """A lossy export to a schema-only target (no ops/events) is types-only."""
    schema_only = CapabilityProfile(operations=False, events=False)
    tier = classify_tier(_report(LossinessKind.OK, LossinessKind.DROP), schema_only)
    assert tier is ExportFidelityTier.TYPES_ONLY


def test_classify_tier_lossy_for_operation_bearing_target():
    """A lossy export to a target that carries operations is lossy (not types-only)."""
    ops_target = CapabilityProfile(operations=True, events=False)
    tier = classify_tier(_report(LossinessKind.OK, LossinessKind.APPROX), ops_target)
    assert tier is ExportFidelityTier.LOSSY


# ---------------------------------------------------------------------------
# build_target_fidelity (integration with the engine + real emitters)
# ---------------------------------------------------------------------------
def test_openapi_to_openapi_is_lossless():
    """OpenAPI → OpenAPI carries every construct (the roadmap's lossless example)."""
    tf = build_target_fidelity(_rest_api_with_operation(), OpenApiEmitter)
    assert tf.tier is ExportFidelityTier.LOSSLESS
    assert tf.preserved_percent == 100
    assert tf.dropped == 0


def test_operations_to_schema_only_target_is_types_only():
    """An operation-bearing source → a schema-only target drops the operation → types-only."""
    tf = build_target_fidelity(_rest_api_with_operation(), SampleEmitter)
    assert tf.tier is ExportFidelityTier.TYPES_ONLY
    assert tf.dropped == 1  # the operation
    assert tf.preserved == 1  # the type
    assert tf.total == 2
    assert tf.preserved_percent == 50


def test_types_only_source_to_schema_only_target_is_lossless():
    """When the source has no operations, a schema-only target loses nothing → lossless."""
    tf = build_target_fidelity(_types_only_api(), SampleEmitter)
    assert tf.tier is ExportFidelityTier.LOSSLESS
    assert tf.preserved_percent == 100


def test_constraint_loss_to_operation_bearing_target_is_lossy():
    """A constrained field → a target that keeps operations but not constraints → lossy."""
    tf = build_target_fidelity(_api_with_constrained_field(), _OpsNoConstraintsEmitter)
    assert tf.tier is ExportFidelityTier.LOSSY
    assert tf.approximated >= 1


# ---------------------------------------------------------------------------
# build_export_fidelity (the full envelope)
# ---------------------------------------------------------------------------
def test_export_fidelity_lossless_suppresses_advisory():
    """A lossless export carries the report + summary but a hidden advisory."""
    xf = build_export_fidelity(_rest_api_with_operation(), OpenApiEmitter)
    assert xf.advisory.show is False
    assert xf.summary.tier is ExportFidelityTier.LOSSLESS
    assert xf.target.key == "openapi"
    assert xf.report.is_lossless


def test_export_fidelity_lossy_shows_advisory_with_counts():
    """A lossy export raises the advisory and the counts match the report."""
    xf = build_export_fidelity(_rest_api_with_operation(), SampleEmitter)
    assert xf.advisory.show is True
    assert xf.summary.tier is ExportFidelityTier.TYPES_ONLY
    # The dropped count agrees across the report, the summary, and the advisory.
    assert xf.report.kind_counts[LossinessKind.DROP.value] == 1
    assert xf.summary.dropped == 1
    assert xf.advisory.dropped == 1


def test_export_fidelity_is_deterministic():
    """A preview and a re-run over the same inputs serialize identically (determinism)."""
    api = _rest_api_with_operation()
    first = build_export_fidelity(api, SampleEmitter).model_dump(mode="json")
    second = build_export_fidelity(api, SampleEmitter).model_dump(mode="json")
    assert first == second


def test_export_fidelity_min_severity_relaxes_advisory():
    """Raising the threshold to WARN suppresses an info-only (sub-threshold) advisory."""
    # A single approximated field at WARN severity: default INFO shows it, WARN+ still shows it,
    # but CRITICAL-only would hide it. Use CRITICAL to prove the threshold is honoured.
    xf_info = build_export_fidelity(_api_with_constrained_field(), _OpsNoConstraintsEmitter)
    xf_critical = build_export_fidelity(
        _api_with_constrained_field(),
        _OpsNoConstraintsEmitter,
        min_severity=LossinessSeverity.CRITICAL,
    )
    assert xf_info.advisory.show is True
    assert xf_critical.advisory.show is False
    # The report + counts are unaffected by the threshold.
    assert xf_info.report.total == xf_critical.report.total
