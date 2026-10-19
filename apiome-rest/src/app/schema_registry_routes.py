"""Schema subject model — Apiome REST routes (CDG-4.2, #5974).

Tenant-scoped routes over the V294 subject model, under ``/v1/tenants/{tenant_slug}/schema-registry``:

* ``GET|PUT /config`` — the tenant's default compatibility level and mode;
* ``GET /subjects`` — live subjects; ``GET|PUT|DELETE /subjects/{subject}`` — one subject, its
  settings (strategy, compatibility level, mode), soft delete;
* ``GET /subjects/{subject}/versions`` and ``…/versions/{version}`` (a number or ``latest``);
* ``POST /subjects/{subject}/versions`` — register a schema (idempotent on its fingerprint);
* ``POST /subjects/{subject}/attach`` — back an empty subject with an existing catalog item;
* ``GET /schemas/ids/{id}`` — resolve a schema id, even after its subjects were deleted.

Permissions: reads need ``imports:view``; register, attach and settings ``imports:create`` /
``imports:edit``; delete ``imports:delete``. The Confluent-compatible wire API is CDG-4.3 (#5975);
compatibility verdicts are not computed here.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from . import schema_registry_store as store
from .auth import validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .schema_registry import (
    COMPATIBILITY_LEVELS,
    MODES,
    STRATEGIES,
    SchemaRegistryError,
    normalize_choice,
    validate_subject_name,
)
from .schema_registry_service import attach_catalog_item, register_schema, schema_text

router = APIRouter(prefix="/v1/tenants", tags=["schema-registry"])

_BASE = "/{tenant_slug}/schema-registry"


class _CamelModel(BaseModel):
    """Wire base: snake_case fields, camelCase JSON."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class RegistryConfig(_CamelModel):
    """The tenant's registry defaults."""

    compatibility_level: str = Field(description="Default compatibility level for subjects that set none.")
    mode: str = Field(description="`READWRITE` or `READONLY`; `READONLY` refuses every new version.")


class RegistryConfigUpdate(_CamelModel):
    """A change to the tenant's registry defaults; an omitted field is kept."""

    compatibility_level: Optional[str] = Field(default=None, description="One of the seven Confluent levels.")
    mode: Optional[str] = Field(default=None, description="`READWRITE` or `READONLY`.")


class SubjectSettings(_CamelModel):
    """Create a subject or change its settings; an omitted field is kept."""

    strategy: Optional[str] = Field(default=None, description="`topic`, `record` or `topic_record`.")
    compatibility_level: Optional[str] = Field(
        default=None, description="This subject's level; unset means the tenant default."
    )
    mode: Optional[str] = Field(default=None, description="`READWRITE` or `READONLY`.")


class SubjectOut(_CamelModel):
    """A schema subject."""

    name: str
    strategy: Optional[str] = None
    compatibility_level: Optional[str] = Field(default=None, description="`null` = the tenant default.")
    effective_compatibility_level: str = Field(description="This subject's level, else the tenant default.")
    mode: str
    project_id: Optional[str] = Field(default=None, description="The catalog item new versions are registered into.")
    version_count: int = 0
    latest_version: Optional[int] = None
    created_at: datetime
    updated_at: datetime


class SubjectList(_CamelModel):
    """The tenant's live subjects, by name."""

    subjects: List[SubjectOut]


class SubjectVersionOut(_CamelModel):
    """One version of a subject: a schema id and the catalog item revision that holds it."""

    subject: str
    version: int
    id: int = Field(description="The schema id (shared by every subject holding the same schema).")
    schema_type: str
    fingerprint: str
    references: List[Any] = Field(default_factory=list)
    project_id: str = Field(description="The catalog item holding the schema.")
    version_record_id: str = Field(description="The catalog item revision holding the schema.")
    created_at: datetime
    schema_text: Optional[str] = Field(
        default=None, alias="schema", description="The schema text (single-version reads only)."
    )


class SubjectVersionList(_CamelModel):
    """A subject's live versions, oldest first."""

    subject: str
    versions: List[SubjectVersionOut]


