"""Stored overlay chain routes — GVM-4.3 (#5878).

``/v1/versions/{tenant}/{project}/{version}/overlays``. Each revision has an ordered chain of
Overlay 1.x documents, applied at export and publish render only (:mod:`app.version_overlay_chain`).

* ``GET    …/overlays``            the chain, plus the publish render record when there is one.
* ``POST   …/overlays``            add an overlay (appends unless ``position`` is given).
* ``PUT    …/overlays/{id}``       replace one overlay in place (delete + insert, one audit event).
* ``DELETE …/overlays/{id}``       remove one overlay.
* ``GET    …/overlays/preview``    the resolved document and its provenance ledger: exactly what an
  export with the same chain renders, because both call
  :func:`app.version_overlay_store.resolve_for_export`.

Reads need ``versions:view``; writes need ``versions:edit``. A published revision is read-only, so
every write on one is refused with ``409 overlay-version-published``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

import psycopg2
from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import version_overlay_store
from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .export_overlay import (
    OVERLAY_SOURCE_UNSUPPORTED,
    ExportOverlay,
    ExportOverlayError,
    ExportOverlayFinding,
    ExportOverlayReport,
    overlay_source_document,
)
from .export_source import ExportSourceError, load_export_source
from .permissions import Action, Resource, enforce_permission
from .version_overlay_chain import (
    MAX_STORED_OVERLAYS,
    OVERLAY_SOURCES,
    StoredOverlay,
    document_fingerprint,
)

router = APIRouter(prefix="/v1/versions", tags=["versions"])

#: Refusal code: the revision is published, so its chain is read-only.
CODE_VERSION_PUBLISHED = "overlay-version-published"
#: Refusal code: the chain already holds :data:`MAX_STORED_OVERLAYS` overlays.
CODE_CHAIN_FULL = "overlay-chain-full"
#: Refusal code: the overlay id is not in this revision's chain.
CODE_NOT_FOUND = "overlay-not-found"
#: Refusal code: another write changed the chain at the same moment; retry.
CODE_CONFLICT = "overlay-chain-conflict"


def _conflict(exc: Exception) -> HTTPException:
    """A concurrent write took the same position: 409, safe to retry."""
    return HTTPException(
        status_code=409,
        detail={
            "code": CODE_CONFLICT,
            "message": "Someone else changed this revision's overlays at the same moment. Try again.",
        },
    )

OverlaySource = Literal["manual", "lint-fix", "export-studio", "enrichment-export"]
assert tuple(OverlaySource.__args__) == OVERLAY_SOURCES  # type: ignore[attr-defined]

_BASE = "/{tenant_slug}/{project_id}/{version_record_id}/overlays"


class VersionOverlayWrite(BaseModel):
    """Body of ``POST`` / ``PUT …/overlays``: one Overlay document and its label and origin."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200, description="The overlay's label, shown in ledger rows.")
    source: OverlaySource = Field(
        default="manual",
        description="Where the overlay came from: `manual` (uploaded), `lint-fix` (a saved fix "
        "plan), `export-studio` (saved from Export Studio) or `enrichment-export` (accepted "
        "agent-toolset enrichment).",
    )
    document: Dict[str, Any] = Field(
        description="The parsed Overlay 1.0 / 1.1 / 1.2 document, at most 1 MiB serialized."
    )
    position: Optional[int] = Field(
        default=None,
        ge=0,
        description="POST only: where to insert it (0 applies first). Omitted or past the end "
        "appends. Ignored by PUT, which keeps the replaced overlay's position.",
    )

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        """Trim the label and refuse a blank one."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("An overlay needs a non-blank 'name'.")
        return stripped

    @field_validator("document")
    @classmethod
    def _valid_overlay(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        """Apply the export overlay checks (Overlay marker, 1 MiB cap) so a stored overlay always renders."""
        ExportOverlay(name="validation", document=value)
        return value


class VersionOverlayOut(BaseModel):
    """One stored overlay of a revision's chain."""

    id: str = Field(description="The overlay id. A replace gives the overlay a new id (rows are write-once).")
    position: int = Field(description="Order in the chain; 0 applies first.")
    name: str
    source: OverlaySource
    content_fingerprint: str = Field(description="`sha256:` of the document's canonical JSON.")
    action_count: int = Field(description="How many actions the overlay declares.")
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    document: Dict[str, Any] = Field(description="The Overlay document.")


