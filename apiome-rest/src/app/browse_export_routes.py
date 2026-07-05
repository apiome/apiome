"""Public browse export endpoints (no authentication) — MFX-7.1 (#3860).

The public export slice of the browse surface: let an **anonymous** visitor of
``apiome-browse`` export a **published, public** version to any registered target, reusing the
same emitter SPI + fidelity engine the authenticated ``/v1/export`` surface uses. Three routes,
mirroring that surface one-for-one but resolved by URL slugs instead of an authenticated tenant:

* **``GET  /v1/browse/tenants/{t}/projects/{p}/versions/{v}/export/targets``** — every
  registered target with its per-source fidelity badge (tier + preserved-%), driving the public
  export dialog's target cards and its "may lose fidelity" warning.
* **``POST …/export/preview``** — the full fidelity envelope (report + advisory + summary) for
  one chosen target, without emitting; backs the public fidelity advisory (MFX-7.2).
* **``POST …/export/document``** — the emitted document itself, JSON by default or YAML under
  ``Accept: application/yaml``, as a download.

Visibility gate: every route loads its source through
:func:`app.export_source.load_public_export_source`, which only resolves revisions matching the
public browse predicate (``published IS TRUE AND visibility = 'public'``, undeleted). Anything
else — private, draft, unknown — is a uniform ``404``, so the routes can never confirm that a
hidden artifact exists. The path is strictly **read-only**: the emit runs without a field-identity
persistence context, so an anonymous export writes nothing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from .export_fidelity import ExportFidelity, build_export_fidelity
from .export_routes import (
    ExportTargetFidelity,
    build_target_fidelity_entries,
    render_emitted_document,
)
from .export_service import ExportError, resolve_emitter
from .export_source import ExportSource, ExportSourceError, load_public_export_source
from .lossiness import LossinessSeverity

router = APIRouter(prefix="/v1/browse", tags=["browse"])


_EXPORT_PATH = "/tenants/{tenant_slug}/projects/{project_slug}/versions/{version_slug}/export"

# Shared OpenAPI documentation for the uniform not-found behaviour of every route here.
_NOT_FOUND_RESPONSES = {
    404: {
        "description": (
            "No published public version matches the slugs (private, draft, and unknown "
            "versions are indistinguishable)."
        )
    },
}


# ===========================================================================
# Response / request models
# ===========================================================================


class PublicExportCoordinates(BaseModel):
    """The slug coordinates + resolved revision every public export response echoes back."""

    model_config = ConfigDict(extra="forbid")

    tenant_slug: str = Field(description="The owning tenant's slug, as requested.")
    project_slug: str = Field(description="The project (artifact) slug, as requested.")
    version_slug: str = Field(description="The version label, as requested (e.g. ``1.0.0``).")
    version_record_id: str = Field(description="The resolved revision (``versions.id``).")
    version_label: Optional[str] = Field(
        default=None, description="The resolved revision's source-declared version label."
    )


class PublicExportTargetsResponse(PublicExportCoordinates):
    """The per-target fidelity list for one published public revision (MFX-7.1)."""

    targets: List[ExportTargetFidelity] = Field(
        default_factory=list,
        description="Every registered target with its per-source fidelity, in registry order.",
    )


class PublicExportPreviewRequest(BaseModel):
    """A dry-run fidelity preview request for the public path: just the chosen target.

    Unlike the authenticated surface, the source coordinates live in the URL (the slugs), so
    the body only selects the target and the advisory threshold.
    """

    model_config = ConfigDict(extra="forbid")

    target: str = Field(
        description="Target emitter key (``openapi``) or format key (``openapi-3.1``).",
    )
    min_severity: LossinessSeverity = Field(
        default=LossinessSeverity.INFO,
        description="Lowest loss severity that raises the advisory (MFX-2.4); does not affect "
        "the report or counts.",
    )


class PublicExportPreviewResponse(PublicExportCoordinates):
    """The dry-run fidelity preview for one (published source, target) pair (MFX-7.1)."""

    fidelity: ExportFidelity = Field(
        description="The full fidelity envelope (target + tier + report + advisory), no artifact.",
    )


class PublicExportDocumentRequest(BaseModel):
    """An emit request for the public path: the chosen target + per-emit options."""

    model_config = ConfigDict(extra="forbid")

    target: str = Field(
        description="Target emitter key (``asyncapi``) or format key (``asyncapi-3``).",
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Per-target emit options (MFX-1.4); null or empty applies the target defaults.",
    )


# ===========================================================================
# Routes
# ===========================================================================


def _load_public_source(
    tenant_slug: str, project_slug: str, version_slug: str
) -> ExportSource:
    """Load the published/public source for the slug coordinates, mapping errors to HTTP."""
    try:
        return load_public_export_source(tenant_slug, project_slug, version_slug)
    except ExportSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get(
    _EXPORT_PATH + "/targets",
    response_model=PublicExportTargetsResponse,
    summary="List export targets for a published public version (no auth)",
    description=(
        "For the published public version identified by the slugs, enumerate every registered "
        "export target (descriptor + capability profile + options) with a cheap per-target "
        "fidelity badge (tier + preserved-%). The anonymous counterpart of "
        "``GET /v1/export/{tenant_slug}/targets``; drives the public export dialog's target "
        "cards and fidelity warning (MFX-7.1)."
    ),
    responses=_NOT_FOUND_RESPONSES,
)
async def list_public_export_targets(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
) -> PublicExportTargetsResponse:
    """Return every export target with its fidelity badge for a published public version.

    Args:
        tenant_slug: The owning tenant's slug.
        project_slug: The project (artifact) slug within the tenant.
        version_slug: The version label (e.g. ``1.0.0``) of the published revision.

    Returns:
        The per-target fidelity list for the resolved published revision.

    Raises:
        HTTPException: 404 when no published public version matches the slugs; 422 when the
            revision has no reconstructable source; 400 when the source format cannot be adapted.
    """
    source = _load_public_source(tenant_slug, project_slug, version_slug)
    return PublicExportTargetsResponse(
        tenant_slug=tenant_slug,
        project_slug=project_slug,
        version_slug=version_slug,
        version_record_id=source.version_record_id,
        version_label=source.version_label,
        targets=build_target_fidelity_entries(source.api),
    )


@router.post(
    _EXPORT_PATH + "/preview",
    response_model=PublicExportPreviewResponse,
    summary="Preview export fidelity for a published public version (no auth)",
    description=(
        "Compute the full fidelity report for exporting the published public version to one "
        "target — the per-construct LossinessReport, the user-facing advisory (MFX-2.4), and "
        "the tier summary — **without producing the artifact**. The anonymous counterpart of "
        "``POST /v1/export/{tenant_slug}/preview``; backs the public fidelity advisory "
        "(MFX-7.2)."
    ),
    responses=_NOT_FOUND_RESPONSES,
)
async def preview_public_export_fidelity(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    request: PublicExportPreviewRequest,
) -> PublicExportPreviewResponse:
    """Return the full fidelity envelope for one public (source, target) export, emitting nothing.

    Args:
        tenant_slug: The owning tenant's slug.
        project_slug: The project (artifact) slug within the tenant.
        version_slug: The version label of the published revision.
        request: The chosen target + advisory threshold.

    Returns:
        The dry-run preview: the full fidelity envelope plus the resolved coordinates.

    Raises:
        HTTPException: 404 when no published public version matches the slugs; 422 when the
            revision has no reconstructable source; 400 when the target or source format is
            unsupported.
    """
    source = _load_public_source(tenant_slug, project_slug, version_slug)

    try:
        emitter_cls = type(resolve_emitter(request.target))
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    fidelity = build_export_fidelity(
        source.api, emitter_cls, min_severity=request.min_severity
    )
    return PublicExportPreviewResponse(
        tenant_slug=tenant_slug,
        project_slug=project_slug,
        version_slug=version_slug,
        version_record_id=source.version_record_id,
        version_label=source.version_label,
        fidelity=fidelity,
    )


@router.post(
    _EXPORT_PATH + "/document",
    summary="Emit the export document for a published public version (no auth)",
    description=(
        "Emit the published public version to one ``target`` through the Emitter SPI and "
        "return the document itself — JSON by default, YAML when ``Accept: application/yaml`` "
        "is sent — as a download. The anonymous counterpart of "
        "``POST /v1/export/{tenant_slug}/document``. Strictly read-only: no field-identity "
        "state is persisted for anonymous exports."
    ),
    response_class=Response,
    responses=_NOT_FOUND_RESPONSES,
)
async def emit_public_export_document(
    tenant_slug: str,
    project_slug: str,
    version_slug: str,
    request: PublicExportDocumentRequest,
    accept: Optional[str] = Header(None),
) -> Response:
    """Emit and return the export document for one public (source, target) pair.

    Args:
        tenant_slug: The owning tenant's slug.
        project_slug: The project (artifact) slug within the tenant.
        version_slug: The version label of the published revision.
        request: The chosen target + optional per-emit options.
        accept: Accept header for JSON/YAML content negotiation.

    Returns:
        The emitted document, serialized as JSON (default) or YAML, with a
        ``Content-Disposition`` filename derived from the emitter's primary output path.

    Raises:
        HTTPException: 404 when no published public version matches the slugs; 422 when the
            revision has no reconstructable source or the emitter produced no document; 400 when
            the target, source format, or options are unsupported.
    """
    source = _load_public_source(tenant_slug, project_slug, version_slug)
    # persistence=None keeps the anonymous path read-only (no field-number writes).
    return render_emitted_document(
        source.api, request.target, request.options, accept, persistence=None
    )
