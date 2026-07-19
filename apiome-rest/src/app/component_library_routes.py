"""Operational component library REST API — DCW-3.1 (private-suite#2353).

The tenant-scoped library of reusable operational components (parameters,
headers, request bodies, responses, security bundles, and Type-Registry-pinned
schemas) with the minimal MVP lifecycle:

* ``GET/POST  /v1/component-library/{tenant_slug}/components`` — list/create.
* ``GET/DELETE /v1/component-library/{tenant_slug}/components/{component_id}``
  — detail (with revisions) / soft delete (blocked while pinned).
* ``POST /…/components/{component_id}/revisions`` — new draft revision.
* ``PUT/DELETE /…/revisions/{revision_id}`` — edit/delete a draft
  (published revisions are immutable and answer 409).
* ``POST /…/revisions/{revision_id}/publish`` — authorized draft→publish with
  the no-unsafe-downgrade rule; idempotent for already-published revisions.
* ``GET/POST /…/projects/{project_id}/versions/{version_record_id}/pins`` and
  ``DELETE …/pins/{pin_id}`` — a draft version pins one published revision;
  library-head changes never mutate pinned versions.
* ``GET …/materialization`` — the deterministic single-file materialization
  preview: final local component names, requested names, and collisions.
  Collisions never overwrite local components.

Authorization: reads require any authenticated tenant member; library
mutations require TYPES create/edit/publish/delete and pin mutations require
VERSIONS edit. Scope misses answer 404 (not 403) so cross-tenant probes
cannot confirm a component, revision, or version exists. Every mutation and
its audit row commit in one transaction (DCW-0.2
``failure-injection-no-partial-mutation``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .auth import get_authenticated_user_id, validate_authentication
from .component_library import (
    COMPONENT_KINDS,
    materialize_pinned_components,
    parse_semver,
    payload_digest,
    validate_component_name,
    validate_component_payload,
)
from .database import ComponentLibraryConflictError, db
from .openapi_generator import generate_openapi_spec
from .permissions import Action, Resource, enforce_permission

router = APIRouter(prefix="/v1/component-library", tags=["component-library"])


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ===========================================================================
# Request / response models
# ===========================================================================


class RevisionBody(_CamelModel):
    """One component revision on the wire."""

    id: str
    revision: str = Field(description="Semver revision string (MAJOR.MINOR.PATCH).")
    state: str = Field(description="draft | published (published is immutable).")
    canonical_payload: Any = Field(
        default=None, description="The canonical OAS fragment this revision materializes."
    )
    schema_primitive_id: Optional[str] = Field(
        default=None,
        description="Schema kind: the pinned Type Registry (primitives) row.",
    )
    payload_digest: str = Field(description="sha256:<hex> of the canonical payload.")
    published_at: Optional[str] = None
    created_at: Optional[str] = None


class ComponentSummaryBody(_CamelModel):
    """One component in the list response."""

    id: str
    name: str
    kind: str
    description: Optional[str] = None
    owner_id: Optional[str] = None
    revision_count: int = 0
    published_count: int = 0
    head_revision: Optional[str] = Field(
        default=None, description="Highest published semver, or null while draft-only."
    )


class ComponentDetailBody(ComponentSummaryBody):
    """Component detail: the summary plus its revisions, highest semver first."""

    revisions: List[RevisionBody] = Field(default_factory=list)


class ComponentListResponse(_CamelModel):
    components: List[ComponentSummaryBody] = Field(default_factory=list)


class InitialRevisionBody(_CamelModel):
    """The initial draft revision created with a new component."""

    revision: str = Field(default="0.1.0", description="Initial semver revision.")
    payload: Any = Field(
        default=None,
        description="Canonical OAS fragment (ignored for schema kind — the "
        "pinned Type Registry schema is snapshotted server-side).",
    )
    schema_primitive_id: Optional[str] = Field(
        default=None, description="Schema kind: the Type Registry row to pin."
    )


class ComponentCreateRequest(_CamelModel):
    """Create a component plus its initial draft revision."""

    name: str = Field(description="Stable library name (component-key safe).")
    kind: str = Field(description="parameter | header | requestBody | response | securityBundle | schema")
    description: Optional[str] = None
    owner_id: Optional[str] = Field(
        default=None, description="Accountable member; defaults to the creator."
    )
    initial_revision: InitialRevisionBody = Field(default_factory=InitialRevisionBody)


class ComponentCreateResponse(_CamelModel):
    component_id: str
    revision_id: str


class RevisionCreateRequest(_CamelModel):
    """Create a new draft revision of an existing component."""

    revision: str = Field(description="Semver revision string, unique per component.")
    payload: Any = Field(default=None)
    schema_primitive_id: Optional[str] = None


class RevisionUpdateRequest(_CamelModel):
    """Replace a draft revision's canonical payload."""

    payload: Any = Field(default=None)
    schema_primitive_id: Optional[str] = None


