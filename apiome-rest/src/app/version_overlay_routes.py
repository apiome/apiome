"""Stored overlay chain routes — GVM-4.3 (#5878).

``/v1/versions/{tenant}/{project}/{version}/overlays``. Each revision has an ordered chain of
Overlay 1.x documents, applied at export and publish render only (:mod:`app.version_overlay_chain`).

* ``GET    …/overlays``            the chain, plus the publish render record when there is one.
* ``POST   …/overlays``            add an overlay (appends unless ``position`` is given).
* ``PUT    …/overlays/{id}``       replace one overlay in place (delete + insert, one audit event).
* ``DELETE …/overlays/{id}``       remove one overlay.
* ``GET    …/overlays/preview``    the resolved document and its provenance ledger: exactly what an
  export with the same chain renders, because both call
  :func:`app.version_overlay_chain.resolve_chain`.
* ``POST   …/overlays/preview``    the same render with an unsaved **draft** overlay — appended, or
  standing in for one stored overlay — so the overlay manager can preview an edit before saving
  it (COA-2.7, #7050). Nothing is written.
* ``POST   …/overlays/apply``      **apply as a version** (COA-2.7): the resolved document is
  imported as a new version of the same project, through the import quality gate and pipeline
  the spec upgrade assistant uses (:mod:`app.openapi_version_import`). The source revision and
  its chain are untouched; the new version starts with an empty chain.

Every preview carries a per-action row (kind, target, how many nodes it matched — ``report.actions``)
and a before / after row per changed value with the actions that changed it (``diff``,
:mod:`app.version_overlay_diff`).

Reads need ``versions:view``; writes need ``versions:edit``. A published revision is read-only, so
every write on one is refused with ``409 overlay-version-published``. Apply reads the chain
(``versions:view``) and adds a version (``imports:create`` and ``projects:edit``), so it works
from a published revision too.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

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
from .export_source import ExportSource, ExportSourceError, load_export_source
from .openapi_version_import import (
    choose_version_label,
    document_bytes,
    enforce_openapi_quality_gate,
    existing_version_labels,
    import_openapi_as_version,
)
from .permissions import Action, Resource, enforce_permission
from .version_overlay_chain import (
    MAX_STORED_OVERLAYS,
    OVERLAY_SOURCES,
    STORED_OVERLAY_PREFIX,
    StoredOverlay,
    document_fingerprint,
    resolve_chain,
)
from .version_overlay_diff import overlay_value_diff

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/versions", tags=["versions"])

#: Refusal code: the revision is published, so its chain is read-only.
CODE_VERSION_PUBLISHED = "overlay-version-published"
#: Refusal code: the chain already holds :data:`MAX_STORED_OVERLAYS` overlays.
CODE_CHAIN_FULL = "overlay-chain-full"
#: Refusal code: the overlay id is not in this revision's chain.
CODE_NOT_FOUND = "overlay-not-found"
#: Refusal code: another write changed the chain at the same moment; retry.
CODE_CONFLICT = "overlay-chain-conflict"
#: Refusal code: apply was asked of a revision with no stored overlays.
CODE_CHAIN_EMPTY = "overlay-chain-empty"
#: Refusal code: the chain changes nothing, so applying it would duplicate the revision.
CODE_NO_CHANGES = "overlay-no-changes"
#: Refusal code: the resolved document could not be imported as a new version.
CODE_APPLY_IMPORT_FAILED = "overlay-apply-import-failed"
#: Label prefix of the unsaved draft overlay in a preview's report.
DRAFT_OVERLAY_PREFIX = "draft:"
#: Workflow-audit action written by every apply.
AUDIT_OVERLAYS_APPLIED = "version.overlays.applied"


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
        default=None,
        description="Ledger rows, per-action match counts (`actions`) and `overlay.*` findings; null "
        "when the chain is empty.",
    )
    diff: List["VersionOverlayDiffRow"] = Field(
        default_factory=list,
        description="One before / after row per changed value (at most 500), with the actions that changed it.",
    )
    draft: Optional[str] = Field(
        default=None, description="The draft overlay's label in `report` (`draft:<name>`), when a draft was previewed."
    )


class VersionOverlayChangedBy(BaseModel):
    """One action that changed a value: the per-value provenance of a diff row."""

    overlay: Optional[str] = Field(default=None, description="The overlay's label (`stored:<name>` / `draft:<name>`).")
    action_index: Optional[int] = Field(default=None, description="0-based index of the action.")
    target: Optional[str] = Field(default=None, description="The action's JSONPath `target`.")
    kind: str = Field(description="`set`, `replaced`, `appended` or `removed`.")


class VersionOverlayDiffRow(BaseModel):
    """A value the chain changed: before (source) and after (resolved), and who changed it."""

    pointer: str = Field(description="JSON Pointer of the value.")
    kind: str = Field(description="The last change's kind: `set`, `replaced`, `appended` or `removed`.")
    before: Any = Field(default=None, description="The value in the source; null when absent (see `before_present`).")
    before_present: bool = Field(description="False when the source had no value here (the chain added it).")
    after: Any = Field(default=None, description="The value after the chain; null when absent (see `after_present`).")
    after_present: bool = Field(description="False when the chain removed the value.")
    changed_by: List[VersionOverlayChangedBy] = Field(
        description="Every action that changed the value, in application order; the last one wins."
    )


VersionOverlayPreviewOut.model_rebuild()


class VersionOverlayDraft(BaseModel):
    """An unsaved overlay to preview."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200, description="The draft's label.")
    document: Dict[str, Any] = Field(description="The Overlay 1.0 / 1.1 / 1.2 document, at most 1 MiB serialized.")

    @field_validator("name")
    @classmethod
    def _strip_name(cls, value: str) -> str:
        """Trim the label and refuse a blank one."""
        stripped = value.strip()
        if not stripped:
            raise ValueError("A draft overlay needs a non-blank 'name'.")
        return stripped

    @field_validator("document")
    @classmethod
    def _valid_overlay(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        """Apply the export overlay checks (Overlay marker, 1 MiB cap)."""
        ExportOverlay(name="validation", document=value)
        return value


class VersionOverlayPreviewRequest(BaseModel):
    """Body of ``POST …/overlays/preview``: an optional draft, and the stored overlay it stands in for."""

    model_config = ConfigDict(extra="forbid")

    draft: Optional[VersionOverlayDraft] = Field(
        default=None, description="The unsaved overlay. Omitted: the stored chain alone (same as GET)."
    )
    replace_overlay_id: Optional[str] = Field(
        default=None,
        description="Preview the draft in this stored overlay's place (an edit). Omitted: the draft is "
        "appended to the chain (a new overlay).",
    )


class VersionOverlayApplyRequest(BaseModel):
    """Body of ``POST …/overlays/apply``."""

    model_config = ConfigDict(extra="forbid")

    version_label: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Label of the new version (for example 1.1.0). Default: a date/time label.",
    )


