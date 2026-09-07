"""``/v1/tenants/{tenant_slug}/projects/{project_ref}/consumers`` — CTG-4.1 (#4479).

The HTTP surface of the consumer contract registry: who consumes a project, what each of them
declares it uses, and the two ways that declaration gets here.

**Two ingestion paths, one stored shape.** ``POST …/consumer-pact-imports`` takes a Pact document
and resolves its interactions; ``PUT …/consumers/{ref}/contract`` takes a picked list of
operations and fields. Both end in the same ``apiome.consumer.contract/v1`` surface with the same
pointers, so nothing downstream has to know which way a contract arrived.

**The catalogue is a separate read.** ``GET …/consumer-surface`` enumerates every operation and
addressable field of a stored version — what the UI picker draws. It is deliberately *not* part
of the consumer resource: the catalogue is a property of the specification, and a project with no
consumers yet still needs it to register the first one.

**Two sibling paths, not sub-paths.** ``consumer-surface`` and ``consumer-pact-imports`` sit
beside ``consumers`` rather than under it, so no reserved word is carved out of the slug space —
a consumer may legitimately be called ``surface``.

**Authorization** uses the ``consumer_contracts`` RBAC resource added by apiome-db V251.
Declaring what your own service consumes is developer work, so the built-in Editor grid carries
view, create, and edit; *deleting* a consumer removes a signal that guards other people's
changes, so it stays with Owner and Admin.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .compatibility_engine import openapi_for_revision
from .consumer_contract import (
    CODE_CONSUMER_NOT_FOUND,
    CODE_CONTRACT_NOT_FOUND,
    CODE_PACT_TOO_LARGE,
    CODE_PROJECT_NOT_FOUND,
    CODE_SLUG_TAKEN,
    CODE_VERSION_NOT_FOUND,
    SOURCE_MANUAL,
    SOURCE_PACT,
    ConsumerContractRecord,
    ConsumerInput,
    ConsumerPatch,
    ConsumerRecord,
    ConsumerSummary,
    ConsumerValidationError,
    SurfaceSelection,
    UnresolvedInteraction,
    slugify_consumer_name,
)
from .consumer_contract_store import (
    actor_from_auth,
    contract_revision,
    contract_revisions,
    create_consumer,
    current_contract,
    ensure_consumer,
    get_consumer,
    list_consumer_summaries,
    record_contract,
    resolve_project,
    resolve_version,
    retire_consumer,
    update_consumer,
)
from .consumer_surface import SpecIndex, resolve_selection
from .database import db
from .pact_contract_import import import_pact, pact_consumer_name, parse_pact_document
from .permissions import Action, Resource, enforce_permission

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["consumer-contracts"])

#: A refusal maps onto the HTTP status that matches *what kind* of refusal it is, so a client can
#: act on the status and read the code for the detail.
_STATUS_BY_CODE = {
    CODE_CONSUMER_NOT_FOUND: 404,
    CODE_CONTRACT_NOT_FOUND: 404,
    CODE_PROJECT_NOT_FOUND: 404,
    CODE_VERSION_NOT_FOUND: 404,
    CODE_SLUG_TAKEN: 409,
    CODE_PACT_TOO_LARGE: 413,
}


# ---------------------------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------------------------


class ConsumerListResponse(BaseModel):
    """Every live consumer of a project with its current contract."""

    model_config = ConfigDict(extra="forbid")

    consumers: List[ConsumerSummary] = Field(
        default_factory=list, description="The project's consumers, newest first."
    )
    count: int = Field(description="How many consumers were returned.")


class ConsumerDetailResponse(BaseModel):
    """One consumer with its current contract, when it has declared one."""

    model_config = ConfigDict(extra="forbid")

    consumer: ConsumerRecord
    contract: Optional[ConsumerContractRecord] = Field(
        default=None, description="The current contract revision, or null when none is declared."
    )


class ContractRevisionsResponse(BaseModel):
    """A consumer's contract history."""

    model_config = ConfigDict(extra="forbid")

    revisions: List[ConsumerContractRecord] = Field(
        default_factory=list, description="Revisions, newest first."
    )
    count: int = Field(description="How many revisions were returned.")


