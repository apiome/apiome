"""``POST /v1/export/{tenant_slug}/schema-registry/push`` — push Avro, JSON Schema or Protobuf (MFX-19.6).

A Confluent-compatible schema registry holds Avro, JSON Schema and Protobuf subjects. This route
exports one version to the format asked for, validates the export with the same check every export
runs (MFX-5.1), then pushes each subject through an existing ``schema-registry`` connector — its
base URL and stored credentials, over the connector's SSRF-guarded client.

The subject naming (``subject_naming``, ``topic``, ``subject_role``) is the same for every format
(:mod:`app.schema_registry_subjects`); ``compatibility_level`` sets each subject's Confluent level
before its check. :func:`run_registry_push` is the pipeline both this route and the Avro-only route
(``/avro/push``, MFX-19.4) run; :mod:`app.schema_registry_push` holds the registry calls.

Pushing writes to the upstream registry with the connector's credentials, so it needs ``imports:edit``
on the connector. A dry run reads only and needs the same permission, since it still uses the stored
credentials. A push that registered at least one subject writes a workflow-audit row.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import catalog_connector_store as store
from .auth import validate_authentication
from .avro_registry_push import plan_avro_push, to_registry_units
from .catalog_connector_sync import unseal_connector_credentials
from .database import db
from .emitter import EmitResult
from .export_dispatch import dispatch_from_source
from .export_service import ExportError
from .export_source import ExportSource, ExportSourceError, load_export_source
from .export_validation import validate_emitted_artifact
from .permissions import Action, Resource, enforce_permission
from .schema_registry_connector_source import KIND as SCHEMA_REGISTRY_KIND
from .schema_registry_connector_source import SchemaRegistrySource
from .schema_registry_push import (
    CompatibilityLevel,
    RegistryPushError,
    RegistryPushSubjectResult,
    RegistryPushUnit,
    push_registry_subjects,
)
from .schema_registry_push_plans import plan_jsonschema_push, plan_protobuf_push
from .schema_registry_subjects import SubjectNaming, SubjectRole
from .transcoding_guards import TranscodeGuardError

router = APIRouter(prefix="/v1/export", tags=["export"])

#: The statuses counted in a push's summary, in the order they are reported.
PUSH_STATUSES = ("registered", "already_registered", "would_register", "incompatible", "failed", "skipped")

#: The formats a registry holds, by request value.
RegistryFormat = Literal["avro", "json-schema", "protobuf"]

#: The Avro emit options that name subjects; on this route they are request fields instead.
_SUBJECT_OPTIONS = ("subject_naming", "topic", "subject_role")


@dataclass(frozen=True)
class RegistryFormatSpec:
    """How one format is exported and planned for a push.

    Attributes:
        emitter: The export target's emitter key.
        label: The format's name in messages.
        article: ``a`` or ``an``, for "an Avro push".
        audit_action: The workflow-audit action of a push that registered something.
        plan: ``(emit, naming, topic, role) -> units``, dependencies first.
    """

    emitter: str
    label: str
    article: str
    audit_action: str
    plan: Callable[[EmitResult, str, Optional[str], str], List[RegistryPushUnit]]


def _plan_avro(emit: EmitResult, naming: str, topic: Optional[str], role: str) -> List[RegistryPushUnit]:
    # The Avro emitter names subjects itself, from the options the route passed it.
    return to_registry_units(plan_avro_push(emit))


#: Each format a push takes.
REGISTRY_FORMATS: Dict[str, RegistryFormatSpec] = {
    "avro": RegistryFormatSpec("avro", "Avro", "an", "export.avro.pushed", _plan_avro),
    "json-schema": RegistryFormatSpec(
        "json-schema", "JSON Schema", "a", "export.json_schema.pushed",
        lambda emit, naming, topic, role: plan_jsonschema_push(emit, naming=naming, topic=topic, role=role),
    ),
    "protobuf": RegistryFormatSpec(
        "proto3", "Protobuf", "a", "export.protobuf.pushed",
        lambda emit, naming, topic, role: plan_protobuf_push(emit, naming=naming, topic=topic, role=role),
    ),
}


class RegistryPushRequest(BaseModel):
    """Which version to export, in which format, and the connector whose registry receives it."""

    model_config = ConfigDict(extra="forbid")

    format: RegistryFormat = Field(description="The schema format to push: ``avro``, ``json-schema`` or ``protobuf``.")
    artifact: str = Field(description="The artifact (project) id to export.")
    version: Optional[str] = Field(
        default=None,
        description="Revision UUID, version label (``1.0.0``), or null for the latest revision.",
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="The format's emit options. Avro: ``output_syntax`` must stay ``avsc``, and subjects "
        "are named by the request fields, not ``options``. JSON Schema: ``packaging`` defaults to "
        "``per-type`` (one subject per type) and ``mode`` must stay ``json-schema``. Null applies the defaults.",
    )
    connector_id: UUID = Field(description="The ``schema-registry`` connector whose registry receives the push.")
    subject_naming: SubjectNaming = Field(
        default="record_name",
        description="``record_name`` (``{record}-value``, one subject per schema), ``topic_name`` "
        "(``{topic}-value``) or ``topic_record_name`` (``{topic}-{record}-value``). The record is the "
        "Avro full name, the JSON Schema ``title``, or the Protobuf file's first message.",
    )
    topic: Optional[str] = Field(
        default=None, description="The Kafka topic of ``topic_name`` and ``topic_record_name``."
    )
    subject_role: SubjectRole = Field(
        default="value", description="``value`` ends each subject in ``-value``, ``key`` in ``-key``."
    )
    compatibility_level: Optional[CompatibilityLevel] = Field(
        default=None,
        description="A Confluent compatibility level to set on each subject the push registers, before its "
        "check (``BACKWARD``, ``FULL_TRANSITIVE``, ``NONE`` …). Null keeps each subject's level. A dry run "
        "sets nothing.",
    )
    dry_run: bool = Field(
        default=False,
        description="Look up and check every subject against the registry, but write nothing.",
    )
    confirm: bool = Field(
        default=False,
        description="Push a **severe** conversion (MFX-3.3) the export guard would otherwise refuse.",
    )

    @model_validator(mode="after")
    def _topic_for_topic_strategies(self) -> "RegistryPushRequest":
        """A topic strategy needs a non-empty ``topic``."""
        if self.subject_naming != "record_name" and not (self.topic or "").strip():
            raise ValueError("topic is required when subject_naming is topic_name or topic_record_name")
        return self


class RegistryPushResponse(BaseModel):
    """What the push did for each subject."""

    model_config = ConfigDict(extra="forbid")

    format: RegistryFormat = Field(description="The schema format pushed.")
    artifact: str = Field(description="The artifact (project) id exported.")
    version_record_id: str = Field(description="The resolved revision (``versions.id``).")
    version_label: Optional[str] = Field(default=None, description="The resolved revision's version label.")
    connector_id: str = Field(description="The connector pushed through.")
    registry_url: str = Field(description="The registry's base URL.")
    dry_run: bool = Field(description="Whether nothing was written.")
    summary: Dict[str, int] = Field(
        description="How many subjects ended in each status (``registered``, ``already_registered``, "
        "``would_register``, ``incompatible``, ``failed``, ``skipped``).",
    )
    subjects: List[RegistryPushSubjectResult] = Field(
        description="One result per subject, in the order they were pushed (referenced schemas first).",
    )


@dataclass(frozen=True)
class RegistryPushOutcome:
    """What :func:`run_registry_push` did, for the route to answer with."""

    source: ExportSource
    connector_id: str
    registry_url: str
    summary: Dict[str, int]
    results: List[RegistryPushSubjectResult]


def _refuse(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _schema_registry_connector(tenant_id: str, connector_id: UUID, prefix: str, label: str) -> Dict[str, Any]:
    """The tenant's live ``schema-registry`` connector, or a 404 / 422."""
    connector = store.get_connector(db, tenant_id, str(connector_id))
    if connector is None:
        raise _refuse(404, f"{prefix}_CONNECTOR_NOT_FOUND", "Connector not found.")
    if connector.get("kind") != SCHEMA_REGISTRY_KIND:
        raise _refuse(
            422,
            f"{prefix}_CONNECTOR_KIND",
            f"Connector {connector.get('name')!r} is a {connector.get('kind')!r} connector; {label} push "
            f"needs a {SCHEMA_REGISTRY_KIND!r} connector.",
        )
    return connector