class VersionOverlayRenderOut(BaseModel):
    """The publish render of the chain: source and resolved fingerprints, side by side."""

    source_fingerprint: str = Field(description="Fingerprint of the source OpenAPI document.")
    resolved_fingerprint: str = Field(description="Fingerprint of the document after the chain.")
    overlays: List[Dict[str, Any]] = Field(
        default_factory=list, description="The chain that was rendered: `{id, name, position, contentFingerprint}`."
    )
    findings: List[ExportOverlayFinding] = Field(default_factory=list)
    changes: int = 0
    rendered_by: Optional[str] = None
    rendered_at: Optional[datetime] = None


class VersionOverlayChainOut(BaseModel):
    """``GET …/overlays``: the chain in application order."""

    version_record_id: str
    published: bool = Field(description="True when the revision is published: the chain is read-only.")
    max_overlays: int = Field(default=MAX_STORED_OVERLAYS, description="Longest chain a revision may hold.")
    overlays: List[VersionOverlayOut]
    render: Optional[VersionOverlayRenderOut] = Field(
        default=None, description="What the publish render recorded; null before publish or without a chain."
    )


class VersionOverlayPreviewOut(BaseModel):
    """``GET …/overlays/preview``: the resolved document and the provenance of every change."""

    version_record_id: str
    source_fingerprint: str = Field(description="Fingerprint of the source OpenAPI document.")
    resolved_fingerprint: str = Field(description="Fingerprint of the resolved document.")
    document: Dict[str, Any] = Field(description="The resolved OpenAPI document (source + chain).")
    report: Optional[ExportOverlayReport] = Field(
        default=None, description="Ledger rows and `overlay.*` findings; null when the chain is empty."
    )


def _overlay_out(row: StoredOverlay) -> VersionOverlayOut:
    """Render a stored row for the API."""
    actions = row.document.get("actions")
    return VersionOverlayOut(
        id=row.id,
        position=row.position,
        name=row.name,
        source=row.source,  # type: ignore[arg-type]
        content_fingerprint=row.content_fingerprint,
        action_count=len(actions) if isinstance(actions, list) else 0,
        created_by=row.created_by,
        created_at=row.created_at,
        document=row.document,
    )


def _version(tenant_id: str, project_id: str, version_record_id: str) -> Dict[str, Any]:
    """Load the revision inside the caller's tenant and project, or raise 404."""
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version or str(version.get("project_id")) != str(project_id):
        raise HTTPException(status_code=404, detail="Version not found")
    return version


def _writable_version(tenant_id: str, project_id: str, version_record_id: str) -> Dict[str, Any]:
    """Load the revision for a write: 404 when unknown, 409 when published."""
    version = _version(tenant_id, project_id, version_record_id)
    if version.get("published"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": CODE_VERSION_PUBLISHED,
                "message": "This revision is published, so its overlay chain is read-only. Change the "
                "chain on a draft revision.",
            },
        )
    return version


def _load_openapi_source(tenant_id: str, project_id: str, version_record_id: str):
    """Load the revision's export source and refuse one that overlays cannot modify (422)."""
    try:
        source = load_export_source(tenant_id, project_id, version_record_id)
    except ExportSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.http_detail()) from exc
    if overlay_source_document(source) is None:
        fmt = source.source_format or source.api.format or "this format"
        raise HTTPException(
            status_code=422,
            detail={
                "code": OVERLAY_SOURCE_UNSUPPORTED,
                "message": f"Overlays modify OpenAPI documents, and this revision's source is {fmt}.",
            },
        )
    return source


@router.get(_BASE, response_model=VersionOverlayChainOut)
async def list_version_overlays(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionOverlayChainOut:
    """List a revision's stored overlay chain, in the order it is applied.

    Args:
        tenant_slug: The tenant slug (the tenant comes from the credential).
        project_id: The project id.
        version_record_id: The revision id.
        auth_data: Authenticated tenant context.

    Returns:
        The chain, whether it is read-only, and the publish render record when there is one.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    version = _version(tenant_id, project_id, version_record_id)
    rows = version_overlay_store.list_overlays(tenant_id, version_record_id)
    render = version_overlay_store.get_render(tenant_id, version_record_id)
    return VersionOverlayChainOut(
        version_record_id=version_record_id,
        published=bool(version.get("published")),
        overlays=[_overlay_out(row) for row in rows],
        render=VersionOverlayRenderOut(**render) if render else None,
    )


@router.get(f"{_BASE}/preview", response_model=VersionOverlayPreviewOut)
async def preview_version_overlays(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionOverlayPreviewOut:
    """Render the revision's source with its stored chain, as an export would.

    Args:
        tenant_slug: The tenant slug.
        project_id: The project id.
        version_record_id: The revision id.
        auth_data: Authenticated tenant context.

    Returns:
        The resolved document, the source and resolved fingerprints, and the ledger/findings.

    Raises:
        HTTPException: 404 for an unknown revision; 422 (``{code, message}``) when the source is not
            OpenAPI or the chain cannot be applied.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _version(tenant_id, project_id, version_record_id)
    source = _load_openapi_source(tenant_id, project_id, version_record_id)
    base = overlay_source_document(source) or {}
    try:
        resolved, report = version_overlay_store.resolve_for_export(tenant_id, source)
    except ExportOverlayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.http_detail()) from exc
    document = dict(resolved.api.raw or {})
    return VersionOverlayPreviewOut(
        version_record_id=version_record_id,
        source_fingerprint=document_fingerprint(base),
        resolved_fingerprint=document_fingerprint(document),
        document=document,
        report=report,
    )


