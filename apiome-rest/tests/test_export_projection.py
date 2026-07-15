"""Unit + contract tests for the cross-target projection manifest — EFP-1.1 (#4810).

Pins the ticket's acceptance criteria:

* **determinism** — identical (revision, target, options, emitter version) yield stable
  node/edge IDs, ordering, status counts, and manifest hash;
* **reason codes** — every ``drop`` / ``approx`` / ``synth`` / ``unavailable`` edge carries
  a reason code (the edge model rejects one without it);
* **reconciliation** — a manifest's status totals reconcile with its fidelity report for
  every registered emitter, and a hand-corrupted manifest fails reconciliation;
* **truthful fallback** — a target with no target-location adapter still reports honest
  per-construct statuses (never a false lossless), just without target pointers;
* **snapshot parity** — the projection summary embedded in the fidelity envelope is the
  same snapshot across contexts for the same inputs, and a different option set is a
  different snapshot;
* **resolvable target pointers** — the OpenAPI adapter's JSON Pointers resolve in the
  emitted document;
* **pagination** — evidence pages are bounded, cursor-driven, deterministic, and cover
  every evidence row exactly once.
"""

from __future__ import annotations

import pytest

from app.avro_emitter import AvroEmitter
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    EnumValue,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import describe_emit_targets, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_projection import (
    DEFAULT_EVIDENCE_PAGE_SIZE,
    MAX_EVIDENCE_PAGE_SIZE,
    ProjectionEdge,
    ProjectionEdgeRelation,
    ProjectionManifest,
    ProjectionNodeKind,
    ProjectionReason,
    ProjectionReconciliationError,
    ProjectionStatus,
    build_export_projection_summary,
    build_projection_manifest,
    paginate_evidence,
    reconcile_with_report,
    summarize_manifest,
)
from app.fidelity_engine import compute_lossiness_for_emitter
from app.openapi_emitter import OpenApiEmitter

# ---------------------------------------------------------------------------
# Model helpers (mirroring test_fidelity_engine.py's rich source)
# ---------------------------------------------------------------------------


def _rich_api() -> CanonicalApi:
    """A REST source exercising operation, channel, record+lossy fields, union, enum, scalar."""
    get_user = Operation(
        key="GET /users/{id}",
        name="getUser",
        kind=OperationKind.REQUEST_RESPONSE,
        http_method="GET",
        http_path="/users/{id}",
    )
    service = Service(key="Users", name="Users", operations=[get_user])
    channel = Channel(key="user/signedup", address="user/signedup", protocol="kafka")
    user = Type(
        key="User",
        name="User",
        kind=TypeKind.RECORD,
        fields=[
            CanonicalField(key="User.id", name="id", type=TypeRef(name="string", nullable=False)),
            CanonicalField(
                key="User.age",
                name="age",
                type=TypeRef(name="integer", nullable=True),
                constraints=Constraints(minimum=0, maximum=120),
            ),
            CanonicalField(
                key="User.email",
                name="email",
                type=TypeRef(name="string", nullable=False),
                constraints=Constraints(pattern=r".+@.+"),
            ),
        ],
    )
    contact = Type(key="Contact", name="Contact", kind=TypeKind.UNION, union_members=["User", "Org"])
    status = Type(
        key="Status",
        name="Status",
        kind=TypeKind.ENUM,
        enum_values=[
            EnumValue(key="Status.ACTIVE", name="ACTIVE"),
            EnumValue(key="Status.CLOSED", name="CLOSED"),
        ],
    )
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Demo"),
        services=[service],
        channels=[channel],
        types=[user, contact, status],
    )


def _empty_api() -> CanonicalApi:
    """A source with no constructs at all — the degenerate/lossless-by-vacuity case."""
    return CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="Empty"),
    )


@pytest.fixture(autouse=True)
def _emitters_loaded() -> None:
    """Ensure every built-in emitter is registered before each test."""
    load_builtin_emitters()


# ---------------------------------------------------------------------------
# Determinism (stable IDs, ordering, counts, hash)
# ---------------------------------------------------------------------------


