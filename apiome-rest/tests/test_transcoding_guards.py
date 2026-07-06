"""Unit tests for the any-to-any transcoding guards — MFX-3.3 (#3846).

Pins the pre-flight classifier and its enforcement gate independently of the REST layer:

* :func:`app.transcoding_guards.classify_transcode` bands a conversion into
  ``clean`` / ``lossy`` / ``near-empty`` / ``severe`` from the source model, the target's
  capability profile, and the fidelity report;
* the two acceptance criteria of MFX-3.3 are asserted directly — an operation-bearing API to
  a types-only target (Avro) is ``near-empty`` and *warns* (does not block), while an
  event-only API to an operation-only target (Protobuf) is ``severe`` and *requires
  confirmation*;
* :func:`app.transcoding_guards.enforce_transcode_guard` raises
  :class:`~app.transcoding_guards.TranscodeGuardError` for a severe conversion the caller has
  not confirmed, and passes every other band (and a confirmed severe one) through;
* the guard corroborates the report (its counts come from the report handed to it), and a
  ``critical`` construct on a paradigm-compatible target is severe on its own.

The emitter path runs the real registry/SPI (OpenAPI, Avro, Protobuf); one controlled
in-test emitter with a bare capability profile exercises the "critical construct on a
compatible target" branch without depending on a specific real target's rule pack.
"""

from __future__ import annotations

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import CapabilityProfile, EmitResult, Emitter, get_emitter
from app.fidelity_engine import compute_lossiness_for_emitter
from app.transcoding_guards import (
    TranscodeGuard,
    TranscodeGuardError,
    TranscodeVerdict,
    classify_transcode,
    enforce_transcode_guard,
)


# ---------------------------------------------------------------------------
# Source fixtures — one per paradigm shape the guard reasons about
# ---------------------------------------------------------------------------
def _record(key: str) -> Type:
    """A minimal one-field record type."""
    return Type(
        key=key,
        name=key,
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key=f"{key}.id", name="id", type=TypeRef(name="string"))],
    )


def _rest_api() -> CanonicalApi:
    """An operation-bearing REST API: one operation + one schema."""
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        services=[Service(key="widgets", name="widgets", operations=[op])],
        types=[_record("Widget")],
    )


def _event_api() -> CanonicalApi:
    """An event-only API: one channel + one message schema, no operations."""
    return CanonicalApi(
        paradigm=ApiParadigm.EVENT,
        format="asyncapi-3",
        identity=ApiIdentity(name="signup"),
        channels=[Channel(key="user/signedup", address="user/signedup")],
        types=[_record("Signup")],
    )


def _openapi() -> type[Emitter]:
    return get_emitter("openapi-3.1")


def _avro() -> type[Emitter]:
    return get_emitter("avro")


def _protobuf() -> type[Emitter]:
    return get_emitter("proto3")


# ---------------------------------------------------------------------------
# clean — a lossless conversion asks for nothing
# ---------------------------------------------------------------------------
def test_lossless_conversion_is_clean_and_needs_no_confirmation():
    """REST → OpenAPI carries everything, so the guard is ``clean`` and never blocks."""
    guard = classify_transcode(_rest_api(), _openapi())

    assert guard.verdict is TranscodeVerdict.CLEAN
    assert guard.requires_confirmation is False
    assert guard.preserved_percent == 100
    assert guard.dropped_operations == 0
    assert guard.dropped_events == 0
    assert guard.reasons == []
    assert guard.source_paradigm is ApiParadigm.REST
    assert guard.target_paradigm is ApiParadigm.REST


# ---------------------------------------------------------------------------
# near-empty — AC: operations → Avro warns that only schemas export
# ---------------------------------------------------------------------------
def test_operations_to_types_only_target_is_near_empty_and_warns_only_schemas_export():
    """An operation-bearing API → Avro is ``near-empty``: it warns, but does not block."""
    guard = classify_transcode(_rest_api(), _avro())

    assert guard.verdict is TranscodeVerdict.NEAR_EMPTY
    # A near-empty warning is surfaced but never gates the export (AC: it *warns*).
    assert guard.requires_confirmation is False
    # The "why": the single operation cannot survive on a types-only target.
    assert guard.dropped_operations == 1
    assert guard.dropped_events == 0
    assert "types-only" in guard.message
    assert "schemas only" in guard.message
    assert guard.target_paradigm is ApiParadigm.DATA_SCHEMA
    assert any("cannot represent operations" in reason for reason in guard.reasons)


