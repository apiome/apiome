"""Consumer contract registry — domain model (CTG-4.1, #4479).

"Breaking" is relative. Removing a field nobody reads breaks nobody; narrowing a type one
service depends on breaks exactly that service. The CTG-1.1 classifier grades a change against
the *whole* published surface because nothing tells it who uses what — which over-warns the
provider and under-informs the consumer.

This module defines the vocabulary that ends that: a **consumer** (a named client of a project)
and a **contract** (one immutable revision of the operations and fields that consumer actually
uses). It is pure — no database, no network, no OpenAPI parsing. Resolution against a stored
specification lives in :mod:`app.consumer_surface`, Pact ingestion in
:mod:`app.pact_contract_import`, persistence in :mod:`app.consumer_contract_store`, and the HTTP
surface in :mod:`app.consumer_contract_routes`.

Two properties are worth stating up front, because everything downstream rests on them.

**Pointers are the CTG-1.1 vocabulary, not a private one.** Every operation and field carries a
JSON Pointer written exactly the way :mod:`app.change_taxonomy_enum` writes one, so intersecting
a classified change with a declared surface (CTG-4.2) is a pointer comparison rather than a
translation. A field reached through a ``$ref`` carries **two** pointers — where it hangs off the
operation, and where the node actually lives — because the classifier reports schema changes at
``/components/schemas/<Name>/...`` and operation changes at ``/paths/...``. A contract that
recorded only one of those would miss half the changes that break it.

**Nothing is dropped silently.** An interaction that cannot be resolved to an operation or a
field becomes an :class:`UnresolvedInteraction` with a stable reason code and is stored beside
the surface. A registry that quietly discarded what it could not understand would read as
coverage it does not have.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "CODE_CONSUMER_NOT_FOUND",
    "CODE_CONTRACT_NOT_FOUND",
    "CODE_EMPTY_SURFACE",
    "CODE_INVALID_SLUG",
    "CODE_PACT_MALFORMED",
    "CODE_PACT_TOO_LARGE",
    "CODE_PROJECT_NOT_FOUND",
    "CODE_SLUG_TAKEN",
    "CODE_VERSION_NOT_FOUND",
    "CONTRACT_SOURCES",
    "FIELD_LOCATIONS",
    "SOURCE_MANUAL",
    "SOURCE_PACT",
    "UNRESOLVED_REASONS",
    "ConsumerContractField",
    "ConsumerContractOperation",
    "ConsumerContractRecord",
    "ConsumerContractSurface",
    "ConsumerInput",
    "ConsumerPatch",
    "ConsumerRecord",
    "ConsumerSummary",
    "ConsumerValidationError",
    "SelectedField",
    "SelectedOperation",
    "SurfaceSelection",
    "UnresolvedInteraction",
    "consumer_record_from_row",
    "contract_pointers",
    "contract_record_from_row",
    "count_fields",
    "is_http_method",
    "normalize_method",
    "slugify_consumer_name",
    "sort_operations",
    "validate_slug",
]

#: The stored surface document's envelope version. Bump only for an incompatible shape change.
CONTRACT_SCHEMA_VERSION = "apiome.consumer.contract/v1"

# ---------------------------------------------------------------------------------------------
# Stable refusal codes. A client branches on the code; the message is for a person.
# ---------------------------------------------------------------------------------------------

CODE_CONSUMER_NOT_FOUND = "consumer-not-found"
CODE_CONTRACT_NOT_FOUND = "consumer-contract-not-found"
CODE_EMPTY_SURFACE = "consumer-empty-surface"
CODE_INVALID_SLUG = "consumer-invalid-slug"
CODE_PACT_MALFORMED = "consumer-pact-malformed"
CODE_PACT_TOO_LARGE = "consumer-pact-too-large"
CODE_PROJECT_NOT_FOUND = "consumer-project-not-found"
CODE_SLUG_TAKEN = "consumer-slug-taken"
CODE_VERSION_NOT_FOUND = "consumer-version-not-found"

#: How a contract revision got here. Mirrors the V251 CHECK constraint.
SOURCE_PACT = "pact"
SOURCE_MANUAL = "manual"
CONTRACT_SOURCES = (SOURCE_PACT, SOURCE_MANUAL)

#: Where a declared field lives in the exchange.
FIELD_LOCATIONS = ("response", "request", "parameter")

#: Why an interaction could not be resolved. Stable codes — the UI groups by them.
UNRESOLVED_REASONS = (
    "operation-not-found",
    "method-not-declared",
    "status-not-declared",
    "media-type-not-declared",
    "field-not-found",
    "parameter-not-declared",
    "interaction-not-http",
    "interaction-malformed",
)

#: A consumer handle: lowercase, hyphen-separated, no leading/trailing hyphen. Mirrors the V251
#: ``consumer_slug_shape_check`` so the API refuses what the database would refuse anyway, with a
#: stable code instead of a driver error.
_SLUG_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")

#: HTTP methods an OpenAPI path item may declare, lowercase as the document spells them.
_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)


class ConsumerValidationError(ValueError):
    """A registry refusal carrying a stable machine code.

    Attributes:
        code: One of the module's ``CODE_*`` constants.
    """

    def __init__(self, code: str, message: str) -> None:
        """Build the refusal.

        Args:
            code: The stable code a client branches on.
            message: The human-readable explanation.
        """
        super().__init__(message)
        self.code = code


def validate_slug(slug: str) -> str:
    """Return a normalized consumer handle, or refuse.

    Args:
        slug: The candidate handle.

    Returns:
        The trimmed, lowercased handle.

    Raises:
        ConsumerValidationError: ``consumer-invalid-slug`` when the shape is wrong.
    """
    candidate = (slug or "").strip().lower()
    if not candidate:
        raise ConsumerValidationError(CODE_INVALID_SLUG, "a consumer needs a slug")
    if not _SLUG_PATTERN.match(candidate):
        raise ConsumerValidationError(
            CODE_INVALID_SLUG,
            f"'{candidate}' is not a valid consumer slug; use lowercase letters, digits and "
            f"hyphens (1-128 characters, not starting or ending with a hyphen)",
        )
    return candidate


def slugify_consumer_name(name: str) -> str:
    """Derive a handle from a display name, the way a Pact import has to.

    A Pact document names its consumer in prose (``"Billing Service"``); the registry keys on a
    handle. Deriving one is the only way an import can create the consumer it names without
    asking a human to invent a slug first.

    Args:
        name: The display name.

    Returns:
        A candidate slug, possibly empty when the name carried no slug-able characters (the
        caller then has to ask for one rather than store something meaningless).
    """
    lowered = (name or "").strip().lower()
    collapsed = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return collapsed[:128].strip("-")


def normalize_method(method: str) -> str:
    """Return an HTTP method in the lowercase spelling an OpenAPI path item uses.

    Args:
        method: The method as written anywhere (``GET``, ``get``, ``GeT``).

    Returns:
        The lowercase method; an unknown verb is returned lowercased rather than rejected, so the
        caller can report it as an unresolved interaction instead of failing the whole import.
    """
    return (method or "").strip().lower()


def is_http_method(method: str) -> bool:
    """Whether ``method`` is one an OpenAPI path item may declare.

    Args:
        method: A normalized (lowercase) method.

    Returns:
        True for the eight OpenAPI operation verbs.
    """
    return method in _HTTP_METHODS


# ---------------------------------------------------------------------------------------------
# The declared surface
# ---------------------------------------------------------------------------------------------


class ConsumerContractField(BaseModel):
    """One field a consumer reads or sends, resolved against a stored specification.

    Attributes:
        pointer: JSON Pointer anchored on the operation — where the field hangs off
            ``/paths/<path>/<method>``. This is the field's identity within the contract.
        schema_pointer: JSON Pointer to where the node actually lives in the document. Equal to
            ``pointer`` for an inline schema; a ``/components/schemas/...`` pointer when the
            field was reached through a ``$ref``. Both are stored because the CTG-1.1 classifier
            reports operation changes and component-schema changes at different pointers.
        location: ``response``, ``request``, or ``parameter``.
        status: Response status code, for a ``response`` field.
        media_type: Media type the body was declared under, for a body field.
        path: Dotted data path relative to the body root (``items.id``), or the parameter name.
            Array levels are not spelled in the path — ``items.id`` names ``id`` inside every
            element of ``items`` — because that is how a consumer talks about it.
    """

    model_config = ConfigDict(extra="forbid")

    pointer: str = Field(description="Operation-anchored JSON Pointer to the field.")
    schema_pointer: str = Field(
        description="Where the node actually lives (a $ref target, or the same pointer)."
    )
    location: Literal["response", "request", "parameter"] = Field(
        description="response | request | parameter."
    )
    status: Optional[str] = Field(default=None, description="Response status code, if a response.")
    media_type: Optional[str] = Field(default=None, description="Media type, for a body field.")
    path: str = Field(default="", description="Dotted data path, or the parameter name.")


class ConsumerContractOperation(BaseModel):
    """One operation a consumer calls, with the fields it uses on that operation.

    Attributes:
        method: Lowercase HTTP method, as the path item spells it.
        path: The specification's path template (``/pets/{petId}``), not the concrete URL a
            Pact interaction happened to exercise.
        pointer: ``/paths/<escaped path>/<method>`` — the classifier's own operation pointer.
        operation_id: The declared ``operationId``, when the specification has one.
        summary: The operation's summary, carried so a list read needs no second fetch.
        fields: Every field this consumer declared on this operation.
    """

    model_config = ConfigDict(extra="forbid")

    method: str = Field(description="Lowercase HTTP method.")
    path: str = Field(description="Specification path template.")
    pointer: str = Field(description="/paths/<escaped path>/<method>.")
    operation_id: Optional[str] = Field(default=None, description="Declared operationId.")
    summary: Optional[str] = Field(default=None, description="Operation summary.")
    fields: List[ConsumerContractField] = Field(
        default_factory=list, description="Fields used on this operation."
    )


class ConsumerContractSurface(BaseModel):
    """Everything a consumer declared it uses.

    Attributes:
        schema_version: The stored envelope version (:data:`CONTRACT_SCHEMA_VERSION`).
        operations: The operations, in stable order (path, then method).
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default=CONTRACT_SCHEMA_VERSION, description="Stored envelope version."
    )
    operations: List[ConsumerContractOperation] = Field(
        default_factory=list, description="Declared operations, ordered by path then method."
    )