async def run_registry_push(
    *,
    tenant_id: str,
    actor_id: Optional[str],
    spec: RegistryFormatSpec,
    artifact: str,
    version: Optional[str],
    options: Optional[Dict[str, Any]],
    connector_id: UUID,
    naming: str = "record_name",
    topic: Optional[str] = None,
    role: str = "value",
    compatibility_level: Optional[str] = None,
    dry_run: bool = False,
    confirm: bool = False,
    code_prefix: str = "REGISTRY_PUSH",
) -> RegistryPushOutcome:
    """Export a version, check it, and push its subjects to a connector's schema registry.

    Args:
        tenant_id: The tenant.
        actor_id: Who pushes, for the audit row.
        spec: The format (:data:`REGISTRY_FORMATS`).
        artifact: The artifact (project) id.
        version: Revision UUID, version label, or ``None`` for the latest.
        options: The format's emit options, already adjusted for a registry by the route.
        connector_id: The ``schema-registry`` connector.
        naming: The subject naming strategy (the Avro emitter reads it from ``options`` instead).
        topic: The Kafka topic of a topic strategy.
        role: ``value`` or ``key``.
        compatibility_level: A Confluent level to set on each subject registered, or ``None``.
        dry_run: Check everything, write nothing.
        confirm: Push a severe conversion.
        code_prefix: The prefix of the connector refusals' codes (``AVRO_PUSH`` on the Avro route).

    Returns:
        The source, the registry and the per-subject results.

    Raises:
        HTTPException: 404 for an unknown connector or artifact/version; 409 for a severe conversion not
            confirmed; 422 for a connector of another kind, an unreadable credential, invalid options, an
            export that fails its check (``EMITTED_ARTIFACT_INVALID``) or a plan the registry cannot hold.
    """
    connector = _schema_registry_connector(tenant_id, connector_id, code_prefix, f"{spec.article} {spec.label}")
    credentials, unreadable = unseal_connector_credentials(db, str(connector["id"]))
    if unreadable:
        raise _refuse(
            422,
            f"{code_prefix}_CREDENTIALS_UNREADABLE",
            "The connector's stored credential cannot be opened; replace it with PUT …/credentials.",
        )

    try:
        source = load_export_source(tenant_id, artifact, version)
    except ExportSourceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.http_detail()) from exc
    try:
        dispatch = dispatch_from_source(source, spec.emitter, options=options, confirm=confirm)
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except TranscodeGuardError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.guard.message, "guard": exc.guard.model_dump(mode="json")},
        ) from exc
    if dispatch.emit is None:  # pragma: no cover - a real dispatch always emits
        raise _refuse(422, f"{code_prefix}_EMPTY", f"The {spec.label} export wrote no schema to register.")

    validation = await validate_emitted_artifact(dispatch.target, dispatch.emit, api=source.api, options=options)
    if validation.failed:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "EMITTED_ARTIFACT_INVALID",
                "message": f"The {spec.label} export failed its check; nothing was pushed.",
                "findings": [finding.model_dump(mode="json") for finding in validation.findings],
            },
        )

    try:
        units = spec.plan(dispatch.emit, naming, topic, role)
    except RegistryPushError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.http_detail()) from exc

    registry = SchemaRegistrySource(connector, credentials)

    def push() -> List[RegistryPushSubjectResult]:
        with registry.http_client() as client:
            return push_registry_subjects(
                client, registry.registry_url, units, dry_run=dry_run,
                compatibility_level=compatibility_level, credentials=credentials,
            )

    results = await asyncio.to_thread(push)
    summary = {status: sum(1 for r in results if r.status == status) for status in PUSH_STATUSES}
    if summary["registered"]:
        db.insert_workflow_audit(
            tenant_id, None, None, spec.audit_action, "success", actor_id,
            {"connectorId": str(connector["id"]), "artifact": source.artifact_id,
             "versionRecordId": source.version_record_id,
             "subjects": [r.subject for r in results if r.status == "registered"]},
        )
    return RegistryPushOutcome(
        source=source,
        connector_id=str(connector["id"]),
        registry_url=registry.registry_url,
        summary=summary,
        results=results,
    )