class RevisionMutationResponse(_CamelModel):
    revision_id: str


class PublishResponse(_CamelModel):
    published: bool
    already_published: bool
    revision: str


class DeletedResponse(_CamelModel):
    deleted: bool


class PinBody(_CamelModel):
    """One live pin joined to its component/revision identity."""

    id: str
    component_id: str
    component_name: str
    kind: str
    revision_id: str
    revision: str
    payload_digest: str
    local_name: Optional[str] = None


class PinListResponse(_CamelModel):
    pins: List[PinBody] = Field(default_factory=list)


class PinCreateRequest(_CamelModel):
    """Pin one published library revision to the draft version."""

    component_revision_id: str
    local_name: Optional[str] = Field(
        default=None,
        description="Optional preferred local components key; collisions still "
        "resolve deterministically and never overwrite local components.",
    )


class PinCreateResponse(_CamelModel):
    pin_id: str


class MaterializationEntryBody(_CamelModel):
    """One deterministic materialization entry (final name + collision flag)."""

    section: str
    name: str
    requested_name: str
    collided: bool
    component_id: str
    revision_id: str
    component_name: str
    revision: str


class MaterializationPreviewResponse(_CamelModel):
    """The deterministic preview of materializing the version's pins."""

    include_origin: bool
    entries: List[MaterializationEntryBody] = Field(default_factory=list)
    collisions: List[MaterializationEntryBody] = Field(default_factory=list)


class PayloadValidationErrorBody(_CamelModel):
    """422 body: structured payload errors, nothing mutated."""

    code: str = Field(default="COMPONENT_PAYLOAD_INVALID")
    errors: List[Dict[str, str]] = Field(default_factory=list)


# ===========================================================================
# Helpers
# ===========================================================================

_CONFLICT_MESSAGES = {
    "duplicate_component": "A live component with this kind and name already exists.",
    "duplicate_revision": "This revision already exists for the component.",
    "duplicate_pin": "The version already pins this revision.",
    "published_immutable": "Published revisions are immutable.",
    "revision_downgrade": "Publishing must move the component's published head forward "
    "(no unsafe downgrades).",
    "revision_not_published": "Only published revisions can be pinned.",
    "component_in_use": "The component is pinned by project versions and cannot be deleted.",
    "revision_in_use": "The revision is pinned by project versions and cannot be deleted.",
    "published_version": "Published project revisions are immutable; pin changes target "
    "an authorized draft.",
}

_NOT_FOUND_CODES = {
    "component_not_found": "Component not found",
    "revision_not_found": "Component revision not found",
    "version_not_found": "Version not found",
    "pin_not_found": "Pin not found",
}


def _raise_conflict(error: ComponentLibraryConflictError) -> None:
    """Map a transactional conflict to its HTTP response (404/409/422)."""
    if error.code in _NOT_FOUND_CODES:
        raise HTTPException(status_code=404, detail=_NOT_FOUND_CODES[error.code])
    if error.code in ("schema_ref_required", "schema_ref_not_found"):
        raise HTTPException(
            status_code=422,
            detail={
                "code": error.code.upper(),
                "message": "Schema-kind components pin an existing Type Registry entry; "
                "operational kinds must not.",
                **error.payload,
            },
        )
    raise HTTPException(
        status_code=409,
        detail={
            "code": error.code.upper(),
            "message": _CONFLICT_MESSAGES.get(error.code, error.code),
            **error.payload,
        },
    )


def _component_or_404(tenant_id: str, component_id: str) -> Dict[str, Any]:
    """Tenant-scoped component row, or 404 (never 403 — do not leak existence)."""
    component = db.get_operational_component(tenant_id, component_id)
    if not component:
        raise HTTPException(status_code=404, detail="Component not found")
    return component


def _version_or_404(tenant_id: str, project_id: str, version_record_id: str) -> Dict[str, Any]:
    """Tenant-scoped version row, or 404 (never 403 — do not leak existence)."""
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version or str(version.get("project_id")) != str(project_id):
        raise HTTPException(status_code=404, detail="Version not found")
    return version


def _validate_payload_or_422(kind: str, payload: Any) -> None:
    """Reject structurally invalid payloads with the structured 422 body."""
    errors = validate_component_payload(kind, payload)
    if errors:
        raise HTTPException(
            status_code=422,
            detail=PayloadValidationErrorBody(errors=errors).model_dump(by_alias=True),
        )


