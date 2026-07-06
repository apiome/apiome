"""Unit tests for the CanonicalApi → emitter dispatch primitive — MFX-3.2 (#3845).

Pins the dispatch composition independently of the REST layer:

* :func:`app.export_dispatch.dispatch_from_source` resolves the target, computes the fidelity
  envelope, runs the emitter, and returns both — with the resolved source coordinates;
* the fidelity envelope it attaches is byte-identical to what ``build_export_fidelity`` (and
  therefore ``POST /export/preview``) computes for the same inputs;
* ``dry_run`` stops after the report: the emitter is never invoked and no artifact is returned;
* an unknown target fails with an :class:`~app.export_service.ExportError` (400) *before* any
  emit; an emitter that yields nothing fails with a 422;
* :func:`app.export_dispatch.dispatch_export` is tenant-scoped — it loads through
  :func:`app.export_source.load_export_source` with the caller's tenant id and scopes the
  field-identity persistence context to ``(tenant, artifact)`` — and propagates the loader's
  typed not-found error unchanged.

The DB-backed source loader is faked (its own logic is covered in ``test_export_source.py``);
the emitter path runs the real registry/SPI.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.emitter import EmitResult
from app.export_dispatch import dispatch_export, dispatch_from_source
from app.export_fidelity import build_export_fidelity
from app.export_service import ExportError, resolve_emitter
from app.export_source import ExportSource, ExportSourceError

TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"


def _source() -> ExportSource:
    """A loaded source: a REST API with one operation + one type, at a fixed revision."""
    widget = Type(
        key="Widget",
        name="Widget",
        kind=TypeKind.RECORD,
        fields=[CanonicalField(key="Widget.id", name="id", type=TypeRef(name="string"))],
    )
    op = Operation(key="GET /widgets", name="listWidgets", kind=OperationKind.QUERY)
    service = Service(key="widgets", name="widgets", operations=[op])
    api = CanonicalApi(
        paradigm=ApiParadigm.REST,
        format="openapi-3.1",
        identity=ApiIdentity(name="widgets"),
        services=[service],
        types=[widget],
    )
    return ExportSource(
        api=api,
        artifact_id="artifact-1",
        version_record_id="rev-uuid-1",
        version_label="1.0.0",
    )


# ---------------------------------------------------------------------------
# dispatch_from_source — the pure composition
# ---------------------------------------------------------------------------
def test_dispatch_runs_the_emitter_and_attaches_the_report():
    """A real dispatch resolves the emitter, runs it, and attaches the fidelity envelope."""
    source = _source()
    dispatch = dispatch_from_source(source, "openapi")

    # Resolved coordinates are echoed from the loaded source.
    assert dispatch.artifact == "artifact-1"
    assert dispatch.version_record_id == "rev-uuid-1"
    assert dispatch.version_label == "1.0.0"
    assert dispatch.target.startswith("openapi")
    assert dispatch.dry_run is False

    # The emitter ran: a document came back.
    assert dispatch.emit is not None
    assert dispatch.emit.files
    assert dispatch.emit.media_type == "application/vnd.oai.openapi+json"

    # The attached report is lossless REST → OpenAPI.
    assert dispatch.fidelity.summary.tier.value == "lossless"
    assert dispatch.fidelity.summary.preserved_percent == 100
    assert dispatch.fidelity.advisory is not None


def test_attached_fidelity_matches_the_preview_builder():
    """The report attached to a dispatch equals the standalone preview builder's — no drift."""
    source = _source()
    emitter_cls = type(resolve_emitter("sample"))
    expected = build_export_fidelity(source.api, emitter_cls)

    dispatch = dispatch_from_source(source, "sample")

    assert dispatch.fidelity.model_dump() == expected.model_dump()
    # A schema-only target drops the operation → types-only.
    assert dispatch.fidelity.summary.tier.value == "types-only"


def test_dry_run_stops_after_the_report_without_emitting():
    """A dry-run carries the report and no artifact; the emitter is never invoked."""
    source = _source()

    def _must_not_emit(*args, **kwargs):
        raise AssertionError("emit_canonical must not run for a dry-run dispatch")

    with patch("app.export_dispatch.emit_canonical", side_effect=_must_not_emit):
        dispatch = dispatch_from_source(source, "openapi", dry_run=True)

    assert dispatch.dry_run is True
    assert dispatch.emit is None
    assert dispatch.fidelity.summary.tier.value == "lossless"


