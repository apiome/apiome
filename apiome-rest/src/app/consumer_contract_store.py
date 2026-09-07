"""Persistence for the consumer contract registry — CTG-4.1 (#4479).

:mod:`app.consumer_contract` says what a consumer and a contract *are*; this module is the only
place one is read or written, so the registry's rules are applied once rather than at each call
site.

**A handle is validated before it is stored.** The slug goes through
:func:`~app.consumer_contract.validate_slug`, which mirrors V251's own CHECK constraint — so a
malformed handle fails at the boundary with a stable code instead of as an opaque driver error.

**Declaring a surface never overwrites one.** :func:`record_contract` always writes revision
N+1 and demotes the previous current revision in the same transaction. There is no code path
here that mutates a stored surface, which is what makes "what did this consumer claim it used
when we published 2.0.0" answerable after the fact.

**Pointers are derived, never supplied.** The ``surface_pointers`` array V251 indexes is computed
from the surface by :func:`~app.consumer_contract.contract_pointers` at write time. A caller
cannot store a pointer set that disagrees with the surface it accompanies, which is what keeps
the CTG-4.2 intersection trustworthy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .consumer_contract import (
    CODE_CONSUMER_NOT_FOUND,
    CODE_CONTRACT_NOT_FOUND,
    CODE_PROJECT_NOT_FOUND,
    CODE_SLUG_TAKEN,
    CODE_VERSION_NOT_FOUND,
    SOURCE_MANUAL,
    ConsumerContractRecord,
    ConsumerContractSurface,
    ConsumerInput,
    ConsumerPatch,
    ConsumerRecord,
    ConsumerSummary,
    ConsumerValidationError,
    UnresolvedInteraction,
    consumer_record_from_row,
    contract_pointers,
    contract_record_from_row,
    count_fields,
    slugify_consumer_name,
    validate_slug,
)
from .database import db
from .revision_deprecation import is_uuid_string

__all__ = [
    "ConsumerActor",
    "actor_from_auth",
    "contract_revision",
    "contract_revisions",
    "contracts_affected_by",
    "create_consumer",
    "current_contract",
    "ensure_consumer",
    "get_consumer",
    "list_consumer_summaries",
    "record_contract",
    "resolve_project",
    "resolve_version",
    "retire_consumer",
    "update_consumer",
]

#: A caller authenticating with an API key is a CI runner; the registry keeps them
#: distinguishable from an interactive user on every contract revision it records.
ACTOR_KIND_USER = "user"
ACTOR_KIND_API_KEY = "api_key"


@dataclass(frozen=True)
class ConsumerActor:
    """Who is acting on the registry.

    Attributes:
        user_id: The resolved acting user id, or ``None`` for an unattributable API-key call.
        label: Email or display name at the time of the action.
        kind: ``user`` for an interactive session, ``api_key`` for a CI runner.
    """

    user_id: Optional[str] = None
    label: Optional[str] = None
    kind: str = ACTOR_KIND_USER


def actor_from_auth(
    auth_data: Mapping[str, Any], user_id: Optional[str] = None
) -> ConsumerActor:
    """Build a :class:`ConsumerActor` from a resolved auth context.

    Args:
        auth_data: The dict :func:`app.auth.validate_authentication` produced.
        user_id: The id :func:`app.permissions.enforce_permission` resolved, when the caller
            already has it.

    Returns:
        The actor. An API-key caller is recorded as a runner even when a user id was resolvable,
        because what authenticated is the key — a Pact import from CI should read as one.
    """
    is_key = auth_data.get("auth_method") == "api_key"
    resolved = user_id or auth_data.get("user_id")
    return ConsumerActor(
        user_id=str(resolved) if resolved else None,
        label=auth_data.get("user_email") or auth_data.get("user_name"),
        kind=ACTOR_KIND_API_KEY if is_key else ACTOR_KIND_USER,
    )


def resolve_project(tenant_id: str, project_ref: str) -> Dict[str, Any]:
    """Resolve a project slug or id to its row, within the tenant.

    Args:
        tenant_id: The caller's tenant.
        project_ref: Project slug or UUID.

    Returns:
        The project row.

    Raises:
        ConsumerValidationError: ``consumer-project-not-found`` when nothing matches.
    """
    ref = (project_ref or "").strip()
    if not ref:
        raise ConsumerValidationError(CODE_PROJECT_NOT_FOUND, "a project reference is required")
    row = (
        db.get_project_by_id(ref, tenant_id)
        if is_uuid_string(ref)
        else db.get_project_by_slug(ref, tenant_id)
    )
    if not row:
        raise ConsumerValidationError(
            CODE_PROJECT_NOT_FOUND, f"no project '{ref}' in this tenant"
        )
    return row


def resolve_version(tenant_id: str, project_id: str, version_ref: Optional[str]) -> Dict[str, Any]:
    """Resolve a version label, revision id, or ``latest`` to a versions row.

    A contract is only meaningful against a specification, and "the current one" is what both
    ingestion paths mean when they say nothing — so an omitted reference resolves to the
    project's latest revision rather than refusing.

    Args:
        tenant_id: The caller's tenant.
        project_id: The owning project.
        version_ref: A version label, a revision UUID, ``latest``, or ``None``.

    Returns:
        The version row.

    Raises:
        ConsumerValidationError: ``consumer-version-not-found`` when nothing matches, including
            when the project has no versions at all.
    """
    requested = (version_ref or "latest").strip() or "latest"

    if requested.lower() == "latest":
        latest_id = db.get_latest_revision_id_for_project(project_id, tenant_id)
        if not latest_id:
            raise ConsumerValidationError(
                CODE_VERSION_NOT_FOUND,
                "this project has no versions to resolve a contract against",
            )
        row = db.get_version_by_id(str(latest_id), tenant_id)
    elif is_uuid_string(requested):
        row = db.get_version_by_id(requested, tenant_id)
        if row is not None and str(row.get("project_id")) != str(project_id):
            row = None
    else:
        row = db.get_version_by_version_id(project_id, requested, tenant_id)

    if not row:
        raise ConsumerValidationError(
            CODE_VERSION_NOT_FOUND, f"no version '{requested}' in this project"
        )
    return row


def get_consumer(tenant_id: str, project_id: str, consumer_ref: str) -> ConsumerRecord:
    """Read one consumer by slug **or** id.

    Accepting both is what lets a Pact file name a stable handle while the UI links by id.

    Args:
        tenant_id: The caller's tenant.
        project_id: The owning project.
        consumer_ref: The consumer's slug or its id.

    Returns:
        The record.

    Raises:
        ConsumerValidationError: ``consumer-not-found`` when nothing matches.
    """
    ref = (consumer_ref or "").strip()
    row = db.get_consumer_by_slug(project_id, tenant_id, ref)
    if row is None and is_uuid_string(ref):
        row = db.get_consumer_by_id(ref, tenant_id)
        if row is not None and str(row.get("project_id")) != str(project_id):
            row = None
    if row is None:
        raise ConsumerValidationError(
            CODE_CONSUMER_NOT_FOUND, f"no consumer '{ref}' in this project"
        )
    return consumer_record_from_row(row)


def list_consumer_summaries(tenant_id: str, project_id: str) -> List[ConsumerSummary]:
    """Every live consumer in a project with its current contract.

    Two reads, not N+1: the consumers, then every current contract in the project, joined in
    memory. A project with forty consumers is one list read either way.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.

    Returns:
        The summaries, newest consumer first, each with its current contract or ``None``.
    """
    consumers = [consumer_record_from_row(row) for row in db.list_consumers(project_id, tenant_id)]
    contracts_by_consumer: Dict[str, ConsumerContractRecord] = {}
    for row in db.list_current_consumer_contracts(project_id, tenant_id):
        record = contract_record_from_row(row)
        contracts_by_consumer[record.consumer_id] = record
    return [
        ConsumerSummary(consumer=consumer, contract=contracts_by_consumer.get(consumer.id))
        for consumer in consumers
    ]


def create_consumer(
    tenant_id: str, project_id: str, definition: ConsumerInput, *, actor: ConsumerActor
) -> ConsumerRecord:
    """Register a new consumer.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project this consumer consumes.
        definition: The consumer's identity and metadata.
        actor: Who is registering it.

    Returns:
        The stored record.

    Raises:
        ConsumerValidationError: ``consumer-invalid-slug`` for a malformed handle,
            ``consumer-slug-taken`` when the project already has a live consumer with it.
    """
    slug = validate_slug(definition.slug or slugify_consumer_name(definition.name))

    if db.get_consumer_by_slug(project_id, tenant_id, slug) is not None:
        raise ConsumerValidationError(
            CODE_SLUG_TAKEN, f"a consumer '{slug}' already exists in this project"
        )

    row = db.insert_consumer(
        tenant_id=tenant_id,
        project_id=project_id,
        slug=slug,
        name=definition.name,
        description=definition.description,
        owner=definition.owner,
        contact=definition.contact,
        metadata=definition.metadata,
        created_by=actor.user_id,
    )
    if row is None:
        raise ConsumerValidationError(
            CODE_PROJECT_NOT_FOUND, "no tenant or project context for this credential"
        )
    return consumer_record_from_row(row)


def ensure_consumer(
    tenant_id: str,
    project_id: str,
    *,
    slug: str,
    name: str,
    actor: ConsumerActor,
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ConsumerRecord:
    """Return the consumer with this handle, registering it when it does not exist.

    A Pact import names its consumer in the file. Requiring the consumer to have been registered
    first would mean a CI job that uploads a pact for a new service fails on its first run, which
    is the run that matters most.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        slug: The handle to find or register.
        name: The display name to register it under, when it is new.
        actor: Who is acting.
        description: Description to register it with, when it is new.
        metadata: Metadata to register it with, when it is new.

    Returns:
        The existing or newly registered consumer.

    Raises:
        ConsumerValidationError: ``consumer-invalid-slug`` when the handle is malformed.
    """
    handle = validate_slug(slug)
    existing = db.get_consumer_by_slug(project_id, tenant_id, handle)
    if existing is not None:
        return consumer_record_from_row(existing)
    return create_consumer(
        tenant_id,
        project_id,
        ConsumerInput(
            slug=handle, name=name or handle, description=description, metadata=metadata or {}
        ),
        actor=actor,
    )


def update_consumer(
    tenant_id: str,
    project_id: str,
    consumer_ref: str,
    patch: ConsumerPatch,
    *,
    actor: ConsumerActor,
) -> ConsumerRecord:
    """Apply a partial update to a consumer's identity.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        consumer_ref: The consumer's slug or id.
        patch: The fields to change; omitted fields are left alone.
        actor: Who is changing them.

    Returns:
        The updated record — unchanged when the patch carried no writable field.

    Raises:
        ConsumerValidationError: ``consumer-not-found``.
    """
    existing = get_consumer(tenant_id, project_id, consumer_ref)
    fields = patch.model_dump(exclude_unset=True, exclude_none=True)
    if not fields:
        return existing
    row = db.update_consumer(existing.id, tenant_id, fields, updated_by=actor.user_id)
    if row is None:
        raise ConsumerValidationError(
            CODE_CONSUMER_NOT_FOUND, f"consumer '{consumer_ref}' could not be updated"
        )
    return consumer_record_from_row(row)


def retire_consumer(
    tenant_id: str, project_id: str, consumer_ref: str, *, actor: ConsumerActor
) -> None:
    """Retire a consumer, keeping its contract history readable.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        consumer_ref: The consumer's slug or id.
        actor: Who is retiring it.

    Raises:
        ConsumerValidationError: ``consumer-not-found``.
    """
    existing = get_consumer(tenant_id, project_id, consumer_ref)
    if not db.soft_delete_consumer(existing.id, tenant_id, deleted_by=actor.user_id):
        raise ConsumerValidationError(
            CODE_CONSUMER_NOT_FOUND, f"consumer '{consumer_ref}' is already retired"
        )


def current_contract(tenant_id: str, consumer_id: str) -> ConsumerContractRecord:
    """A consumer's current contract revision.

    Args:
        tenant_id: The caller's tenant.
        consumer_id: The consumer.

    Returns:
        The record.

    Raises:
        ConsumerValidationError: ``consumer-contract-not-found`` when nothing is declared yet.
    """
    row = db.get_current_consumer_contract(consumer_id, tenant_id)
    if row is None:
        raise ConsumerValidationError(
            CODE_CONTRACT_NOT_FOUND, "this consumer has not declared a contract yet"
        )
    return contract_record_from_row(row)


def contract_revision(
    tenant_id: str, consumer_id: str, revision: int
) -> ConsumerContractRecord:
    """One stored contract revision by number.

    Args:
        tenant_id: The caller's tenant.
        consumer_id: The consumer.
        revision: The revision number, from 1.

    Returns:
        The record.

    Raises:
        ConsumerValidationError: ``consumer-contract-not-found``.
    """
    row = db.get_consumer_contract_revision(consumer_id, tenant_id, revision)
    if row is None:
        raise ConsumerValidationError(
            CODE_CONTRACT_NOT_FOUND, f"this consumer has no revision {revision}"
        )
    return contract_record_from_row(row)


def contract_revisions(
    tenant_id: str, consumer_id: str, *, limit: int = 50
) -> List[ConsumerContractRecord]:
    """A consumer's contract revisions, newest first.

    Args:
        tenant_id: The caller's tenant.
        consumer_id: The consumer.
        limit: Maximum revisions to return.

    Returns:
        The records; empty when nothing has been declared.
    """
    return [
        contract_record_from_row(row)
        for row in db.list_consumer_contracts(consumer_id, tenant_id, limit=limit)
    ]


def record_contract(
    tenant_id: str,
    project_id: str,
    consumer: ConsumerRecord,
    surface: ConsumerContractSurface,
    *,
    actor: ConsumerActor,
    unresolved: Optional[Sequence[UnresolvedInteraction]] = None,
    source: str = SOURCE_MANUAL,
    version_id: Optional[str] = None,
    version_label: Optional[str] = None,
    source_metadata: Optional[Dict[str, Any]] = None,
    source_digest: Optional[str] = None,
    note: Optional[str] = None,
) -> ConsumerContractRecord:
    """Store the consumer's next contract revision.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project.
        consumer: The consumer declaring the surface.
        surface: The resolved surface.
        actor: Who declared it.
        unresolved: Anything that could not be placed; stored, never dropped.
        source: ``pact`` or ``manual``.
        version_id: The specification revision the pointers were resolved against.
        version_label: That revision's label.
        source_metadata: Pact provenance, for a Pact import.
        source_digest: ``sha256:<hex>`` of the uploaded Pact document.
        note: Free text explaining the revision.

    Returns:
        The stored revision.

    Raises:
        ConsumerValidationError: ``consumer-not-found`` when the write found no consumer.
    """
    entries = list(unresolved or [])
    row = db.insert_consumer_contract(
        tenant_id=tenant_id,
        project_id=project_id,
        consumer_id=consumer.id,
        surface=surface.model_dump(),
        surface_pointers=contract_pointers(surface),
        operation_count=len(surface.operations),
        field_count=count_fields(surface),
        source=source,
        version_id=version_id,
        version_label=version_label,
        unresolved=[entry.model_dump() for entry in entries],
        source_metadata=source_metadata or {},
        source_digest=source_digest,
        note=note,
        created_by=actor.user_id,
        actor_label=actor.label,
    )
    if row is None:
        raise ConsumerValidationError(
            CODE_CONSUMER_NOT_FOUND,
            f"consumer '{consumer.slug}' could not be given a contract revision",
        )
    return contract_record_from_row(row)


def contracts_affected_by(
    tenant_id: str, project_id: str, pointers: Sequence[str]
) -> List[ConsumerContractRecord]:
    """Current contracts whose declared surface meets any of ``pointers``.

    The enabling read for CTG-4.2's per-consumer analysis: hand it the JSON Pointers of a
    classified diff and it answers which consumers' declared surfaces those changes touch. The
    *verdict* — which of those changes actually break which consumer — is CTG-4.2's to make;
    this only narrows the field to the consumers a change can possibly concern.

    Args:
        tenant_id: The caller's tenant.
        project_id: The project the change is against.
        pointers: The changed JSON Pointers, in the CTG-1.1 vocabulary.

    Returns:
        The matching current contract records, one per affected consumer.
    """
    return [
        contract_record_from_row(row)
        for row in db.find_consumer_contracts_by_pointers(
            project_id, tenant_id, [str(pointer) for pointer in pointers]
        )
    ]
