"""Cross-format projection fixture & contract corpus tests — EFP-1.3 (#4812).

Drives the corpus in :mod:`tests.projection_corpus` to pin the ticket's acceptance
criteria:

* **coverage gate** — every registered emitter must declare projection coverage
  (deep / generic) or a documented waiver; a new emitter that skips the corpus fails
  here with instructions;
* **all-emitter sweep** — for every registered target × every corpus source: the
  manifest is deterministic, reconciles with the fidelity report, its envelope passes
  the parity checker, and every non-preserved edge carries registry evidence
  (reason + explanation + documentation) drawn from the canonical taxonomy;
* **deep MVP matrix** — OpenAPI / AsyncAPI / GraphQL / Proto3 / Avro: golden manifests
  (deterministic, redacted), artifact emission, and claimed target pointers resolving
  in the emitted document (with no fabricated locations for locator-less targets);
* **full vocabulary** — scenario fixtures exercise every ProjectionStatus and every
  ProjectionReason (including the report-less unavailable / not-applicable statuses and
  the source-incomplete / parser-limited / option-excluded / tool-unavailable reasons),
  and unknown status or reason codes are rejected at the model layer;
* **cross-surface parity** — target cards, preview, verify, dispatch (dry + real), and
  the export job result all describe the same snapshot hash and agree count-for-count;
  a tampered envelope is detected by the parity checker.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from projection_corpus import (
    CORPUS_COVERAGE,
    DEEP,
    DEEP_TARGETS,
    GENERIC,
    SENSITIVE_SENTINEL,
    Waiver,
    assert_golden_is_redacted,
    assert_matches_golden,
    builtin_formats,
    empty_api,
    envelope_parity_issues,
    event_api,
    golden_path,
    normalize_volatile_provenance,
    parity_fixture_payload,
    redact_manifest_payload,
    rich_api,
    types_only_api,
)

from app.auth import validate_authentication
from app.canonical_model import CanonicalApi
from app.capability_registry import (
    REGISTRY_VERSION,
    documentation_for,
    is_safe_documentation_url,
    reason_explanation,
)
from app.emitter import get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_job_engine import (
    ExportJobStartRequest,
    get_export_job_status,
    schedule_export_job,
)
from app.export_projection import (
    ProjectionEdge,
    ProjectionEdgeRelation,
    ProjectionManifest,
    ProjectionNode,
    ProjectionNodeKind,
    ProjectionReason,
    ProjectionReconciliationError,
    ProjectionStatus,
    build_projection_manifest,
    paginate_evidence,
    reconcile_with_report,
    summarize_manifest,
)
from app.export_service import emit_canonical
from app.export_source import ExportSource
from app.lossiness import LossinessKind, LossinessReportBuilder, LossinessSeverity
from app.main import app
from app.openapi_emitter import OpenApiEmitter


@pytest.fixture(autouse=True)
def _emitters_loaded() -> None:
    """Ensure every built-in emitter is registered before each test."""
    load_builtin_emitters()


# The corpus source matrix the all-emitter sweep runs against.
_SWEEP_SOURCES = {
    "rich": rich_api,
    "event": event_api,
    "types_only": types_only_api,
    "empty": empty_api,
}


# ---------------------------------------------------------------------------
# Coverage gate: add fixtures or an explicit documented waiver
# ---------------------------------------------------------------------------


def test_every_emitter_declares_projection_coverage() -> None:
    """Every built-in emitter format appears in CORPUS_COVERAGE (or is waived).

    Scoped to built-in (``app.*``) emitters so throwaway emitters other test modules
    register into the shared registry cannot trip the gate in a full-suite run.
    """
    registered = set(builtin_formats())
    declared = set(CORPUS_COVERAGE)

    missing = sorted(registered - declared)
    assert not missing, (
        f"emitters {missing} are registered but declare no projection coverage; add them to "
        "tests/projection_corpus.py CORPUS_COVERAGE as DEEP (with a golden), GENERIC (sweep "
        "only), or an explicit Waiver('reason') — new emitters must add projection fixtures "
        "or a documented waiver (EFP-1.3)"
    )
    stale = sorted(declared - registered)
    assert not stale, (
        f"CORPUS_COVERAGE declares {stale} which are not registered emitters; remove the "
        "stale entries from tests/projection_corpus.py"
    )


def test_coverage_levels_and_waivers_are_well_formed() -> None:
    """Coverage values are DEEP/GENERIC or a Waiver with a non-empty documented reason."""
    for fmt, level in CORPUS_COVERAGE.items():
        if isinstance(level, Waiver):
            assert level.reason.strip(), f"waiver for {fmt!r} must document a non-empty reason"
        else:
            assert level in (DEEP, GENERIC), f"unknown coverage level {level!r} for {fmt!r}"
    # The MVP deep matrix is exactly the five representative targets the roadmap names.
    assert sorted(DEEP_TARGETS) == sorted(["openapi-3.1", "asyncapi-3", "graphql", "proto3", "avro"])


# ---------------------------------------------------------------------------
# All-emitter sweep: determinism, reconciliation, parity, registry evidence
# ---------------------------------------------------------------------------


def _swept_formats() -> List[str]:
    """Every built-in format with non-waived coverage, in stable order."""
    return [fmt for fmt in builtin_formats() if not isinstance(CORPUS_COVERAGE.get(fmt), Waiver)]


@pytest.mark.parametrize("source_name", sorted(_SWEEP_SOURCES))
def test_sweep_manifests_are_deterministic_and_reconciled(source_name: str) -> None:
    """For every emitter × source: two builds agree byte-for-byte and reconcile with the report."""
    api = _SWEEP_SOURCES[source_name]()
    for fmt in _swept_formats():
        emitter = get_emitter(fmt)
        assert emitter is not None
        first = build_projection_manifest(api, emitter)
        second = build_projection_manifest(api, emitter)
        assert first.manifest_hash == second.manifest_hash, fmt
        assert first.model_dump(mode="json") == second.model_dump(mode="json"), fmt
        # Registry/tool versions ride in the evidence (EFP-1.2 AC re-pinned at corpus level).
        assert first.target.registry_version == REGISTRY_VERSION, fmt
        assert first.target.emitter_version == emitter.version, fmt


@pytest.mark.parametrize("source_name", sorted(_SWEEP_SOURCES))
def test_sweep_envelopes_pass_the_parity_checker(source_name: str) -> None:
    """For every emitter × source, the serialized fidelity envelope is internally consistent."""
    api = _SWEEP_SOURCES[source_name]()
    for fmt in _swept_formats():
        emitter = get_emitter(fmt)
        envelope = build_export_fidelity(api, emitter).model_dump(mode="json")
        issues = envelope_parity_issues(envelope)
        assert issues == [], f"{fmt}/{source_name}: {issues}"


def test_sweep_non_preserved_edges_carry_registry_evidence() -> None:
    """Every drop/approx/synth/unavailable edge has a reason, explanation, and documentation."""
    api = rich_api()
    for fmt in _swept_formats():
        emitter = get_emitter(fmt)
        manifest = build_projection_manifest(api, emitter)
        for edge in manifest.projects_edges:
            if edge.status is ProjectionStatus.RETAINED:
                assert edge.explanation is None, f"{fmt}:{edge.id}"
                assert edge.documentation is None, f"{fmt}:{edge.id}"
                continue
            assert edge.reason is not None, f"{fmt}:{edge.id}"
            assert edge.explanation, f"{fmt}:{edge.id}"
            assert edge.documentation is not None, f"{fmt}:{edge.id}"
            if edge.documentation.url is not None:
                assert is_safe_documentation_url(edge.documentation.url), f"{fmt}:{edge.id}"
            else:
                assert edge.documentation.documentation_unavailable, f"{fmt}:{edge.id}"


# ---------------------------------------------------------------------------
# Deep MVP matrix: goldens, artifact emission, pointer resolution
# ---------------------------------------------------------------------------


def _resolve_json_pointer(document: Any, pointer: str) -> Any:
    """Resolve an RFC 6901 JSON Pointer in ``document``; raise KeyError when absent."""
    if pointer == "":
        return document
    node = document
    for raw_token in pointer.lstrip("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict):
            if token not in node:
                raise KeyError(f"pointer {pointer!r} does not resolve at token {token!r}")
            node = node[token]
        else:
            raise KeyError(f"pointer {pointer!r} hit a scalar at token {token!r}")
    return node


def _golden_name(fmt: str) -> str:
    """The golden file base name for one deep-target manifest."""
    return f"manifest_{fmt.replace('.', '_').replace('-', '_')}"


@pytest.mark.parametrize("fmt", sorted(DEEP_TARGETS))
def test_deep_manifest_matches_redacted_golden(fmt: str) -> None:
    """Each MVP target's rich-source manifest matches its checked-in, redacted golden.

    The golden is redacted (no source-sensitive native values) and normalized (no
    release-volatile ``apiome_version`` / ``manifest_hash``), so it pins structure,
    statuses, reasons, explanations, documentation, and target locations — and survives
    a routine package-version bump while still catching behavioral drift.
    """
    emitter = get_emitter(fmt)
    manifest = build_projection_manifest(rich_api(), emitter)
    payload = normalize_volatile_provenance(
        redact_manifest_payload(manifest.model_dump(mode="json"))
    )
    assert_matches_golden(_golden_name(fmt), payload)
    assert_golden_is_redacted(_golden_name(fmt))


def test_goldens_never_leak_the_source_sensitive_sentinel() -> None:
    """The planted secret reaches the live manifest but never the redacted golden payload.

    Avro is the sentinel target: its constraint losses produce field-level report items,
    so the planted ``User.email`` native evidence (id + source location) lands in the
    live manifest — and must be scrubbed from the golden.
    """
    manifest = build_projection_manifest(rich_api(), get_emitter("avro"))
    live = json.dumps(manifest.model_dump(mode="json"))
    assert SENSITIVE_SENTINEL in live, (
        "fixture should plant the sentinel into native evidence — if this fails the "
        "redaction test is no longer proving anything"
    )
    redacted = json.dumps(redact_manifest_payload(manifest.model_dump(mode="json")))
    assert SENSITIVE_SENTINEL not in redacted


def test_openapi_manifest_never_leaks_when_fields_are_carried_cleanly() -> None:
    """A target that carries the sensitive field cleanly emits no native detail for it."""
    manifest = build_projection_manifest(rich_api(), OpenApiEmitter)
    # OpenAPI carries User.email faithfully, so the report has no field item and the
    # manifest no native-evidence node for it — nothing sensitive to redact.
    assert SENSITIVE_SENTINEL not in json.dumps(manifest.model_dump(mode="json"))


@pytest.mark.parametrize("fmt", sorted(DEEP_TARGETS))
def test_deep_claimed_target_pointers_resolve_in_the_emitted_artifact(fmt: str) -> None:
    """Where a manifest claims a JSON Pointer target location, it resolves in the artifact.

    OpenAPI is the one MVP target with a registered location adapter; its pointers must
    resolve in the emitted document. Every other deep target must make **no** location
    claims (the truthful ``None`` fallback) — if a location adapter is added later, this
    test forces the corpus to grow resolution coverage with it.
    """
    api = rich_api()
    emitter = get_emitter(fmt)
    manifest = build_projection_manifest(api, emitter)
    target_nodes = [n for n in manifest.nodes if n.kind is ProjectionNodeKind.TARGET]

    if fmt != "openapi-3.1":
        assert target_nodes == [], (
            f"{fmt} claims target locations but the corpus has no resolution coverage for "
            "it; extend this test alongside the new location adapter"
        )
        return

    assert target_nodes, "the OpenAPI adapter should claim locations for the rich source"
    result = emit_canonical(api, fmt)
    document = result.files[0].content
    assert isinstance(document, dict)
    for node in target_nodes:
        assert node.target is not None and node.target.json_pointer, node.id
        resolved = _resolve_json_pointer(document, node.target.json_pointer)
        assert resolved is not None, f"{node.target.json_pointer} resolved to nothing"


# ---------------------------------------------------------------------------
# Full status/reason vocabulary (scenario fixtures)
# ---------------------------------------------------------------------------

# Scenario rows: (construct, status, reason) covering every ProjectionStatus and every
# ProjectionReason at least once — including the report-less statuses and the reasons
# the default engine build never produces (parser limits, redaction, options, tooling).
_VOCABULARY_ROWS: List[tuple] = [
    ("Kept.record", ProjectionStatus.RETAINED, None),
    ("Renamed.operation", ProjectionStatus.TRANSFORMED, None),
    ("Approx.constraint", ProjectionStatus.APPROXIMATED, ProjectionReason.DESTINATION_UNSUPPORTED),
    ("Synth.fieldNumber", ProjectionStatus.SYNTHESIZED, ProjectionReason.DESTINATION_UNSUPPORTED),
    ("Dropped.route", ProjectionStatus.DROPPED, ProjectionReason.DESTINATION_UNSUPPORTED),
    ("Dropped.binding", ProjectionStatus.DROPPED, ProjectionReason.EMITTER_UNSUPPORTED),
    ("Dropped.example", ProjectionStatus.DROPPED, ProjectionReason.OPTION_EXCLUDED),
    ("Dropped.toolOutput", ProjectionStatus.DROPPED, ProjectionReason.TARGET_TOOL_UNAVAILABLE),
    ("Unavailable.docBlock", ProjectionStatus.UNAVAILABLE, ProjectionReason.SOURCE_INCOMPLETE),
    ("Unavailable.grammar", ProjectionStatus.UNAVAILABLE, ProjectionReason.SOURCE_PARSE_LIMIT),
    ("Unavailable.secret", ProjectionStatus.UNAVAILABLE, ProjectionReason.SECURITY_REDACTED),
    ("Skipped.channel", ProjectionStatus.NOT_APPLICABLE, ProjectionReason.NOT_APPLICABLE),
]


def _vocabulary_manifest() -> ProjectionManifest:
    """A hand-authored manifest exercising every status and reason in one graph."""
    target = build_projection_manifest(empty_api(), OpenApiEmitter).target
    nodes: List[ProjectionNode] = []
    edges: List[ProjectionEdge] = []
    for construct, status, reason in _VOCABULARY_ROWS:
        canonical_id = f"canonical:{construct}"
        nodes.append(
            ProjectionNode(
                id=canonical_id,
                kind=ProjectionNodeKind.CANONICAL,
                label=construct,
                construct_key=construct,
                canonical_kind="type",
            )
        )
        edges.append(
            ProjectionEdge(
                id=f"projects:{construct}#0",
                relation=ProjectionEdgeRelation.PROJECTS,
                source=canonical_id,
                target=None,
                status=status,
                reason=reason,
                severity=LossinessSeverity.INFO,
                detail=f"scenario row for {status.value}",
            )
        )
    return ProjectionManifest(target=target, nodes=nodes, edges=edges)


def test_vocabulary_scenarios_cover_every_status_and_reason() -> None:
    """The scenario matrix touches all 7 statuses and all 8 reasons — by construction."""
    statuses = {status for _, status, _ in _VOCABULARY_ROWS}
    reasons = {reason for _, _, reason in _VOCABULARY_ROWS if reason is not None}
    assert statuses == set(ProjectionStatus)
    assert reasons == set(ProjectionReason)


def test_vocabulary_manifest_validates_counts_and_paginates() -> None:
    """The full-vocabulary manifest validates, counts correctly, and pages every row once."""
    manifest = _vocabulary_manifest()

    assert manifest.status_counts[ProjectionStatus.DROPPED.value] == 4
    assert manifest.status_counts[ProjectionStatus.UNAVAILABLE.value] == 3
    assert manifest.status_counts[ProjectionStatus.RETAINED.value] == 1
    assert manifest.status_counts[ProjectionStatus.TRANSFORMED.value] == 1
    assert manifest.status_counts[ProjectionStatus.NOT_APPLICABLE.value] == 1
    for reason in ProjectionReason:
        assert manifest.reason_counts[reason.value] >= 1, reason

    summary = summarize_manifest(manifest)
    assert summary.evidence_count == len(_VOCABULARY_ROWS)
    assert summary.is_lossless is False

    # Pagination covers every evidence row exactly once, in canonical order.
    seen: List[str] = []
    cursor: Optional[str] = None
    while True:
        page = paginate_evidence(manifest, cursor=cursor, limit=5)
        seen.extend(edge.id for edge in page.edges)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert seen == [edge.id for edge in manifest.projects_edges]

    # Round-trip: persisted JSON revalidates to the same manifest.
    revalidated = ProjectionManifest.model_validate(manifest.model_dump(mode="json"))
    assert revalidated.model_dump(mode="json") == manifest.model_dump(mode="json")


def test_vocabulary_reasons_resolve_registry_evidence() -> None:
    """Every reason has a reviewed explanation; only destination limits get a format link."""
    for reason in ProjectionReason:
        explanation = reason_explanation(reason)
        assert explanation.summary_template and explanation.remediation
        doc = documentation_for(OpenApiEmitter, reason)
        if reason is ProjectionReason.DESTINATION_UNSUPPORTED:
            assert doc.url and is_safe_documentation_url(doc.url)
        else:
            assert doc.url is None and doc.documentation_unavailable


def test_unknown_status_and_reason_codes_are_rejected() -> None:
    """The models refuse vocabulary the taxonomy does not define."""
    with pytest.raises(Exception):
        ProjectionEdge(
            id="projects:x#0",
            relation=ProjectionEdgeRelation.PROJECTS,
            source="canonical:x",
            status="vanished",  # type: ignore[arg-type]
            detail="bogus status",
        )
    with pytest.raises(Exception):
        ProjectionEdge(
            id="projects:x#0",
            relation=ProjectionEdgeRelation.PROJECTS,
            source="canonical:x",
            status=ProjectionStatus.DROPPED,
            reason="destination_broken",  # type: ignore[arg-type]
            detail="bogus reason",
        )
    # A reason-required status without a reason is refused too (EFP-1.1 rule, corpus-pinned).
    with pytest.raises(Exception):
        ProjectionEdge(
            id="projects:x#0",
            relation=ProjectionEdgeRelation.PROJECTS,
            source="canonical:x",
            status=ProjectionStatus.UNAVAILABLE,
            detail="missing reason",
        )


def test_reconciliation_excludes_reportless_statuses() -> None:
    """unavailable / not-applicable rows do not participate in report reconciliation."""
    manifest = _vocabulary_manifest()
    builder = LossinessReportBuilder()
    # Reconcilable rows: retained+transformed→ok, approx, synth, four drops.
    builder.add("Kept.record", LossinessKind.OK, LossinessSeverity.INFO, "kept")
    builder.add("Renamed.operation", LossinessKind.OK, LossinessSeverity.INFO, "transformed")
    builder.add("Approx.constraint", LossinessKind.APPROX, LossinessSeverity.WARN, "approx")
    builder.add("Synth.fieldNumber", LossinessKind.SYNTH, LossinessSeverity.INFO, "synth")
    for construct in ("Dropped.route", "Dropped.binding", "Dropped.example", "Dropped.toolOutput"):
        builder.add(construct, LossinessKind.DROP, LossinessSeverity.WARN, "drop")
    report = builder.build()

    # The 3 unavailable + 1 not-applicable rows are excluded — this reconciles cleanly.
    reconcile_with_report(manifest, report)

    # And a count drift is still a hard error.
    builder.add("Extra.row", LossinessKind.DROP, LossinessSeverity.WARN, "drift")
    with pytest.raises(ProjectionReconciliationError):
        reconcile_with_report(manifest, builder.build())


# ---------------------------------------------------------------------------
# Parity checker self-tests: disagreements are detected
# ---------------------------------------------------------------------------


def _clean_envelope() -> Dict[str, Any]:
    """A serialized, internally consistent lossy envelope (rich source → GraphQL SDL)."""
    return build_export_fidelity(rich_api(), get_emitter("graphql")).model_dump(mode="json")


def test_parity_checker_accepts_a_consistent_envelope() -> None:
    assert envelope_parity_issues(_clean_envelope()) == []


@pytest.mark.parametrize(
    "tamper, expected_fragment",
    [
        (lambda e: e["report"]["kind_counts"].__setitem__("drop", 99), "kind_counts['drop']"),
        (lambda e: e["summary"].__setitem__("dropped", 99), "summary dropped=99"),
        (lambda e: e["summary"].__setitem__("total", 99), "summary total=99"),
        (
            lambda e: e["projection"]["status_counts"].__setitem__("retained", 99),
            "disagrees with projection",
        ),
        (
            lambda e: e["projection"]["reason_counts"].__setitem__("destination_broken", 1),
            "unknown reason code",
        ),
        (lambda e: e["projection"].__setitem__("is_lossless", True), "is_lossless"),
        (lambda e: e["projection"].__setitem__("manifest_hash", ""), "manifest_hash"),
        (lambda e: e.pop("projection"), "missing its projection"),
    ],
)
def test_parity_checker_detects_each_disagreement(tamper, expected_fragment: str) -> None:
    """Each single-surface tampering is caught with a pointed description."""
    envelope = _clean_envelope()
    tamper(envelope)
    issues = envelope_parity_issues(envelope)
    assert issues, "tampered envelope must not pass"
    assert any(expected_fragment in issue for issue in issues), issues


# ---------------------------------------------------------------------------
# Cross-surface parity: cards / preview / verify / dispatch / job = one snapshot
# ---------------------------------------------------------------------------

client = TestClient(app)
_MOCK_AUTH = {"tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}
_TENANT = "test-tenant"


def _source(api: Optional[CanonicalApi] = None) -> ExportSource:
    """A loaded export source wrapping the corpus's rich model."""
    return ExportSource(
        api=api or rich_api(),
        artifact_id="artifact-1",
        version_record_id="rev-uuid-1",
        version_label="1.0.0",
    )