def _validate_semver_or_422(revision: str) -> None:
    if parse_semver(revision) is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "REVISION_SEMVER_INVALID",
                "message": "Revisions are semver strings (MAJOR.MINOR.PATCH).",
            },
        )


def _revision_body(row: Dict[str, Any]) -> RevisionBody:
    return RevisionBody(
        id=str(row["id"]),
        revision=str(row["revision"]),
        state=str(row["state"]),
        canonical_payload=row.get("canonical_payload"),
        schema_primitive_id=(
            str(row["schema_primitive_id"]) if row.get("schema_primitive_id") else None
        ),
        payload_digest=str(row.get("payload_digest") or ""),
        published_at=str(row["published_at"]) if row.get("published_at") else None,
        created_at=str(row["created_at"]) if row.get("created_at") else None,
    )


def _summary_body(row: Dict[str, Any]) -> ComponentSummaryBody:
    return ComponentSummaryBody(
        id=str(row["id"]),
        name=str(row["name"]),
        kind=str(row["kind"]),
        description=row.get("description"),
        owner_id=str(row["owner_id"]) if row.get("owner_id") else None,
        revision_count=int(row.get("revision_count") or 0),
        published_count=int(row.get("published_count") or 0),
        head_revision=row.get("head_revision"),
    )


# ===========================================================================
# Library components
# ===========================================================================