def _registry_options(request: RegistryPushRequest) -> Optional[Dict[str, Any]]:
    """The emit options a registry can hold, or a 422 for options it cannot.

    Avro gets the request's subject naming as its options (the Avro emitter names subjects); JSON
    Schema defaults to one document per type and refuses JTD.
    """
    options = dict(request.options or {})
    if request.format == "avro":
        if options.get("output_syntax", "avsc") != "avsc":
            raise _refuse(
                422, "REGISTRY_PUSH_NOT_AVSC", "A registry holds .avsc schemas; output_syntax must be 'avsc'."
            )
        named = [key for key in _SUBJECT_OPTIONS if key in options]
        if named:
            raise _refuse(
                422,
                "REGISTRY_PUSH_SUBJECT_OPTIONS",
                f"Set {', '.join(named)} on the request, not in options: subjects are named the same way "
                "for every format.",
            )
        options.update(subject_naming=request.subject_naming, subject_role=request.subject_role)
        if request.topic is not None:
            options["topic"] = request.topic
    elif request.format == "json-schema":
        if options.get("mode", "json-schema") != "json-schema":
            raise _refuse(
                422,
                "REGISTRY_PUSH_NOT_JSON_SCHEMA",
                "A registry holds JSON Schema documents; mode must be 'json-schema', not JSON Type Definition.",
            )
        options.setdefault("packaging", "per-type")
    return options or None


