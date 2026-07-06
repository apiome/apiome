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

* **``POST /v1/export/{tenant_slug}/dispatch``** — the "run it, attach the fidelity report" step
  (MFX-3.2) in one round-trip: emit the chosen ``target`` **and** return its full fidelity
  envelope together. Where ``/preview`` predicts the loss and ``/document`` returns only the
  bytes, ``/dispatch`` returns both — the synchronous, one-shot twin of submitting an export
  job (``POST …/jobs``) and polling it, without the poll. Intended for small artifacts and the
  ``apiome export`` CLI; large or toolchain-backed exports still use the async job. ``dry_run``
  stops after the report (no artifact), the same shape ``/preview`` returns.

All endpoints are tenant-scoped (JWT or API key, via :func:`app.auth.validate_authentication`)
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
from .export_dispatch import dispatch_export
from .export_fidelity import (
    ExportFidelity,
    TargetFidelity,
    build_export_fidelity,
    build_target_fidelity,
)
from .export_service import ExportError, ExportPersistenceContext, emit_canonical, resolve_emitter
from .export_source import ExportSourceError, load_export_source
from .lossiness import LossinessSeverity
from .transcoding_guards import TranscodeGuard, TranscodeGuardError, classify_transcode

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
    guard: TranscodeGuard = Field(
        description="The pre-flight transcoding guard (MFX-3.3): the conversion band "
        "(clean / lossy / near-empty / severe), whether it needs an explicit confirmation, and "
        "why. Lets the UI/CLI warn (near-empty) or prompt for confirmation (severe) before "
        "dispatching the export.",
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


class ExportDispatchRequest(BaseModel):
    """A dispatch request: source revision + chosen target + options + dry-run flag (MFX-3.2)."""

    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(description="The artifact (project) id to export.")
    version: Optional[str] = Field(
        default=None,
        description="Revision UUID, version label (``1.0.0``), or null for the latest revision.",
    )
    target: str = Field(
        description="Target emitter key (``openapi``) or format key (``openapi-3.1``).",
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Per-target emit options (MFX-1.4); null or empty applies the target defaults.",
    )
    dry_run: bool = Field(
        default=False,
        description="When true, stop after the fidelity report: no artifact is emitted.",
    )
    confirm: bool = Field(
        default=False,
        description="When true, proceed with a **severe** conversion (MFX-3.3) the transcoding "
        "guard would otherwise block with 409. Ignored for non-severe conversions and dry-runs.",
    )
    min_severity: LossinessSeverity = Field(
        default=LossinessSeverity.INFO,
        description="Lowest loss severity that raises the advisory (MFX-2.4); does not affect "
        "the report or counts.",
    )


class ExportDispatchFile(BaseModel):
    """One emitted file returned inline by the dispatch surface (MFX-3.2).

    Unlike the async job's metadata-only manifest (the bytes are served later by MFX-4.x),
    a synchronous dispatch returns the ``content`` inline — there is no job to poll and no
    separate download step.
    """

    model_config = ConfigDict(extra="forbid")

    path: str = Field(description="Relative path within the output bundle.")
    content: Any = Field(description="The emitted file's content (structured document or text).")
    media_type: Optional[str] = Field(
        default=None, description="Per-file media type when it differs from the bundle default."
    )
    subject: Optional[str] = Field(
        default=None,
        description="Schema Registry subject when the target assigns one (e.g. Avro).",
    )


class ExportDispatchResponse(BaseModel):
    """The dispatch result: resolved coordinates + fidelity envelope + emitted artifact (MFX-3.2)."""

    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(description="The artifact (project) id the dispatch exported.")
    version: Optional[str] = Field(
        default=None, description="The version selector as requested (label, UUID, or null)."
    )
    version_record_id: str = Field(description="The resolved revision (``versions.id``).")
    version_label: Optional[str] = Field(
        default=None, description="The resolved revision's version label (e.g. ``1.0.0``)."
    )
    target: str = Field(description="The resolved target format key (e.g. ``openapi-3.1``).")
    dry_run: bool = Field(description="True when the dispatch stopped after the fidelity report.")
    fidelity: ExportFidelity = Field(
        description="The full fidelity envelope (target + tier + report + advisory).",
    )
    guard: TranscodeGuard = Field(
        description="The pre-flight transcoding guard (MFX-3.3): the conversion band and why. "
        "A severe conversion only reaches a real (non-dry-run) dispatch when ``confirm`` was set.",
    )
    files: List[ExportDispatchFile] = Field(
        default_factory=list,
        description="The emitted files (inline); empty for a dry-run.",
    )
    media_type: Optional[str] = Field(
        default=None,
        description="The bundle's primary media type; null for a dry-run.",
    )


# ===========================================================================
# Shared route helpers
# ===========================================================================


def build_target_fidelity_entries(api: Any) -> List[ExportTargetFidelity]:
    """Enumerate every registered export target with its per-source fidelity badge.

    The shared body of every ``…/targets`` route (authenticated and public browse alike):
    walk the emitter registry's public view and pair each target's descriptor/profile/options
    with the cheap :func:`~app.export_fidelity.build_target_fidelity` badge for ``api``.

    Args:
        api: The source :class:`~app.canonical_model.CanonicalApi` fidelity is measured against.

    Returns:
        One :class:`ExportTargetFidelity` per registered target, in registry (key) order.
    """
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
                fidelity=build_target_fidelity(api, emitter_cls),
            )
        )
    return entries


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

    entries = build_target_fidelity_entries(source.api)

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
    # Classify the conversion off the envelope's report so the preview and the eventual
    # dispatch/job agree, and the UI knows up front whether it must confirm (MFX-3.3).
    guard = classify_transcode(source.api, emitter_cls, report=fidelity.report)
    return ExportPreviewResponse(
        artifact=source.artifact_id,
        version=request.version,
        version_record_id=source.version_record_id,
        version_label=source.version_label,
        fidelity=fidelity,
        guard=guard,
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


def render_emitted_document(
    api: Any,
    target: str,
    options: Optional[Dict[str, Any]],
    accept: Optional[str],
    *,
    persistence: Optional[ExportPersistenceContext] = None,
) -> Response:
    """Emit ``api`` to ``target`` and wrap the primary file as an HTTP download response.

    The shared tail of every ``…/document`` route (authenticated and public browse alike):
    run the Emitter SPI, pick the primary emitted file, serialize it as JSON (default) or YAML
    (when ``accept`` asks for it), and attach a ``Content-Disposition`` filename derived from
    the emitter's output path.

    Args:
        api: The source :class:`~app.canonical_model.CanonicalApi` to emit.
        target: Target emitter key (``asyncapi``) or format key (``asyncapi-3``).
        options: Per-target emit options; ``None``/empty applies the target defaults.
        accept: The request's ``Accept`` header, for JSON/YAML content negotiation.
        persistence: Optional field-identity persistence context; ``None`` keeps the emit
            fully read-only (the public path must never write).

    Returns:
        The emitted document as a download :class:`~fastapi.Response`.

    Raises:
        HTTPException: 400 when the target or options are unsupported; 422 when the emitter
            produced no document.
    """
    try:
        result = emit_canonical(api, target, opts=options, persistence=persistence)
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    if not result.files:  # pragma: no cover - registered emitters always produce a file
        raise HTTPException(
            status_code=422,
            detail=f"Target {target!r} produced no document for this source.",
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

    return render_emitted_document(
        source.api,
        request.target,
        request.options,
        accept,
        persistence=ExportPersistenceContext(
            tenant_id=tenant_id,
            artifact_id=source.artifact_id,
        ),
    )


@router.post(
    "/{tenant_slug}/dispatch",
    response_model=ExportDispatchResponse,
    summary="Dispatch an export: emit one target and attach its fidelity report",
    description=(
        "The one-shot transcode (MFX-3.2): load the source artifact/version, resolve the target "
        "emitter, run it, and return the emitted document **together with** its full fidelity "
        "envelope (report + advisory + summary). The synchronous twin of submitting an export job "
        "and polling it — for small artifacts and the ``apiome export`` CLI; large or "
        "toolchain-backed exports should use ``POST …/jobs``. ``dry_run: true`` stops after the "
        "fidelity report (no artifact), the same shape ``POST …/preview`` returns."
    ),
)
async def dispatch_export_document(
    tenant_slug: str,
    request: ExportDispatchRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportDispatchResponse:
    """Emit one (source, target) pair and return the artifact alongside its fidelity report.

    Args:
        tenant_slug: The tenant slug (scopes the artifact lookup).
        request: Source coordinates + chosen target + optional per-emit options + dry-run flag.
        auth_data: Authenticated tenant context (JWT or API key).

    Returns:
        The dispatch result: resolved coordinates, the full fidelity envelope, and — for a real
        (non-dry-run) export — the emitted files inline.

    Raises:
        HTTPException: 404 when the artifact/version is unknown; 422 when the revision has no
            reconstructable source or the emitter produced no document; 400 when the target or
            source format is unsupported; 422 when the emit options are invalid for the target;
            409 when the conversion is severe (MFX-3.3) and ``confirm`` was not set.
    """
    tenant_id = str(auth_data["tenant_id"])
    try:
        dispatch = dispatch_export(
            tenant_id,
            request.artifact,
            request.version,
            request.target,
            options=request.options,
            min_severity=request.min_severity,
            dry_run=request.dry_run,
            confirm=request.confirm,
        )
    except ExportSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except TranscodeGuardError as exc:
        # A severe conversion the caller did not confirm: 409 with the guard so the client can
        # render the confirmation prompt and retry with ``confirm: true`` (MFX-3.3).
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.guard.message, "guard": exc.guard.model_dump(mode="json")},
        ) from exc

    files: List[ExportDispatchFile] = []
    media_type: Optional[str] = None
    if dispatch.emit is not None:
        media_type = dispatch.emit.media_type
        files = [
            ExportDispatchFile(
                path=f.path,
                content=f.content,
                media_type=f.media_type,
                subject=f.subject,
            )
            for f in dispatch.emit.files
        ]

    return ExportDispatchResponse(
        artifact=dispatch.artifact,
        version=request.version,
        version_record_id=dispatch.version_record_id,
        version_label=dispatch.version_label,
        target=dispatch.target,
        dry_run=dispatch.dry_run,
        fidelity=dispatch.fidelity,
        guard=dispatch.guard,
        files=files,
        media_type=media_type,
    )
