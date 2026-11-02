"""``POST /v1/export/{tenant_slug}/avro/push`` — register an Avro export on a schema registry (MFX-19.4).

The route exports one version to Avro (``.avsc``, MFX-19.1/19.3), validates the export with the same
check every export runs (MFX-5.1, fastavro), then pushes each subject through an existing
``schema-registry`` connector — its base URL and stored credentials, over the connector's SSRF-guarded
client. :mod:`app.avro_registry_push` holds the plan and the registry calls.

Pushing writes to the upstream registry with the connector's credentials, so it needs ``imports:edit``
on the connector, the permission that changes the connector itself. A dry run reads only (lookup and
compatibility check) and needs the same permission, since it still uses the stored credentials. A
push that registered at least one subject writes a workflow-audit row.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import catalog_connector_store as store
from .auth import validate_authentication
from .avro_registry_push import AvroPushError, AvroPushSubjectResult, plan_avro_push, push_avro_subjects
from .catalog_connector_sync import unseal_connector_credentials
from .database import db
from .export_dispatch import dispatch_from_source
from .export_service import ExportError
from .export_source import ExportSourceError, load_export_source
from .export_validation import validate_emitted_artifact
from .permissions import Action, Resource, enforce_permission
from .schema_registry_connector_source import KIND as SCHEMA_REGISTRY_KIND
from .schema_registry_connector_source import SchemaRegistrySource
from .transcoding_guards import TranscodeGuardError

router = APIRouter(prefix="/v1/export", tags=["export"])

#: The workflow-audit action of a push that registered at least one subject.
AUDIT_AVRO_PUSH = "export.avro.pushed"

#: The statuses counted in a push's summary, in the order they are reported.
_STATUSES = ("registered", "already_registered", "would_register", "incompatible", "failed", "skipped")


class AvroPushRequest(BaseModel):
    """Which version to export to Avro, and the connector whose registry receives it."""

    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(description="The artifact (project) id to export.")
    version: Optional[str] = Field(
        default=None,
        description="Revision UUID, version label (``1.0.0``), or null for the latest revision.",
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Avro emit options (``namespace``, ``subject_naming``, ``topic``, ``subject_role``); "
        "``output_syntax`` must stay ``avsc``. Null applies the defaults.",
    )
    connector_id: UUID = Field(description="The ``schema-registry`` connector whose registry receives the push.")
    dry_run: bool = Field(
        default=False,
        description="Look up and check every subject against the registry, but register nothing.",
    )
    confirm: bool = Field(
        default=False,
        description="Push a **severe** conversion (MFX-3.3) the export guard would otherwise refuse.",
    )


class AvroPushResponse(BaseModel):
    """What the push did for each subject."""

    model_config = ConfigDict(extra="forbid")

    artifact: str = Field(description="The artifact (project) id exported.")
    version_record_id: str = Field(description="The resolved revision (``versions.id``).")
    version_label: Optional[str] = Field(default=None, description="The resolved revision's version label.")
    connector_id: str = Field(description="The connector pushed through.")
    registry_url: str = Field(description="The registry's base URL.")
    dry_run: bool = Field(description="Whether nothing was registered.")
    summary: Dict[str, int] = Field(
        description="How many subjects ended in each status (``registered``, ``already_registered``, "
        "``would_register``, ``incompatible``, ``failed``, ``skipped``).",
    )
    subjects: List[AvroPushSubjectResult] = Field(
        description="One result per subject, in the order they were pushed (referenced schemas first).",
    )


def _refuse(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _schema_registry_connector(tenant_id: str, connector_id: UUID) -> Dict[str, Any]:
    """The tenant's live ``schema-registry`` connector, or a 404 / 422."""
    connector = store.get_connector(db, tenant_id, str(connector_id))
    if connector is None:
        raise _refuse(404, "AVRO_PUSH_CONNECTOR_NOT_FOUND", "Connector not found.")
    if connector.get("kind") != SCHEMA_REGISTRY_KIND:
        raise _refuse(
            422,
            "AVRO_PUSH_CONNECTOR_KIND",
            f"Connector {connector.get('name')!r} is a {connector.get('kind')!r} connector; an Avro push "
            f"needs a {SCHEMA_REGISTRY_KIND!r} connector.",
        )
    return connector