def test_manifest_is_deterministic_across_builds() -> None:
    api = _rich_api()
    first = build_projection_manifest(api, AvroEmitter)
    second = build_projection_manifest(api, AvroEmitter)
    assert first.manifest_hash == second.manifest_hash
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_manifest_round_trips_byte_stable() -> None:
    manifest = build_projection_manifest(_rich_api(), AvroEmitter)
    revalidated = ProjectionManifest.model_validate(manifest.model_dump(mode="json"))
    assert revalidated.model_dump(mode="json") == manifest.model_dump(mode="json")
    assert revalidated.manifest_hash == manifest.manifest_hash


def test_emitter_version_changes_the_snapshot_hash() -> None:
    api = _rich_api()
    baseline = build_projection_manifest(api, AvroEmitter)

    class _BumpedAvro(AvroEmitter):
        version = "999"

    bumped = build_projection_manifest(api, _BumpedAvro)
    assert bumped.manifest_hash != baseline.manifest_hash
    assert bumped.target.emitter_version == "999"


def test_none_and_empty_options_normalize_to_the_same_snapshot() -> None:
    # Preview (no options) and a default dispatch (options={}) must agree on the snapshot,
    # because both normalize to the target's default option set.
    api = _rich_api()
    from_none = build_export_projection_summary(api, OpenApiEmitter, options=None)
    from_empty = build_export_projection_summary(api, OpenApiEmitter, options={})
    assert from_none.manifest_hash == from_empty.manifest_hash


def test_options_are_folded_into_the_snapshot_hash() -> None:
    # A distinct normalized option set must yield a distinct snapshot; the report (and thus
    # the status counts) is option-independent, so a differing hash still reconciles.
    api = _rich_api()
    fields = list(OpenApiEmitter.options_model.model_fields)
    if not fields:
        pytest.skip("target has no per-emit options to vary")
    defaults = OpenApiEmitter.default_options().model_dump()
    override = dict(defaults)
    # Flip the first boolean option; if none is boolean, there is nothing safe to vary here.
    boolean_field = next((f for f in fields if isinstance(defaults.get(f), bool)), None)
    if boolean_field is None:
        pytest.skip("target has no boolean option to flip safely")
    override[boolean_field] = not defaults[boolean_field]
    base = build_export_projection_summary(api, OpenApiEmitter, options=None)
    varied = build_export_projection_summary(api, OpenApiEmitter, options=override)
    assert varied.manifest_hash != base.manifest_hash
    assert varied.status_counts == base.status_counts


# ---------------------------------------------------------------------------
# Reason codes
# ---------------------------------------------------------------------------


def test_every_non_preserved_edge_has_a_reason_code() -> None:
    manifest = build_projection_manifest(_rich_api(), AvroEmitter)
    for edge in manifest.projects_edges:
        if edge.status in (
            ProjectionStatus.DROPPED,
            ProjectionStatus.APPROXIMATED,
            ProjectionStatus.SYNTHESIZED,
            ProjectionStatus.UNAVAILABLE,
        ):
            assert edge.reason is not None, f"{edge.id} missing reason"
        if edge.status is ProjectionStatus.RETAINED:
            assert edge.reason is None


def test_capability_driven_losses_are_destination_unsupported() -> None:
    manifest = build_projection_manifest(_rich_api(), AvroEmitter)
    reasons = {e.reason for e in manifest.projects_edges if e.reason is not None}
    assert reasons == {ProjectionReason.DESTINATION_UNSUPPORTED}


def test_edge_rejects_missing_reason_for_drop() -> None:
    with pytest.raises(ValueError):
        ProjectionEdge(
            id="projects:x#0",
            relation=ProjectionEdgeRelation.PROJECTS,
            source="canonical:x",
            status=ProjectionStatus.DROPPED,
            detail="dropped",
        )


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------


