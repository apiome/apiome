"""``POST /v1/export/{tenant_slug}/avro/push`` — register an Avro export on a schema registry (MFX-19.4).

The route exports one version to Avro (``.avsc``, MFX-19.1/19.3), validates the export with the same
check every export runs (MFX-5.1, fastavro), then pushes each subject through an existing
``schema-registry`` connector — its base URL and stored credentials, over the connector's SSRF-guarded
client. It runs the pipeline every format's push shares,
:func:`app.schema_registry_push_routes.run_registry_push` (MFX-19.6), whose
``/schema-registry/push`` route pushes JSON Schema and Protobuf too; :mod:`app.avro_registry_push`
holds the Avro plan.

Pushing writes to the upstream registry with the connector's credentials, so it needs ``imports:edit``
on the connector, the permission that changes the connector itself. A dry run reads only (lookup and
compatibility check) and needs the same permission, since it still uses the stored credentials. A
push that registered at least one subject writes a workflow-audit row.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .avro_registry_push import AvroPushSubjectResult
from .database import db
from .permissions import Action, Resource, enforce_permission
from .schema_registry_push import CompatibilityLevel
from .schema_registry_push_routes import REGISTRY_FORMATS, run_registry_push

router = APIRouter(prefix="/v1/export", tags=["export"])

#: The workflow-audit action of a push that registered at least one subject.
AUDIT_AVRO_PUSH = "export.avro.pushed"


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
    compatibility_level: Optional[CompatibilityLevel] = Field(
        default=None,
        description="A Confluent compatibility level to set on each subject the push registers, before its "
        "check (MFX-19.6). Null keeps each subject's level. A dry run sets nothing.",
    )
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
    if (request.options or {}).get("output_syntax", "avsc") != "avsc":
        raise _refuse(422, "AVRO_PUSH_NOT_AVSC", "A registry holds .avsc schemas; output_syntax must be 'avsc'.")
    outcome = await run_registry_push(
        tenant_id=tenant_id,
        actor_id=actor_id,
        spec=REGISTRY_FORMATS["avro"],
        artifact=request.artifact,
        version=request.version,
        options=request.options,
        connector_id=request.connector_id,
        compatibility_level=request.compatibility_level,
        dry_run=request.dry_run,
        confirm=request.confirm,
        code_prefix="AVRO_PUSH",
    )
    return AvroPushResponse(
        artifact=outcome.source.artifact_id,
        version_record_id=outcome.source.version_record_id,
        version_label=outcome.source.version_label,
        connector_id=outcome.connector_id,
        registry_url=outcome.registry_url,
        dry_run=request.dry_run,
        summary=outcome.summary,
        subjects=outcome.results,
    )