def test_unknown_target_fails_before_any_emit():
    """An unknown target raises ExportError (400) at resolve time, never reaching the emitter."""
    source = _source()

    def _must_not_emit(*args, **kwargs):
        raise AssertionError("emit_canonical must not run for an unknown target")

    with patch("app.export_dispatch.emit_canonical", side_effect=_must_not_emit):
        with pytest.raises(ExportError) as excinfo:
            dispatch_from_source(source, "does-not-exist")
    assert excinfo.value.status_code == 400


def test_empty_emit_is_a_422_target_error():
    """An emitter that yields no file is a 422 target error, not a silent empty result."""
    source = _source()
    with patch(
        "app.export_dispatch.emit_canonical",
        return_value=EmitResult(files=[], media_type="application/json"),
    ):
        with pytest.raises(ExportError) as excinfo:
            dispatch_from_source(source, "openapi")
    assert excinfo.value.status_code == 422
    assert "no document" in str(excinfo.value)


def test_dispatch_passes_options_through_to_the_emitter():
    """Per-target options reach the emitter (here: dropping paths from the OpenAPI output)."""
    source = _source()

    full = dispatch_from_source(source, "openapi")
    assert full.emit is not None
    assert full.emit.document.get("paths")

    trimmed = dispatch_from_source(source, "openapi", options={"include_paths": False})
    assert trimmed.emit is not None
    # With paths excluded the emitted document carries no (or empty) paths object.
    assert not trimmed.emit.document.get("paths")


# ---------------------------------------------------------------------------
# dispatch_export — the tenant-scoped loader wrapper
# ---------------------------------------------------------------------------
def test_dispatch_export_is_tenant_scoped():
    """The loader is called with the caller's tenant id and the requested coordinates."""
    with patch(
        "app.export_dispatch.load_export_source", return_value=_source()
    ) as loader:
        dispatch = dispatch_export(TENANT_ID, "artifact-1", "1.0.0", "openapi")

    loader.assert_called_once_with(TENANT_ID, "artifact-1", "1.0.0")
    assert dispatch.artifact == "artifact-1"
    assert dispatch.emit is not None


def test_dispatch_export_persists_field_identity_scoped_to_the_tenant():
    """A real (persisting) export threads a tenant/artifact-scoped persistence context to emit."""
    captured = {}

    def _capture(api, target, *, opts=None, persistence=None):
        captured["persistence"] = persistence
        return EmitResult.from_document({"openapi": "3.1.0"})

    with patch("app.export_dispatch.load_export_source", return_value=_source()), patch(
        "app.export_dispatch.emit_canonical", side_effect=_capture
    ):
        dispatch_export(TENANT_ID, "artifact-1", None, "openapi")

    persistence = captured["persistence"]
    assert persistence is not None
    assert persistence.tenant_id == TENANT_ID
    assert persistence.artifact_id == "artifact-1"


def test_dispatch_export_can_opt_out_of_persistence():
    """``persist=False`` keeps the emit read-only (no persistence context)."""
    captured = {}

    def _capture(api, target, *, opts=None, persistence=None):
        captured["persistence"] = persistence
        return EmitResult.from_document({"openapi": "3.1.0"})

    with patch("app.export_dispatch.load_export_source", return_value=_source()), patch(
        "app.export_dispatch.emit_canonical", side_effect=_capture
    ):
        dispatch_export(TENANT_ID, "artifact-1", None, "openapi", persist=False)

    assert captured["persistence"] is None


def test_dispatch_export_dry_run_never_loads_field_identity():
    """A dry-run stops before emit, so persistence is irrelevant and no artifact is returned."""
    with patch("app.export_dispatch.load_export_source", return_value=_source()), patch(
        "app.export_dispatch.emit_canonical",
        side_effect=AssertionError("dry-run must not emit"),
    ):
        dispatch = dispatch_export(TENANT_ID, "artifact-1", None, "openapi", dry_run=True)

    assert dispatch.dry_run is True
    assert dispatch.emit is None


def test_dispatch_export_propagates_source_not_found():
    """The loader's typed 404 propagates unchanged for the caller to map to HTTP."""
    with patch(
        "app.export_dispatch.load_export_source",
        side_effect=ExportSourceError("Artifact 'missing' was not found.", status_code=404),
    ):
        with pytest.raises(ExportSourceError) as excinfo:
            dispatch_export(TENANT_ID, "missing", None, "openapi")
    assert excinfo.value.status_code == 404