class RegisterRequest(_CamelModel):
    """A schema to register under a subject."""

    schema_text: str = Field(alias="schema", description="The schema text (Avro JSON, JSON Schema or .proto).")
    schema_type: str = Field(default="AVRO", description="`AVRO` (default), `JSON` or `PROTOBUF`.")
    references: List[Any] = Field(default_factory=list, description="Schema references, stored as sent.")
    strategy: Optional[str] = Field(default=None, description="Naming strategy for a subject this creates.")


class RegisterResponse(SubjectVersionOut):
    """The registered version; ``created`` is ``false`` when the subject already held this schema."""

    created: bool


class AttachRequest(_CamelModel):
    """An existing catalog item to back an empty subject."""

    project_id: str = Field(description="The catalog item id (an Avro, JSON Schema or Protobuf item).")
    strategy: Optional[str] = Field(default=None, description="Naming strategy for a subject this creates.")


class SchemaSubjectRef(_CamelModel):
    """A live subject version holding a schema id."""

    subject: str
    version: int


class SchemaByIdOut(_CamelModel):
    """A schema resolved by id."""

    id: int
    schema_type: str
    fingerprint: str
    fingerprint_kind: str = Field(description="`canonical-model` today; `avro-pcf` once MFI-12.1 ships.")
    references: List[Any] = Field(default_factory=list)
    project_id: str
    version_record_id: str
    schema_text: Optional[str] = Field(default=None, alias="schema")
    subjects: List[SchemaSubjectRef] = Field(
        default_factory=list, description="Live subject versions holding it (empty once all are deleted)."
    )


def _tenant_id(auth_data: Mapping[str, Any]) -> str:
    """The authenticated tenant id, or a 403."""
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for the schema registry.")
    return str(tenant_id)


def _http(exc: SchemaRegistryError) -> HTTPException:
    """Map a registry refusal onto its HTTP status."""
    return HTTPException(status_code=exc.status_code, detail=exc.as_detail())


def _require_subject(tenant_id: str, subject: str) -> Dict[str, Any]:
    """Return the live subject or raise ``404 subject-not-found``."""
    try:
        validate_subject_name(subject)
    except SchemaRegistryError as exc:
        raise _http(exc) from exc
    row = store.get_subject(db, tenant_id, subject)
    if row is None:
        raise _http(SchemaRegistryError("subject-not-found", f"Subject {subject!r} not found.", status_code=404))
    return row