@pytest.fixture()
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def test_all_surfaces_reference_the_same_projection_snapshot(_auth) -> None:
    """Cards, preview, verify, dispatch (dry + real), and the job result agree.

    The rich source exported to GraphQL SDL (a lossy target the emitter can actually
    run against this fixture) must produce the same manifest hash and reconciled counts
    on every surface; any disagreement is the exact drift this corpus exists to catch.
    """
    body = {"artifact": "artifact-1", "version": "1.0.0", "target": "graphql"}

    # /targets, /preview, and /verify load through export_routes; /dispatch loads inside
    # export_dispatch — patch both so every surface sees the same corpus source.
    with (
        patch("app.export_routes.load_export_source", return_value=_source()),
        patch("app.export_dispatch.load_export_source", return_value=_source()),
    ):
        cards = client.get(
            f"/v1/export/{_TENANT}/targets", params={"artifact": "artifact-1", "version": "1.0.0"}
        )
        preview = client.post(f"/v1/export/{_TENANT}/preview", json=body)
        verify = client.post(f"/v1/export/{_TENANT}/verify", json=body)
        dry = client.post(f"/v1/export/{_TENANT}/dispatch", json={**body, "dry_run": True})
        real = client.post(f"/v1/export/{_TENANT}/dispatch", json={**body, "confirm": True})
    for response in (cards, preview, verify, dry, real):
        assert response.status_code == 200, response.text

    envelopes = {
        "preview": preview.json()["fidelity"],
        "verify": verify.json()["fidelity"],
        "dispatch-dry": dry.json()["fidelity"],
        "dispatch": real.json()["fidelity"],
    }

    # Every envelope is internally consistent and shares one snapshot hash.
    hashes = set()
    for surface, envelope in envelopes.items():
        issues = envelope_parity_issues(envelope)
        assert issues == [], f"{surface}: {issues}"
        hashes.add(envelope["projection"]["manifest_hash"])
    assert len(hashes) == 1, f"surfaces disagree on the snapshot: {hashes}"

    # The target card's cheap badge counts agree with the envelope's report counts.
    card = next(
        t for t in cards.json()["targets"] if t["descriptor"]["format"] == "graphql"
    )
    kind_counts = envelopes["preview"]["report"]["kind_counts"]
    assert card["fidelity"]["preserved"] == kind_counts["ok"]
    assert card["fidelity"]["dropped"] == kind_counts["drop"]
    assert card["fidelity"]["approximated"] == kind_counts["approx"]
    assert card["fidelity"]["synthesized"] == kind_counts["synth"]

    # The direct builder (what the CLI's --json ultimately serializes) agrees too.
    direct = build_export_fidelity(rich_api(), get_emitter("graphql")).model_dump(mode="json")
    assert direct["projection"]["manifest_hash"] in hashes