class AvailableFieldOut(BaseModel):
    """One field the picker may offer."""

    model_config = ConfigDict(extra="forbid")

    pointer: str
    schema_pointer: str
    location: str
    path: str
    status: Optional[str] = None
    media_type: Optional[str] = None
    type_name: Optional[str] = None
    required: bool = False


class AvailableOperationOut(BaseModel):
    """One operation the picker may offer, with its addressable fields."""

    model_config = ConfigDict(extra="forbid")

    method: str
    path: str
    pointer: str
    operation_id: Optional[str] = None
    summary: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    fields: List[AvailableFieldOut] = Field(default_factory=list)
    truncated: bool = Field(
        default=False,
        description="True when this operation has more fields than are listed.",
    )


class AvailableSurfaceResponse(BaseModel):
    """The picker's catalogue for one stored version."""

    model_config = ConfigDict(extra="forbid")

    version_record_id: str = Field(description="The revision the catalogue was built from.")
    version_label: Optional[str] = Field(default=None, description="That revision's label.")
    operations: List[AvailableOperationOut] = Field(default_factory=list)
    count: int = Field(description="How many operations the specification declares.")
    truncated: bool = Field(
        default=False,
        description="True when any operation's field list was cut short by the walk limits.",
    )


class PactImportRequest(BaseModel):
    """A Pact document to import.

    Attributes:
        pact: The Pact document as raw JSON text.
        consumer_slug: The handle to store it under. Derived from the document's own
            ``consumer.name`` when omitted, which is what lets a CI job upload a pact for a
            service that has never been registered.
        consumer_name: Display name for a consumer this import registers.
        version: Version label, revision id, or ``latest`` to resolve the interactions against.
        note: Free text explaining the revision.
    """

    model_config = ConfigDict(extra="forbid")

    pact: str = Field(description="The Pact document as raw JSON text.")
    consumer_slug: Optional[str] = Field(default=None, max_length=128)
    consumer_name: Optional[str] = Field(default=None, max_length=200)
    version: Optional[str] = Field(default=None, max_length=128)
    note: Optional[str] = Field(default=None, max_length=2000)


class ContractResponse(BaseModel):
    """A stored contract revision plus the consumer it belongs to."""

    model_config = ConfigDict(extra="forbid")

    consumer: ConsumerRecord
    contract: ConsumerContractRecord
    unresolved: List[UnresolvedInteraction] = Field(
        default_factory=list,
        description=(
            "Interactions or fields that could not be resolved against the specification. "
            "Repeated from the stored contract so an importing client sees them without a "
            "second read; they are never silently dropped."
        ),
    )


# ---------------------------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------------------------


def _tenant_id(auth_data: Dict[str, Any]) -> str:
    """Return the authenticated tenant id, or refuse.

    Args:
        auth_data: The resolved auth context.

    Returns:
        The tenant id.

    Raises:
        HTTPException: 403 when the credential carries no tenant.
    """
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for this credential.")
    return str(tenant_id)


def _http_error(exc: ConsumerValidationError) -> HTTPException:
    """Translate a registry refusal into the HTTP error a client sees.

    Args:
        exc: The refusal.

    Returns:
        The ``HTTPException`` to raise — 404 for anything unknown, 409 for a taken handle, 413
        for an oversized document, 400 for every other fault, always carrying
        ``{"code", "message"}`` so a client branches on the code rather than the prose.
    """
    return HTTPException(
        status_code=_STATUS_BY_CODE.get(exc.code, 400),
        detail={"code": exc.code, "message": str(exc)},
    )


def _spec_index(tenant_id: str, tenant_slug: str, version_row: Dict[str, Any]) -> SpecIndex:
    """Build a specification index for a resolved version.

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: The tenant slug the document renderer needs.
        version_row: The resolved versions row.

    Returns:
        The index.

    Raises:
        HTTPException: 422 when the stored revision cannot be rendered as OpenAPI — a contract
            resolved against a document that would not load would be a contract about nothing.
    """
    try:
        document = openapi_for_revision(version_row, tenant_slug, tenant_id)
    except Exception as exc:  # noqa: BLE001 - any render fault is the same answer to a client
        raise HTTPException(
            status_code=422,
            detail={
                "code": "consumer-specification-unavailable",
                "message": (
                    f"the stored version could not be rendered as OpenAPI, so a contract "
                    f"cannot be resolved against it: {exc}"
                ),
            },
        ) from exc
    return SpecIndex(document)