@router.post(_BASE, response_model=VersionOverlayOut, status_code=201)
async def add_version_overlay(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: VersionOverlayWrite = Body(...),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionOverlayOut:
    """Add an overlay to a draft revision's chain.

    Args:
        tenant_slug: The tenant slug.
        project_id: The project id.
        version_record_id: The revision id.
        body: The overlay, its label, source and optional position.
        auth_data: Authenticated tenant context.

    Returns:
        The stored overlay.

    Raises:
        HTTPException: 404 unknown revision; 409 ``overlay-version-published``,
            ``overlay-chain-full`` or ``overlay-chain-conflict`` (a concurrent write; retry); 422 when
            the source is not OpenAPI or the body is invalid.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    _writable_version(tenant_id, project_id, version_record_id)
    if len(version_overlay_store.list_overlays(tenant_id, version_record_id)) >= MAX_STORED_OVERLAYS:
        raise HTTPException(
            status_code=409,
            detail={
                "code": CODE_CHAIN_FULL,
                "message": f"A revision's chain holds at most {MAX_STORED_OVERLAYS} overlays. Remove "
                "or replace one first.",
            },
        )
    _load_openapi_source(tenant_id, project_id, version_record_id)
    try:
        stored = version_overlay_store.insert_overlay(
            tenant_id=tenant_id,
            project_id=project_id,
            version_record_id=version_record_id,
            name=body.name,
            source=body.source,
            document=body.document,
            actor_id=get_authenticated_user_id(auth_data),
            position=body.position,
        )
    except psycopg2.errors.UniqueViolation as exc:
        raise _conflict(exc) from exc
    return _overlay_out(stored)


@router.put(f"{_BASE}/{{overlay_id}}", response_model=VersionOverlayOut)
async def replace_version_overlay(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    overlay_id: str,
    body: VersionOverlayWrite = Body(...),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionOverlayOut:
    """Replace one overlay of a draft revision's chain, keeping its position.

    Args:
        tenant_slug: The tenant slug.
        project_id: The project id.
        version_record_id: The revision id.
        overlay_id: The overlay to replace.
        body: The new overlay (``position`` is ignored).
        auth_data: Authenticated tenant context.

    Returns:
        The new stored overlay. It has a new id, because stored overlays are write-once.

    Raises:
        HTTPException: 404 unknown revision or overlay; 409 ``overlay-version-published``.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    _writable_version(tenant_id, project_id, version_record_id)
    try:
        stored = version_overlay_store.replace_overlay(
            tenant_id=tenant_id,
            project_id=project_id,
            version_record_id=version_record_id,
            overlay_id=overlay_id,
            name=body.name,
            source=body.source,
            document=body.document,
            actor_id=get_authenticated_user_id(auth_data),
        )
    except psycopg2.errors.UniqueViolation as exc:
        raise _conflict(exc) from exc
    if stored is None:
        raise HTTPException(status_code=404, detail={"code": CODE_NOT_FOUND, "message": "Overlay not found"})
    return _overlay_out(stored)


@router.delete(f"{_BASE}/{{overlay_id}}", status_code=204)
async def delete_version_overlay(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    overlay_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Remove one overlay from a draft revision's chain.

    Args:
        tenant_slug: The tenant slug.
        project_id: The project id.
        version_record_id: The revision id.
        overlay_id: The overlay to remove.
        auth_data: Authenticated tenant context.

    Returns:
        204 No Content.

    Raises:
        HTTPException: 404 unknown revision or overlay; 409 ``overlay-version-published``.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    _writable_version(tenant_id, project_id, version_record_id)
    try:
        removed = version_overlay_store.delete_overlay(
            tenant_id=tenant_id,
            project_id=project_id,
            version_record_id=version_record_id,
            overlay_id=overlay_id,
            actor_id=get_authenticated_user_id(auth_data),
        )
    except psycopg2.errors.UniqueViolation as exc:
        raise _conflict(exc) from exc
    if not removed:
        raise HTTPException(status_code=404, detail={"code": CODE_NOT_FOUND, "message": "Overlay not found"})
    return Response(status_code=204)