class UnresolvedInteraction(BaseModel):
    """Something the importer could not place, kept rather than dropped.

    Attributes:
        reason: One of :data:`UNRESOLVED_REASONS`.
        message: What specifically could not be resolved.
        description: The interaction's own description, when it had one.
        method: The method as the source named it.
        path: The path as the source named it (concrete, not templated).
        status: The response status the source named, when relevant.
        field_path: The data path that could not be resolved, for a field-level failure.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(description=f"One of: {', '.join(UNRESOLVED_REASONS)}.")
    message: str = Field(description="What could not be resolved.")
    description: Optional[str] = Field(default=None, description="Interaction description.")
    method: Optional[str] = Field(default=None, description="Method as named by the source.")
    path: Optional[str] = Field(default=None, description="Path as named by the source.")
    status: Optional[str] = Field(default=None, description="Response status, when relevant.")
    field_path: Optional[str] = Field(
        default=None, description="Data path that did not resolve, for a field failure."
    )


# ---------------------------------------------------------------------------------------------
# The UI picker's input
# ---------------------------------------------------------------------------------------------


class SelectedField(BaseModel):
    """One field picked in the UI, named the way a person picks it.

    The picker sends *what it means* — "the ``id`` field of the 200 response of ``GET /pets``" —
    and the server resolves that against the specification. It deliberately does not send
    pointers: a client that computed its own pointers could store a surface the specification
    does not contain, and the whole point of the registry is that it does.

    Attributes:
        location: ``response``, ``request``, or ``parameter``.
        path: Dotted data path, or the parameter name.
        status: Response status code, for a ``response`` field. Defaults to the operation's
            first declared 2xx.
        media_type: Media type, for a body field. Defaults to the first declared JSON media type.
    """

    model_config = ConfigDict(extra="forbid")

    location: Literal["response", "request", "parameter"] = Field(default="response")
    path: str = Field(default="", description="Dotted data path, or the parameter name.")
    status: Optional[str] = Field(default=None, description="Response status code.")
    media_type: Optional[str] = Field(default=None, description="Media type for a body field.")


class SelectedOperation(BaseModel):
    """One operation picked in the UI, with the fields picked under it.

    Attributes:
        method: HTTP method (any case; normalized server-side).
        path: The specification's path template.
        fields: Fields picked on this operation; empty means "the whole operation".
    """

    model_config = ConfigDict(extra="forbid")

    method: str = Field(description="HTTP method.")
    path: str = Field(description="Specification path template.")
    fields: List[SelectedField] = Field(
        default_factory=list,
        description="Fields picked on this operation; empty declares the operation only.",
    )

    @field_validator("method")
    @classmethod
    def _lowercase_method(cls, value: str) -> str:
        """Normalize the method so ``GET`` and ``get`` are the same selection."""
        return normalize_method(value)


class SurfaceSelection(BaseModel):
    """A whole picked surface, as the UI picker submits it.

    Attributes:
        operations: The picked operations. Refused when empty — an empty contract declares
            nothing and would silently exempt the consumer from every future analysis.
        note: Optional free text explaining the revision.
    """

    model_config = ConfigDict(extra="forbid")

    operations: List[SelectedOperation] = Field(default_factory=list)
    note: Optional[str] = Field(default=None, max_length=2000)


# ---------------------------------------------------------------------------------------------
# Consumers
# ---------------------------------------------------------------------------------------------


class ConsumerInput(BaseModel):
    """A new consumer, as a caller defines one.

    Attributes:
        slug: Stable handle. Derived from ``name`` when omitted.
        name: Display name.
        description: What this consumer is.
        owner: Free text — the team, squad, channel, or person accountable.
        contact: Email or URL to notify when this consumer's contract would break.
        metadata: Non-secret free-form context (repository, environment, CI job).
    """

    model_config = ConfigDict(extra="forbid")

    slug: Optional[str] = Field(default=None, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    owner: Optional[str] = Field(default=None, max_length=200)
    contact: Optional[str] = Field(default=None, max_length=320)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConsumerPatch(BaseModel):
    """A partial update. Omitted fields are left alone.

    ``slug`` is deliberately absent: it is the handle CI and Pact files name, and renaming it
    would silently orphan every reference to it.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    owner: Optional[str] = Field(default=None, max_length=200)
    contact: Optional[str] = Field(default=None, max_length=320)
    metadata: Optional[Dict[str, Any]] = Field(default=None)