def test_manifest_reconciles_with_report_for_every_registered_emitter() -> None:
    api = _rich_api()
    formats = [t.descriptor.format for t in describe_emit_targets()]
    assert formats, "expected at least one registered emitter"
    for fmt in formats:
        emitter = get_emitter(fmt)
        assert emitter is not None
        report = compute_lossiness_for_emitter(api, emitter)
        manifest = build_projection_manifest(api, emitter, report=report)
        # Does not raise, and the mapped status counts equal the report kind counts.
        reconcile_with_report(manifest, report)
        assert manifest.status_counts[ProjectionStatus.DROPPED.value] == report.kind_counts["drop"]
        assert manifest.status_counts[ProjectionStatus.APPROXIMATED.value] == report.kind_counts["approx"]
        assert manifest.status_counts[ProjectionStatus.SYNTHESIZED.value] == report.kind_counts["synth"]
        assert manifest.status_counts[ProjectionStatus.RETAINED.value] == report.kind_counts["ok"]


def test_reconciliation_fails_on_a_corrupted_manifest() -> None:
    api = _rich_api()
    report = compute_lossiness_for_emitter(api, AvroEmitter)
    manifest = build_projection_manifest(api, AvroEmitter, report=report)
    # Flip one dropped edge to retained: the counts now diverge from the report.
    dropped = next(e for e in manifest.projects_edges if e.status is ProjectionStatus.DROPPED)
    dropped.status = ProjectionStatus.RETAINED
    dropped.reason = None
    with pytest.raises(ProjectionReconciliationError):
        reconcile_with_report(manifest, report)


# ---------------------------------------------------------------------------
# Truthful fallback / aggregate
# ---------------------------------------------------------------------------


def test_target_without_locator_is_truthful_not_lossless() -> None:
    # Avro has no target-location adapter registered: no target nodes, but honest statuses.
    manifest = build_projection_manifest(_rich_api(), AvroEmitter)
    assert not any(n.kind is ProjectionNodeKind.TARGET for n in manifest.nodes)
    assert not manifest.is_lossless  # a lossy export must never report lossless
    assert manifest.status_counts[ProjectionStatus.DROPPED.value] > 0


def test_empty_source_is_vacuously_lossless() -> None:
    manifest = build_projection_manifest(_empty_api(), AvroEmitter)
    assert manifest.total_constructs == 0
    assert manifest.projects_edges == []
    assert manifest.is_lossless
    assert manifest.worst_severity is None


def test_unknown_target_documentation_falls_back_safely() -> None:
    manifest = build_projection_manifest(_rich_api(), _UnknownFormatEmitter)
    assert manifest.target.documentation.documentation_unavailable
    assert manifest.target.documentation.url is None


def test_known_target_carries_reviewed_documentation() -> None:
    manifest = build_projection_manifest(_rich_api(), OpenApiEmitter)
    assert manifest.target.documentation.url is not None
    assert not manifest.target.documentation.documentation_unavailable


# ---------------------------------------------------------------------------
# Snapshot parity across the fidelity envelope
# ---------------------------------------------------------------------------


def test_envelope_projection_matches_a_standalone_manifest() -> None:
    api = _rich_api()
    envelope = build_export_fidelity(api, OpenApiEmitter)
    manifest = build_projection_manifest(api, OpenApiEmitter)
    assert envelope.projection.manifest_hash == manifest.manifest_hash
    # The envelope summary reconciles with the envelope's own fidelity report.
    assert envelope.projection.status_counts[ProjectionStatus.DROPPED.value] == envelope.report.kind_counts["drop"]


def test_snapshot_is_stable_across_repeated_envelope_builds() -> None:
    api = _rich_api()
    a = build_export_fidelity(api, OpenApiEmitter)
    b = build_export_fidelity(api, OpenApiEmitter)
    assert a.projection.manifest_hash == b.projection.manifest_hash


# ---------------------------------------------------------------------------
# Target pointers resolve in the emitted artifact
# ---------------------------------------------------------------------------


def _resolve_pointer(pointer: str, document: dict) -> object:
    cursor: object = document
    for raw in pointer.split("/")[1:]:
        token = raw.replace("~1", "/").replace("~0", "~")
        cursor = cursor[token]  # type: ignore[index]
    return cursor