# ---------------------------------------------------------------------------------------------
# Consumers
# ---------------------------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/projects/{project_ref}/consumers",
    response_model=ConsumerListResponse,
    summary="List a project's consumers",
    description=(
        "Every live consumer of the project, newest first, each with its **current** contract "
        "revision — the operations and fields it declares it uses, plus how many interactions "
        "could not be resolved.\n\n"
        "A consumer that has never declared a contract is still listed, with `contract: null`. "
        "That is the state a newly registered consumer is in, and hiding it would make the "
        "registration look like it failed.\n\n"
        "Requires `consumer_contracts:view`."
    ),
)
async def list_project_consumers(
    tenant_slug: str,
    project_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConsumerListResponse:
    """List the project's consumers with their current contracts.

    Args:
        tenant_slug: The tenant in the URL (the authenticated tenant is what actually scopes it).
        project_ref: Project slug or id.
        auth_data: The authenticated principal.

    Returns:
        The consumer summaries.

    Raises:
        HTTPException: 404 for an unknown project, 403 without ``consumer_contracts:view``.
    """
    enforce_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        project = resolve_project(tenant_id, project_ref)
        summaries = list_consumer_summaries(tenant_id, str(project["id"]))
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc
    return ConsumerListResponse(consumers=summaries, count=len(summaries))


@router.post(
    "/{tenant_slug}/projects/{project_ref}/consumers",
    response_model=ConsumerRecord,
    status_code=201,
    summary="Register a consumer",
    description=(
        "Register a named client of this project. The handle (`slug`) is what CI and Pact files "
        "name; it is derived from `name` when omitted, and is **not** editable afterwards — "
        "renaming it would orphan every reference to it.\n\n"
        "Registering a consumer declares nothing on its own. The surface it uses arrives "
        "separately, either by importing a Pact file or by declaring a picked selection.\n\n"
        "Requires `consumer_contracts:create`."
    ),
)
async def register_consumer(
    tenant_slug: str,
    project_ref: str,
    body: ConsumerInput,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConsumerRecord:
    """Register a new consumer.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        body: The consumer's identity and metadata.
        auth_data: The authenticated principal.

    Returns:
        The stored consumer.

    Raises:
        HTTPException: 400 for a malformed handle, 404 for an unknown project, 409 when the
            handle is taken, 403 without ``consumer_contracts:create``.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.CONSUMER_CONTRACTS, Action.CREATE, target=body.slug or body.name
    )
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        project = resolve_project(tenant_id, project_ref)
        return create_consumer(
            tenant_id,
            str(project["id"]),
            body,
            actor=actor_from_auth(auth_data, user_id),
        )
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}",
    response_model=ConsumerDetailResponse,
    summary="Read one consumer and its current contract",
    description=(
        "Read a consumer by its handle or its id, together with the full surface of its current "
        "contract revision.\n\n"
        "Requires `consumer_contracts:view`."
    ),
)
async def read_consumer(
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConsumerDetailResponse:
    """Read one consumer with its current contract.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id.
        auth_data: The authenticated principal.

    Returns:
        The consumer and its current contract, or the consumer alone when it has declared none.

    Raises:
        HTTPException: 404 when the project or consumer is unknown, 403 without
            ``consumer_contracts:view``.
    """
    enforce_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        project = resolve_project(tenant_id, project_ref)
        consumer = get_consumer(tenant_id, str(project["id"]), consumer_ref)
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc

    try:
        contract: Optional[ConsumerContractRecord] = current_contract(tenant_id, consumer.id)
    except ConsumerValidationError:
        contract = None
    return ConsumerDetailResponse(consumer=consumer, contract=contract)


@router.patch(
    "/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}",
    response_model=ConsumerRecord,
    summary="Update a consumer",
    description=(
        "Apply a partial update to a consumer's identity — its name, description, owner, "
        "contact, or metadata. Omitted fields are left alone.\n\n"
        "The handle is not updatable. It is the name CI and Pact files use, and changing it "
        "would silently orphan every reference to it; retire the consumer and register a new "
        "one instead.\n\n"
        "Requires `consumer_contracts:edit`."
    ),
)
async def patch_consumer(
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    body: ConsumerPatch,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConsumerRecord:
    """Update a consumer's identity.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id.
        body: The fields to change.
        auth_data: The authenticated principal.

    Returns:
        The updated consumer.

    Raises:
        HTTPException: 404 when the project or consumer is unknown, 403 without
            ``consumer_contracts:edit``.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.CONSUMER_CONTRACTS, Action.EDIT, target=consumer_ref
    )
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        project = resolve_project(tenant_id, project_ref)
        return update_consumer(
            tenant_id,
            str(project["id"]),
            consumer_ref,
            body,
            actor=actor_from_auth(auth_data, user_id),
        )
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc


@router.delete(
    "/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}",
    status_code=204,
    summary="Retire a consumer",
    description=(
        "Retire a consumer. Its contract revisions are **kept**: a published version's "
        "per-consumer verdict has to stay explicable after the consumer is decommissioned, and "
        "the handle becomes available again for a new registration.\n\n"
        "Requires `consumer_contracts:delete`, which the built-in grids give Owner and Admin "
        "only — removing a consumer removes a signal that guards other people's changes."
    ),
)
async def delete_consumer(
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Retire a consumer.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id.
        auth_data: The authenticated principal.

    Returns:
        An empty 204 response.

    Raises:
        HTTPException: 404 when the project or consumer is unknown, 403 without
            ``consumer_contracts:delete``.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.CONSUMER_CONTRACTS, Action.DELETE, target=consumer_ref
    )
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        project = resolve_project(tenant_id, project_ref)
        retire_consumer(
            tenant_id,
            str(project["id"]),
            consumer_ref,
            actor=actor_from_auth(auth_data, user_id),
        )
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=204)