def test_near_empty_message_names_both_dropped_operations_and_events():
    """A source with operations *and* events → Avro names both in the near-empty copy."""
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="mixed"),
        services=[Service(key="s", name="s", operations=[op])],
        channels=[Channel(key="user/signedup", address="user/signedup")],
        types=[_record("Widget")],
    )
    guard = classify_transcode(api, _avro())

    assert guard.verdict is TranscodeVerdict.NEAR_EMPTY
    assert guard.dropped_operations == 1
    assert guard.dropped_events == 1
    assert "1 operation" in guard.message
    assert "1 event channel" in guard.message


# ---------------------------------------------------------------------------
# severe — AC: event-only → gRPC/Protobuf requires confirmation
# ---------------------------------------------------------------------------
def test_event_only_to_operation_target_is_severe_and_requires_confirmation():
    """An event-only API → Protobuf is a nonsensical paradigm shift: ``severe``, must confirm."""
    guard = classify_transcode(_event_api(), _protobuf())

    assert guard.verdict is TranscodeVerdict.SEVERE
    assert guard.requires_confirmation is True
    # Protobuf carries operations but not events, and it is not a types-only reduction, so the
    # source's entire event surface is unrepresentable.
    assert guard.dropped_events == 1
    assert guard.dropped_operations == 0
    assert "event channel" in guard.message
    assert guard.source_paradigm is ApiParadigm.EVENT
    assert guard.target_paradigm is ApiParadigm.RPC


# ---------------------------------------------------------------------------
# severe — a critical construct on a paradigm-compatible target
# ---------------------------------------------------------------------------
class _OperationOnlyEmitter(Emitter):
    """A controlled target that carries operations but nothing else (bare profile).

    Not registered — instantiated only for tests. It hosts the source's operations (so the
    conversion is *not* a paradigm mismatch) but cannot carry unions, so a source union drops
    at ``critical`` severity under the default capability rule pack — exactly the
    "compatible paradigm, critical loss" branch.
    """

    key = "opsonly"
    format = "opsonly"
    label = "Operations-Only"
    description = "A test target that carries operations only."
    paradigm = ApiParadigm.RPC

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(operations=True)

    def emit(self, api, *, opts=None) -> EmitResult:  # pragma: no cover - never emitted in tests
        raise NotImplementedError


def _api_with_operation_and_union() -> CanonicalApi:
    """An RPC API whose operations survive but whose union type drops critically."""
    op = Operation(key="acme.Svc.Get", name="Get", kind=OperationKind.REQUEST_RESPONSE)
    union = Type(key="Result", name="Result", kind=TypeKind.UNION)
    return CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="grpc",
        identity=ApiIdentity(name="acme"),
        services=[Service(key="acme.Svc", name="Svc", operations=[op])],
        types=[union],
    )


def test_critical_construct_on_compatible_target_is_severe():
    """Operations survive but a union drops critically → ``severe`` on paradigm grounds alone."""
    api = _api_with_operation_and_union()
    # Sanity: the report really does carry a critical drop (the union) and no dropped operation.
    report = compute_lossiness_for_emitter(api, _OperationOnlyEmitter)
    assert report.severity_counts["critical"] >= 1

    guard = classify_transcode(api, _OperationOnlyEmitter, report=report)

    assert guard.verdict is TranscodeVerdict.SEVERE
    assert guard.requires_confirmation is True
    # The operations are hosted, so nothing is flagged as an unrepresentable operation…
    assert guard.dropped_operations == 0
    # …but the critical construct is surfaced as the reason.
    assert guard.critical_constructs >= 1
    assert any("critical severity" in reason for reason in guard.reasons)