class ConsumerContractRecord(BaseModel):
    """One stored contract revision.

    Attributes:
        id: Row id.
        consumer_id: The consumer this revision belongs to.
        revision: Per-consumer counter, from 1.
        is_current: Whether this is the consumer's current revision.
        source: ``pact`` or ``manual``.
        version_id: The specification revision the pointers were resolved against.
        version_label: That revision's version label, snapshotted.
        surface: The declared surface.
        operation_count: How many operations it declares.
        field_count: How many fields it declares.
        unresolved: Interactions that could not be placed.
        unresolved_count: How many of those there are.
        source_metadata: Pact provenance; empty for a manual declaration.
        source_digest: ``sha256:<hex>`` of the uploaded Pact document, when there was one.
        note: Free text explaining the revision.
        actor_label: Who declared it, at the time.
        created_at: When it was declared (ISO-8601).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    consumer_id: str
    revision: int
    is_current: bool = True
    source: str = SOURCE_MANUAL
    version_id: Optional[str] = None
    version_label: Optional[str] = None
    surface: ConsumerContractSurface = Field(default_factory=ConsumerContractSurface)
    operation_count: int = 0
    field_count: int = 0
    unresolved: List[UnresolvedInteraction] = Field(default_factory=list)
    unresolved_count: int = 0
    source_metadata: Dict[str, Any] = Field(default_factory=dict)
    source_digest: Optional[str] = None
    note: Optional[str] = None
    actor_label: Optional[str] = None
    created_at: Optional[str] = None


class ConsumerRecord(BaseModel):
    """A stored consumer.

    Attributes:
        id: Row id.
        tenant_id: Owning tenant.
        project_id: Project this consumer consumes.
        slug: Stable handle.
        name: Display name.
        description: What this consumer is.
        owner: Accountable team or person.
        contact: Where to reach them.
        metadata: Free-form non-secret context.
        created_at: When it was registered.
        updated_at: When it was last changed.
        deleted_at: Retirement stamp, when retired.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    tenant_id: str
    project_id: str
    slug: str
    name: str
    description: Optional[str] = None
    owner: Optional[str] = None
    contact: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    deleted_at: Optional[str] = None