# ---------------------------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------------------------


@router.put(
    "/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/contract",
    response_model=ContractResponse,
    status_code=201,
    summary="Declare a consumer's contract from a picked surface",
    description=(
        "Declare which operations — and, optionally, which fields on them — this consumer "
        "uses, without a Pact file. This is what the UI picker submits.\n\n"
        "The selection names operations and fields **the way a person picks them** (method, "
        "path template, dotted data path); the server resolves each against the stored "
        "specification and stores the resulting JSON Pointers. A client cannot supply its own "
        "pointers, so a stored surface always describes something the specification actually "
        "contains.\n\n"
        "Anything that does not resolve is **reported, not dropped**: an operation that no "
        "longer exists, or a field that has been removed, comes back in `unresolved` with a "
        "stable reason code and is stored on the revision.\n\n"
        "Every call writes a **new revision**; nothing is overwritten.\n\n"
        "Requires `consumer_contracts:edit`."
    ),
)
async def declare_contract(
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    body: SurfaceSelection,
    version: Optional[str] = Query(
        default=None,
        description=(
            "Version label, revision id, or `latest` to resolve the selection against. "
            "Defaults to the project's latest revision."
        ),
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ContractResponse:
    """Store a new contract revision from a picked surface.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id.
        body: The picked operations and fields.
        version: Which stored revision to resolve against.
        auth_data: The authenticated principal.

    Returns:
        The consumer, the stored revision, and everything that did not resolve.

    Raises:
        HTTPException: 400 for an empty selection, 404 for an unknown project, consumer, or
            version, 422 when the version cannot be rendered, 403 without
            ``consumer_contracts:edit``.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.CONSUMER_CONTRACTS, Action.EDIT, target=consumer_ref
    )
    tenant_id = _tenant_id(auth_data)
    if not body.operations:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "consumer-empty-surface",
                "message": (
                    "a contract must declare at least one operation; an empty surface would "
                    "silently exempt this consumer from every future analysis"
                ),
            },
        )

    try:
        project = resolve_project(tenant_id, project_ref)
        consumer = get_consumer(tenant_id, str(project["id"]), consumer_ref)
        version_row = resolve_version(tenant_id, str(project["id"]), version)
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc

    index = _spec_index(tenant_id, tenant_slug, version_row)
    surface, unresolved = resolve_selection(body, index)

    try:
        stored = record_contract(
            tenant_id,
            str(project["id"]),
            consumer,
            surface,
            actor=actor_from_auth(auth_data, user_id),
            unresolved=unresolved,
            source=SOURCE_MANUAL,
            version_id=str(version_row["id"]),
            version_label=str(version_row.get("version_id") or ""),
            note=body.note,
        )
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc

    return ContractResponse(consumer=consumer, contract=stored, unresolved=unresolved)


@router.get(
    "/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/contract",
    response_model=ConsumerContractRecord,
    summary="Read a consumer's contract",
    description=(
        "The consumer's current contract revision, or a specific one with `?revision=`.\n\n"
        "Requires `consumer_contracts:view`."
    ),
)
async def read_contract(
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    revision: Optional[int] = Query(
        default=None, ge=1, description="A specific revision number; defaults to the current one."
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ConsumerContractRecord:
    """Read one contract revision.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id.
        revision: A specific revision, or the current one when omitted.
        auth_data: The authenticated principal.

    Returns:
        The revision.

    Raises:
        HTTPException: 404 when the project, consumer, or revision is unknown, 403 without
            ``consumer_contracts:view``.
    """
    enforce_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        project = resolve_project(tenant_id, project_ref)
        consumer = get_consumer(tenant_id, str(project["id"]), consumer_ref)
        if revision is None:
            return current_contract(tenant_id, consumer.id)
        return contract_revision(tenant_id, consumer.id, revision)
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc


@router.get(
    "/{tenant_slug}/projects/{project_ref}/consumers/{consumer_ref}/contract-revisions",
    response_model=ContractRevisionsResponse,
    summary="List a consumer's contract history",
    description=(
        "Every stored revision of this consumer's contract, newest first. Revisions are never "
        "overwritten, so this is the record of what the consumer claimed it used over time.\n\n"
        "Requires `consumer_contracts:view`."
    ),
)
async def list_contract_revisions(
    tenant_slug: str,
    project_ref: str,
    consumer_ref: str,
    limit: int = Query(default=50, ge=1, le=200, description="Maximum revisions to return."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ContractRevisionsResponse:
    """List a consumer's contract revisions.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        consumer_ref: Consumer slug or id.
        limit: Maximum revisions to return.
        auth_data: The authenticated principal.

    Returns:
        The revisions, newest first.

    Raises:
        HTTPException: 404 when the project or consumer is unknown, 403 without
            ``consumer_contracts:view``.
    """
    enforce_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW)
    _ = tenant_slug
    tenant_id = _tenant_id(auth_data)
    try:
        project = resolve_project(tenant_id, project_ref)
        consumer = get_consumer(tenant_id, str(project["id"]), consumer_ref)
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc
    revisions = contract_revisions(tenant_id, consumer.id, limit=limit)
    return ContractRevisionsResponse(revisions=revisions, count=len(revisions))


# ---------------------------------------------------------------------------------------------
# The picker's catalogue, and the Pact ingestion path
# ---------------------------------------------------------------------------------------------


@router.get(
    "/{tenant_slug}/projects/{project_ref}/consumer-surface",
    response_model=AvailableSurfaceResponse,
    summary="List the operations and fields a consumer could declare",
    description=(
        "Every operation of a stored version, with the request, response, and parameter fields "
        "a consumer can declare against it. This is the catalogue the UI picker draws.\n\n"
        "Field enumeration is bounded — recursive schemas terminate and very wide operations "
        "are cut short — and an operation whose list was cut says so with `truncated: true`. A "
        "field the catalogue omitted can still be declared by naming it explicitly.\n\n"
        "Requires `consumer_contracts:view`."
    ),
)
async def read_available_surface(
    tenant_slug: str,
    project_ref: str,
    version: Optional[str] = Query(
        default=None,
        description="Version label, revision id, or `latest`. Defaults to the latest revision.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> AvailableSurfaceResponse:
    """Enumerate what a consumer could declare against a stored version.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        version: Which stored revision to enumerate.
        auth_data: The authenticated principal.

    Returns:
        The catalogue.

    Raises:
        HTTPException: 404 for an unknown project or version, 422 when the version cannot be
            rendered, 403 without ``consumer_contracts:view``.
    """
    enforce_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW)
    tenant_id = _tenant_id(auth_data)
    try:
        project = resolve_project(tenant_id, project_ref)
        version_row = resolve_version(tenant_id, str(project["id"]), version)
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc

    index = _spec_index(tenant_id, tenant_slug, version_row)
    available = index.available_surface()
    operations = [
        AvailableOperationOut(
            method=operation.method,
            path=operation.path,
            pointer=operation.pointer,
            operation_id=operation.operation_id,
            summary=operation.summary,
            tags=list(operation.tags),
            fields=[
                AvailableFieldOut(
                    pointer=field.pointer,
                    schema_pointer=field.schema_pointer,
                    location=field.location,
                    path=field.path,
                    status=field.status,
                    media_type=field.media_type,
                    type_name=field.type_name,
                    required=field.required,
                )
                for field in operation.fields
            ],
            truncated=operation.truncated,
        )
        for operation in available.operations
    ]
    return AvailableSurfaceResponse(
        version_record_id=str(version_row["id"]),
        version_label=str(version_row.get("version_id") or "") or None,
        operations=operations,
        count=len(operations),
        truncated=available.truncated,
    )


@router.post(
    "/{tenant_slug}/projects/{project_ref}/consumer-pact-imports",
    response_model=ContractResponse,
    status_code=201,
    summary="Import a Pact file into a consumer contract",
    description=(
        "Import a Pact document (specification 1.x-4.x). Each interaction's method and path is "
        "resolved onto the project's path **template** — `/pets/42` becomes `/pets/{petId}` — "
        "and the keys of its example request and response bodies become the fields the consumer "
        "declares, resolved against that operation's schemas at the interaction's own status "
        "code. Query parameters are declared as parameter usage.\n\n"
        "**Nothing is dropped.** An interaction naming a retired endpoint, a status the "
        "specification does not declare, or a field that has been removed comes back in "
        "`unresolved` with a stable reason code and is stored on the revision. An import whose "
        "interactions all fail to resolve stores a visibly empty surface rather than "
        "succeeding quietly.\n\n"
        "`matchingRules`, `providerStates`, and generators are deliberately not read: they say "
        "how a value is compared, not which fields are used.\n\n"
        "The consumer is **registered if it does not exist**, under the handle in "
        "`consumer_slug` or one derived from the document's own `consumer.name` — so a CI job "
        "uploading a pact for a new service succeeds on its first run.\n\n"
        "Requires `consumer_contracts:create`."
    ),
)
async def import_pact_contract(
    tenant_slug: str,
    project_ref: str,
    body: PactImportRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ContractResponse:
    """Import a Pact document as a contract revision.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        body: The Pact document and where to file it.
        auth_data: The authenticated principal.

    Returns:
        The consumer, the stored revision, and everything that did not resolve.

    Raises:
        HTTPException: 400 for a malformed document or an underivable handle, 404 for an unknown
            project or version, 413 for an oversized document, 422 when the version cannot be
            rendered, 403 without ``consumer_contracts:create``.
    """
    user_id = enforce_permission(
        db, auth_data, Resource.CONSUMER_CONTRACTS, Action.CREATE, target=body.consumer_slug
    )
    tenant_id = _tenant_id(auth_data)
    actor = actor_from_auth(auth_data, user_id)

    try:
        document, digest = parse_pact_document(body.pact)
        project = resolve_project(tenant_id, project_ref)
        version_row = resolve_version(tenant_id, str(project["id"]), body.version)
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc

    declared_name = (
        body.consumer_name or pact_consumer_name(document) or body.consumer_slug or ""
    )
    handle = (body.consumer_slug or slugify_consumer_name(str(declared_name))).strip()
    if not handle:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "consumer-invalid-slug",
                "message": (
                    "the Pact document names no consumer this registry can derive a handle "
                    "from; supply consumer_slug"
                ),
            },
        )

    index = _spec_index(tenant_id, tenant_slug, version_row)
    result = import_pact(document, index)

    try:
        consumer = ensure_consumer(
            tenant_id,
            str(project["id"]),
            slug=handle,
            name=str(declared_name) or handle,
            actor=actor,
            description=None,
            metadata={"source": "pact"},
        )
        stored = record_contract(
            tenant_id,
            str(project["id"]),
            consumer,
            result.surface,
            actor=actor,
            unresolved=result.unresolved,
            source=SOURCE_PACT,
            version_id=str(version_row["id"]),
            version_label=str(version_row.get("version_id") or ""),
            source_metadata=result.metadata,
            source_digest=digest,
            note=body.note,
        )
    except ConsumerValidationError as exc:
        raise _http_error(exc) from exc

    return ContractResponse(
        consumer=consumer, contract=stored, unresolved=result.unresolved
    )