# ---------------------------------------------------------------------------
# lossy — degraded but the operational surface survives
# ---------------------------------------------------------------------------
def test_degraded_but_compatible_conversion_is_lossy_without_a_gate():
    """A constraint-only demotion on a compatible target is ``lossy`` — surfaced, not gated."""
    # A REST API whose field carries a constraint the bare operations-only target can't enforce.
    field = CanonicalField(
        key="Widget.size",
        name="size",
        type=TypeRef(name="integer"),
    )
    # Attach a minimum constraint so the field degrades to APPROX (warn), never critical.
    field = field.model_copy(update={"constraints": _min_constraint()})
    widget = Type(key="Widget", name="Widget", kind=TypeKind.RECORD, fields=[field])
    op = Operation(key="acme.Svc.Get", name="Get", kind=OperationKind.REQUEST_RESPONSE)
    api = CanonicalApi(
        paradigm=ApiParadigm.RPC,
        format="grpc",
        identity=ApiIdentity(name="acme"),
        services=[Service(key="acme.Svc", name="Svc", operations=[op])],
        types=[widget],
    )

    guard = classify_transcode(api, _OperationOnlyEmitter)

    assert guard.verdict is TranscodeVerdict.LOSSY
    assert guard.requires_confirmation is False
    assert guard.critical_constructs == 0
    assert guard.dropped_operations == 0


def _min_constraint():
    """A canonical constraints object carrying a single ``minimum`` facet."""
    from app.canonical_model import Constraints

    return Constraints(minimum=0)


# ---------------------------------------------------------------------------
# enforcement gate
# ---------------------------------------------------------------------------
def test_enforce_blocks_severe_without_confirmation():
    """A severe guard raises :class:`TranscodeGuardError` (409) when unconfirmed."""
    guard = classify_transcode(_event_api(), _protobuf())
    assert guard.requires_confirmation is True

    with pytest.raises(TranscodeGuardError) as exc_info:
        enforce_transcode_guard(guard, confirmed=False)

    assert exc_info.value.status_code == 409
    assert exc_info.value.guard is guard
    assert str(exc_info.value) == guard.message


def test_enforce_allows_severe_when_confirmed():
    """A confirmed severe conversion passes the gate and returns the guard unchanged."""
    guard = classify_transcode(_event_api(), _protobuf())

    returned = enforce_transcode_guard(guard, confirmed=True)

    assert returned is guard


@pytest.mark.parametrize(
    "api_factory, emitter_factory",
    [
        (_rest_api, _openapi),  # clean
        (_rest_api, _avro),  # near-empty
    ],
)
def test_enforce_never_blocks_non_severe_conversions(api_factory, emitter_factory):
    """Clean and near-empty conversions pass the gate regardless of the confirm flag."""
    guard = classify_transcode(api_factory(), emitter_factory())
    assert guard.requires_confirmation is False

    # Neither confirmed nor unconfirmed blocks a non-severe conversion.
    assert enforce_transcode_guard(guard, confirmed=False) is guard
    assert enforce_transcode_guard(guard, confirmed=True) is guard


# ---------------------------------------------------------------------------
# the guard corroborates the report handed to it (no second walk, no drift)
# ---------------------------------------------------------------------------
def test_guard_uses_the_report_it_is_given():
    """When a report is passed, the guard's counts are read from *that* report."""
    api = _rest_api()
    emitter = _avro()
    report = compute_lossiness_for_emitter(api, emitter)

    guard = classify_transcode(api, emitter, report=report)

    assert guard.dropped_constructs == report.kind_counts["drop"]
    assert guard.critical_constructs == report.severity_counts["critical"]
    # preserved_percent matches the fidelity summary's definition (OK ÷ total).
    total = report.total
    expected = 100 if total == 0 else round(100 * report.kind_counts["ok"] / total)
    assert guard.preserved_percent == expected


def test_guard_is_deterministic():
    """Classifying the same inputs twice yields an equal guard (pure/deterministic)."""
    api = _event_api()
    emitter = _protobuf()

    first = classify_transcode(api, emitter)
    second = classify_transcode(api, emitter)

    assert isinstance(first, TranscodeGuard)
    assert first.model_dump() == second.model_dump()