async def test_export_job_result_embeds_the_same_snapshot() -> None:
    """A completed export job's fidelity envelope carries the shared snapshot hash."""
    expected = build_export_fidelity(rich_api(), get_emitter("graphql")).model_dump(mode="json")

    request = ExportJobStartRequest(artifact="artifact-1", target="graphql", confirm=True)
    with patch("app.export_job_engine.load_export_source", return_value=_source()):
        accepted = await schedule_export_job(_TENANT, _MOCK_AUTH["tenant_id"], request)
        status = None
        for _ in range(500):
            status = await get_export_job_status(_TENANT, accepted.job_id)
            if status.state in ("completed", "failed", "canceled"):
                break
            await asyncio.sleep(0.01)
    assert status is not None and status.state in ("completed", "failed", "canceled"), (
        "export job did not reach a terminal state"
    )
    payload = status.model_dump(mode="json")
    assert payload["state"] == "completed", payload.get("error")

    envelope = payload["result"]["fidelity"]
    assert envelope_parity_issues(envelope) == []
    assert envelope["projection"]["manifest_hash"] == expected["projection"]["manifest_hash"]


# ---------------------------------------------------------------------------
# Shared parity fixture (bytes reused by the UI jest corpus)
# ---------------------------------------------------------------------------


def test_parity_envelope_golden_matches_and_is_shared() -> None:
    """The reduced parity fixture is golden-pinned; the UI jest corpus reuses its bytes.

    ``apiome-ui/tests/fixtures/projectionParityEnvelope.json`` is a checked-in copy of
    this golden, so the TypeScript parity checker is exercised over the exact envelope
    shape this corpus produced. Regenerate both together when the contract changes
    (UPDATE_PROJECTION_GOLDENS=1, then copy the file).
    """
    envelope = build_export_fidelity(rich_api(), get_emitter("graphql")).model_dump(mode="json")
    fixture = normalize_volatile_provenance(parity_fixture_payload(envelope))
    assert_matches_golden("parity_envelope_graphql", fixture)
    # The normalized fixture still passes the checker — its hash placeholder is non-empty
    # and every count survives normalization untouched.
    assert envelope_parity_issues(fixture) == []


def test_shared_parity_fixture_copies_are_byte_identical() -> None:
    """The CLI and UI copies of the parity fixture match this corpus's golden exactly.

    All three surfaces run their parity checker against the same bytes; a drifted copy
    means one surface is proving parity against a stale contract. Re-copy from
    ``tests/fixtures/projection_corpus/parity_envelope_graphql.json`` after regenerating.
    """
    golden = golden_path("parity_envelope_graphql")
    repo_root = golden.parents[4]
    copies = {
        "apiome-cli": repo_root / "apiome-cli" / "tests" / "fixtures" / "export-projection-parity.json",
        "apiome-ui": repo_root / "apiome-ui" / "tests" / "fixtures" / "projectionParityEnvelope.json",
    }
    golden_bytes = golden.read_bytes()
    for package, copy_path in copies.items():
        assert copy_path.exists(), f"{package} is missing its shared parity fixture at {copy_path}"
        assert copy_path.read_bytes() == golden_bytes, (
            f"{package}'s parity fixture has drifted from the corpus golden; re-copy "
            f"{golden.name} to {copy_path}"
        )