def _subject_out(row: Mapping[str, Any], tenant_level: str) -> SubjectOut:
    """Project a subject row."""
    return SubjectOut(
        name=row["name"],
        strategy=row.get("strategy"),
        compatibility_level=row.get("compatibility_level"),
        effective_compatibility_level=row.get("compatibility_level") or tenant_level,
        mode=row["mode"],
        project_id=str(row["project_id"]) if row.get("project_id") else None,
        version_count=int(row.get("version_count") or 0),
        latest_version=row.get("latest_version"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _version_out(subject: str, row: Mapping[str, Any], *, text: Optional[str] = None) -> Dict[str, Any]:
    """Project a version row to its wire fields (snake_case; the model aliases them)."""
    return {
        "subject": subject,
        "version": int(row["version"]),
        "id": int(row["schema_id"]),
        "schema_type": row["schema_type"],
        "fingerprint": row["fingerprint"],
        "references": list(row.get("references") or []),
        "project_id": str(row["project_id"]),
        "version_record_id": str(row["version_record_id"]),
        "created_at": row["created_at"],
        "schema_text": text,
    }


@router.get(_BASE + "/config", response_model=RegistryConfig, response_model_by_alias=True)
async def get_registry_config(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> RegistryConfig:
    """Return the tenant's registry defaults (``imports:view``)."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target="schema-registry")
    return RegistryConfig(**store.get_config(db, tenant_id))


@router.put(_BASE + "/config", response_model=RegistryConfig, response_model_by_alias=True)
async def put_registry_config(
    tenant_slug: str,
    body: RegistryConfigUpdate,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegistryConfig:
    """Set the tenant's default compatibility level and/or mode (``imports:edit``)."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.EDIT, target="schema-registry")
    try:
        level = normalize_choice(body.compatibility_level, COMPATIBILITY_LEVELS, field="compatibilityLevel")
        mode = normalize_choice(body.mode, MODES, field="mode")
    except SchemaRegistryError as exc:
        raise _http(exc) from exc
    return RegistryConfig(**store.put_config(db, tenant_id, compatibility_level=level, mode=mode))


@router.get(_BASE + "/subjects", response_model=SubjectList, response_model_by_alias=True)
async def list_schema_subjects(
    tenant_slug: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> SubjectList:
    """List the tenant's live subjects (``imports:view``); deleted subjects are left out."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target="schema-registry")
    level = store.get_config(db, tenant_id)["compatibility_level"]
    return SubjectList(subjects=[_subject_out(r, level) for r in store.list_subjects(db, tenant_id)])


@router.get(_BASE + "/subjects/{subject}", response_model=SubjectOut, response_model_by_alias=True)
async def get_schema_subject(
    tenant_slug: str, subject: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> SubjectOut:
    """Return one live subject (``imports:view``)."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target=f"subject:{subject}")
    row = _require_subject(tenant_id, subject)
    versions = store.list_versions(db, str(row["id"]))
    row = {**row, "version_count": len(versions), "latest_version": versions[-1]["version"] if versions else None}
    return _subject_out(row, store.get_config(db, tenant_id)["compatibility_level"])


@router.put(_BASE + "/subjects/{subject}", response_model=SubjectOut, response_model_by_alias=True)
async def put_schema_subject(
    tenant_slug: str,
    subject: str,
    body: SubjectSettings,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SubjectOut:
    """Create a subject or change its strategy, compatibility level or mode (``imports:edit``)."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.EDIT, target=f"subject:{subject}")
    try:
        validate_subject_name(subject)
        strategy = normalize_choice(body.strategy, STRATEGIES, field="strategy")
        level = normalize_choice(body.compatibility_level, COMPATIBILITY_LEVELS, field="compatibilityLevel")
        mode = normalize_choice(body.mode, MODES, field="mode")
    except SchemaRegistryError as exc:
        raise _http(exc) from exc
    row = store.upsert_subject(
        db, tenant_id, subject, strategy=strategy, compatibility_level=level, mode=mode, actor_id=actor_id
    )
    versions = store.list_versions(db, str(row["id"]))
    row = {**row, "version_count": len(versions), "latest_version": versions[-1]["version"] if versions else None}
    return _subject_out(row, store.get_config(db, tenant_id)["compatibility_level"])


@router.delete(_BASE + "/subjects/{subject}", response_model=List[int])
async def delete_schema_subject(
    tenant_slug: str, subject: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> List[int]:
    """Soft-delete a subject and its versions (``imports:delete``); returns the deleted versions.

    The versions leave every list, but their schema ids keep resolving at ``/schemas/ids/{id}``
    and the catalog item revisions are untouched.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.DELETE, target=f"subject:{subject}")
    deleted = store.soft_delete_subject(db, tenant_id, subject)
    if deleted is None:
        raise _http(SchemaRegistryError("subject-not-found", f"Subject {subject!r} not found.", status_code=404))
    return deleted


@router.get(
    _BASE + "/subjects/{subject}/versions", response_model=SubjectVersionList, response_model_by_alias=True
)
async def list_schema_subject_versions(
    tenant_slug: str, subject: str, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> SubjectVersionList:
    """List a subject's live versions, oldest first (``imports:view``)."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target=f"subject:{subject}")
    row = _require_subject(tenant_id, subject)
    return SubjectVersionList(
        subject=subject,
        versions=[SubjectVersionOut(**_version_out(subject, v)) for v in store.list_versions(db, str(row["id"]))],
    )


@router.get(
    _BASE + "/subjects/{subject}/versions/{version}",
    response_model=SubjectVersionOut,
    response_model_by_alias=True,
)
async def get_schema_subject_version(
    tenant_slug: str,
    subject: str,
    version: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SubjectVersionOut:
    """Return one version (a number or ``latest``) with its schema text (``imports:view``)."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target=f"subject:{subject}")
    row = _require_subject(tenant_id, subject)
    if version == "latest":
        versions = store.list_versions(db, str(row["id"]))
        found = versions[-1] if versions else None
    elif version.isdigit() and int(version) >= 1:
        found = store.get_version(db, str(row["id"]), int(version))
    else:
        raise _http(SchemaRegistryError("version-invalid", "A version is a positive integer or `latest`."))
    if found is None:
        raise _http(SchemaRegistryError("version-not-found", f"Version {version} not found.", status_code=404))
    text = await asyncio.to_thread(schema_text, db, found["version_record_id"])
    return SubjectVersionOut(**_version_out(subject, found, text=text))


@router.post(
    _BASE + "/subjects/{subject}/versions",
    response_model=RegisterResponse,
    response_model_by_alias=True,
)
async def register_schema_version(
    tenant_slug: str,
    subject: str,
    body: RegisterRequest = Body(...),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegisterResponse:
    """Register a schema under a subject (``imports:create``).

    The schema is read by the same import source a catalog upload uses. Registering content the
    subject already holds returns its version (``created: false``); content another subject holds
    reuses that schema id and revision; new content becomes a new revision of the subject's catalog
    item (created on the first registration).
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.CREATE, target=f"subject:{subject}")
    try:
        row = await asyncio.to_thread(
            register_schema,
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            subject=subject,
            schema=body.schema_text,
            schema_type=body.schema_type,
            references=body.references,
            strategy=body.strategy,
        )
    except SchemaRegistryError as exc:
        raise _http(exc) from exc
    return RegisterResponse(**_version_out(subject, row), created=bool(row.get("created")))


@router.post(
    _BASE + "/subjects/{subject}/attach",
    response_model=RegisterResponse,
    response_model_by_alias=True,
)
async def attach_catalog_item_to_subject(
    tenant_slug: str,
    subject: str,
    body: AttachRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegisterResponse:
    """Back an empty subject with an existing catalog item (``imports:edit``).

    The item's latest revision becomes version 1; its earlier revisions stay as they are, and later
    registrations add revisions to the item.
    """
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    actor_id = enforce_permission(db, auth_data, Resource.IMPORTS, Action.EDIT, target=f"subject:{subject}")
    try:
        row = await asyncio.to_thread(
            attach_catalog_item,
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            subject=subject,
            project_id=body.project_id,
            strategy=body.strategy,
        )
    except SchemaRegistryError as exc:
        raise _http(exc) from exc
    return RegisterResponse(**_version_out(subject, row), created=bool(row.get("created")))


@router.get(
    _BASE + "/schemas/ids/{schema_id}", response_model=SchemaByIdOut, response_model_by_alias=True
)
async def get_schema_by_id(
    tenant_slug: str, schema_id: int, auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> SchemaByIdOut:
    """Resolve a schema id (``imports:view``) — it keeps resolving after its subjects are deleted."""
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW, target=f"schema:{schema_id}")
    row = store.get_schema_by_id(db, tenant_id, schema_id)
    if row is None:
        raise _http(SchemaRegistryError("schema-not-found", f"Schema id {schema_id} not found.", status_code=404))
    text = await asyncio.to_thread(schema_text, db, row["version_record_id"])
    return SchemaByIdOut(
        id=int(row["schema_id"]),
        schema_type=row["schema_type"],
        fingerprint=row["fingerprint"],
        fingerprint_kind=row["fingerprint_kind"],
        references=list(row.get("references") or []),
        project_id=str(row["project_id"]),
        version_record_id=str(row["version_record_id"]),
        schema_text=text,
        subjects=[SchemaSubjectRef(**s) for s in row.get("subjects") or []],
    )