class ConsumerSummary(BaseModel):
    """A consumer plus its current contract — the project page's row.

    Attributes:
        consumer: The consumer.
        contract: Its current contract revision, or ``None`` when it has declared nothing yet.
    """

    model_config = ConfigDict(extra="forbid")

    consumer: ConsumerRecord
    contract: Optional[ConsumerContractRecord] = None


# ---------------------------------------------------------------------------------------------
# Derivations
# ---------------------------------------------------------------------------------------------


def count_fields(surface: ConsumerContractSurface) -> int:
    """How many fields a surface declares in total.

    Args:
        surface: The declared surface.

    Returns:
        The sum of every operation's field count.
    """
    return sum(len(operation.fields) for operation in surface.operations)


def contract_pointers(surface: ConsumerContractSurface) -> List[str]:
    """Every JSON Pointer a surface touches, deduplicated and sorted.

    This is what the V251 ``surface_pointers`` column stores and what the CTG-4.2 intersection
    reads. Both pointers of a field are included: a classified change may be reported against
    the operation-anchored pointer (an inline schema) or against the component-schema pointer
    (a ``$ref``), and a contract that recorded only one of the two would miss the other.

    Args:
        surface: The declared surface.

    Returns:
        Sorted unique pointers — operation pointers first by sort order, then field pointers.
    """
    pointers = set()
    for operation in surface.operations:
        pointers.add(operation.pointer)
        for field in operation.fields:
            pointers.add(field.pointer)
            if field.schema_pointer:
                pointers.add(field.schema_pointer)
    return sorted(pointers)


