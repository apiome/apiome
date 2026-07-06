"""Tests for the one-call verify route — ``POST /v1/export/{tenant_slug}/verify`` — MFX-42.5 (#4358).

Pins the route contract the Verify workbench (MFX-42.1) depends on:

* the endpoint requires authentication and is tenant-scoped;
* **one call** returns all three lenses (fidelity + validation + lint) plus an overall ``verdict``;
* a lossless, valid conversion is ``clean``; a loss-bearing one is ``lossy``; a rejected artifact
  is ``invalid`` and the validator's structured detail rides along;
* **no artifact/job row is persisted** — the emit is read-only (``persistence=None``) and a severe
  conversion is *verified* (``confirm=True``), never blocked;
* the emitted artifact rides back inline under the size cap, with ``truncated`` when it overflows
  or empty when the caller opted out (``include_content: false``);
* the loader's not-found (404) and an unknown target (400) map to the right HTTP status.

The source loader is faked (its own DB-backed logic is exercised in ``test_export_source.py``), so
these tests pin only the route wiring; the emitter + validation paths run for real.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import export_routes
from app.auth import validate_authentication
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
from app.export_fidelity import ExportFidelityTier
from app.export_routes import ExportVerifyVerdict, _verify_verdict
from app.export_source import ExportSource, ExportSourceError
from app.export_validation import EmittedArtifactValidation, ValidationFinding
from app.export_validation_gate import build_validation_report
from app.main import app

client = TestClient(app)

_MOCK_AUTH = {"tenant_id": "test-tenant-id", "user_id": "test-user-id", "auth_method": "jwt"}


def _override_auth():
    return _MOCK_AUTH


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


def _post(json_body: dict):
    """POST the verify route with auth + the faked source loader; returns the response."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("app.export_routes.load_export_source", return_value=_source()):
            return client.post("/v1/export/test-tenant/verify", json=json_body)
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def test_verify_requires_auth():
    response = client.post(
        "/v1/export/test-tenant/verify",
        json={"artifact": "artifact-1", "target": "openapi"},
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# One call → three lenses + verdict
# ---------------------------------------------------------------------------
def test_verify_returns_all_three_lenses_and_verdict():
    """A lossless, valid REST→OpenAPI verify is ``clean`` and carries all three lens slots."""
    response = _post({"artifact": "artifact-1", "version": "1.0.0", "target": "openapi"})
    assert response.status_code == 200
    body = response.json()

    assert body["artifact"] == "artifact-1"
    assert body["version_record_id"] == "rev-uuid-1"
    assert body["target"].startswith("openapi")

    # Fidelity lens — lossless REST → OpenAPI.
    assert body["fidelity"]["summary"]["tier"] == "lossless"
    assert body["fidelity"]["advisory"] is not None
    # Validation lens — a real re-parse verdict (valid / skipped / not_applicable, never blocking).
    assert body["validation"]["verdict"] in {"valid", "skipped", "not_applicable"}
    assert body["validation"]["blocks_delivery"] is False
    # Lint lens — MFX-5.2 not yet implemented, so null (the UI renders the empty state).
    assert body["lint"] is None
    # Verdict — clean, and the guard rides along.
    assert body["verdict"] == "clean"
    assert body["guard"] is not None


def test_verify_lossy_target_reports_lossy_verdict():
    """A loss-bearing conversion (REST → Avro drops operations) is ``lossy`` when still valid."""
    response = _post({"artifact": "artifact-1", "version": "1.0.0", "target": "avro"})
    assert response.status_code == 200
    body = response.json()
    assert body["fidelity"]["summary"]["tier"] != "lossless"
    assert body["validation"]["blocks_delivery"] is False
    assert body["verdict"] == "lossy"


def test_verify_invalid_artifact_blocks_with_detail():
    """A validator that rejects the artifact yields ``invalid`` + structured findings (MFX-5.3)."""
    failing = EmittedArtifactValidation(
        target="openapi-3.1",
        applicable=True,
        validated=True,
        valid=False,
        errors=["Field number 0 is not allowed."],
        findings=[
            ValidationFinding(
                message="Field number 0 is not allowed.",
                file="widgets.json",
                line=12,
                column=3,
                keyword="minimum",
            )
        ],
    )
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("app.export_routes.load_export_source", return_value=_source()):
            with patch(
                "app.export_routes.validate_emitted_artifact",
                new=AsyncMock(return_value=failing),
            ):
                response = client.post(
                    "/v1/export/test-tenant/verify",
                    json={"artifact": "artifact-1", "version": "1.0.0", "target": "openapi"},
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["verdict"] == "invalid"
    assert body["validation"]["verdict"] == "invalid"
    assert body["validation"]["blocks_delivery"] is True
    finding = body["validation"]["findings"][0]
    assert finding["message"] == "Field number 0 is not allowed."
    assert finding["file"] == "widgets.json"
    assert finding["line"] == 12
    assert finding["keyword"] == "minimum"


# ---------------------------------------------------------------------------
# No persistence + inline content cap
# ---------------------------------------------------------------------------
def test_verify_emits_read_only_and_never_dry_runs():
    """The verify emit is read-only (no persistence) and always confirmed, never a dry run."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("app.export_routes.load_export_source", return_value=_source()):
            with patch(
                "app.export_routes.dispatch_from_source",
                wraps=export_routes.dispatch_from_source,
            ) as spy:
                response = client.post(
                    "/v1/export/test-tenant/verify",
                    json={"artifact": "artifact-1", "target": "openapi"},
                )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    kwargs = spy.call_args.kwargs
    assert kwargs["persistence"] is None  # a verify never persists field identities
    assert kwargs["confirm"] is True  # severe conversions are verified, not blocked
    assert kwargs["dry_run"] is False  # a real emit is needed to validate + lint

    # The response shape carries no job/download reference — nothing was persisted to poll.
    body = response.json()
    assert "download_path" not in body
    assert "job_id" not in body


def test_verify_returns_artifact_inline_under_the_cap():
    """By default the emitted artifact rides back inline (for the Monaco viewer), not truncated."""
    body = _post({"artifact": "artifact-1", "target": "openapi"}).json()
    assert body["truncated"] is False
    assert len(body["files"]) == 1
    assert body["files"][0]["content"]["openapi"].startswith("3.")


def test_verify_omits_content_when_not_requested():
    """``include_content: false`` returns no inline files and does not flag truncation."""
    body = _post(
        {"artifact": "artifact-1", "target": "openapi", "include_content": False}
    ).json()
    assert body["files"] == []
    assert body["truncated"] is False


def test_verify_truncates_when_artifact_exceeds_the_cap():
    """An artifact over the inline cap is omitted from ``files`` and flagged ``truncated``."""
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch("app.export_routes.load_export_source", return_value=_source()):
            # Shrink the cap so the small fixture artifact overflows it.
            with patch.object(export_routes, "_VERIFY_INLINE_CONTENT_CAP", 1):
                response = client.post(
                    "/v1/export/test-tenant/verify",
                    json={"artifact": "artifact-1", "target": "openapi"},
                )
    finally:
        app.dependency_overrides.clear()

    body = response.json()
    assert response.status_code == 200
    assert body["truncated"] is True
    assert body["files"] == []
    # The verdict + lenses are unaffected by content truncation.
    assert body["verdict"] == "clean"


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------
def test_verify_unknown_artifact_maps_to_404():
    app.dependency_overrides[validate_authentication] = _override_auth
    try:
        with patch(
            "app.export_routes.load_export_source",
            side_effect=ExportSourceError("No such artifact", status_code=404),
        ):
            response = client.post(
                "/v1/export/test-tenant/verify",
                json={"artifact": "nope", "target": "openapi"},
            )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


def test_verify_unknown_target_maps_to_400():
    response = _post({"artifact": "artifact-1", "target": "not-a-real-target"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Verdict derivation (unit)
# ---------------------------------------------------------------------------
def _report(verdict_valid: bool, *, applicable=True, validated=True):
    """Build an MFX-5.3 validation report for the given re-parse outcome."""
    return build_validation_report(
        EmittedArtifactValidation(
            target="openapi-3.1",
            applicable=applicable,
            validated=validated,
            valid=verdict_valid,
            errors=[] if verdict_valid else ["boom"],
            findings=[]
            if verdict_valid
            else [ValidationFinding(message="boom")],
        )
    )


def test_verify_verdict_matrix():
    # invalid validation blocks regardless of a lossless tier.
    assert (
        _verify_verdict(_report(False), ExportFidelityTier.LOSSLESS)
        is ExportVerifyVerdict.INVALID
    )
    # a non-lossless tier with a valid artifact is lossy.
    assert (
        _verify_verdict(_report(True), ExportFidelityTier.LOSSY) is ExportVerifyVerdict.LOSSY
    )
    assert (
        _verify_verdict(_report(True), ExportFidelityTier.TYPES_ONLY)
        is ExportVerifyVerdict.LOSSY
    )
    # a lossless, valid conversion is clean.
    assert (
        _verify_verdict(_report(True), ExportFidelityTier.LOSSLESS)
        is ExportVerifyVerdict.CLEAN
    )
    # a skipped (toolchain-unavailable) validation does not demote a clean band.
    assert (
        _verify_verdict(_report(True, validated=False), ExportFidelityTier.LOSSLESS)
        is ExportVerifyVerdict.CLEAN
    )
