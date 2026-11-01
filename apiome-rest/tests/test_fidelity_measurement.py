"""Tests for round-trip fidelity measurement — MFX-2.6 (#3843).

Pins the ticket's acceptance criteria:

* **an empirical loss list** — every source → re-import difference becomes a loss in the
  lossiness vocabulary (removed → drop, added → synth, changed → approx), paired with the
  predicted finding that explains it;
* **round-trip diff matches predicted DROPs on fixtures** — exporting the probe document
  to real targets and re-importing it through the matching parser corroborates every
  predicted ``drop`` with a removed/changed difference;
* **flagged where they diverge** — an unpredicted loss, a predicted drop that did not
  happen, and an ``OK`` the round trip contradicts are each listed as a divergence and
  set ``diverges``;
* **surfaced on the round-trip route** — ``run_export_roundtrip`` and
  ``POST /v1/export/{tenant}/roundtrip`` carry the measurement, null when the loop did
  not close, without changing the IXH-4.4 verdict.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from test_export_roundtrip import _imported_api, _source

import app.export_roundtrip as export_roundtrip_module
from app.auth import validate_authentication
from app.emitter import get_emitter, load_builtin_emitters
from app.export_roundtrip import run_export_roundtrip
from app.fidelity_engine import compute_lossiness_for_emitter
from app.fidelity_measurement import (
    FidelityDivergenceKind,
    empirical_kind,
    measure_roundtrip_fidelity,
)
from app.import_source import (
    CanonicalDiff,
    CanonicalDiffEntry,
    DiffChangeKind,
    canonical_diff,
    get_import_source,
    load_builtin_import_sources,
)
from app.lossiness import LossinessKind, LossinessReport, LossinessSeverity, LossItem
from app.roundtrip_matrix import (
    MatrixCellStatus,
    import_adapter_for_emit,
    production_emit_targets,
    reconcile,
    reimport_emitted,
)


@pytest.fixture(autouse=True)
def _registries() -> None:
    """Emitters + import adapters registered for every test."""
    load_builtin_emitters()
    load_builtin_import_sources()


def _entry(entity: str, key: str, change: DiffChangeKind) -> CanonicalDiffEntry:
    return CanonicalDiffEntry(entity=entity, key=key, change=change)


def _item(key: str, kind: LossinessKind) -> LossItem:
    return LossItem(
        construct_key=key,
        kind=kind,
        severity=LossinessSeverity.WARN,
        message=f"{kind.value} {key}",
    )


def _kinds(measurement) -> list:
    return [d.kind for d in measurement.divergences]


# ---------------------------------------------------------------------------
# Unit: measure_roundtrip_fidelity
# ---------------------------------------------------------------------------


def test_empty_diff_and_report_measure_clean() -> None:
    m = measure_roundtrip_fidelity(CanonicalDiff(), LossinessReport())
    assert m.empirical_losses == [] and m.drops == [] and m.divergences == []
    assert m.predicted_drop_count == m.corroborated_drop_count == m.unpredicted_loss_count == 0
    assert m.diverges is False


@pytest.mark.parametrize(
    ("change", "kind"),
    [
        (DiffChangeKind.REMOVED, LossinessKind.DROP),
        (DiffChangeKind.ADDED, LossinessKind.SYNTH),
        (DiffChangeKind.CHANGED, LossinessKind.APPROX),
    ],
)
def test_empirical_kind_maps_each_change(change: DiffChangeKind, kind: LossinessKind) -> None:
    assert empirical_kind(change) is kind


def test_removed_entity_corroborates_its_predicted_drop() -> None:
    removed = _entry("type", "User", DiffChangeKind.REMOVED)
    drop = _item("User", LossinessKind.DROP)
    m = measure_roundtrip_fidelity(CanonicalDiff(entries=[removed]), LossinessReport(items=[drop]))

    [loss] = m.empirical_losses
    assert (loss.key, loss.change, loss.kind) == ("User", DiffChangeKind.REMOVED, LossinessKind.DROP)
    assert loss.predicted is True and loss.finding == drop
    [corroboration] = m.drops
    assert corroboration.corroborated is True and corroboration.evidence == [removed]
    assert m.predicted_drop_count == m.corroborated_drop_count == 1
    assert m.diverges is False


def test_nested_drop_is_corroborated_by_its_owner_changing() -> None:
    """A dropped field (``User.email``) shows up as its type coming back changed."""
    changed = _entry("type", "User", DiffChangeKind.CHANGED)
    drop = _item("User.email", LossinessKind.DROP)
    m = measure_roundtrip_fidelity(CanonicalDiff(entries=[changed]), LossinessReport(items=[drop]))
    assert m.drops[0].corroborated is True
    assert m.drops[0].evidence == [changed]
    assert m.diverges is False


def test_root_drop_is_corroborated_by_root_change() -> None:
    changed_root = _entry("root", "", DiffChangeKind.CHANGED)
    m = measure_roundtrip_fidelity(
        CanonicalDiff(entries=[changed_root]), LossinessReport(items=[_item("", LossinessKind.DROP)])
    )
    assert m.drops[0].corroborated is True
    assert m.diverges is False


def test_added_entity_is_not_evidence_for_a_drop() -> None:
    """A drop is confirmed only by something removed or changed, never by an addition."""
    added = _entry("type", "User", DiffChangeKind.ADDED)
    m = measure_roundtrip_fidelity(
        CanonicalDiff(entries=[added]), LossinessReport(items=[_item("User", LossinessKind.DROP)])
    )
    assert m.drops[0].corroborated is False
    assert FidelityDivergenceKind.UNOBSERVED_DROP in _kinds(m)


def test_predicted_drop_that_did_not_happen_is_flagged() -> None:
    m = measure_roundtrip_fidelity(
        CanonicalDiff(), LossinessReport(items=[_item("User", LossinessKind.DROP)])
    )
    assert m.drops[0].corroborated is False and m.drops[0].evidence == []
    assert m.corroborated_drop_count == 0
    [divergence] = m.divergences
    assert divergence.kind is FidelityDivergenceKind.UNOBSERVED_DROP
    assert divergence.construct == "User"
    assert "came back unchanged" in divergence.message
    assert m.diverges is True


def test_unpredicted_loss_is_flagged() -> None:
    removed = _entry("operation", "GET /users", DiffChangeKind.REMOVED)
    m = measure_roundtrip_fidelity(CanonicalDiff(entries=[removed]), LossinessReport())
    [loss] = m.empirical_losses
    assert loss.predicted is False and loss.finding is None
    [divergence] = m.divergences
    assert divergence.kind is FidelityDivergenceKind.UNPREDICTED_LOSS
    assert divergence.construct == "GET /users"
    assert "operation 'GET /users'" in divergence.message
    assert m.unpredicted_loss_count == 1 and m.diverges is True


def test_overclaim_is_flagged() -> None:
    """An ``OK`` on a construct the round trip changed is an over-claim (and unpredicted)."""
    changed = _entry("type", "User", DiffChangeKind.CHANGED)
    m = measure_roundtrip_fidelity(
        CanonicalDiff(entries=[changed]), LossinessReport(items=[_item("User", LossinessKind.OK)])
    )
    assert _kinds(m) == [
        FidelityDivergenceKind.UNPREDICTED_LOSS,
        FidelityDivergenceKind.OVERCLAIM,
    ]
    assert m.divergences[1].construct == "User"


def test_divergences_are_ordered_unpredicted_unobserved_overclaim() -> None:
    diff = CanonicalDiff(
        entries=[
            _entry("type", "Gone", DiffChangeKind.REMOVED),
            _entry("type", "Pet", DiffChangeKind.CHANGED),
        ]
    )
    report = LossinessReport(
        items=[_item("Pet", LossinessKind.OK), _item("Kept", LossinessKind.DROP)]
    )
    m = measure_roundtrip_fidelity(diff, report)
    assert _kinds(m) == [
        FidelityDivergenceKind.UNPREDICTED_LOSS,
        FidelityDivergenceKind.UNPREDICTED_LOSS,
        FidelityDivergenceKind.UNOBSERVED_DROP,
        FidelityDivergenceKind.OVERCLAIM,
    ]


def test_supplied_reconciliation_matches_computed_one() -> None:
    diff = CanonicalDiff(entries=[_entry("type", "User", DiffChangeKind.REMOVED)])
    report = LossinessReport(items=[_item("User", LossinessKind.DROP)])
    assert measure_roundtrip_fidelity(
        diff, report, reconciliation=reconcile(diff, report)
    ) == measure_roundtrip_fidelity(diff, report)


def test_findings_serialize_with_the_construct_alias() -> None:
    diff = CanonicalDiff(entries=[_entry("type", "User", DiffChangeKind.REMOVED)])
    payload = measure_roundtrip_fidelity(
        diff, LossinessReport(items=[_item("User", LossinessKind.DROP)])
    ).model_dump(mode="json")
    assert payload["drops"][0]["finding"]["construct"] == "User"
    assert payload["empirical_losses"][0]["finding"]["construct"] == "User"
    assert payload["empirical_losses"][0]["kind"] == "drop"


# ---------------------------------------------------------------------------
# Fixtures: real export → re-import → diff (the acceptance criterion)
# ---------------------------------------------------------------------------


def _measure_real_roundtrip(emit_key: str):
    """Export the probe document to ``emit_key``, re-import it, and measure the loss."""
    targets = [t for t in production_emit_targets() if t.descriptor.key == emit_key]
    if not targets or not targets[0].descriptor.available:
        pytest.skip(f"emitter {emit_key!r} unavailable in this runtime")
    descriptor = targets[0].descriptor
    adapter_key = import_adapter_for_emit(descriptor.key, descriptor.format)
    assert adapter_key is not None
    api = _imported_api()
    emitter = get_emitter(descriptor.format)()
    report = compute_lossiness_for_emitter(api, emitter)
    reimported = reimport_emitted(
        get_import_source(adapter_key), emitter.emit(api), multi_file=descriptor.multi_file
    )
    return report, measure_roundtrip_fidelity(canonical_diff(api, reimported), report)


@pytest.mark.parametrize("emit_key", ["sql-ddl", "thrift", "corbaidl"])
def test_fixture_roundtrip_corroborates_every_predicted_drop(emit_key: str) -> None:
    """AC: the round-trip diff matches the predicted DROPs, with nothing diverging."""
    report, m = _measure_real_roundtrip(emit_key)
    assert m.predicted_drop_count == report.kind_counts.get("drop", 0) > 0
    assert m.corroborated_drop_count == m.predicted_drop_count
    assert all(drop.evidence for drop in m.drops)
    assert m.diverges is False
    assert all(loss.predicted for loss in m.empirical_losses)


def test_fixture_types_only_target_drops_the_operation() -> None:
    """REST → JSON Schema: the predicted operation DROP is confirmed by its removal."""
    _report, m = _measure_real_roundtrip("json-schema")
    [operation_drop] = [d for d in m.drops if d.finding.construct_key == "GET /users/{id}"]
    assert operation_drop.corroborated is True
    assert any(
        e.entity == "operation" and e.change is DiffChangeKind.REMOVED
        for e in operation_drop.evidence
    )
    assert m.corroborated_drop_count == m.predicted_drop_count
    # Differences the report does not predict are flagged rather than hidden.
    assert m.diverges is (m.unpredicted_loss_count > 0)


def test_fixture_same_format_roundtrip_measures_lossless() -> None:
    report, m = _measure_real_roundtrip("openapi")
    assert report.kind_counts.get("drop", 0) == 0
    assert m.empirical_losses == [] and m.diverges is False


# ---------------------------------------------------------------------------
# Surfaced on the round-trip run and route
# ---------------------------------------------------------------------------


def test_export_roundtrip_carries_measurement() -> None:
    resp = run_export_roundtrip(_source(), "openapi")
    assert resp.status is MatrixCellStatus.PASS
    assert resp.measurement is not None
    assert resp.measurement.diverges is False
    assert len(resp.measurement.empirical_losses) == resp.diff_count


def test_export_roundtrip_skip_has_no_measurement() -> None:
    resp = run_export_roundtrip(_source(), "sample")
    assert resp.status is MatrixCellStatus.UNSUPPORTED
    assert resp.measurement is None


def test_unobserved_drop_is_flagged_without_changing_the_verdict() -> None:
    """A drop the report predicts but the round trip did not perform diverges, yet the
    IXH-4.4 verdict (every difference explained, no over-claim) still passes."""
    real_dispatch = export_roundtrip_module.dispatch_from_source

    def dispatch_with_phantom_drop(*args, **kwargs):
        dispatch = real_dispatch(*args, **kwargs)
        report = LossinessReport(items=[_item("User", LossinessKind.DROP)])
        fidelity = dispatch.fidelity.model_copy(update={"report": report})
        return dispatch.model_copy(update={"fidelity": fidelity})

    with patch.object(export_roundtrip_module, "dispatch_from_source", dispatch_with_phantom_drop):
        resp = run_export_roundtrip(_source(), "openapi")

    assert resp.status is MatrixCellStatus.PASS
    assert resp.measurement is not None and resp.measurement.diverges is True
    [divergence] = resp.measurement.divergences
    assert divergence.kind is FidelityDivergenceKind.UNOBSERVED_DROP
    assert divergence.construct == "User"


def test_route_returns_measurement() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    api = _imported_api()
    mutated = api.model_copy(update={"types": [t for t in api.types if t.key != "User"]})
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": "test-tenant-id",
        "user_id": "test-user-id",
        "auth_method": "jwt",
    }
    try:
        with (
            patch("app.export_routes.load_export_source", return_value=_source(api)),
            patch.object(export_roundtrip_module, "reimport_emitted", lambda *a, **k: mutated),
        ):
            response = TestClient(app).post(
                "/v1/export/test-tenant/roundtrip",
                json={"artifact": "artifact-1", "target": "openapi"},
            )
        assert response.status_code == 200
        measurement = response.json()["measurement"]
        assert measurement["diverges"] is True
        assert measurement["empirical_losses"][0]["key"] == "User"
        assert measurement["empirical_losses"][0]["kind"] == "drop"
        assert measurement["divergences"][0]["kind"] == "unpredicted_loss"
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