def _as_dict(value: Any) -> Dict[str, Any]:
    """Coerce a stored JSON column to a dict.

    Args:
        value: Whatever the driver returned.

    Returns:
        The dict, or an empty one for anything else (a NULL column, a JSON scalar).
    """
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    """Coerce a stored JSON column to a list.

    Args:
        value: Whatever the driver returned.

    Returns:
        The list, or an empty one for anything else.
    """
    return value if isinstance(value, list) else []


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp column as ISO-8601 text.

    Args:
        value: A ``datetime``, a string, or ``None``.

    Returns:
        The ISO-8601 string, or ``None``.
    """
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def consumer_record_from_row(row: Dict[str, Any]) -> ConsumerRecord:
    """Adapt a ``consumer`` row into its record.

    Args:
        row: The row as :mod:`app.database` returns it.

    Returns:
        The record.
    """
    return ConsumerRecord(
        id=str(row.get("id")),
        tenant_id=str(row.get("tenant_id")),
        project_id=str(row.get("project_id")),
        slug=str(row.get("slug") or ""),
        name=str(row.get("name") or ""),
        description=row.get("description"),
        owner=row.get("owner"),
        contact=row.get("contact"),
        metadata=_as_dict(row.get("metadata")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
        deleted_at=_iso(row.get("deleted_at")),
    )


def contract_record_from_row(row: Dict[str, Any]) -> ConsumerContractRecord:
    """Adapt a ``consumer_contract`` row into its record.

    A stored surface that no longer parses (an envelope change applied without a migration)
    degrades to an empty surface rather than raising: the registry must stay readable, and the
    counts stored alongside still say what the revision claimed.

    Args:
        row: The row as :mod:`app.database` returns it.

    Returns:
        The record.
    """
    raw_surface = _as_dict(row.get("surface"))
    try:
        surface = ConsumerContractSurface.model_validate(
            {**raw_surface, "schema_version": raw_surface.get("schema_version")
             or CONTRACT_SCHEMA_VERSION}
        )
    except Exception:  # noqa: BLE001 - an unreadable surface must not make the row unreadable
        surface = ConsumerContractSurface()

    unresolved: List[UnresolvedInteraction] = []
    for entry in _as_list(row.get("unresolved")):
        try:
            unresolved.append(UnresolvedInteraction.model_validate(entry))
        except Exception:  # noqa: BLE001 - keep the readable entries
            continue

    return ConsumerContractRecord(
        id=str(row.get("id")),
        consumer_id=str(row.get("consumer_id")),
        revision=int(row.get("revision") or 1),
        is_current=bool(row.get("is_current", True)),
        source=str(row.get("source") or SOURCE_MANUAL),
        version_id=str(row["version_id"]) if row.get("version_id") else None,
        version_label=row.get("version_label"),
        surface=surface,
        operation_count=int(row.get("operation_count") or 0),
        field_count=int(row.get("field_count") or 0),
        unresolved=unresolved,
        unresolved_count=int(row.get("unresolved_count") or 0),
        source_metadata=_as_dict(row.get("source_metadata")),
        source_digest=row.get("source_digest"),
        note=row.get("note"),
        actor_label=row.get("actor_label"),
        created_at=_iso(row.get("created_at")),
    )


def sort_operations(
    operations: Sequence[ConsumerContractOperation],
) -> List[ConsumerContractOperation]:
    """Return operations in the stored order: path, then method.

    Storage order is fixed so two declarations of the same surface produce the same document,
    which is what lets a re-import be recognised as a no-op rather than a new revision.

    Args:
        operations: The operations in any order.

    Returns:
        A new list in stable order, each operation's fields sorted by pointer.
    """
    ordered: List[ConsumerContractOperation] = []
    for operation in sorted(operations, key=lambda op: (op.path, op.method)):
        ordered.append(
            operation.model_copy(
                update={"fields": sorted(operation.fields, key=lambda f: f.pointer)}
            )
        )
    return ordered