class VersionOverlayApplyOut(BaseModel):
    """The version an apply created."""

    project_id: str
    version_record_id: str = Field(description="The new version's id (versions.id).")
    version_label: str
    source_version_record_id: str = Field(description="The revision whose chain was applied.")
    overlay_count: int = Field(description="Overlays in the applied chain.")
    change_count: int = Field(description="Values the chain changed.")


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


def _render_preview(
    version_record_id: str,
    source: ExportSource,
    stored: Sequence[StoredOverlay],
    inline: Sequence[ExportOverlay] = (),
    draft_label: Optional[str] = None,
) -> VersionOverlayPreviewOut:
    """Render ``source`` with ``stored`` then ``inline`` and build the preview reply.

    Args:
        version_record_id: The revision.
        source: The revision's OpenAPI export source.
        stored: The chain to apply (possibly with one overlay swapped for a draft).
        inline: Overlays applied after the chain (an appended draft).
        draft_label: The draft's label in the report, when there is one.

    Returns:
        The resolved document, fingerprints, report and before / after rows.

    Raises:
        HTTPException: 422 (``{code, message}``) when the chain cannot be applied.
    """
    base = overlay_source_document(source) or {}
    try:
        resolved, report = resolve_chain(source, stored, list(inline))
    except ExportOverlayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.http_detail()) from exc
    document = dict(resolved.api.raw or {})
    diff = overlay_value_diff(base, document, report.ledger) if report else []
    return VersionOverlayPreviewOut(
        version_record_id=version_record_id,
        source_fingerprint=document_fingerprint(base),
        resolved_fingerprint=document_fingerprint(document),
        document=document,
        report=report,
        diff=[VersionOverlayDiffRow(**row) for row in diff],
        draft=draft_label,
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
        The resolved document, the source and resolved fingerprints, the ledger / per-action rows /
        findings, and the before / after rows.

    Raises:
        HTTPException: 404 for an unknown revision; 422 (``{code, message}``) when the source is not
            OpenAPI or the chain cannot be applied.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _version(tenant_id, project_id, version_record_id)
    source = _load_openapi_source(tenant_id, project_id, version_record_id)
    stored = version_overlay_store.list_overlays(tenant_id, version_record_id)
    return _render_preview(version_record_id, source, stored)


def _chain_with_draft(
    stored: Sequence[StoredOverlay], body: VersionOverlayPreviewRequest
) -> Tuple[List[StoredOverlay], List[ExportOverlay], Optional[str]]:
    """Place the request's draft in the chain: in a stored overlay's slot, or after the chain.

    Args:
        stored: The revision's stored chain.
        body: The preview request.

    Returns:
        ``(stored, inline, draft_label)`` to render.

    Raises:
        HTTPException: 422 when ``replace_overlay_id`` comes without a draft; 404
            ``overlay-not-found`` when it is not in the chain.
    """
    if body.draft is None:
        if body.replace_overlay_id:
            raise HTTPException(
                status_code=422,
                detail={"code": "overlay-draft-missing", "message": "replace_overlay_id needs a draft overlay."},
            )
        return list(stored), [], None
    if body.replace_overlay_id:
        if not any(row.id == body.replace_overlay_id for row in stored):
            raise HTTPException(status_code=404, detail={"code": CODE_NOT_FOUND, "message": "Overlay not found"})
        swapped = [
            dataclasses.replace(row, name=body.draft.name, document=body.draft.document)
            if row.id == body.replace_overlay_id
            else row
            for row in stored
        ]
        return swapped, [], f"{STORED_OVERLAY_PREFIX}{body.draft.name}"
    label = f"{DRAFT_OVERLAY_PREFIX}{body.draft.name}"
    return list(stored), [ExportOverlay(name=label, document=body.draft.document)], label


@router.post(f"{_BASE}/preview", response_model=VersionOverlayPreviewOut)
async def preview_version_overlay_draft(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: VersionOverlayPreviewRequest = Body(...),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionOverlayPreviewOut:
    """Render the chain with an unsaved draft overlay, so an edit can be checked before it is saved.

    The draft is appended to the chain (a new overlay) or stands in for ``replace_overlay_id`` (an
    edit). Nothing is written, so a published revision can be previewed too.

    Args:
        tenant_slug: The tenant slug.
        project_id: The project id.
        version_record_id: The revision id.
        body: The draft and the overlay it replaces, if any.
        auth_data: Authenticated tenant context.

    Returns:
        The preview, with ``draft`` naming the draft's label in the report.

    Raises:
        HTTPException: 404 unknown revision or overlay; 422 when the source is not OpenAPI, the draft
            is not an Overlay document, or the chain cannot be applied.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _version(tenant_id, project_id, version_record_id)
    source = _load_openapi_source(tenant_id, project_id, version_record_id)
    stored, inline, label = _chain_with_draft(version_overlay_store.list_overlays(tenant_id, version_record_id), body)
    return _render_preview(version_record_id, source, stored, inline, label)


@router.post(f"{_BASE}/apply", response_model=VersionOverlayApplyOut, status_code=201)
async def apply_version_overlays(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: VersionOverlayApplyRequest = Body(default_factory=VersionOverlayApplyRequest),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionOverlayApplyOut:
    """Apply the revision's stored chain as a new version of the same project.

    The resolved document — exactly what the preview and an export render — passes the tenant's
    import quality gate and is imported as a new version. The source revision and its chain are not
    changed; the new version has an empty chain, since the overlays are now part of its source.

    Args:
        tenant_slug: The tenant slug.
        project_id: The project id.
        version_record_id: The revision whose chain is applied.
        body: The new version's label (optional).
        auth_data: Authenticated tenant context.

    Returns:
        The new version's id and label, and what was applied.

    Raises:
        HTTPException: 404 unknown revision; 409 ``overlay-chain-empty``, ``overlay-no-changes``,
            ``version-exists`` or ``QUALITY_POLICY_BLOCKED``; 422 when the source is not OpenAPI,
            the chain cannot be applied, or the import fails (``overlay-apply-import-failed``).
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    target = f"project:{project_id}:overlays-apply"
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.CREATE, target=target)
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT, target=target)
    tenant_id = str(auth_data["tenant_id"])
    version = _version(tenant_id, project_id, version_record_id)
    stored = version_overlay_store.list_overlays(tenant_id, version_record_id)
    if not stored:
        raise HTTPException(
            status_code=409,
            detail={"code": CODE_CHAIN_EMPTY, "message": "This revision has no overlays to apply."},
        )
    source = _load_openapi_source(tenant_id, project_id, version_record_id)
    preview = _render_preview(version_record_id, source, stored)
    changes = preview.report.changes if preview.report else 0
    if changes == 0:
        raise HTTPException(
            status_code=409,
            detail={
                "code": CODE_NO_CHANGES,
                "message": "The overlays change nothing in this revision, so applying them would only copy it.",
            },
        )

    existing = await asyncio.to_thread(existing_version_labels, project_id, tenant_id)
    label = choose_version_label(body.version_label, existing)
    raw = document_bytes(preview.document)
    await enforce_openapi_quality_gate(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        user_id=str(actor_id or ""),
        project_id=project_id,
        label=label,
        raw=raw,
        filename="overlaid-openapi.json",
    )
    projection = db.get_version_source_projection(version_record_id, tenant_id) or {}
    names = ", ".join(row.name for row in sorted(stored, key=lambda r: r.position))
    source_label = version.get("version_id") or version_record_id
    new_id = await asyncio.to_thread(
        import_openapi_as_version,
        tenant_id=tenant_id,
        actor_id=str(actor_id) if actor_id else None,
        project_id=project_id,
        format_metadata=projection.get("format_metadata"),
        fallback_slug=projection.get("project_slug"),
        label=label,
        raw=raw,
        filename_suffix="-overlaid.json",
        description=f"Version {source_label} with overlays applied: {names}.",
        rest_job_id=f"overlay-apply-{project_id}",
        failure_code=CODE_APPLY_IMPORT_FAILED,
        failure_message="The overlaid document could not be imported",
    )
    detail = {
        "projectId": project_id,
        "sourceVersionId": version_record_id,
        "versionId": new_id,
        "versionLabel": label,
        "overlays": [{"id": row.id, "name": row.name, "contentFingerprint": row.content_fingerprint} for row in stored],
        "changeCount": changes,
        "resolvedFingerprint": preview.resolved_fingerprint,
    }
    try:
        db.insert_workflow_audit(tenant_id, None, None, AUDIT_OVERLAYS_APPLIED, "success", actor_id, detail)
    except Exception:  # noqa: BLE001 — an audit failure never fails the request.
        logger.exception("overlay apply audit write failed project=%s", project_id)
    return VersionOverlayApplyOut(
        project_id=project_id,
        version_record_id=new_id,
        version_label=label,
        source_version_record_id=version_record_id,
        overlay_count=len(stored),
        change_count=changes,
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