@router.get(
    "/{tenant_slug}/components",
    response_model=ComponentListResponse,
    response_model_by_alias=True,
)
async def list_components(
    tenant_slug: str,
    kind: Optional[str] = Query(default=None),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ComponentListResponse:
    """List the tenant's live library components with publication summary."""
    if kind is not None and kind not in COMPONENT_KINDS:
        raise HTTPException(status_code=422, detail={"code": "COMPONENT_KIND_INVALID"})
    rows = db.list_operational_components(auth_data["tenant_id"], kind)
    return ComponentListResponse(components=[_summary_body(row) for row in rows])


@router.post(
    "/{tenant_slug}/components",
    response_model=ComponentCreateResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_component(
    tenant_slug: str,
    body: ComponentCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ComponentCreateResponse:
    """Create a component and its initial draft revision (TYPES/CREATE)."""
    enforce_permission(db, auth_data, Resource.TYPES, Action.CREATE)
    if body.kind not in COMPONENT_KINDS:
        raise HTTPException(status_code=422, detail={"code": "COMPONENT_KIND_INVALID"})
    if not validate_component_name(body.name):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "COMPONENT_NAME_INVALID",
                "message": "Component names start with a letter and use only "
                "letters, digits, '_', '.', and '-' (max 128 chars).",
            },
        )
    _validate_semver_or_422(body.initial_revision.revision)
    payload = body.initial_revision.payload
    if body.kind != "schema":
        _validate_payload_or_422(body.kind, payload)
    actor_id = get_authenticated_user_id(auth_data)
    try:
        result = db.create_operational_component(
            auth_data["tenant_id"],
            name=body.name,
            kind=body.kind,
            description=body.description,
            owner_id=body.owner_id,
            revision=body.initial_revision.revision,
            payload=payload if isinstance(payload, dict) else {},
            payload_digest=payload_digest(payload if isinstance(payload, dict) else {}),
            schema_primitive_id=body.initial_revision.schema_primitive_id,
            actor_id=actor_id,
        )
    except ComponentLibraryConflictError as error:
        _raise_conflict(error)
    return ComponentCreateResponse(
        component_id=result["componentId"], revision_id=result["revisionId"]
    )


@router.get(
    "/{tenant_slug}/components/{component_id}",
    response_model=ComponentDetailBody,
    response_model_by_alias=True,
)
async def get_component(
    tenant_slug: str,
    component_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ComponentDetailBody:
    """One component with its revisions, highest semver first."""
    tenant_id = auth_data["tenant_id"]
    component = _component_or_404(tenant_id, component_id)
    revisions = db.get_component_revisions(tenant_id, component_id)
    published = [
        r["revision"] for r in revisions
        if r.get("state") == "published" and parse_semver(r.get("revision"))
    ]
    summary = dict(component)
    summary["revision_count"] = len(revisions)
    summary["published_count"] = len(published)
    summary["head_revision"] = max(published, key=parse_semver) if published else None
    return ComponentDetailBody(
        **_summary_body(summary).model_dump(),
        revisions=[_revision_body(row) for row in revisions],
    )


@router.delete(
    "/{tenant_slug}/components/{component_id}",
    response_model=DeletedResponse,
    response_model_by_alias=True,
)
async def delete_component(
    tenant_slug: str,
    component_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeletedResponse:
    """Soft-delete a component (TYPES/DELETE); blocked while pinned (409)."""
    enforce_permission(db, auth_data, Resource.TYPES, Action.DELETE)
    actor_id = get_authenticated_user_id(auth_data)
    try:
        db.delete_operational_component(auth_data["tenant_id"], component_id, actor_id)
    except ComponentLibraryConflictError as error:
        _raise_conflict(error)
    return DeletedResponse(deleted=True)


# ===========================================================================
# Revisions (draft → publish lifecycle)
# ===========================================================================


@router.post(
    "/{tenant_slug}/components/{component_id}/revisions",
    response_model=RevisionMutationResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_revision(
    tenant_slug: str,
    component_id: str,
    body: RevisionCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RevisionMutationResponse:
    """Add a draft revision to a component (TYPES/EDIT)."""
    enforce_permission(db, auth_data, Resource.TYPES, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    component = _component_or_404(tenant_id, component_id)
    _validate_semver_or_422(body.revision)
    if component["kind"] != "schema":
        _validate_payload_or_422(str(component["kind"]), body.payload)
    actor_id = get_authenticated_user_id(auth_data)
    try:
        result = db.create_component_revision(
            tenant_id,
            component_id,
            revision=body.revision,
            payload=body.payload if isinstance(body.payload, dict) else {},
            payload_digest=payload_digest(
                body.payload if isinstance(body.payload, dict) else {}
            ),
            schema_primitive_id=body.schema_primitive_id,
            actor_id=actor_id,
        )
    except ComponentLibraryConflictError as error:
        _raise_conflict(error)
    return RevisionMutationResponse(revision_id=result["revisionId"])


@router.put(
    "/{tenant_slug}/components/{component_id}/revisions/{revision_id}",
    response_model=RevisionMutationResponse,
    response_model_by_alias=True,
)
async def update_revision(
    tenant_slug: str,
    component_id: str,
    revision_id: str,
    body: RevisionUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RevisionMutationResponse:
    """Replace a draft revision's payload (TYPES/EDIT); published answers 409."""
    enforce_permission(db, auth_data, Resource.TYPES, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    component = _component_or_404(tenant_id, component_id)
    if component["kind"] != "schema":
        _validate_payload_or_422(str(component["kind"]), body.payload)
    actor_id = get_authenticated_user_id(auth_data)
    try:
        result = db.update_component_revision(
            tenant_id,
            component_id,
            revision_id,
            payload=body.payload if isinstance(body.payload, dict) else {},
            payload_digest=payload_digest(
                body.payload if isinstance(body.payload, dict) else {}
            ),
            schema_primitive_id=body.schema_primitive_id,
            actor_id=actor_id,
        )
    except ComponentLibraryConflictError as error:
        _raise_conflict(error)
    return RevisionMutationResponse(revision_id=result["revisionId"])


@router.post(
    "/{tenant_slug}/components/{component_id}/revisions/{revision_id}/publish",
    response_model=PublishResponse,
    response_model_by_alias=True,
)
async def publish_revision(
    tenant_slug: str,
    component_id: str,
    revision_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PublishResponse:
    """Publish a draft revision (TYPES/PUBLISH) — immutable from then on.

    Enforces the no-unsafe-downgrade rule inside the transaction: the revision
    must be strictly greater than the highest already-published revision.
    Republishing a published revision is an idempotent no-op.
    """
    enforce_permission(db, auth_data, Resource.TYPES, Action.PUBLISH)
    actor_id = get_authenticated_user_id(auth_data)
    try:
        result = db.publish_component_revision(
            auth_data["tenant_id"], component_id, revision_id, actor_id
        )
    except ComponentLibraryConflictError as error:
        _raise_conflict(error)
    return PublishResponse(
        published=bool(result.get("published")),
        already_published=bool(result.get("alreadyPublished")),
        revision=str(result.get("revision") or ""),
    )


@router.delete(
    "/{tenant_slug}/components/{component_id}/revisions/{revision_id}",
    response_model=DeletedResponse,
    response_model_by_alias=True,
)
async def delete_revision(
    tenant_slug: str,
    component_id: str,
    revision_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeletedResponse:
    """Delete a draft revision (TYPES/DELETE); published or pinned answers 409."""
    enforce_permission(db, auth_data, Resource.TYPES, Action.DELETE)
    actor_id = get_authenticated_user_id(auth_data)
    try:
        db.delete_component_revision(
            auth_data["tenant_id"], component_id, revision_id, actor_id
        )
    except ComponentLibraryConflictError as error:
        _raise_conflict(error)
    return DeletedResponse(deleted=True)


# ===========================================================================
# Version pins and materialization preview
# ===========================================================================


@router.get(
    "/{tenant_slug}/projects/{project_id}/versions/{version_record_id}/pins",
    response_model=PinListResponse,
    response_model_by_alias=True,
)
async def list_pins(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PinListResponse:
    """The version's live pins with component/revision identity."""
    tenant_id = auth_data["tenant_id"]
    _version_or_404(tenant_id, project_id, version_record_id)
    rows = db.get_component_pins_for_version(tenant_id, version_record_id)
    return PinListResponse(
        pins=[
            PinBody(
                id=str(row["id"]),
                component_id=str(row["component_id"]),
                component_name=str(row["component_name"]),
                kind=str(row["kind"]),
                revision_id=str(row["revision_id"]),
                revision=str(row["revision"]),
                payload_digest=str(row.get("payload_digest") or ""),
                local_name=row.get("local_name"),
            )
            for row in rows
        ]
    )


@router.post(
    "/{tenant_slug}/projects/{project_id}/versions/{version_record_id}/pins",
    response_model=PinCreateResponse,
    response_model_by_alias=True,
    status_code=201,
)
async def create_pin(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: PinCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PinCreateResponse:
    """Pin a published library revision to the draft version (VERSIONS/EDIT)."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    _version_or_404(tenant_id, project_id, version_record_id)
    if body.local_name is not None and not validate_component_name(body.local_name):
        raise HTTPException(
            status_code=422,
            detail={"code": "COMPONENT_NAME_INVALID", "message": "Invalid local name."},
        )
    actor_id = get_authenticated_user_id(auth_data)
    try:
        result = db.create_version_component_pin(
            tenant_id,
            project_id,
            version_record_id,
            component_revision_id=body.component_revision_id,
            local_name=body.local_name,
            actor_id=actor_id,
        )
    except ComponentLibraryConflictError as error:
        _raise_conflict(error)
    return PinCreateResponse(pin_id=result["pinId"])


@router.delete(
    "/{tenant_slug}/projects/{project_id}/versions/{version_record_id}/pins/{pin_id}",
    response_model=DeletedResponse,
    response_model_by_alias=True,
)
async def delete_pin(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    pin_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeletedResponse:
    """Unpin one live pin from the draft version (VERSIONS/EDIT)."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    _version_or_404(tenant_id, project_id, version_record_id)
    actor_id = get_authenticated_user_id(auth_data)
    try:
        db.delete_version_component_pin(
            tenant_id, project_id, version_record_id, pin_id, actor_id
        )
    except ComponentLibraryConflictError as error:
        _raise_conflict(error)
    return DeletedResponse(deleted=True)


@router.get(
    "/{tenant_slug}/projects/{project_id}/versions/{version_record_id}/materialization",
    response_model=MaterializationPreviewResponse,
    response_model_by_alias=True,
)
async def materialization_preview(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    include_origin: bool = Query(default=True, alias="includeOrigin"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> MaterializationPreviewResponse:
    """Deterministic preview of materializing the version's pins.

    Runs the same materializer export uses against the version's generated
    document (with pins excluded from generation so nothing double-counts),
    reporting the final local component names and every collision-safe
    rename. Never mutates anything; local components are never overwritten.
    """
    tenant_id = auth_data["tenant_id"]
    version = _version_or_404(tenant_id, project_id, version_record_id)

    classes = db.get_classes_for_version(version["id"])
    all_properties: Dict[str, List[Dict[str, Any]]] = {}
    for class_data in classes:
        all_properties[class_data["id"]] = db.get_properties_for_class(class_data["id"])
    document = generate_openapi_spec(
        tenant_slug,
        str(version.get("project_slug") or version["project_id"]),
        str(version["version_id"]),
        classes,
        all_properties,
        version.get("project_description"),
        version_db_id=version["id"],
        revision_metadata=version.get("metadata"),
        project_metadata=version.get("project_metadata"),
        component_pin_rows=[],
    )

    pin_rows = db.get_materializable_pins_for_version(str(version["id"]))
    result = materialize_pinned_components(
        document, pin_rows, include_origin=include_origin
    )
    entries = [MaterializationEntryBody(**entry.as_dict()) for entry in result.entries]
    collisions = [
        MaterializationEntryBody(**entry.as_dict()) for entry in result.collisions
    ]
    return MaterializationPreviewResponse(
        include_origin=include_origin, entries=entries, collisions=collisions
    )
