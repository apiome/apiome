"""
Catalog API Routes (MFI-23.2)

Read endpoints for the *Catalog* — the ``publishable = false`` slice of projects, i.e. the
OpenAPI-worthy non-OpenAPI imports that are deliberately *not* publishable Projects (MFI-23.1).

The list + detail responses deliberately mirror the Projects contract (``projects_routes.py``):
the same envelope (id/name/slug/description/timestamps/creator/qualityScore/qualityGrade) plus the
catalog-only format/source fields (``sourceFormat``, ``protocol``, ``formatMetadata``,
``toolVersions``) and the ``publishable = false`` invariant. Matching the Projects shape is the
whole point — it lets the Catalog screen (MFI-23.3) be cloned from the Projects dashboard.

Catalog items are created by the import routing (MFI-23.7), not through this API, so only read
endpoints exist here. All endpoints are tenant-scoped and require authentication via JWT token or
API key.
"""

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import RedirectResponse, StreamingResponse
from typing import Dict, Any, List

from .database import db
from .models import (
    CatalogItemSchema,
    CatalogItemDetailSchema,
    CatalogNormalizedSummary,
    CatalogSourceDescriptor,
    LintReportResponse,
)
from .catalog_detail import (
    derive_catalog_summary,
    derive_catalog_source,
    resolve_source_payload,
)
from .lint_routes import build_lint_report
from .auth import validate_authentication

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


@router.get("/{tenant_slug}")
async def list_catalog_items(
    tenant_slug: str,
    include_deleted: bool = Query(
        False,
        description="When true, include soft-deleted catalog items (active items listed first).",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[CatalogItemSchema]:
    """
    List all catalog items for a tenant.

    Returns the same envelope as ``GET /v1/projects/{tenant_slug}`` (so the Catalog screen can be
    cloned from the Projects dashboard) restricted to the non-publishable slice, with each item
    also carrying the latest revision's format/protocol/source provenance.

    Supports authentication via:
    - JWT token in Authorization header (Bearer token)
    - API key in X-API-Key header

    Args:
        tenant_slug: The tenant slug.
        include_deleted: Include rows with deleted_at set (for trash / restore flows).
        auth_data: Authentication data (injected by dependency).

    Returns:
        List of catalog items for the tenant (active first when include_deleted is set).
    """
    items = db.get_catalog_items_for_tenant(
        auth_data['tenant_id'], include_deleted=include_deleted
    )

    return [CatalogItemSchema(**item) for item in items]


@router.get("/{tenant_slug}/{item_id}")
async def get_catalog_item(
    tenant_slug: str,
    item_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CatalogItemDetailSchema:
    """
    Get a specific catalog item by ID, with the MFI-23.9 detail enrichments.

    Returns the MFI-23.2 list envelope plus a normalized-content ``summary`` (services/operations/
    types/channels counts) and a ``source`` material descriptor, both derived from the latest
    revision's ``format_metadata``. A publishable Project is intentionally *not* returned here: only
    the non-publishable slice is a catalog item, so requesting a Project's id (or an unknown id)
    yields 404.

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug.
        item_id: The catalog item ID.
        auth_data: Authentication data (injected by dependency).

    Returns:
        The catalog item details, including its normalized summary and source descriptor.
    """
    item = db.get_catalog_item_by_id(item_id, auth_data['tenant_id'])

    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"Catalog item not found: {item_id}"
        )

    summary = derive_catalog_summary(item.get("format_metadata"))
    source = derive_catalog_source(item.get("format_metadata"), item.get("metadata"))

    return CatalogItemDetailSchema(
        **item,
        summary=CatalogNormalizedSummary(**summary),
        source=CatalogSourceDescriptor(**source),
    )


@router.get(
    "/{tenant_slug}/{item_id}/lint",
    response_model=LintReportResponse,
)
async def lint_catalog_item(
    tenant_slug: str,
    item_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> LintReportResponse:
    """
    Score a catalog item's latest revision and return itemized lint findings (MFI-23.10).

    The catalog analog of ``GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint``:
    it lets the Catalog card/detail lint orbs open the *same* server-computed lint report the
    Projects screens use, populated from the item's own revision rather than browser-local history.

    A catalog item's id *is* a project id (the Catalog is the non-publishable slice of projects,
    MFI-23.1), so the latest revision is resolved here and fed to the shared
    :func:`app.lint_routes.build_lint_report`. Like the other catalog reads this is restricted to
    the non-publishable slice — a Project's id, or an unknown id, yields 404 — and authenticated via
    JWT token or API key.

    Args:
        tenant_slug: The tenant slug (used to reconstruct the OpenAPI document).
        item_id: The catalog item ID (a project id).
        auth_data: Authentication data (injected by dependency).

    Returns:
        The server-computed quality score, A-F grade and itemized findings for the latest revision.
    """
    tenant_id = auth_data["tenant_id"]

    item = db.get_catalog_item_by_id(item_id, tenant_id)
    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"Catalog item not found: {item_id}",
        )

    revision_id = db.get_latest_revision_id_for_project(item_id, tenant_id)
    if not revision_id:
        raise HTTPException(
            status_code=404,
            detail=f"No revision to lint for catalog item: {item_id}",
        )

    version = db.get_version_by_id(revision_id, tenant_id)
    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Revision not found: {revision_id}",
        )

    return build_lint_report(version, item_id, tenant_slug, tenant_id)


@router.get("/{tenant_slug}/{item_id}/source")
async def get_catalog_item_source(
    tenant_slug: str,
    item_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
):
    """
    Serve a catalog item's original source material (MFI-23.9): viewable / downloadable.

    Resolves what the import captured onto the item's ``format_metadata``:

    * **inline content** — streamed back as a downloadable attachment (typed by source format);
    * **a source URL** (when no content was captured) — answered with a redirect to that URL;
    * **neither** — ``404``, since the raw source has not (yet) been captured for this item.

    Like the other catalog reads this is restricted to the non-publishable slice (a Project's id, or
    an unknown id, yields 404) and authenticated via JWT token or API key.

    Args:
        tenant_slug: The tenant slug.
        item_id: The catalog item ID.
        auth_data: Authentication data (injected by dependency).

    Returns:
        A StreamingResponse of the captured source, or a RedirectResponse to the source URL.
    """
    item = db.get_catalog_item_by_id(item_id, auth_data['tenant_id'])

    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"Catalog item not found: {item_id}"
        )

    payload = resolve_source_payload(item)

    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=f"No source material captured for catalog item: {item_id}",
        )

    if payload["mode"] == "redirect":
        # 307 preserves the method and lets the browser fetch the original source directly.
        return RedirectResponse(url=payload["url"], status_code=307)

    return StreamingResponse(
        iter([payload["content"]]),
        media_type=payload["media_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{payload["filename"]}"',
        },
    )
