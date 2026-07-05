"""Fidelity report REST surfacing — ``/export/targets`` + ``/export/preview`` — MFX-2.5 (#3842).

Two granularities the export UX needs *before* a download is committed:

* **``GET /v1/export/{tenant_slug}/targets?artifact=&version=``** — for the given source
  revision, every registered target's descriptor + capability profile + options (the emitter
  registry's public view, MFX-1.2) **plus** a cheap per-target fidelity badge: a
  :class:`~app.export_fidelity.ExportFidelityTier` (``lossless`` / ``lossy`` / ``types-only``)
  and a ``preserved_percent`` estimate, computed from the prediction engine with no emit. This
  drives the export dialog's target-card badges (MFX-6.1) and the version-view pre-summary
  (MFX-6.5) in one round-trip.

* **``POST /v1/export/{tenant_slug}/preview``** — for one chosen ``target``, the full
  :class:`~app.export_fidelity.ExportFidelity` envelope: the per-construct
  :class:`~app.lossiness.LossinessReport`, the user-facing advisory (MFX-2.4), and the tier
  summary — again **without emitting an artifact**. It backs the dialog's detailed fidelity
  panel and is the same envelope an export job embeds in its result (MFX-3.1/3.2).

* **``POST /v1/export/{tenant_slug}/document``** — for one chosen ``target``, the emitted
  document itself, produced through the Emitter SPI (:func:`app.export_service.emit_canonical`)
  and serialized as JSON (default) or YAML (``Accept: application/yaml``). This is the emit
  counterpart to ``/preview``: ``/preview`` predicts the loss, ``/document`` returns the bytes.
  It gives non-OpenAPI targets (AsyncAPI, MFX-11.5) a byte source the legacy OpenAPI browse
  reconstruction (``GET /v1/schema/…``) cannot supply, and the ``apiome export <target>`` CLI
  pairs it with ``/preview`` to write the artifact and surface its honest fidelity.

All three endpoints are tenant-scoped (JWT or API key, via :func:`app.auth.validate_authentication`)
and load the source model version-scoped through :func:`app.export_source.load_export_source`.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .emitter import (
    CapabilityProfile,
    EmitterDescriptor,
    describe_emit_targets,
    get_emitter,
)
from .export_fidelity import (
    ExportFidelity,
    TargetFidelity,
    build_export_fidelity,
    build_target_fidelity,
)
from .export_service import ExportError, emit_canonical, resolve_emitter
from .export_source import ExportSourceError, load_export_source
from .lossiness import LossinessSeverity

router = APIRouter(prefix="/v1/export", tags=["export"])


# ===========================================================================
# Response / request models
# ===========================================================================


class ExportTargetFidelity(BaseModel):
    """One registered target's descriptor + options + its per-source fidelity badge (MFX-2.5).

    The union of the emitter registry's public view (descriptor, capability profile, options
    schema + defaults — MFX-1.1/1.4) and the cheap fidelity summary for the requested source
    (:class:`~app.export_fidelity.TargetFidelity` — tier + preserved-%), so a single
    ``/export/targets`` call gives the export dialog everything a target card needs.
    """

    model_config = ConfigDict(extra="forbid")

    descriptor: EmitterDescriptor
    capability_profile: CapabilityProfile
    options_schema: Dict[str, Any] = Field(
        description="JSON Schema for this target's per-emit options (MFX-1.4).",
    )
    default_options: Dict[str, Any] = Field(
        description="Validated default option values for this target (MFX-1.4).",
    )
    fidelity: TargetFidelity = Field(
        description="Cheap tier + preserved-% badge for exporting the requested source here.",
    )


class ExportTargetsResponse(BaseModel):
    """The per-target fidelity list for one source revision (MFX-2.5)."""

    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(description="The artifact (project) id the fidelity was computed for.")
    version: Optional[str] = Field(
        default=None, description="The version selector as requested (label, UUID, or null)."
    )
    version_record_id: str = Field(description="The resolved revision (``versions.id``).")
    version_label: Optional[str] = Field(
        default=None, description="The resolved revision's version label (e.g. ``1.0.0``)."
    )
    targets: List[ExportTargetFidelity] = Field(
        default_factory=list,
        description="Every registered target with its per-source fidelity, sorted by target key.",
    )


class ExportPreviewRequest(BaseModel):
    """A dry-run fidelity preview request: source revision + chosen target (MFX-2.5)."""

    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(description="The artifact (project) id to export.")
    version: Optional[str] = Field(
        default=None,
        description="Revision UUID, version label (``1.0.0``), or null for the latest revision.",
    )
    target: str = Field(
        description="Target emitter key (``openapi``) or format key (``openapi-3.1``).",
    )
    min_severity: LossinessSeverity = Field(
        default=LossinessSeverity.INFO,
        description="Lowest loss severity that raises the advisory (MFX-2.4); does not affect "
        "the report or counts.",
    )


class ExportPreviewResponse(BaseModel):
    """The dry-run fidelity preview: the full envelope + the resolved source coordinates (MFX-2.5)."""

    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(description="The artifact (project) id the preview was computed for.")
    version: Optional[str] = Field(
        default=None, description="The version selector as requested (label, UUID, or null)."
    )
    version_record_id: str = Field(description="The resolved revision (``versions.id``).")
    version_label: Optional[str] = Field(
        default=None, description="The resolved revision's version label (e.g. ``1.0.0``)."
    )
    fidelity: ExportFidelity = Field(
        description="The full fidelity envelope (target + tier + report + advisory), no artifact.",
    )


class ExportDocumentRequest(BaseModel):
    """An emit request: source revision + chosen target + per-emit options (MFX-11.5)."""

    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(description="The artifact (project) id to export.")
    version: Optional[str] = Field(
        default=None,
        description="Revision UUID, version label (``1.0.0``), or null for the latest revision.",
    )
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


@router.get(
    "/{tenant_slug}/targets",
    response_model=ExportTargetsResponse,
    summary="List export targets with per-source fidelity",
    description=(
        "For the given source artifact/version, enumerate every registered export target "
        "(descriptor + capability profile + options) with a cheap per-target fidelity badge "
        "(tier + preserved-%), computed from the prediction engine without emitting an "
        "artifact. Drives the export dialog's card badges (MFX-6.1) and the version pre-summary "
        "(MFX-6.5)."
    ),
)
async def list_export_targets(
    tenant_slug: str,
    artifact: str = Query(..., description="The artifact (project) id to export."),
    version: Optional[str] = Query(
        None,
        description="Revision UUID, version label (``1.0.0``), or omitted for the latest revision.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportTargetsResponse:
    """Return every export target with its per-source fidelity badge.

    Args:
        tenant_slug: The tenant slug (scopes the artifact lookup).
        artifact: The artifact (project) id whose source model fidelity is measured against.
        version: The revision to measure (UUID or label); the latest revision when omitted.
        auth_data: Authenticated tenant context (JWT or API key).

    Returns:
        The per-target fidelity list for the resolved source revision.

    Raises:
        HTTPException: 404 when the artifact/version is unknown; 422 when the revision has no
            reconstructable source; 400 when the source format cannot be adapted.
    """
    tenant_id = auth_data["tenant_id"]
    try:
        source = load_export_source(tenant_id, artifact, version)
    except ExportSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    entries: List[ExportTargetFidelity] = []
    for target in describe_emit_targets():
        emitter_cls = get_emitter(target.descriptor.format)
        if emitter_cls is None:  # pragma: no cover - registry/describe are always in sync
            continue
        entries.append(
            ExportTargetFidelity(
                descriptor=target.descriptor,
                capability_profile=target.capability_profile,
                options_schema=target.options_schema,
                default_options=target.default_options,
                fidelity=build_target_fidelity(source.api, emitter_cls),
            )
        )

    return ExportTargetsResponse(
        artifact=source.artifact_id,
        version=version,
        version_record_id=source.version_record_id,
        version_label=source.version_label,
        targets=entries,
    )


@router.post(
    "/{tenant_slug}/preview",
    response_model=ExportPreviewResponse,
    summary="Preview export fidelity for one target",
    description=(
        "Compute the full fidelity report for exporting the given source artifact/version to "
        "one target — the per-construct LossinessReport, the user-facing advisory (MFX-2.4), and "
        "the tier summary — **without producing the artifact**. Backs the export dialog's "
        "detailed fidelity panel; the same envelope is embedded in an export job result."
    ),
)
async def preview_export_fidelity(
    tenant_slug: str,
    request: ExportPreviewRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportPreviewResponse:
    """Return the full fidelity envelope for one (source, target) export, emitting nothing.

    Args:
        tenant_slug: The tenant slug (scopes the artifact lookup).
        request: The source coordinates + chosen target + advisory threshold.
        auth_data: Authenticated tenant context (JWT or API key).

    Returns:
        The dry-run preview: the full :class:`~app.export_fidelity.ExportFidelity` envelope plus
        the resolved source coordinates.

    Raises:
        HTTPException: 404 when the artifact/version is unknown; 422 when the revision has no
            reconstructable source; 400 when the target or source format is unsupported.
    """
    tenant_id = auth_data["tenant_id"]
    try:
        source = load_export_source(tenant_id, request.artifact, request.version)
    except ExportSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    try:
        emitter_cls = type(resolve_emitter(request.target))
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    fidelity = build_export_fidelity(
        source.api, emitter_cls, min_severity=request.min_severity
    )
    return ExportPreviewResponse(
        artifact=source.artifact_id,
        version=request.version,
        version_record_id=source.version_record_id,
        version_label=source.version_label,
        fidelity=fidelity,
    )


# Accept-header tokens that select YAML serialization of the emitted document.
_YAML_ACCEPT_TOKENS = ("application/yaml", "application/x-yaml", "text/yaml", "text/x-yaml")


def _wants_yaml(accept: Optional[str]) -> bool:
    """True when the ``Accept`` header requests a YAML serialization of the document."""
    header = (accept or "").lower()
    return any(token in header for token in _YAML_ACCEPT_TOKENS)


def _document_filename(base_path: str, *, yaml_serialization: bool) -> str:
    """Derive the download filename from the emitted file's path, honouring the serialization.

    ``base_path`` is the emitter's primary file path (e.g. ``asyncapi.json``); when the caller
    asked for YAML we swap the extension so a saved artifact keeps an honest suffix.
    """
    name = (base_path or "document").rsplit("/", 1)[-1]
    if yaml_serialization:
        stem = name.rsplit(".", 1)[0] if "." in name else name
        return f"{stem}.yaml"
    return name


@router.post(
    "/{tenant_slug}/document",
    summary="Emit the export document for one target",
    description=(
        "Emit the source artifact/version to one ``target`` through the Emitter SPI and return "
        "the document itself — JSON by default, YAML when ``Accept: application/yaml`` is sent. "
        "This is the emit counterpart to ``/preview`` (which predicts the loss without emitting); "
        "the ``apiome export <target>`` CLI pairs the two to write the artifact and surface its "
        "fidelity. Gives non-OpenAPI targets (AsyncAPI) a byte source the OpenAPI-only browse "
        "reconstruction cannot supply."
    ),
    response_class=Response,
)
async def emit_export_document(
    tenant_slug: str,
    request: ExportDocumentRequest,
    accept: Optional[str] = Header(None),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Emit and return the export document for one (source, target) pair.

    Args:
        tenant_slug: The tenant slug (scopes the artifact lookup).
        request: The source coordinates + chosen target + optional per-emit options.
        accept: Accept header for JSON/YAML content negotiation.
        auth_data: Authenticated tenant context (JWT or API key).

    Returns:
        The emitted document, serialized as JSON (default) or YAML, with a ``Content-Disposition``
        filename derived from the emitter's primary output path.

    Raises:
        HTTPException: 404 when the artifact/version is unknown; 422 when the revision has no
            reconstructable source or the emitter produced no document; 400 when the target,
            source format, or options are unsupported.
    """
    tenant_id = auth_data["tenant_id"]
    try:
        source = load_export_source(tenant_id, request.artifact, request.version)
    except ExportSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    try:
        result = emit_canonical(source.api, request.target, opts=request.options)
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if not result.files:  # pragma: no cover - registered emitters always produce a file
        raise HTTPException(
            status_code=422,
            detail=f"Target {request.target!r} produced no document for this source.",
        )

    primary = result.files[0]
    content = primary.content
    yaml_serialization = _wants_yaml(accept)
    filename = _document_filename(primary.path, yaml_serialization=yaml_serialization)
    disposition = {"Content-Disposition": f'attachment; filename="{filename}"'}

    # Structured (dict) documents serialize to the requested wire format; a plain-text bundle
    # (rare, non-JSON/YAML targets) is returned verbatim under its own media type.
    if isinstance(content, dict):
        if yaml_serialization:
            body = yaml.dump(content, sort_keys=False, default_flow_style=False)
            return Response(
                content=body, media_type="application/x-yaml", headers=disposition
            )
        body = json.dumps(content, indent=2, ensure_ascii=False)
        return Response(
            content=body,
            media_type=primary.media_type or result.media_type or "application/json",
            headers=disposition,
        )

    return Response(
        content=str(content),
        media_type=primary.media_type or result.media_type or "text/plain",
        headers=disposition,
    )