@router.post(
    "/{tenant_slug}/schema-registry/push",
    response_model=RegistryPushResponse,
    summary="Register an Avro, JSON Schema or Protobuf export on a schema registry through a connector",
    description=(
        "MFX-19.6: export one version to ``avro`` (``.avsc``), ``json-schema`` (one document per type by "
        "default) or ``protobuf`` (one ``.proto`` per package), validate it, then push each schema to the "
        "registry of an existing ``schema-registry`` connector with its ``schemaType`` (``AVRO``, ``JSON``, "
        "``PROTOBUF``), using the connector's base URL and stored credentials. Subjects are named the same "
        "way for every format (``subject_naming``, ``topic``, ``subject_role``). Per subject, referenced "
        "schemas first: look the schema up (already registered → nothing written), set "
        "``compatibility_level`` when asked, check it against the subject's latest version (incompatible → "
        "not registered), then register it, with Confluent ``references`` to the subjects it names. "
        "``dry_run`` writes nothing. Needs ``imports:edit``."
    ),
)
async def push_registry_export(
    tenant_slug: str,
    request: RegistryPushRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegistryPushResponse:
    """Export a version to Avro, JSON Schema or Protobuf and push its subjects to a connector's registry.

    Args:
        tenant_slug: The tenant slug.
        request: The format, version, options, subject naming, compatibility level, connector and ``dry_run``.
        auth_data: Authenticated tenant context (JWT or API key).

    Returns:
        The per-subject results and a count per status. Subjects the registry refused are results, not
        an error: the response is ``200`` whenever the push ran.

    Raises:
        HTTPException: 403 without ``imports:edit``; 404, 409 and 422 as :func:`run_registry_push`
            raises them; 422 for options a registry cannot take (``REGISTRY_PUSH_NOT_AVSC``,
            ``REGISTRY_PUSH_NOT_JSON_SCHEMA``, ``REGISTRY_PUSH_SUBJECT_OPTIONS``) or a plan it cannot
            hold (``REGISTRY_PUSH_DUPLICATE_SUBJECT``, ``REGISTRY_PUSH_REFERENCE_CYCLE``,
            ``REGISTRY_PUSH_NO_RECORD``).
    """
    tenant_id = auth_data["tenant_id"]
    actor_id = enforce_permission(
        db, auth_data, Resource.IMPORTS, Action.EDIT, target=f"connector:{request.connector_id}"
    )
    options = _registry_options(request)
    outcome = await run_registry_push(
        tenant_id=tenant_id,
        actor_id=actor_id,
        spec=REGISTRY_FORMATS[request.format],
        artifact=request.artifact,
        version=request.version,
        options=options,
        connector_id=request.connector_id,
        naming=request.subject_naming,
        topic=request.topic,
        role=request.subject_role,
        compatibility_level=request.compatibility_level,
        dry_run=request.dry_run,
        confirm=request.confirm,
    )
    return RegistryPushResponse(
        format=request.format,
        artifact=outcome.source.artifact_id,
        version_record_id=outcome.source.version_record_id,
        version_label=outcome.source.version_label,
        connector_id=outcome.connector_id,
        registry_url=outcome.registry_url,
        dry_run=request.dry_run,
        summary=outcome.summary,
        subjects=outcome.results,
    )