def test_openapi_target_pointers_resolve_in_emitted_document() -> None:
    api = _rich_api()
    document = OpenApiEmitter().emit(api).files[0].content
    manifest = build_projection_manifest(api, OpenApiEmitter)
    target_nodes = [n for n in manifest.nodes if n.kind is ProjectionNodeKind.TARGET]
    assert target_nodes, "OpenAPI should place at least one construct"
    for node in target_nodes:
        pointer = node.target.json_pointer
        assert pointer is not None
        # Resolves without raising KeyError → the claimed location exists in the artifact.
        _resolve_pointer(pointer, document)


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_pagination_covers_every_evidence_row_once() -> None:
    manifest = build_projection_manifest(_rich_api(), AvroEmitter)
    total = len(manifest.projects_edges)
    seen: list[str] = []
    cursor = None
    while True:
        page = paginate_evidence(manifest, cursor=cursor, limit=2)
        assert page.total == total
        assert page.manifest_hash == manifest.manifest_hash
        seen.extend(e.id for e in page.edges)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert seen == [e.id for e in manifest.projects_edges]
    assert len(seen) == total


def test_pagination_is_deterministic() -> None:
    manifest = build_projection_manifest(_rich_api(), AvroEmitter)
    first = paginate_evidence(manifest, limit=3)
    second = paginate_evidence(manifest, limit=3)
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_pagination_page_includes_referenced_nodes() -> None:
    manifest = build_projection_manifest(_rich_api(), AvroEmitter)
    page = paginate_evidence(manifest, limit=100)
    node_ids = {n.id for n in page.nodes}
    for edge in page.edges:
        assert edge.source in node_ids  # canonical node present
        if edge.target is not None:
            assert edge.target in node_ids


def test_pagination_clamps_the_limit() -> None:
    manifest = build_projection_manifest(_rich_api(), AvroEmitter)
    page = paginate_evidence(manifest, limit=10_000)
    assert len(page.edges) <= MAX_EVIDENCE_PAGE_SIZE
    assert DEFAULT_EVIDENCE_PAGE_SIZE <= MAX_EVIDENCE_PAGE_SIZE


def test_malformed_cursor_raises() -> None:
    manifest = build_projection_manifest(_rich_api(), AvroEmitter)
    with pytest.raises(ValueError):
        paginate_evidence(manifest, cursor="not-a-cursor")


# ---------------------------------------------------------------------------
# Node/edge shape
# ---------------------------------------------------------------------------


def test_every_construct_has_native_and_canonical_nodes() -> None:
    manifest = build_projection_manifest(_rich_api(), AvroEmitter)
    canonical = {n.construct_key for n in manifest.nodes if n.kind is ProjectionNodeKind.CANONICAL}
    native = {n.construct_key for n in manifest.nodes if n.kind is ProjectionNodeKind.NATIVE}
    assert canonical == native  # one native + one canonical node per projected construct
    # Every projected construct also has a provenance (derives) edge.
    derives = {e.source.split(":", 1)[1] for e in manifest.edges if e.relation is ProjectionEdgeRelation.DERIVES}
    assert derives == {k for k in canonical if k}


def test_summary_is_bounded_and_reflects_the_manifest() -> None:
    manifest = build_projection_manifest(_rich_api(), AvroEmitter)
    summary = summarize_manifest(manifest)
    assert summary.manifest_hash == manifest.manifest_hash
    assert summary.node_count == len(manifest.nodes)
    assert summary.edge_count == len(manifest.edges)
    assert summary.evidence_count == len(manifest.projects_edges)
    assert summary.status_counts == manifest.status_counts
    # The bounded summary carries no node/edge lists (it is a reference, not the graph).
    assert "nodes" not in summary.model_dump()
    assert "edges" not in summary.model_dump()


# A tiny emitter with an unregistered format, to exercise the documentation fallback.
class _UnknownFormatEmitter(OpenApiEmitter):
    key = "mystery"
    format = "mystery-1"
    label = "Mystery"