@router.post(
    "/{tenant_slug}/avro/push",
    response_model=AvroPushResponse,
    summary="Register an Avro export on a schema registry through a connector",
    description=(
        "MFX-19.4: export one version to Avro (``.avsc``, one schema per type, each under the subject "
        "its naming strategy gives it), validate it with fastavro, then push each subject to the "
        "registry of an existing ``schema-registry`` connector, using the connector's base URL and stored "
        "credentials. Per subject, referenced schemas first: look the schema up (already registered → "
        "nothing written), check it against the subject's latest version under the subject's "
        "compatibility level (incompatible → not registered), then register it, with Confluent "
        "``references`` to the subjects of the types it names. ``dry_run`` does everything but register. "
        "The response gives each subject's status, schema id and version. Needs ``imports:edit``."
    ),
)
async def push_avro_export(
    tenant_slug: str,
    request: AvroPushRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AvroPushResponse:
    """Export a version to Avro and push its subjects to a connector's schema registry.

    Args:
        tenant_slug: The tenant slug.
        request: The version, the Avro options, the connector and ``dry_run``.
        auth_data: Authenticated tenant context (JWT or API key).

    Returns:
        The per-subject results and a count per status. Subjects the registry refused are results,
        not an error: the response is ``200`` whenever the push ran.

    Raises:
        HTTPException: 403 without ``imports:edit``; 404 when the connector or the artifact/version is
            unknown; 409 for a severe conversion not confirmed; 422 when the connector is not a
            ``schema-registry`` connector, its credential cannot be opened, the options are invalid or
            ask for ``avdl``, the export fails its check (``EMITTED_ARTIFACT_INVALID``), or two schemas
            share a subject (``AVRO_PUSH_DUPLICATE_SUBJECT``).
    """
    tenant_id = auth_data["tenant_id"]
    actor_id = enforce_permission(
        db, auth_data, Resource.IMPORTS, Action.EDIT, target=f"connector:{request.connector_id}"
    )
    connector = _schema_registry_connector(tenant_id, request.connector_id)
    if (request.options or {}).get("output_syntax", "avsc") != "avsc":
        raise _refuse(422, "AVRO_PUSH_NOT_AVSC", "A registry holds .avsc schemas; output_syntax must be 'avsc'.")
    credentials, unreadable = unseal_connector_credentials(db, str(connector["id"]))
    if unreadable:
        raise _refuse(
            422,
            "AVRO_PUSH_CREDENTIALS_UNREADABLE",
            "The connector's stored credential cannot be opened; replace it with PUT …/credentials.",
        )

    try:
        source = load_export_source(tenant_id, request.artifact, request.version)
    except ExportSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.http_detail()) from exc
    try:
        dispatch = dispatch_from_source(source, "avro", options=request.options, confirm=request.confirm)
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except TranscodeGuardError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.guard.message, "guard": exc.guard.model_dump(mode="json")},
        ) from exc
    if dispatch.emit is None:  # pragma: no cover - a real dispatch always emits
        raise _refuse(422, "AVRO_PUSH_EMPTY", "The Avro export wrote no schema to register.")

    validation = await validate_emitted_artifact(
        dispatch.target, dispatch.emit, api=source.api, options=request.options
    )
    if validation.failed:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EMITTED_ARTIFACT_INVALID",
                "message": "The Avro export failed its check; nothing was pushed.",
                "findings": [finding.model_dump(mode="json") for finding in validation.findings],
            },
        )

    try:
        units = plan_avro_push(dispatch.emit)
    except AvroPushError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.http_detail()) from exc

    registry = SchemaRegistrySource(connector, credentials)

    def push() -> List[AvroPushSubjectResult]:
        with registry.http_client() as client:
            return push_avro_subjects(
                client, registry.registry_url, units, dry_run=request.dry_run, credentials=credentials
            )

    results = await asyncio.to_thread(push)
    summary = {status: sum(1 for r in results if r.status == status) for status in _STATUSES}
    if summary["registered"]:
        db.insert_workflow_audit(
            tenant_id, None, None, AUDIT_AVRO_PUSH, "success", actor_id,
            {"connectorId": str(connector["id"]), "artifact": source.artifact_id,
             "versionRecordId": source.version_record_id,
             "subjects": [r.subject for r in results if r.status == "registered"]},
        )
    return AvroPushResponse(
        artifact=source.artifact_id,
        version_record_id=source.version_record_id,
        version_label=source.version_label,
        connector_id=str(connector["id"]),
        registry_url=registry.registry_url,
        dry_run=request.dry_run,
        summary=summary,
        subjects=results,
    )
