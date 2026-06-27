import ipaddress
from datetime import datetime
from typing import Any, Callable, Dict, List, Literal, Optional, Union
from urllib.parse import urlsplit, urlunsplit

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from .config import settings
from .repository_refresh_status import RefreshStatus, compute_refresh_status


class TagSchema(BaseModel):
    """Pydantic model for a tag."""
    id: str
    project_id: str
    name: str
    color: str = "default"
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        from_attributes = True


class ClassTagSchema(BaseModel):
    """Pydantic model for a class-tag relationship."""
    id: str
    class_id: str
    tag_id: str
    tag_name: Optional[str] = None
    tag_color: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class ClassSchema(BaseModel):
    """Pydantic model for a class schema."""
    id: str
    version_id: str
    name: str
    description: Optional[str] = None
    schema: Optional[Dict[str, Any]] = None
    enabled: bool = True
    tags: Optional[List[TagSchema]] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class ClassCreateRequest(BaseModel):
    """Request model for creating a class."""
    version_id: str
    name: str
    description: Optional[str] = None
    schema: Dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    class Config:
        from_attributes = True


class ClassUpdateRequest(BaseModel):
    """Request model for updating a class."""
    name: Optional[str] = None
    description: Optional[str] = None
    schema: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None
    canvas_metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class PropertySchema(BaseModel):
    """Pydantic model for a class property."""
    id: str
    class_id: str
    property_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    property_source_id: Optional[str] = None
    property_source_name: Optional[str] = None
    parent_id: Optional[str] = None  # New: nested properties support
    # Property→type registry binding (#3448 model, persisted by #3475). A real FK
    # to the resolved odb.primitives row plus the stored registry $ref string.
    # Both NULL for inline/library-only properties that are not bound to a type.
    primitive_id: Optional[str] = None
    primitive_ref: Optional[str] = None

    class Config:
        from_attributes = True


class VersionInfo(BaseModel):
    """Pydantic model for version information."""
    id: str
    version_id: str
    visibility: str
    published: bool

    class Config:
        from_attributes = True


class OpenAPIResponse(BaseModel):
    """Pydantic model for OpenAPI specification response."""
    openapi: str = "3.1.0"
    info: Dict[str, Any]
    paths: Dict[str, Any] = Field(default_factory=dict)
    components: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        from_attributes = True


class PrimitiveSchema(BaseModel):
    """Pydantic model for a primitive type definition."""
    id: str
    tenant_id: str
    name: str
    description: Optional[str] = None
    category: str
    schema: Dict[str, Any]
    tags: Optional[List[str]] = None
    created_by: Optional[str] = None
    is_system: bool = False
    is_public: bool = False
    usage_count: int = 0
    source: str = 'human'  # Provenance: 'human' (authored in-app) or 'imported' (#3448)
    # JSON Schema 2020-12 registry identity (#3452). schema_id is the computed/stored
    # `$id`; draft is the dialect (default '2020-12'); namespace/base_uri locate it in
    # the registry. Optional so legacy flat primitives (no `$id`) still round-trip.
    schema_id: Optional[str] = None
    draft: str = '2020-12'
    namespace: Optional[str] = None
    base_uri: Optional[str] = None
    # Resolved relative-`$ref` edges for this primitive's schema (#3456). Each edge is
    # {relative_ref, resolved_target, status} with status resolved|unresolved|circular.
    refs: List[Dict[str, Any]] = []
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None
    enabled: bool = True

    class Config:
        from_attributes = True


class PrimitiveCreateRequest(BaseModel):
    """Request model for creating a primitive."""
    name: str
    description: Optional[str] = None
    category: str
    schema: Dict[str, Any]
    tags: Optional[List[str]] = None
    # Optional registry placement (#3452). When omitted, the `$id` is derived from a
    # stable tenant-default base URI; when provided, the primitive's `$id` is computed
    # against this namespace / base URI.
    namespace: Optional[str] = None
    base_uri: Optional[str] = None

    class Config:
        from_attributes = True


class PrimitiveUpdateRequest(BaseModel):
    """Request model for updating a primitive."""
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    schema: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    enabled: Optional[bool] = None
    # Registry placement may be re-pinned on update (#3452); see PrimitiveCreateRequest.
    namespace: Optional[str] = None
    base_uri: Optional[str] = None

    class Config:
        from_attributes = True


class ImportResolution(BaseModel):
    """How to resolve one conflicting type during import (#3464).

    Keyed by definition name in :attr:`PrimitiveImportRequest.resolutions`. Applies only to a
    type the review classified as a **Conflict** (an existing type with the same registry
    identity but a different schema); New and Identical types ignore any resolution.
    """
    # One of 'keep' (leave existing) | 'overwrite' | 'rename'. Kept a plain ``str`` rather than an
    # ``Enum`` deliberately: ``_normalize_resolutions`` validates it against
    # ``primitives_review.VALID_ACTIONS`` and rejects an unknown action with a domain-specific
    # **400** ("Invalid resolution action ..."). A Pydantic ``Enum`` field would instead reject it
    # with a generic **422** before that handler runs, so a typo like 'Overwrite' is *not* silently
    # accepted today — it is surfaced as a clear 400.
    action: str = 'keep'
    new_name: Optional[str] = None  # Required when action == 'rename'.

    class Config:
        from_attributes = True


class PrimitiveImportRequest(BaseModel):
    """Request model for importing primitives from JSON Schema."""
    schema: Dict[str, Any]  # Full JSON Schema document
    import_all: bool = False  # If True, import all definitions; if False, select specific ones
    selected_definitions: Optional[List[str]] = None  # List of definition keys to import
    # Provenance metadata recorded on the import record (#3448).
    source_kind: str = 'json-schema'  # 'json-schema' | 'type-def-bundle' | 'openapi'
    source_label: Optional[str] = None  # Human label / filename / URL of the source
    target_namespace: Optional[str] = None  # Registry namespace imported into, if any
    # Map recognized string formats (email, uuid, uri, date, date-time, time) to the seeded
    # std/v0/types core types by injecting a relative $ref during rewrite (#3463). Default on.
    map_core_formats: bool = True
    # Import review controls (#3464). When dedupe is on (default), a definition identical to an
    # existing type is silently skipped; resolutions carries per-type conflict choices
    # (keep / overwrite / rename), keyed by definition name.
    dedupe: bool = True
    resolutions: Optional[Dict[str, ImportResolution]] = None

    class Config:
        from_attributes = True


class RegistryHealthResponse(BaseModel):
    """Health/ping response for the Primitives type-registry layer (#3450).

    Reports whether the registry's storage backend — the shared
    ``objectified-db`` connection backing ``odb.primitives`` — is reachable.
    """
    status: str  # 'healthy' | 'unhealthy'
    service: str = 'primitives-registry'
    database: str = 'objectified-db'
    connection: str  # 'connected' | 'disconnected'
    storage_present: bool = False  # whether the odb.primitives registry table is reachable
    error: Optional[str] = None  # populated only when status == 'unhealthy'

    class Config:
        from_attributes = True


class PrimitiveImportRecord(BaseModel):
    """Provenance record for a single primitive import (#3448)."""
    id: str
    tenant_id: str
    source_kind: str
    source_label: Optional[str] = None
    target_namespace: Optional[str] = None
    options: Dict[str, Any] = {}
    report: Dict[str, Any] = {}
    imported_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    imported_by: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


# ==================== Import pipeline staging (#3460) ====================


class GitSourceLocator(BaseModel):
    """Locator for the ``git`` import method — a single file in a Git repository (#3460).

    MVP supports public ``github.com`` repositories; the file is fetched via the
    GitHub contents API.
    """
    repo_url: str  # A github.com repository URL.
    path: str  # Path to the file within the repository.
    ref: Optional[str] = None  # Branch / tag / SHA; defaults to 'main' when omitted.

    class Config:
        from_attributes = True


class PrimitiveImportStageRequest(BaseModel):
    """Request to stage an import through the pipeline (#3460).

    The pipeline accepts a source ``kind`` (json-schema / type-def-bundle / openapi)
    by one of four ``method``s (paste / file / url / git), fetches and parses it, and
    returns a *staged* result — candidate types ready for parsing (#3461/#3462),
    ref-rewrite (#3463), and review (#3464). Nothing is committed to the registry.

    Locator fields are method-specific: ``content`` carries paste/file text, ``url``
    the http(s) source, and ``git`` the repository locator.
    """
    source_kind: str = 'json-schema'  # 'json-schema' | 'type-def-bundle' | 'openapi'
    source_method: str = 'paste'  # 'paste' | 'file' | 'url' | 'git'
    source_label: Optional[str] = None  # Human label / filename for provenance.
    target_namespace: Optional[str] = None  # Registry namespace the import targets.
    content: Optional[str] = None  # Raw document text (paste/file); JSON or YAML.
    url: Optional[str] = None  # Source URL (url method).
    git: Optional[GitSourceLocator] = None  # Git locator (git method).

    class Config:
        from_attributes = True


class StagedTypeCandidate(BaseModel):
    """One candidate type detected in a staged import (#3460, #3461)."""
    name: str  # The candidate's name (schema key or derived single-doc name).
    pointer: str  # JSON Pointer to the fragment within the source (e.g. #/$defs/Money).
    ref_count: int = 0  # Number of $ref values in the fragment (rewrite signal).
    # Intra-document $ref edges (#/$defs/...) captured for the rewrite stage (#3463),
    # each {relative_ref, resolved_target, status} with status == 'internal' (#3461).
    internal_refs: List[Dict[str, Any]] = []
    valid: bool = True  # Whether the fragment is a valid draft 2020-12 schema (#3461).
    validation_errors: List[Dict[str, Any]] = []  # Field-level errors when not valid.

    class Config:
        from_attributes = True


class PrimitiveImportStageResult(BaseModel):
    """The staged result of an import plus the id of its provenance record (#3460)."""
    import_id: Optional[str] = None  # The recorded odb.primitive_imports row id.
    status: str = 'staged'  # Lifecycle status of the import (always 'staged' here).
    source_kind: str
    source_method: str
    source_label: Optional[str] = None
    target_namespace: Optional[str] = None
    detected_count: int = 0  # Number of candidate types detected.
    candidates: List[StagedTypeCandidate] = []
    warnings: List[str] = []  # Non-fatal notes (e.g. an empty container).

    class Config:
        from_attributes = True


class UnresolvedRefPrimitive(BaseModel):
    """A primitive that carries one or more unresolved relative-``$ref`` edges (#3457).

    Surfaced to the registry overview (#3454) and resolver UI (#3470) so a dangling
    reference can be located and re-resolved. ``unresolved_refs`` is the subset of the
    primitive's ``refs`` edges whose ``status`` is ``unresolved``.
    """
    id: str
    name: str
    schema_id: Optional[str] = None
    namespace: Optional[str] = None
    base_uri: Optional[str] = None
    unresolved_count: int = 0
    unresolved_refs: List[Dict[str, Any]] = []

    class Config:
        from_attributes = True


class UnresolvedRefsResponse(BaseModel):
    """Tenant-wide unresolved-``$ref`` summary for the type registry (#3457).

    ``unresolved_ref_count`` (every unresolved edge) and ``affected_primitive_count``
    (distinct primitives carrying at least one) are the KPIs consumed by the registry
    coverage/stats endpoint (#3454); ``primitives`` is the per-primitive breakdown the
    resolver UI lists (#3470).
    """
    unresolved_ref_count: int = 0
    affected_primitive_count: int = 0
    primitives: List[UnresolvedRefPrimitive] = []

    class Config:
        from_attributes = True


# ==================== Type-registry resolver API (#3459) ====================


class ResolvedRefEdge(BaseModel):
    """One re-resolved ``$ref`` dependency edge of a primitive (#3459).

    The persisted edge fields (``relative_ref`` / ``resolved_target`` / ``status``)
    plus the resolved dependency target's identity. ``target_id`` / ``target_name``
    are populated only for a ``resolved`` edge (the primitive currently carrying the
    target ``$id`` within the caller's read scope); they are ``None`` for an
    ``unresolved`` edge whose target does not yet exist.
    """
    relative_ref: Optional[str] = None
    resolved_target: Optional[str] = None
    status: str  # 'resolved' | 'unresolved'
    target_id: Optional[str] = None
    target_name: Optional[str] = None

    class Config:
        from_attributes = True


class ResolvedPrimitiveRefs(BaseModel):
    """A primitive and its re-resolved dependency edges (#3459).

    One row of the resolver UI table (#3470): the source primitive's identity, its
    per-edge resolved/unresolved counts, and its dependency edges.
    """
    id: str
    name: str
    schema_id: Optional[str] = None
    namespace: Optional[str] = None
    base_uri: Optional[str] = None
    ref_count: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    refs: List[ResolvedRefEdge] = []

    class Config:
        from_attributes = True


class ResolveResponse(BaseModel):
    """Result of a tenant-wide ``$ref`` re-resolution pass (#3459).

    ``POST /v1/types/{tenant_slug}/resolve`` recomputes the resolved/unresolved status
    of every dependency edge across the tenant's primitives against the current registry
    state, persists any edge whose status changed, and returns the per-primitive
    dependency listing the resolver UI consumes (#3470). The top-level counts mirror the
    coverage KPIs of ``GET …/unresolved`` (#3457/#3454); ``reresolved_primitive_count``
    is how many primitives had at least one edge status flip during this pass.
    """
    total_primitives: int = 0  # primitives carrying at least one $ref edge
    ref_count: int = 0  # total dependency edges across those primitives
    resolved_ref_count: int = 0
    unresolved_ref_count: int = 0
    affected_primitive_count: int = 0  # primitives with at least one unresolved edge
    reresolved_primitive_count: int = 0  # primitives whose stored statuses were updated
    primitives: List[ResolvedPrimitiveRefs] = []

    class Config:
        from_attributes = True


# ==================== Registry coverage/stats (#3454) ====================


class RegistryCoverageStatsResponse(BaseModel):
    """Aggregate registry coverage KPIs for the Primitives overview (#3454).

    Counts are scoped to the caller's tenant: system-core types are seeded per tenant
    (``is_system = true`` rows owned by the tenant), tenant types are private rows
    (``is_system = false``). ``unresolved_ref_count`` mirrors ``GET …/unresolved`` (#3457).
    """
    core_type_count: int = 0
    tenant_type_count: int = 0
    imported_count: int = 0
    properties_bound_count: int = 0
    bound_class_count: int = 0
    unresolved_ref_count: int = 0
    namespace_count: int = 0

    class Config:
        from_attributes = True


# ==================== Type-registry namespaces (#3451) ====================


class TypeNamespaceSchema(BaseModel):
    """A type-registry namespace: scope, base URI, version root, visibility, and default flag.

    ``scope`` is derived from ``is_system`` for the client. ``type_count`` is the number of
    primitives the caller's tenant has in this namespace.
    """
    id: str
    tenant_id: Optional[str] = None  # None for system-core namespaces
    namespace: str
    base_uri: str
    version_root: Optional[str] = None
    description: Optional[str] = None
    scope: str  # 'system' | 'tenant'
    is_system: bool = False
    is_public: bool = False
    is_default: bool = False
    type_count: int = 0
    created_by: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    model_config = ConfigDict(from_attributes=True)


class TypeNamespaceCreateRequest(BaseModel):
    """Request model for creating a namespace.

    ``scope`` selects system-core vs tenant ownership; system namespaces require a platform admin
    (currently unavailable via the API, so they are effectively read-only). ``base_uri`` and
    ``version_root`` are derived from the namespace path when omitted.
    """
    namespace: str
    scope: Literal["system", "tenant"] = "tenant"
    base_uri: Optional[str] = None
    version_root: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None
    is_default: bool = False

    model_config = ConfigDict(from_attributes=True)


class TypeNamespaceUpdateRequest(BaseModel):
    """Request model for updating a namespace. The namespace path is immutable (it links the
    namespace to its primitives); only base URI, version root, description, visibility, and the
    default flag may change."""
    base_uri: Optional[str] = None
    version_root: Optional[str] = None
    description: Optional[str] = None
    is_public: Optional[bool] = None
    is_default: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== Type-registry settings (#3472) ====================


# Allowed enum values, shared by the request/response models and asserted against the
# DB CHECK constraints in 20260623-120000.sql.
DefaultDraft = Literal["2020-12", "2019-09", "draft-07"]
RefStyle = Literal["relative", "absolute", "anchor"]
CircularRefPolicy = Literal["error", "warn"]
ImportScope = Literal["tenant", "system"]
CorePublishRole = Literal["platform_admin", "tenant_admin", "maintainer"]


class TypeRegistrySettingsSchema(BaseModel):
    """Per-tenant type-registry behavior settings (#3472).

    Configures the default JSON Schema dialect, the ``$ref`` resolution policy, import
    defaults, and the validation/publishing governance toggles read by the validation gate
    (#3479). A tenant that has never saved settings receives the column defaults below.
    """
    # JSON Schema dialect
    default_draft: DefaultDraft = "2020-12"
    strict_validation: bool = True
    allow_annotation_keywords: bool = True
    coerce_imported_drafts: bool = True

    # Reference resolution
    resolution_base_url: str = "https://api.objectified.dev/types/"
    ref_style: RefStyle = "relative"
    allow_remote_refs: bool = False
    remote_host_allowlist: List[str] = ["json-schema.org", "spec.openapis.org"]
    max_resolution_depth: int = 12
    circular_ref_policy: CircularRefPolicy = "error"

    # Import defaults
    default_import_scope: ImportScope = "tenant"
    default_target_namespace: Optional[str] = None
    rewrite_refs_on_import: bool = True
    accepted_formats: List[str] = ["json-schema-2020-12", "type-def-bundle", "openapi-3.1"]
    dedupe_identical_types: bool = True

    # Validation & publishing governance
    validate_on_save: bool = True
    block_publish_on_errors: bool = True
    core_publish_role: CorePublishRole = "platform_admin"

    # Provenance — null until the tenant first saves settings (defaults are unsaved).
    is_default: bool = True  # True when no row exists yet (these are the unsaved defaults)
    updated_by: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    model_config = ConfigDict(from_attributes=True)


class TypeRegistrySettingsUpdateRequest(BaseModel):
    """Request model for saving a tenant's type-registry settings (#3472).

    Every field is optional so the UI may send a partial update; omitted fields keep their
    current persisted value (or the default when no row exists yet). Enum and range checks
    here mirror the ``odb.type_registry_settings`` CHECK constraints so an invalid value is
    rejected with a clean 422 before it ever reaches the database.
    """
    default_draft: Optional[DefaultDraft] = None
    strict_validation: Optional[bool] = None
    allow_annotation_keywords: Optional[bool] = None
    coerce_imported_drafts: Optional[bool] = None

    resolution_base_url: Optional[str] = None
    ref_style: Optional[RefStyle] = None
    allow_remote_refs: Optional[bool] = None
    remote_host_allowlist: Optional[List[str]] = None
    max_resolution_depth: Optional[int] = Field(default=None, ge=1, le=64)
    circular_ref_policy: Optional[CircularRefPolicy] = None

    default_import_scope: Optional[ImportScope] = None
    default_target_namespace: Optional[str] = None
    rewrite_refs_on_import: Optional[bool] = None
    accepted_formats: Optional[List[str]] = None
    dedupe_identical_types: Optional[bool] = None

    validate_on_save: Optional[bool] = None
    block_publish_on_errors: Optional[bool] = None
    core_publish_role: Optional[CorePublishRole] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== Specification import job (CLI / REST contract) ====================
#
# Today the dashboard runs imports via Next.js server actions (see objectified-ui/lib/db/import-helper.ts).
# These models describe the canonical tenant-scoped REST surface for CLI "import spec" (#3329).

SpecImportJobState = Literal[
    "queued",
    "running",
    "pending-approval",
    "committing",
    "completed",
    "failed",
    "canceled",
    "rolled-back",
]


class SpecImportProjectTarget(BaseModel):
    """Project identity for a specification import job."""

    model_config = ConfigDict(extra="forbid")

    name: str
    slug: str
    description: Optional[str] = None


class SpecImportVersionTarget(BaseModel):
    """Target catalog revision for an import job."""

    model_config = ConfigDict(extra="forbid")

    version_id: str = Field(description="Semantic version id for the draft/catalog revision (for example 1.0.0).")
    description: Optional[str] = None


class SpecImportOptions(BaseModel):
    """Optional importer flags (parity with dashboard Import dialog)."""

    model_config = ConfigDict(extra="forbid")

    selected_schemas: List[str] = Field(default_factory=list)
    dry_run: bool = False
    incremental_mode: bool = False
    apply_naming_convention: bool = False
    class_naming_convention: Optional[
        Literal["PascalCase", "camelCase", "snake_case", "kebab-case", "none"]
    ] = None
    property_naming_convention: Optional[
        Literal["PascalCase", "camelCase", "snake_case", "kebab-case", "none"]
    ] = None
    auto_layout: bool = False
    create_relationships: bool = False
    skip_duplicate_versions: bool = Field(
        False,
        description=(
            "When true, if the target catalog version line already exists in the project, "
            "complete successfully without re-importing (idempotent no-op)."
        ),
    )


# Current envelope version for a persisted repository import spec. Bumped by
# RAR-1.4 when the stored option shape changes; readers use it to migrate older
# rows forward without losing data.
REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION = 1


class RepositoryImportSpec(BaseModel):
    """Persisted import specification for one imported repository file (RAR-1.1).

    Mirrors the ``odb.repository_import_spec`` row. Keyed to the imported-file
    lineage ``(repository_id, branch, path)`` it captures the full
    ``SpecImportOptions`` payload plus the source descriptor used at import time,
    so a repository auto-refresh can replay the user's original request instead
    of falling back to importer defaults.
    """

    model_config = ConfigDict(extra="forbid")

    id: Optional[str] = Field(
        default=None,
        description="Row id; absent for a not-yet-persisted spec.",
    )
    tenant_id: str
    repository_id: str
    branch: str
    path: str = Field(description="Repository-relative file path (lineage key).")
    project_id: str
    source_kind: str = Field(
        description="Importer discriminator (for example openapi-3, arazzo).",
    )
    format_override: Optional[str] = Field(
        default=None,
        description="Explicit format override (the importer --format flag), when the user forced one.",
    )
    content_type: Optional[str] = Field(
        default=None,
        description="MIME type used to read the file (for example application/yaml), when known.",
    )
    options: SpecImportOptions = Field(
        default_factory=SpecImportOptions,
        description="Full SpecImportOptions payload submitted at import time.",
    )
    spec_schema_version: int = Field(
        default=REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION,
        description="Envelope version of the stored spec.",
    )
    last_imported_commit_sha: Optional[str] = Field(
        default=None,
        description="Branch tip commit SHA observed for this file at import time (RAR-2.1).",
    )
    last_imported_committed_at: Optional[Union[datetime, str]] = Field(
        default=None,
        description="Committed-at timestamp of the file at import time; the newer-than anchor (RAR-2.1).",
    )
    last_imported_blob_sha: Optional[str] = Field(
        default=None,
        description="Blob SHA of the file content at import time (RAR-2.1).",
    )
    created_by: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None


# --- Versioned spec envelope upgrade path (RAR-1.4, #3515) -------------------
#
# A persisted import spec is a forward-compatible envelope:
# ``{ spec_schema_version, options }``. When the ``SpecImportOptions`` shape
# changes (a renamed or dropped field, a new default), the envelope version is
# bumped and a single-step upgrader is registered below so that *reads* of an
# older row migrate the stored ``options`` blob forward to the current shape
# before it is validated. Without this, a raw blob with no version marker — or
# one written under an older shape — would be impossible to interpret safely and
# would break replay of old imports.
#
# An upgrader migrates an ``options`` dict from version N to version N+1. The
# registry is keyed by the *source* version N; ``upgrade_repository_import_options``
# walks it one step at a time up to ``REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION``.
RepositoryImportOptionsUpgrader = Callable[[Dict[str, Any]], Dict[str, Any]]


def _upgrade_repository_import_options_v0_to_v1(
    options: Dict[str, Any],
) -> Dict[str, Any]:
    """Migrate a pre-envelope (version 0) options blob to the version 1 shape.

    Version 0 is the legacy "raw ``options_json`` blob with no ``spec_schema_version``
    marker" described in the ticket: a spec persisted before the versioned
    envelope existed (or one whose marker is missing/``NULL``). It may carry keys
    that are no longer part of ``SpecImportOptions``. This upgrader keeps only the
    keys the current model recognizes, so the result validates under the
    ``extra="forbid"`` model; fields absent from the legacy blob fall back to
    their current defaults at validation time.

    Args:
        options: The legacy version-0 options dictionary.

    Returns:
        A new dictionary containing only keys valid for the version-1 shape.
    """
    known_fields = set(SpecImportOptions.model_fields.keys())
    return {key: value for key, value in options.items() if key in known_fields}


# Single-step upgraders keyed by the source envelope version they migrate *from*.
# To add a v1 -> v2 migration: bump ``REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION`` to
# 2 and register ``1: _upgrade_..._v1_to_v2`` here. No read site changes.
_REPOSITORY_IMPORT_OPTIONS_UPGRADERS: Dict[int, RepositoryImportOptionsUpgrader] = {
    0: _upgrade_repository_import_options_v0_to_v1,
}


def upgrade_repository_import_options(
    options: Optional[Dict[str, Any]],
    from_version: Optional[int],
) -> Dict[str, Any]:
    """Migrate a stored options dict forward to the current envelope shape.

    Applies the registered single-step upgraders in order, starting at
    ``from_version`` and stopping at ``REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION``.
    A missing/``None`` version is treated as the unversioned legacy shape
    (version 0). When ``from_version`` already equals the current version the
    options are returned as a shallow copy, untouched.

    Args:
        options: The stored options dictionary (may be ``None`` or empty).
        from_version: The envelope version the options were stored under;
            ``None`` is interpreted as version 0 (legacy, unmarked).

    Returns:
        The options dictionary migrated to the current envelope shape.

    Raises:
        ValueError: If ``from_version`` is newer than this code understands
            (a downgrade), or if no upgrader is registered for an intermediate
            version (a gap in the migration chain).
    """
    version = 0 if from_version is None else int(from_version)
    if version > REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION:
        raise ValueError(
            "Stored import spec envelope version "
            f"{version} is newer than the supported version "
            f"{REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION}; cannot downgrade."
        )

    migrated: Dict[str, Any] = dict(options or {})
    while version < REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION:
        upgrader = _REPOSITORY_IMPORT_OPTIONS_UPGRADERS.get(version)
        if upgrader is None:
            raise ValueError(
                "No upgrader registered for repository import options envelope "
                f"version {version}; cannot migrate to version "
                f"{REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION}."
            )
        migrated = upgrader(migrated)
        version += 1
    return migrated


def load_repository_import_options(
    envelope: Optional[Dict[str, Any]],
) -> SpecImportOptions:
    """Read a stored import-spec envelope and return current-shape options.

    This is the read entry point for persisted specs: it pulls the stored
    options blob and ``spec_schema_version`` out of a DAO row (or any
    envelope-shaped dict), migrates the blob forward with
    ``upgrade_repository_import_options``, and validates it into a current
    ``SpecImportOptions``. Repository auto-refresh uses it to replay the user's
    original request regardless of when the spec was written.

    The options blob is read from ``options_json`` (the DAO/JSONB column name)
    or, failing that, ``options`` (the model field name); a JSON-encoded string
    is decoded transparently for cursors that return JSONB as text.

    Args:
        envelope: A stored import-spec row or envelope dict, or ``None``.

    Returns:
        A validated, current-shape ``SpecImportOptions`` (defaults when the
        envelope is ``None`` or carries no options).
    """
    if not envelope:
        return SpecImportOptions()

    raw = envelope.get("options_json")
    if raw is None:
        raw = envelope.get("options")
    if isinstance(raw, str):
        import json

        raw = json.loads(raw) if raw.strip() else {}
    if raw is None:
        raw = {}

    migrated = upgrade_repository_import_options(raw, envelope.get("spec_schema_version"))
    return SpecImportOptions.model_validate(migrated)


class RepositoryImportSpecRead(BaseModel):
    """Current-shape import spec returned by the read endpoint (RAR-1.5).

    The response surface for ``GET …/repository-imports/{id}/spec`` (and its
    ``?path=`` lookup variant). It exposes the captured source descriptor and the
    full ``SpecImportOptions`` payload, upgraded on read to the current envelope
    shape, so the refresh worker, the UI status surface, and the CLI can replay
    the user's original import request. ``spec_schema_version`` always reports the
    current envelope version because ``options`` has already been migrated forward.
    """

    model_config = ConfigDict(extra="forbid")

    spec_schema_version: int = Field(
        default=REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION,
        description="Current envelope version the returned options conform to.",
    )
    source_kind: str = Field(
        description="Importer discriminator (for example openapi-3, arazzo).",
    )
    format_override: Optional[str] = Field(
        default=None,
        description="Explicit format override (the importer --format flag), when the user forced one.",
    )
    content_type: Optional[str] = Field(
        default=None,
        description="MIME type used to read the file (for example application/yaml), when known.",
    )
    options: SpecImportOptions = Field(
        default_factory=SpecImportOptions,
        description="Full SpecImportOptions payload, upgraded to the current shape.",
    )
    last_imported_commit_sha: Optional[str] = Field(
        default=None,
        description="Branch tip commit SHA observed for this file at import time (RAR-2.1).",
    )
    last_imported_committed_at: Optional[Union[datetime, str]] = Field(
        default=None,
        description=(
            "Committed-at timestamp of the file at import time. A later auto-refresh "
            "compares the remote committed_at against this anchor to gate newer-than "
            "re-imports (RAR-2.1/RAR-2.2)."
        ),
    )
    last_imported_blob_sha: Optional[str] = Field(
        default=None,
        description="Blob SHA of the file content at import time (RAR-2.1).",
    )
    refresh_status: RefreshStatus = Field(
        default=RefreshStatus.UP_TO_DATE,
        description=(
            "Materialized per-file refresh state (RAR-2.3): one of up-to-date / "
            "stale / refreshing / failed / diverged. Derived from the current scan "
            "recency vs the last_imported_* anchors, overlaid with any in-flight "
            "refresh, last-attempt failure, or divergence hold."
        ),
    )


def repository_import_spec_read_from_row(
    row: Optional[Dict[str, Any]],
) -> RepositoryImportSpecRead:
    """Build a :class:`RepositoryImportSpecRead` from a stored spec row.

    Reuses :func:`load_repository_import_options` to migrate the persisted
    ``options_json`` blob forward, then surfaces the source descriptor and the
    freshness anchor columns (RAR-2.1) verbatim. ``spec_schema_version`` is
    reported as the current envelope version because the options have been
    upgraded on read.

    ``refresh_status`` (RAR-2.3) is materialized on read by comparing the current
    scan recency for the file — the ``remote_committed_at`` / ``remote_blob_sha``
    columns the read DAO joins from ``odb.tenant_repository_files`` — against the
    ``last_imported_*`` anchors, overlaid with the operational flags
    (``is_refreshing`` / ``last_refresh_failed`` / ``diverged``) carried on the
    row when the sweep (RAR-3/RAR-4) and divergence check (RAR-4.4) populate them.
    Deriving on read means the status is recomputed whenever its inputs change —
    the scan refreshes the remote recency columns and a finished refresh updates
    the anchors — so it is always current without a separate stored column.

    Args:
        row: A ``odb.repository_import_spec`` row as a dict, optionally joined to
            the current indexed file row (``remote_committed_at`` /
            ``remote_blob_sha``) and any operational refresh flags.

    Returns:
        The current-shape read model for the endpoint response.
    """
    options = load_repository_import_options(row)
    row = row or {}
    refresh_status = compute_refresh_status(
        remote_committed_at=row.get("remote_committed_at"),
        last_imported_committed_at=row.get("last_imported_committed_at"),
        remote_checksum=row.get("remote_blob_sha"),
        last_imported_checksum=row.get("last_imported_blob_sha"),
        is_refreshing=bool(row.get("is_refreshing")),
        last_refresh_failed=bool(row.get("last_refresh_failed")),
        diverged=bool(row.get("diverged")),
    )
    return RepositoryImportSpecRead(
        spec_schema_version=REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION,
        source_kind=str(row.get("source_kind") or ""),
        format_override=row.get("format_override"),
        content_type=row.get("content_type"),
        options=options,
        last_imported_commit_sha=row.get("last_imported_commit_sha"),
        last_imported_committed_at=row.get("last_imported_committed_at"),
        last_imported_blob_sha=row.get("last_imported_blob_sha"),
        refresh_status=refresh_status,
    )


# Synthetic ``source_kind`` the REST layer stamps on a repository auto-refresh
# import (REPO-12.1). It is not a real importer kind: when the spec-import worker
# sees it, the actual importer kind, options, and parsing come from the stored
# import spec carried in ``SpecImportStartMetadata.repository_import_spec`` rather
# than the request metadata (RAR-4.1).
REPOSITORY_AUTO_IMPORT_SOURCE_KIND = "repository_auto_import"


class SpecImportStoredSpec(BaseModel):
    """Stored import spec carried into the worker for a repository auto-refresh (RAR-4.1).

    A repository auto-refresh re-imports a file the user already imported, and must
    replay that original request rather than fall back to importer defaults. This
    model carries the captured spec (RAR-1.1/1.2) and its source descriptor
    (RAR-1.3) to the spec-import worker so it routes, parses, and applies options
    identically to the first run.

    ``options`` is the verbatim options blob persisted at first import (the worker's
    camelCase option shape), passed through untouched — not re-validated into the
    lossy :class:`SpecImportOptions` subset — so advanced options (class prefixes,
    type mappings, …) survive the round-trip to the worker.
    """

    model_config = ConfigDict(extra="forbid")

    source_kind: str = Field(
        description="Importer discriminator used at first import (for example openapi-3, arazzo).",
    )
    format_override: Optional[str] = Field(
        default=None,
        description="Resolved spec format the importer routed on (RAR-1.3); drives format detection on refresh.",
    )
    content_type: Optional[str] = Field(
        default=None,
        description="MIME type the document was read as at first import (RAR-1.3); drives parsing on refresh.",
    )
    options: Dict[str, Any] = Field(
        default_factory=dict,
        description="Verbatim options blob persisted at first import, replayed as-is.",
    )
    spec_schema_version: int = Field(
        default=REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION,
        description="Envelope version of the stored spec (RAR-1.4).",
    )


class RepositoryRefreshProvenance(BaseModel):
    """Provenance for a version created by a repository auto-refresh (RAR-4.2, #3528).

    A refresh re-imports a changed file and creates a NEW catalog version. That
    version must be traceable back to the prior version it supersedes
    (``parent_version_id``) and to the exact source commit that triggered the
    refresh (``source_commit_sha`` + ``source_committed_at``). The RAR-3.2 sweep
    captures the commit signals on the ``odb.tenant_repository_refresh_jobs`` row;
    this model carries them from the executor through to version creation so they
    land on the new ``odb.versions`` row.
    """

    model_config = ConfigDict(extra="forbid")

    parent_version_id: Optional[str] = Field(
        default=None,
        description="Prior version (versions.id) this refresh supersedes; the new version's linear parent.",
    )
    source_commit_sha: Optional[str] = Field(
        default=None,
        description="Repository source commit SHA that triggered the refresh.",
    )
    source_committed_at: Optional[Union[datetime, str]] = Field(
        default=None,
        description="Commit timestamp of source_commit_sha.",
    )


class SpecImportStartMetadata(BaseModel):
    """Shared metadata for JSON-base64 and multipart upload flows."""

    model_config = ConfigDict(extra="forbid")

    source_kind: str = Field(
        description=(
            "Importer discriminator (for example openapi-3, asyncapi-2, protobuf). "
            "Supported values match product import kinds. The synthetic value "
            f"'{REPOSITORY_AUTO_IMPORT_SOURCE_KIND}' marks a repository auto-refresh, "
            "in which case the importer kind/options/parsing come from "
            "'repository_import_spec' rather than this metadata (RAR-4.1)."
        )
    )
    project: SpecImportProjectTarget
    version: SpecImportVersionTarget
    existing_project_id: Optional[str] = Field(
        None,
        description="When set, skip project creation and attach the job to this catalog project id.",
    )
    options: SpecImportOptions = Field(default_factory=SpecImportOptions)
    repository_import_spec: Optional[SpecImportStoredSpec] = Field(
        default=None,
        description=(
            "Stored import spec for a repository auto-refresh; required and consulted "
            f"only when source_kind is '{REPOSITORY_AUTO_IMPORT_SOURCE_KIND}' (RAR-4.1)."
        ),
    )
    refresh_provenance: Optional[RepositoryRefreshProvenance] = Field(
        default=None,
        description=(
            "Refresh lineage (prior version + source commit) recorded on the version a "
            f"repository auto-refresh creates; set only when source_kind is "
            f"'{REPOSITORY_AUTO_IMPORT_SOURCE_KIND}' (RAR-4.2)."
        ),
    )


class SpecImportStartJsonRequest(BaseModel):
    """Start an import using base64-encoded document bytes (application/json)."""

    model_config = ConfigDict(extra="forbid")

    metadata: SpecImportStartMetadata
    document_base64: str = Field(
        ...,
        description="Standard base64 (RFC 4648) of the spec file bytes; no data: URL prefix.",
    )
    filename: Optional[str] = Field(
        None,
        description="Original filename for format sniffing when bytes alone are ambiguous.",
    )
    content_type: Optional[str] = Field(
        None,
        description="Optional MIME type hint (for example application/yaml or application/json).",
    )


class SpecImportEvent(BaseModel):
    """Structured log line from an import job."""

    model_config = ConfigDict(extra="allow")

    id: str
    ts: int
    level: Literal["info", "warn", "error"]
    code: str
    message: str
    context: Optional[Dict[str, Any]] = None


class SpecImportProgress(BaseModel):
    """Coarse-grained progress snapshot."""

    model_config = ConfigDict(extra="forbid")

    phase: Literal[
        "initializing",
        "creating-project",
        "creating-version",
        "creating-properties",
        "creating-classes",
        "linking-properties",
        "verifying",
        "finalizing",
    ]
    total: int
    completed: int
    current_item: Optional[str] = None


class SpecImportJobResult(BaseModel):
    """Identifiers produced when an import finishes or after commit."""

    model_config = ConfigDict(extra="forbid")

    project_id: Optional[str] = None
    project_slug: Optional[str] = None
    version_id: Optional[str] = None
    version_record_id: Optional[str] = None


class SpecImportJobStatus(BaseModel):
    """Poll payload for an import job."""

    job_id: str
    state: SpecImportJobState
    percent: int = Field(0, ge=0, le=100)
    events: List[SpecImportEvent] = Field(default_factory=list)
    progress: Optional[SpecImportProgress] = None
    summary: Optional[Dict[str, Any]] = None
    result: Optional[SpecImportJobResult] = None


class SpecImportJobListItem(BaseModel):
    """Summary row for GET …/imports (no full event log)."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    state: SpecImportJobState
    percent: int = Field(0, ge=0, le=100)
    status_path: str = Field(description="Relative URL for GET …/imports/{job_id}.")
    progress: Optional[SpecImportProgress] = None
    result: Optional[SpecImportJobResult] = None


class SpecImportJobListResponse(BaseModel):
    """Tenant-scoped import jobs visible to this API process."""

    model_config = ConfigDict(extra="forbid")

    jobs: List[SpecImportJobListItem]


class SpecImportJobAccepted(BaseModel):
    """Returned when a job is accepted (HTTP 202)."""

    job_id: str
    status_path: str = Field(
        description="Relative URL path for GET …/imports/{job_id} until the job reaches a terminal state.",
    )


class SpecImportCommitResponse(BaseModel):
    """Response after a successful commit."""

    job_id: str
    state: Literal["completed"] = "completed"
    project_id: str
    project_slug: str
    version_id: str
    version_record_id: str


class SpecImportRollbackResponse(BaseModel):
    """Response after rolling back a committed import."""

    job_id: str
    state: Literal["rolled-back"] = "rolled-back"
    project_id: Optional[str] = None
    version_record_id: Optional[str] = None


# ==================== Project Models ====================

class ProjectSchema(BaseModel):
    """Pydantic model for a project."""
    id: str
    tenant_id: str
    creator_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    slug: str
    enabled: bool = True
    deleted_at: Optional[Union[datetime, str]] = None
    metadata: Optional[Dict[str, Any]] = None
    change_report_template_version_id: Optional[str] = Field(
        None,
        serialization_alias="changeReportTemplateVersionId",
    )
    # Captured quality score of the project's latest revision (#3609 follow-up). Populated from the
    # score persisted onto a revision at import; NULL until a revision has been scored.
    quality_score: Optional[int] = Field(None, serialization_alias="qualityScore")
    quality_grade: Optional[str] = Field(None, serialization_alias="qualityGrade")
    creator_name: Optional[str] = None
    creator_email: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class ProjectCreateRequest(BaseModel):
    """Request model for creating a project."""
    name: str
    description: Optional[str] = None
    slug: str
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class ProjectUpdateRequest(BaseModel):
    """Request model for updating a project."""
    name: Optional[str] = None
    description: Optional[str] = None
    slug: Optional[str] = None
    enabled: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None
    change_report_template_version_id: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("changeReportTemplateVersionId", "change_report_template_version_id"),
    )

    class Config:
        from_attributes = True


# ==================== Version Models ====================

class VersionSchema(BaseModel):
    """Schema revision: shortMessage = commit-style note; changelog = release notes (markdown)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    project_id: str
    creator_id: Optional[str] = None
    version_id: str
    short_message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("shortMessage", "description"),
        serialization_alias="shortMessage",
        description="Human-readable revision note (stored as description in DB).",
    )
    changelog: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("changelog", "change_log"),
        description="Markdown changelog / release notes (stored as change_log in DB).",
    )
    author: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("author", "commit_author"),
        serialization_alias="author",
        description="Optional commit author string (audit / CI identity; stored as commit_author).",
    )
    message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("message", "commit_message"),
        serialization_alias="message",
        description="Optional full commit message body (stored as commit_message).",
    )
    external_ref: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("externalRef", "external_ref"),
        serialization_alias="externalRef",
        description="External work item id or URL (Jira, Linear, etc.).",
    )
    visibility: str = "private"
    published: bool = False
    published_at: Optional[Union[datetime, str]] = None
    published_immutable: bool = Field(
        default=False,
        validation_alias=AliasChoices("publishedImmutable", "published_immutable"),
        serialization_alias="publishedImmutable",
        description="When published: if true, git-like writes require tenant-admin override (#2586).",
    )
    enabled: bool = True
    parent_version_id: Optional[str] = None
    merge_parent_version_id: Optional[str] = None
    source_commit_sha: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("sourceCommitSha", "source_commit_sha"),
        serialization_alias="sourceCommitSha",
        description=(
            "Repository source commit SHA that triggered this revision "
            "(RAR-4.2 refresh provenance); NULL for hand-authored revisions."
        ),
    )
    source_committed_at: Optional[Union[datetime, str]] = Field(
        default=None,
        validation_alias=AliasChoices("sourceCommittedAt", "source_committed_at"),
        serialization_alias="sourceCommittedAt",
        description="Commit timestamp of source_commit_sha (RAR-4.2 refresh provenance).",
    )
    forked_from_revision_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("forkedFromRevisionId", "forked_from_revision_id"),
        serialization_alias="forkedFromRevisionId",
        description="Source revision (versions.id) if this row is a fork.",
    )
    upstream_project_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("upstreamProjectId", "upstream_project_id"),
        serialization_alias="upstreamProjectId",
        description="Upstream project for merge/sync (optional).",
    )
    fork_source_version_label: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("forkSourceVersionLabel", "fork_source_version_string"),
        serialization_alias="forkSourceVersionLabel",
    )
    fork_source_project_name: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("forkSourceProjectName", "fork_source_project_name"),
        serialization_alias="forkSourceProjectName",
    )
    upstream_project_name: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("upstreamProjectName", "upstream_project_name"),
        serialization_alias="upstreamProjectName",
    )
    revision_locked: bool = Field(
        default=False,
        validation_alias=AliasChoices("revisionLocked", "revision_locked"),
        serialization_alias="revisionLocked",
        description="Tenant-admin lock: revision cannot be soft-deleted by non-admins.",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Revision-level JSON (deprecation, sunset, successor revision id, lifecycle tag, etc.).",
    )
    lifecycle: str = Field(
        default="stable",
        description="Governance lifecycle tag: stable | beta | deprecated | archived (#739); aligns with metadata.lifecycle and #507 deprecation when unset.",
    )
    creator_name: Optional[str] = None
    creator_email: Optional[str] = None
    project_name: Optional[str] = None
    project_slug: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    @model_validator(mode="before")
    @classmethod
    def _inject_lifecycle(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        from .revision_lifecycle import effective_lifecycle

        return {**data, "lifecycle": effective_lifecycle(data.get("metadata"))}


class VersionCreateRequest(BaseModel):
    """Request model for creating a version."""

    model_config = ConfigDict(populate_by_name=True)

    version_id: Optional[str] = None  # Optional - auto-generated if not provided
    short_message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("shortMessage", "description"),
        description="Revision note (commit message analog).",
    )
    changelog: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("changelog", "change_log"),
    )
    author: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("author", "commit_author"),
    )
    message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("message", "commit_message"),
    )
    external_ref: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("externalRef", "external_ref"),
    )
    base_revision_id: str = Field(
        ...,
        validation_alias=AliasChoices("baseRevisionId", "base_revision_id"),
        description="Revision id the client believes is the current head (optimistic lock; #2566).",
    )
    branch_name: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("branchName", "branch_name"),
        description="Named branch to advance; required when the project has multiple branches.",
    )
    source_version_id: Optional[str] = None  # Copy classes from this version
    source_commit_sha: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("sourceCommitSha", "source_commit_sha"),
        description=(
            "Repository source commit SHA that triggered this revision "
            "(RAR-4.2 refresh provenance); recorded for repository auto-refresh imports."
        ),
    )
    source_committed_at: Optional[Union[datetime, str]] = Field(
        default=None,
        validation_alias=AliasChoices("sourceCommittedAt", "source_committed_at"),
        description="Commit timestamp of source_commit_sha (RAR-4.2 refresh provenance).",
    )
    bump_strategy: Optional[str] = None  # 'patch' or 'minor' for auto-versioning
    override_published_immutability: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "overridePublishedImmutability", "override_published_immutability"
        ),
        description="Tenant admin only: allow push from an immutable published tip (#2586).",
    )
    override_reason: Optional[str] = Field(
        default=None,
        max_length=2000,
        validation_alias=AliasChoices("overrideReason", "override_reason"),
        description="Audit text when overriding published immutability (#2586).",
    )


class VersionForkRequest(BaseModel):
    """Fork a schema version line into another project from a source revision (cross-project sandbox)."""

    model_config = ConfigDict(populate_by_name=True)

    source_revision_id: str = Field(
        ...,
        validation_alias=AliasChoices("sourceRevisionId", "source_revision_id"),
        description="Source version row id (revision) to copy from.",
    )
    upstream_project_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("upstreamProjectId", "upstream_project_id"),
        description="Optional upstream project for merge-back; defaults to the source revision's project.",
    )
    version_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("versionId", "version_id"),
        description="Explicit semantic version string for the forked version (e.g. '2.0.0').",
    )
    short_message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("shortMessage", "description"),
    )
    changelog: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("changelog", "change_log"),
    )
    author: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("author", "commit_author"),
    )
    message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("message", "commit_message"),
    )
    external_ref: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("externalRef", "external_ref"),
    )
    bump_strategy: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("bumpStrategy", "bump_strategy"),
        description="Auto-versioning strategy when versionId is omitted: 'minor' or 'patch' (default).",
    )


class VersionBranchFromRevisionRequest(BaseModel):
    """Create a named branch whose tip is an existing revision (in-project; #2570)."""

    model_config = ConfigDict(populate_by_name=True)

    source_revision_id: str = Field(
        ...,
        validation_alias=AliasChoices("sourceRevisionId", "source_revision_id"),
        description="Revision (versions.id) to use as the branch tip.",
    )
    branch_name: str = Field(
        ...,
        validation_alias=AliasChoices("branchName", "branch_name"),
        description="New branch name; unique per project.",
    )


class VersionBranchRecordOut(BaseModel):
    """Named version branch row (REST camelCase)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    project_id: str = Field(..., serialization_alias="projectId")
    name: str
    tip_revision_id: str = Field(
        ...,
        serialization_alias="tipRevisionId",
    )
    branched_from_revision_id: Optional[str] = Field(
        default=None,
        serialization_alias="branchedFromRevisionId",
        description="Revision this branch was created from (lineage; persists when tip advances).",
    )
    protected: bool = False
    is_default: bool = Field(
        default=False,
        serialization_alias="isDefault",
        description="True when this is the project's default branch.",
    )
    require_merge_path: bool = Field(
        default=False,
        serialization_alias="requireMergePath",
        description="When true, non-admin direct pushes may not advance this branch tip; use merge (#2583).",
    )
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")
    created_at: Optional[Union[datetime, str]] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[Union[datetime, str]] = Field(default=None, serialization_alias="updatedAt")


class VersionBranchDivergenceBranchOut(BaseModel):
    """Branch descriptor used in divergence responses (#2721)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    tip_revision_id: str = Field(serialization_alias="tipRevisionId")


class VersionBranchDivergenceMergeBaseOut(BaseModel):
    """Merge-base revision metadata for branch divergence."""

    model_config = ConfigDict(populate_by_name=True)

    revision_id: str = Field(serialization_alias="revisionId")
    created_at: Optional[Union[datetime, str]] = Field(default=None, serialization_alias="createdAt")


class VersionBranchDivergenceSampleOut(BaseModel):
    """Sampled revision entry in ahead/behind lists."""

    model_config = ConfigDict(populate_by_name=True)

    revision_id: str = Field(
        validation_alias=AliasChoices("revisionId", "revision_id"),
        serialization_alias="revisionId",
    )
    short_message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("shortMessage", "short_message"),
        serialization_alias="shortMessage",
    )


class VersionBranchDivergenceResponse(BaseModel):
    """Branch-vs-branch divergence metrics and commit samples (#2721)."""

    model_config = ConfigDict(populate_by_name=True)

    branch: VersionBranchDivergenceBranchOut
    against: VersionBranchDivergenceBranchOut
    merge_base: Optional[VersionBranchDivergenceMergeBaseOut] = Field(
        default=None,
        serialization_alias="mergeBase",
    )
    ahead: int
    behind: int
    ahead_sample: List[VersionBranchDivergenceSampleOut] = Field(
        default_factory=list,
        serialization_alias="aheadSample",
    )
    behind_sample: List[VersionBranchDivergenceSampleOut] = Field(
        default_factory=list,
        serialization_alias="behindSample",
    )


class VersionBranchPolicyPatchRequest(BaseModel):
    """Tenant-admin: branch protection and merge-path policy (#504, #2583)."""

    model_config = ConfigDict(populate_by_name=True)

    protected: Optional[bool] = None
    is_default: Optional[bool] = Field(
        default=None,
        validation_alias=AliasChoices("isDefault", "is_default"),
    )
    require_merge_path: Optional[bool] = Field(
        default=None,
        validation_alias=AliasChoices("requireMergePath", "require_merge_path"),
    )

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "VersionBranchPolicyPatchRequest":
        if self.protected is None and self.require_merge_path is None and self.is_default is None:
            raise ValueError("Provide protected, requireMergePath, and/or isDefault")
        return self


class VersionBranchFromRevisionResponse(BaseModel):
    """Result of branch-from-revision; idempotentReplay documents safe retries (#2570)."""

    model_config = ConfigDict(populate_by_name=True)

    branch: VersionBranchRecordOut
    tip_version: VersionSchema = Field(
        ...,
        validation_alias=AliasChoices("tipVersion", "tip_version"),
        serialization_alias="tipVersion",
    )
    idempotent_replay: bool = Field(
        default=False,
        validation_alias=AliasChoices("idempotentReplay", "idempotent_replay"),
        serialization_alias="idempotentReplay",
        description="True when the branch already existed with the same tip and lineage (safe retry).",
    )


class VersionBranchMergePreviewRequest(BaseModel):
    """Dry-run merge preview (three-way schema merge + merge-base)."""

    model_config = ConfigDict(populate_by_name=True)

    source_branch_name: str = Field(
        ...,
        validation_alias=AliasChoices("sourceBranchName", "source_branch_name"),
    )
    target_branch_name: str = Field(
        ...,
        validation_alias=AliasChoices("targetBranchName", "target_branch_name"),
    )
    include_merged_open_api: bool = Field(
        default=True,
        validation_alias=AliasChoices("includeMergedOpenApi", "include_merged_open_api"),
        description=(
            "When true (default), include merged OpenAPI preview when auto-merge is possible "
            "and under the size cap; set false to omit large payloads (counts and conflicts unchanged)."
        ),
    )
    persist_merge_session: bool = Field(
        default=False,
        validation_alias=AliasChoices("persistMergeSession", "persist_merge_session"),
        description="When true, insert merge_sessions + conflict rows for resumable resolution (#2573).",
    )
    override_published_immutability: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "overridePublishedImmutability", "override_published_immutability"
        ),
        description="Tenant admin only: preview merge when a branch tip is published immutable (#2586).",
    )
    override_reason: Optional[str] = Field(
        default=None,
        max_length=2000,
        validation_alias=AliasChoices("overrideReason", "override_reason"),
        description="Audit text when overriding published immutability (#2586).",
    )


class MergeSessionStatusPatchRequest(BaseModel):
    """Update merge session lifecycle state (#2573)."""

    model_config = ConfigDict(populate_by_name=True)

    status: Literal["resolving", "applied", "aborted"] = Field(
        ...,
        validation_alias=AliasChoices("status"),
        description="Target status: resolving, applied, or aborted (from preview/resolving only).",
    )


class VersionBranchMergeRequest(BaseModel):
    """Merge source branch into target: requires baseRevisionId = current target tip (optimistic lock)."""

    model_config = ConfigDict(populate_by_name=True)

    source_branch_name: str = Field(
        ...,
        validation_alias=AliasChoices("sourceBranchName", "source_branch_name"),
    )
    target_branch_name: str = Field(
        ...,
        validation_alias=AliasChoices("targetBranchName", "target_branch_name"),
    )
    base_revision_id: str = Field(
        ...,
        validation_alias=AliasChoices("baseRevisionId", "base_revision_id"),
    )
    skip_compat_gate: bool = Field(
        default=False,
        validation_alias=AliasChoices("skipCompatGate", "skip_compat_gate"),
        description="When true, skip optional project compatGateOnMerge check against merge result.",
    )
    compat_gate_override_reason: Optional[str] = Field(
        default=None,
        max_length=2000,
        validation_alias=AliasChoices(
            "compatGateOverrideReason", "compat_gate_override_reason"
        ),
        description="Required when skipCompatGate is true and compatGateOnMerge is enabled (#2590).",
    )
    override_published_immutability: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "overridePublishedImmutability", "override_published_immutability"
        ),
        description="Tenant admin only: merge when a branch tip is published immutable (#2586).",
    )
    override_reason: Optional[str] = Field(
        default=None,
        max_length=2000,
        validation_alias=AliasChoices("overrideReason", "override_reason"),
        description="Audit text when overriding published immutability (#2586).",
    )


class VersionBranchRollbackPreviewRequest(BaseModel):
    """Dry-run rollback: compatibility / deprecation signals before apply (#745)."""

    model_config = ConfigDict(populate_by_name=True)

    branch_name: str = Field(
        ...,
        validation_alias=AliasChoices("branchName", "branch_name"),
        description="Named branch whose tip is rolled forward with restored content.",
    )
    target_revision_id: str = Field(
        ...,
        validation_alias=AliasChoices("targetRevisionId", "target_revision_id"),
        description="Revision (versions.id) whose class snapshot is restored (must be an ancestor of the branch tip).",
    )
    override_published_immutability: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "overridePublishedImmutability", "override_published_immutability"
        ),
        description="Tenant admin only: preview rollback when branch tip is published immutable (#2586).",
    )
    override_reason: Optional[str] = Field(
        default=None,
        max_length=2000,
        validation_alias=AliasChoices("overrideReason", "override_reason"),
        description="Audit text when overriding published immutability (#2586).",
    )


class VersionBranchRollbackRequest(BaseModel):
    """Revert-style rollback: new revision whose tree matches target; parent = prior branch tip (#745)."""

    model_config = ConfigDict(populate_by_name=True)

    branch_name: str = Field(
        ...,
        validation_alias=AliasChoices("branchName", "branch_name"),
    )
    target_revision_id: str = Field(
        ...,
        validation_alias=AliasChoices("targetRevisionId", "target_revision_id"),
    )
    base_revision_id: str = Field(
        ...,
        validation_alias=AliasChoices("baseRevisionId", "base_revision_id"),
        description="Must equal current branch tip (optimistic concurrency).",
    )
    skip_compat_warning: bool = Field(
        default=False,
        validation_alias=AliasChoices("skipCompatWarning", "skip_compat_warning"),
        description="When true, apply even if compat analysis is not safe (still blocked if compatGateOnRollback is on).",
    )
    short_message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("shortMessage", "description"),
    )
    changelog: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("changelog", "change_log"),
    )
    reason: Optional[str] = Field(
        default=None,
        description="Optional audit reason persisted on rollback workflow audit (#2582).",
        max_length=2000,
    )
    override_published_immutability: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "overridePublishedImmutability", "override_published_immutability"
        ),
        description="Tenant admin only: roll back when branch tip is published immutable (#2586).",
    )
    override_reason: Optional[str] = Field(
        default=None,
        max_length=2000,
        validation_alias=AliasChoices("overrideReason", "override_reason"),
        description="Audit text when overriding published immutability (#2586).",
    )


class VersionUpdateRequest(BaseModel):
    """Request model for updating a version."""

    model_config = ConfigDict(populate_by_name=True)

    short_message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("shortMessage", "description"),
    )
    changelog: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("changelog", "change_log"),
    )
    enabled: Optional[bool] = None
    revision_locked: Optional[bool] = Field(
        default=None,
        validation_alias=AliasChoices("revisionLocked", "revision_locked"),
        description="Tenant admins only: lock revision against deletion.",
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Shallow-merge into versions.metadata (deprecation fields, lifecycle tag #739, etc.).",
    )


class VersionPublishRequest(BaseModel):
    """Publish: optional last-minute revision note / changelog applied before freeze."""

    model_config = ConfigDict(populate_by_name=True)

    visibility: Optional[str] = "private"  # 'public' or 'private'
    short_message: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("shortMessage", "description"),
    )
    changelog: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("changelog", "change_log"),
    )
    published_immutable: Optional[bool] = Field(
        default=True,
        validation_alias=AliasChoices("publishedImmutable", "published_immutable"),
        description="If true (default), published revision rejects git-like writes unless admin override (#2586).",
    )
    change_report_baseline_mode: Literal["auto", "initial", "manual"] = Field(
        default="auto",
        validation_alias=AliasChoices("changeReportBaselineMode", "change_report_baseline_mode"),
        description="How to choose the baseline for the publication change report: auto (prior published ancestor), initial (empty baseline), or manual.",
    )
    change_report_baseline_revision_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("changeReportBaselineRevisionId", "change_report_baseline_revision_id"),
        description="Required when changeReportBaselineMode is manual: published revision to diff from.",
    )
    allow_breaking: Optional[bool] = Field(
        default=False,
        validation_alias=AliasChoices("allowBreaking", "allow_breaking"),
        description="Allow publishing when backward-compatibility vs the baseline is breaking (#3212).",
    )
    skip_publish_checks: Optional[bool] = Field(
        default=False,
        validation_alias=AliasChoices("skipPublishChecks", "skip_publish_checks"),
        description="Bypass OpenAPI build, documentation, and compatibility gates (emergency only; prefer CLI flags).",
    )

    @model_validator(mode="after")
    def _validate_change_report_manual_baseline(self) -> "VersionPublishRequest":
        if self.change_report_baseline_mode == "manual":
            bid = (self.change_report_baseline_revision_id or "").strip()
            if not bid:
                raise ValueError(
                    "changeReportBaselineRevisionId is required when changeReportBaselineMode is manual"
                )
            self.change_report_baseline_revision_id = bid
        return self


class VersionPublishChangeReportPreviewRequest(BaseModel):
    """Preview publication change report before publishing (same baseline fields as publish)."""

    model_config = ConfigDict(populate_by_name=True)

    change_report_baseline_mode: Literal["auto", "initial", "manual"] = Field(
        default="auto",
        validation_alias=AliasChoices("changeReportBaselineMode", "change_report_baseline_mode"),
    )
    change_report_baseline_revision_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("changeReportBaselineRevisionId", "change_report_baseline_revision_id"),
    )

    @model_validator(mode="after")
    def _validate_preview_manual_baseline(self) -> "VersionPublishChangeReportPreviewRequest":
        if self.change_report_baseline_mode == "manual":
            bid = (self.change_report_baseline_revision_id or "").strip()
            if not bid:
                raise ValueError(
                    "changeReportBaselineRevisionId is required when changeReportBaselineMode is manual"
                )
            self.change_report_baseline_revision_id = bid
        return self


class VersionPublishChangeReportPreviewOut(BaseModel):
    """Draft change report Mustache output for pre-publish preview."""

    model_config = ConfigDict(populate_by_name=True)

    header_snapshot: str = Field(serialization_alias="headerSnapshot")
    rendered_body: str = Field(serialization_alias="renderedBody")
    footnote_snapshot: str = Field(serialization_alias="footnoteSnapshot")
    change_model_json: Dict[str, Any] = Field(serialization_alias="changeModelJson")
    baseline_revision_id: Optional[str] = Field(None, serialization_alias="baselineRevisionId")
    template_version_id: Optional[str] = Field(None, serialization_alias="templateVersionId")
    from_version_label: str = Field(serialization_alias="fromVersionLabel")
    to_version_label: str = Field(serialization_alias="toVersionLabel")
    initial_publication: bool = Field(
        default=False,
        serialization_alias="initialPublication",
        validation_alias=AliasChoices("initialPublication", "initial_publication"),
    )


class CompatibilityRulesPayload(BaseModel):
    """Optional toggles for backward-compatibility checks (defaults are strict)."""

    model_config = ConfigDict(populate_by_name=True)

    check_paths: bool = Field(
        True,
        validation_alias=AliasChoices("checkPaths", "check_paths"),
    )
    check_schemas: bool = Field(
        True,
        validation_alias=AliasChoices("checkSchemas", "check_schemas"),
    )
    treat_removed_schema_as_breaking: bool = Field(
        True,
        validation_alias=AliasChoices(
            "treatRemovedSchemaAsBreaking", "treat_removed_schema_as_breaking"
        ),
    )
    treat_removed_property_as_breaking: bool = Field(
        True,
        validation_alias=AliasChoices(
            "treatRemovedPropertyAsBreaking", "treat_removed_property_as_breaking"
        ),
    )
    treat_removed_path_as_breaking: bool = Field(
        True,
        validation_alias=AliasChoices(
            "treatRemovedPathAsBreaking", "treat_removed_path_as_breaking"
        ),
    )
    treat_removed_operation_as_breaking: bool = Field(
        True,
        validation_alias=AliasChoices(
            "treatRemovedOperationAsBreaking", "treat_removed_operation_as_breaking"
        ),
    )
    detect_possible_renames: bool = Field(
        True,
        validation_alias=AliasChoices("detectPossibleRenames", "detect_possible_renames"),
    )


class CompatibilityPolicyPayload(BaseModel):
    """Optional HTTP semantics (e.g. CI gate)."""

    model_config = ConfigDict(populate_by_name=True)

    http409_when_breaking: bool = Field(
        False,
        validation_alias=AliasChoices("http409WhenBreaking", "http409_when_breaking"),
        description="Return 409 Conflict when overall classification is breaking.",
    )
    http409_when_deprecated_revision: bool = Field(
        False,
        validation_alias=AliasChoices(
            "http409WhenDeprecatedRevision", "http409_when_deprecated_revision"
        ),
        description="Return 409 when either revision is deprecated (strict CI / CLI).",
    )


class CompatibilityCheckRequest(BaseModel):
    """Compare two schema revisions (versions.id) for backward compatibility."""

    model_config = ConfigDict(populate_by_name=True)

    base_revision_id: str = Field(
        ...,
        validation_alias=AliasChoices("baseRevisionId", "base_revision_id"),
        description="Older / merge-base side revision (versions.id UUID).",
    )
    head_revision_id: str = Field(
        ...,
        validation_alias=AliasChoices("headRevisionId", "head_revision_id"),
        description="Newer / branch tip side revision (versions.id UUID).",
    )
    rules: Optional[CompatibilityRulesPayload] = None
    policy: Optional[CompatibilityPolicyPayload] = None


class CompatibilityFindingOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    path: str
    category: str
    rule: str
    message: str


class RevisionDeprecationWarningOut(BaseModel):
    """Structured warning when a revision in the compat pair is deprecated (#507)."""

    model_config = ConfigDict(populate_by_name=True)

    revision_id: str = Field(serialization_alias="revisionId")
    role: str
    version_id: str = Field(serialization_alias="versionId")
    message: str
    replacement_revision_id: Optional[str] = Field(
        default=None,
        serialization_alias="replacementRevisionId",
    )
    sunset_date: Optional[str] = Field(default=None, serialization_alias="sunsetDate")
    migration_guide_url: str = Field(
        ...,
        serialization_alias="migrationGuideUrl",
    )


class SunsetTimelineEntryOut(BaseModel):
    """One row in the tenant-wide deprecation / sunset schedule (#508)."""

    model_config = ConfigDict(populate_by_name=True)

    revision_id: str = Field(serialization_alias="revisionId")
    project_id: str = Field(serialization_alias="projectId")
    project_name: Optional[str] = Field(default=None, serialization_alias="projectName")
    project_slug: Optional[str] = Field(default=None, serialization_alias="projectSlug")
    version_line: str = Field(serialization_alias="versionLine")
    sunset_date: Optional[str] = Field(default=None, serialization_alias="sunsetDate")
    sunset_at: Optional[str] = Field(
        default=None,
        serialization_alias="sunsetAt",
        description="Same normalized UTC instant as sunsetDate; canonical name for #748.",
    )
    timeline_status: str = Field(serialization_alias="timelineStatus")
    lifecycle_phase: str = Field(serialization_alias="lifecyclePhase")
    deprecation_message: Optional[str] = Field(default=None, serialization_alias="deprecationMessage")
    successor_revision_id: Optional[str] = Field(default=None, serialization_alias="successorRevisionId")
    published: bool
    deprecation_warnings: List[RevisionDeprecationWarningOut] = Field(
        default_factory=list,
        serialization_alias="deprecationWarnings",
    )


class SunsetTimelineResponse(BaseModel):
    """Aggregated sunset / deprecation timeline for accessible projects (#508)."""

    model_config = ConfigDict(populate_by_name=True)

    entries: List[SunsetTimelineEntryOut] = Field(default_factory=list)


class VersionDraftLockAcquireRequest(BaseModel):
    """Optional lease duration for draft lock acquire/renew (#2584)."""

    model_config = ConfigDict(populate_by_name=True)

    lease_seconds: Optional[int] = Field(
        default=None,
        ge=60,
        le=86400,
        validation_alias=AliasChoices("leaseSeconds", "lease_seconds"),
        serialization_alias="leaseSeconds",
        description="Lock duration in seconds (default 900).",
    )


class VersionDraftLockRenewRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    lease_seconds: Optional[int] = Field(
        default=None,
        ge=60,
        le=86400,
        validation_alias=AliasChoices("leaseSeconds", "lease_seconds"),
        serialization_alias="leaseSeconds",
    )


class VersionDraftLockResponse(BaseModel):
    """Active draft edit lock on an unpublished revision (#2584)."""

    model_config = ConfigDict(populate_by_name=True)

    version_id: str = Field(serialization_alias="versionId")
    owner_user_id: str = Field(serialization_alias="ownerUserId")
    expires_at: datetime = Field(serialization_alias="expiresAt")


class VersionDraftLockStatusResponse(BaseModel):
    """Draft lock presence for a revision — used for Studio polling (#2585)."""

    model_config = ConfigDict(populate_by_name=True)

    active: bool
    version_id: Optional[str] = Field(default=None, serialization_alias="versionId")
    owner_user_id: Optional[str] = Field(default=None, serialization_alias="ownerUserId")
    expires_at: Optional[datetime] = Field(default=None, serialization_alias="expiresAt")


class PushWebhookSubscriptionCreateRequest(BaseModel):
    """Create a push webhook subscription (#2587). Plaintext signing secret is write-only."""

    model_config = ConfigDict(populate_by_name=True)

    url: str = Field(
        ...,
        min_length=8,
        description="HTTPS webhook URL (validated server-side).",
    )
    signing_secret: str = Field(
        ...,
        min_length=8,
        validation_alias=AliasChoices("signingSecret", "signing_secret"),
        serialization_alias="signingSecret",
        description="Shared secret for signing deliveries; never returned after create.",
    )
    active: bool = Field(default=True, description="Whether deliveries are enabled.")


class PushWebhookSubscriptionUpdateRequest(BaseModel):
    """Update URL, active flag, and/or rotate signing secret (#2587)."""

    model_config = ConfigDict(populate_by_name=True)

    url: Optional[str] = Field(
        default=None,
        description="New HTTPS URL (must remain unique per tenant).",
    )
    signing_secret: Optional[str] = Field(
        default=None,
        min_length=8,
        validation_alias=AliasChoices("signingSecret", "signing_secret"),
        serialization_alias="signingSecret",
    )
    active: Optional[bool] = None


class PushWebhookSubscriptionResponse(BaseModel):
    """Push webhook subscription — signing secret is never included; only signingSecretRef."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    url: str
    active: bool
    signing_secret_ref: str = Field(serialization_alias="signingSecretRef")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")


class PushWebhookDeadLetterItem(BaseModel):
    """Terminal failed delivery (#2588)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    subscription_id: str = Field(serialization_alias="subscriptionId")
    event_type: str = Field(serialization_alias="eventType")
    payload: Dict[str, Any]
    attempt_count: int = Field(serialization_alias="attemptCount")
    last_error: Optional[str] = Field(default=None, serialization_alias="lastError")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")


class PushWebhookDeliveryAttemptItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    attempt_number: int = Field(serialization_alias="attemptNumber")
    http_status: Optional[int] = Field(default=None, serialization_alias="httpStatus")
    response_body_preview: Optional[str] = Field(default=None, serialization_alias="responseBodyPreview")
    error_message: Optional[str] = Field(default=None, serialization_alias="errorMessage")
    latency_ms: Optional[int] = Field(default=None, serialization_alias="latencyMs")
    attempted_at: Optional[datetime] = Field(default=None, serialization_alias="attemptedAt")


class PushWebhookDeliveryEventDetailResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    subscription_id: str = Field(serialization_alias="subscriptionId")
    event_type: str = Field(serialization_alias="eventType")
    status: str
    payload: Dict[str, Any]
    attempt_count: int = Field(serialization_alias="attemptCount")
    next_retry_at: Optional[datetime] = Field(default=None, serialization_alias="nextRetryAt")
    last_error: Optional[str] = Field(default=None, serialization_alias="lastError")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")
    attempts: List[PushWebhookDeliveryAttemptItem] = Field(default_factory=list)


class CompatibilityCheckResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    overall: str
    base_revision_id: str = Field(serialization_alias="baseRevisionId")
    head_revision_id: str = Field(serialization_alias="headRevisionId")
    findings: List[CompatibilityFindingOut]
    rule_hits: Dict[str, int] = Field(
        default_factory=dict,
        serialization_alias="ruleHits",
        description="Count of findings per rule id (deterministic classification; #2589).",
    )
    breaking_change_documentation_issue_url: Optional[str] = Field(
        default=None,
        serialization_alias="breakingChangeDocumentationIssueUrl",
    )
    report_fingerprint: str = Field(serialization_alias="reportFingerprint")
    tenant_compat_gate_active: bool = Field(
        default=False,
        serialization_alias="tenantCompatGateActive",
        description="True when project metadata requests merge-time compat gating.",
    )
    merge_blocked_by_compat_gate: bool = Field(
        default=False,
        serialization_alias="mergeBlockedByCompatGate",
        description="True when tenant gate is on and the revision pair is not fully safe.",
    )
    deprecation_warnings: List[RevisionDeprecationWarningOut] = Field(
        default_factory=list,
        serialization_alias="deprecationWarnings",
    )
    deprecated_revision_blocked: bool = Field(
        default=False,
        serialization_alias="deprecatedRevisionBlocked",
        description="True when project metadata requests strict deprecation handling and a revision is deprecated.",
    )


class LintFindingOut(BaseModel):
    """One itemized lint finding from the deterministic quality-scoring service (#3609)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    path: str
    category: str
    rule: str
    severity: str
    message: str


class LintReportResponse(BaseModel):
    """Server-computed quality score + itemized findings for one project version (#3609)."""

    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(serialization_alias="projectId")
    version_record_id: str = Field(serialization_alias="versionRecordId")
    version_id: str = Field(
        serialization_alias="versionId",
        description="Human-readable version label (e.g. 1.0.0).",
    )
    score: int = Field(description="Deterministic 0-100 quality score.")
    grade: str = Field(description="A-F letter grade derived from the score.")
    findings: List[LintFindingOut]
    rule_hits: Dict[str, int] = Field(
        default_factory=dict,
        serialization_alias="ruleHits",
        description="Count of findings per rule id (deterministic).",
    )
    severity_counts: Dict[str, int] = Field(
        default_factory=dict,
        serialization_alias="severityCounts",
        description="Count of findings per severity (error/warning/info).",
    )
    report_fingerprint: str = Field(
        serialization_alias="reportFingerprint",
        description="Stable hash over score, grade, and findings for a fixed input.",
    )
    base_revision_id: Optional[str] = Field(
        default=None,
        serialization_alias="baseRevisionId",
        description="Base revision used for breaking-change comparison, when provided.",
    )
    compatibility_overall: Optional[str] = Field(
        default=None,
        serialization_alias="compatibilityOverall",
        description="Compatibility verdict vs base revision (safe/breaking/unknown), when compared.",
    )


class VersionTagSchema(BaseModel):
    """Git-like tag pointing at a schema revision (versions.id)."""

    id: str
    project_id: str
    version_id: str
    name: str
    message: Optional[str] = None
    channel: Optional[str] = None
    immutable: bool = False
    protected: bool = False
    created_by: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None
    target_version_string: Optional[str] = None

    class Config:
        from_attributes = True


class VersionTagCreateRequest(BaseModel):
    """Create a named tag at a revision."""

    version_id: str
    name: str
    message: Optional[str] = None
    channel: Optional[str] = None
    immutable: Optional[bool] = False
    protected: Optional[bool] = False

    class Config:
        from_attributes = True


class VersionTagUpdateRequest(BaseModel):
    """Move tag to another revision and/or lock it."""

    version_id: Optional[str] = None
    immutable: Optional[bool] = None
    protected: Optional[bool] = None

    class Config:
        from_attributes = True


# ==================== Project Property Models ====================

class ProjectPropertySchema(BaseModel):
    """Pydantic model for a project property (library property)."""
    id: str
    project_id: str
    name: str
    description: Optional[str] = None
    data: Dict[str, Any]
    enabled: bool = True
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class ProjectPropertyCreateRequest(BaseModel):
    """Request model for creating a project property."""
    name: str
    description: Optional[str] = None
    data: Dict[str, Any]

    class Config:
        from_attributes = True


class ProjectPropertyUpdateRequest(BaseModel):
    """Request model for updating a project property."""
    name: Optional[str] = None
    description: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    enabled: Optional[bool] = None

    class Config:
        from_attributes = True


# ==================== Path Models ====================

class PathSchema(BaseModel):
    """Pydantic model for a path."""
    id: str
    version_id: str
    pathname: str
    metadata: Optional[Dict[str, Any]] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class PathCreateRequest(BaseModel):
    """Request model for creating a path."""
    pathname: str
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class PathUpdateRequest(BaseModel):
    """Request model for updating a path."""
    pathname: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class PathsCanvasViewport(BaseModel):
    """React Flow viewport for Paths designer canvas (#2642)."""

    x: float = 0
    y: float = 0
    zoom: float = 1


class PathsCanvasPayload(BaseModel):
    """Persisted React Flow graph snapshot (layout only; path/ops remain in OpenAPI tables)."""

    nodes: List[Any] = Field(default_factory=list)
    edges: List[Any] = Field(default_factory=list)
    viewport: PathsCanvasViewport = Field(default_factory=PathsCanvasViewport)

    class Config:
        from_attributes = True


class OperationSchema(BaseModel):
    """Pydantic model for a path operation."""
    id: str
    version_path_id: str
    operation: str
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class OperationCreateRequest(BaseModel):
    """Request model for creating an operation."""
    operation: str  # GET, POST, PUT, PATCH, DELETE, etc.
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class OperationUpdateRequest(BaseModel):
    """Request model for updating an operation."""
    operation: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class OperationDescriptionSchema(BaseModel):
    """Pydantic model for operation description."""
    id: str
    path_operation_id: str
    summary: Optional[str] = None
    description: Optional[str] = None
    operation_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class OperationDescriptionRequest(BaseModel):
    """Request model for operation description."""
    summary: Optional[str] = None
    description: Optional[str] = None
    operation_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None  # Contains tags, deprecated, externalDocs

    class Config:
        from_attributes = True


class SharedParameterSchema(BaseModel):
    """Pydantic model for a shared path parameter."""
    id: str
    version_path_id: str
    name: str
    in_location: str  # path, query, header, cookie
    summary: Optional[str] = None
    description: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class SharedParameterCreateRequest(BaseModel):
    """Request model for creating a shared parameter."""
    name: str
    in_location: str  # path, query, header, cookie
    summary: Optional[str] = None
    description: Optional[str] = None
    data: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class SharedRequestBodySchema(BaseModel):
    """Pydantic model for a shared request body."""
    id: str
    version_path_id: str
    name: str
    description: Optional[str] = None
    required: bool = True
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class SharedRequestBodyCreateRequest(BaseModel):
    """Request model for creating a shared request body."""
    name: str
    description: Optional[str] = None
    required: bool = True

    class Config:
        from_attributes = True


class RequestBodyContentTypeRequest(BaseModel):
    """Request model for adding a content type to a request body."""
    media_type: str  # e.g., application/json
    class_id: Optional[str] = None  # Reference to existing class
    inline_schema: Optional[Dict[str, Any]] = None  # Or inline schema
    encoding: Optional[Dict[str, Any]] = None
    examples: Optional[List[Dict[str, Any]]] = None

    class Config:
        from_attributes = True


class SharedResponseSchema(BaseModel):
    """Pydantic model for a shared response."""
    id: str
    version_path_id: str
    status_code: str
    description: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    class_id: Optional[str] = None
    inline_schema: Optional[Dict[str, Any]] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class SharedResponseCreateRequest(BaseModel):
    """Request model for creating a shared response."""
    status_code: str
    description: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    class_id: Optional[str] = None
    inline_schema: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class ResponseContentTypeRequest(BaseModel):
    """Request model for adding a content type to a response."""
    media_type: str
    class_id: Optional[str] = None
    inline_schema: Optional[Dict[str, Any]] = None
    examples: Optional[List[Dict[str, Any]]] = None

    class Config:
        from_attributes = True


class LinkOperationRequest(BaseModel):
    """Request model for linking entities to operations."""
    metadata: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class CopyClassToInlineSchemaRequest(BaseModel):
    """Request model for copying class properties to inline schema."""
    class_id: str

    class Config:
        from_attributes = True


# ==================== Database Data Storage (class_schema, data_record, data_snapshot) ====================

class FrozenClassSchemaModel(BaseModel):
    """Pydantic model for odb.class_schema (frozen JSON Schema 2020-12 per class per version)."""
    id: str
    version_id: str
    class_id: str
    schema: Dict[str, Any]
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class DataRecordModel(BaseModel):
    """Pydantic model for odb.data_record (event log: created/updated/deleted/restored per logical record)."""
    id: str
    record_id: str
    class_schema_id: str
    action: Literal["created", "updated", "deleted", "restored"]
    record_sequence: int
    data: Optional[Dict[str, Any]] = None
    tenant_id: str
    created_at: Optional[Union[datetime, str]] = None
    created_by: Optional[str] = None

    class Config:
        from_attributes = True


class DataSnapshotModel(BaseModel):
    """Pydantic model for odb.data_snapshot (current state per logical record)."""
    record_id: str
    class_schema_id: str
    data: Dict[str, Any]
    tenant_id: str
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


# ==================== Workflow audit (git-like ledger, #2578) ====================


class WorkflowAuditEntryOut(BaseModel):
    """One row from odb.workflow_audit (newest-first list endpoint)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    tenant_id: str = Field(serialization_alias="tenantId")
    project_id: Optional[str] = Field(None, serialization_alias="projectId")
    version_id: Optional[str] = Field(None, serialization_alias="versionId")
    action: str
    outcome: str
    actor_id: Optional[str] = Field(None, serialization_alias="actorId")
    detail: Optional[Dict[str, Any]] = None
    created_at: str = Field(serialization_alias="createdAt")


class WorkflowAuditPaginationOut(BaseModel):
    """Offset and/or cursor pagination metadata."""

    model_config = ConfigDict(populate_by_name=True)

    limit: int
    total: int
    has_more: bool = Field(serialization_alias="hasMore")
    offset: Optional[int] = Field(
        None,
        description="Effective offset for this page (offset mode only).",
    )
    next_offset: Optional[int] = Field(
        None,
        serialization_alias="nextOffset",
        description="Pass as offset for the next page when hasMore is true (offset mode).",
    )
    next_cursor: Optional[str] = Field(
        None,
        serialization_alias="nextCursor",
        description="Opaque cursor for the next page when hasMore is true (cursor mode).",
    )


class WorkflowAuditPageResponse(BaseModel):
    """Stable JSON envelope for GET .../workflow-audit (schemaVersion bumps on breaking changes)."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = Field(
        default=1,
        serialization_alias="schemaVersion",
        description="Bumped only when item or pagination shape changes incompatibly.",
    )
    items: List[WorkflowAuditEntryOut]
    pagination: WorkflowAuditPaginationOut


# ==================== Registry audit log (7.4, #3481) ====================


class RegistryAuditEntryOut(BaseModel):
    """One row from odb.registry_audit (newest-first list endpoint)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    tenant_id: str = Field(serialization_alias="tenantId")
    primitive_id: Optional[str] = Field(None, serialization_alias="primitiveId")
    schema_id: Optional[str] = Field(None, serialization_alias="schemaId")
    namespace: Optional[str] = None
    action: str
    outcome: str
    actor_id: Optional[str] = Field(None, serialization_alias="actorId")
    detail: Optional[Dict[str, Any]] = None
    created_at: str = Field(serialization_alias="createdAt")


class RegistryAuditPaginationOut(BaseModel):
    """Offset and/or cursor pagination metadata for the registry audit log."""

    model_config = ConfigDict(populate_by_name=True)

    limit: int
    total: int
    has_more: bool = Field(serialization_alias="hasMore")
    offset: Optional[int] = Field(
        None,
        description="Effective offset for this page (offset mode only).",
    )
    next_offset: Optional[int] = Field(
        None,
        serialization_alias="nextOffset",
        description="Pass as offset for the next page when hasMore is true (offset mode).",
    )
    next_cursor: Optional[str] = Field(
        None,
        serialization_alias="nextCursor",
        description="Opaque cursor for the next page when hasMore is true (cursor mode).",
    )


class RegistryAuditPageResponse(BaseModel):
    """Stable JSON envelope for GET /v1/primitives/{tenant_slug}/audit (schemaVersion bumps on breaking changes)."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = Field(
        default=1,
        serialization_alias="schemaVersion",
        description="Bumped only when item or pagination shape changes incompatibly.",
    )
    items: List[RegistryAuditEntryOut]
    pagination: RegistryAuditPaginationOut


# ==================== Repository refresh history (RAR-5.3, #3534) ====================


class RefreshHistoryEntryOut(BaseModel):
    """One refresh-cycle audit row, projected from ``odb.workflow_audit`` (RAR-5.3).

    Hoists the refresh-specific facets the cycle stored in the audit row's ``detail``
    JSONB — trigger, file lineage, decision, outcome, and the version / change-report
    links — to first-class fields so the refresh history is self-describing. The raw
    ``detail`` is preserved for any extra context.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    repository_id: Optional[str] = Field(None, serialization_alias="repositoryId")
    branch: Optional[str] = None
    path: Optional[str] = None
    trigger: Optional[str] = Field(
        None, description="scheduled | manual | webhook"
    )
    decision: Optional[str] = Field(
        None, description="RAR-2.2 freshness reason code, when known."
    )
    outcome: Optional[str] = Field(
        None, description="new-version | unchanged | diverged | failed"
    )
    project_id: Optional[str] = Field(None, serialization_alias="projectId")
    version_id: Optional[str] = Field(None, serialization_alias="versionId")
    parent_version_id: Optional[str] = Field(
        None, serialization_alias="parentVersionId"
    )
    change_report_id: Optional[str] = Field(
        None,
        serialization_alias="changeReportId",
        description="Change report documenting the refresh diff (RAR-4.3), when any.",
    )
    source_commit_sha: Optional[str] = Field(
        None, serialization_alias="sourceCommitSha"
    )
    actor_id: Optional[str] = Field(None, serialization_alias="actorId")
    detail: Optional[Dict[str, Any]] = None
    created_at: str = Field(serialization_alias="createdAt")


class RefreshHistoryPaginationOut(BaseModel):
    """Offset pagination metadata for the refresh-history list."""

    model_config = ConfigDict(populate_by_name=True)

    limit: int
    total: int
    offset: int
    has_more: bool = Field(serialization_alias="hasMore")
    next_offset: Optional[int] = Field(
        None,
        serialization_alias="nextOffset",
        description="Pass as offset for the next page when hasMore is true.",
    )


class RefreshHistoryPageResponse(BaseModel):
    """Stable JSON envelope for GET .../repositories/{id}/refresh-history (RAR-5.3)."""

    model_config = ConfigDict(populate_by_name=True)

    schema_version: int = Field(
        default=1,
        serialization_alias="schemaVersion",
        description="Bumped only when item or pagination shape changes incompatibly.",
    )
    items: List[RefreshHistoryEntryOut]
    pagination: RefreshHistoryPaginationOut


# ==================== OpenAPI semantic change report (CR-01, #2699) ====================


class OpenApiChangeReportRequest(BaseModel):
    """Two resolved OpenAPI 3.x JSON documents for semantic comparison."""

    model_config = ConfigDict(populate_by_name=True)

    baseline_open_api: Dict[str, Any] = Field(
        ...,
        validation_alias=AliasChoices("baselineOpenApi", "baseline_open_api"),
        description="Older / baseline resolved OpenAPI JSON.",
    )
    candidate_open_api: Dict[str, Any] = Field(
        ...,
        validation_alias=AliasChoices("candidateOpenApi", "candidate_open_api"),
        description="Newer / candidate resolved OpenAPI JSON.",
    )


class SchemasChangeSection(BaseModel):
    """Component schema name changes (``components.schemas``)."""

    model_config = ConfigDict(populate_by_name=True)

    added: List[Dict[str, str]]
    removed: List[Dict[str, str]]
    modified: List[Dict[str, str]]


class ChangeReportModel(BaseModel):
    """
    Versioned semantic diff between two resolved OpenAPI documents.
    ``schemaVersion`` bumps when this JSON shape changes incompatibly.
    """

    model_config = ConfigDict(populate_by_name=True)

    schema_version: str = Field(
        serialization_alias="schemaVersion",
        validation_alias=AliasChoices("schemaVersion", "schema_version"),
    )
    schemas: SchemasChangeSection
    properties: List[Dict[str, Any]]
    references: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    documentation: List[Dict[str, Any]]
    warnings: List[Dict[str, Any]]
    skipped: List[Dict[str, Any]]


# ==================== Persisted change report per revision (CR-02, #2700) ====================


class VersionChangeReportOut(BaseModel):
    """Stored change report row plus effective (edited-over-rendered) snapshots."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    tenant_id: str = Field(serialization_alias="tenantId")
    project_id: str = Field(serialization_alias="projectId")
    published_revision_id: str = Field(serialization_alias="publishedRevisionId")
    baseline_revision_id: Optional[str] = Field(None, serialization_alias="baselineRevisionId")
    change_model_json: Dict[str, Any] = Field(serialization_alias="changeModelJson")
    rendered_body: Optional[str] = Field(None, serialization_alias="renderedBody")
    header_snapshot: Optional[str] = Field(None, serialization_alias="headerSnapshot")
    footnote_snapshot: Optional[str] = Field(None, serialization_alias="footnoteSnapshot")
    edited_rendered_body: Optional[str] = Field(None, serialization_alias="editedRenderedBody")
    edited_header_snapshot: Optional[str] = Field(None, serialization_alias="editedHeaderSnapshot")
    edited_footnote_snapshot: Optional[str] = Field(None, serialization_alias="editedFootnoteSnapshot")
    effective_rendered_body: Optional[str] = Field(None, serialization_alias="effectiveRenderedBody")
    effective_header_snapshot: Optional[str] = Field(None, serialization_alias="effectiveHeaderSnapshot")
    effective_footnote_snapshot: Optional[str] = Field(None, serialization_alias="effectiveFootnoteSnapshot")
    edited_at: Optional[str] = Field(None, serialization_alias="editedAt")
    edited_by: Optional[str] = Field(None, serialization_alias="editedBy")
    template_version_id: Optional[str] = Field(None, serialization_alias="templateVersionId")
    rendered_at: Optional[str] = Field(None, serialization_alias="renderedAt")
    regenerated_at: Optional[str] = Field(None, serialization_alias="regeneratedAt")
    created_at: Optional[str] = Field(None, serialization_alias="createdAt")
    updated_at: Optional[str] = Field(None, serialization_alias="updatedAt")


class VersionChangeReportPatch(BaseModel):
    """PATCH user edits as full snapshots per field (null in JSON clears that override)."""

    model_config = ConfigDict(populate_by_name=True)

    edited_rendered_body: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("editedRenderedBody", "edited_rendered_body"),
    )
    edited_header_snapshot: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("editedHeaderSnapshot", "edited_header_snapshot"),
    )
    edited_footnote_snapshot: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("editedFootnoteSnapshot", "edited_footnote_snapshot"),
    )
    clear_edits: Optional[bool] = Field(
        None,
        validation_alias=AliasChoices("clearEdits", "clear_edits"),
        description="When true, remove all user edit snapshots and clear editedAt/editedBy.",
    )


class VersionChangeReportRegenerateRequest(BaseModel):
    """Optional template version id; effective template resolved per CR-03."""

    model_config = ConfigDict(populate_by_name=True)

    template_version_id: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("templateVersionId", "template_version_id"),
    )
    discard_user_edits: bool = Field(
        True,
        validation_alias=AliasChoices("discardUserEdits", "discard_user_edits"),
    )


# ==================== Change report templates (CR-03, #2701) ====================


class ChangeReportTemplateVersionSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    semver: str
    owner_tenant_id: Optional[str] = Field(None, serialization_alias="ownerTenantId")
    created_at: Optional[str] = Field(None, serialization_alias="createdAt")


class ChangeReportTemplateVersionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    semver: str
    owner_tenant_id: Optional[str] = Field(None, serialization_alias="ownerTenantId")
    header_template: str = Field(serialization_alias="headerTemplate")
    body_template: str = Field(serialization_alias="bodyTemplate")
    footnote_template: str = Field(serialization_alias="footnoteTemplate")
    created_at: Optional[str] = Field(None, serialization_alias="createdAt")
    created_by: Optional[str] = Field(None, serialization_alias="createdBy")


class ChangeReportTemplateVersionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    semver: str
    header_template: str = Field(
        ...,
        validation_alias=AliasChoices("headerTemplate", "header_template"),
    )
    body_template: str = Field(
        ...,
        validation_alias=AliasChoices("bodyTemplate", "body_template"),
    )
    footnote_template: str = Field(
        ...,
        validation_alias=AliasChoices("footnoteTemplate", "footnote_template"),
    )


class ChangeReportTemplateDefaultPut(BaseModel):
    """Set tenant or project default template pointer; null clears override."""

    model_config = ConfigDict(populate_by_name=True)

    template_version_id: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("templateVersionId", "template_version_id"),
    )


class TenantRepositoryCreate(BaseModel):
    """Dashboard: register a Git repository under a tenant."""

    model_config = ConfigDict(populate_by_name=True)

    source: Literal["public_url", "linked_account"]
    clone_url: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("cloneUrl", "clone_url"),
    )
    linked_account_id: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("linkedAccountId", "linked_account_id"),
    )
    repository_full_name: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("repositoryFullName", "repository_full_name"),
    )

    @model_validator(mode="after")
    def _require_fields_for_source(self) -> "TenantRepositoryCreate":
        if self.source == "public_url":
            if self.clone_url is None or not str(self.clone_url).strip():
                raise ValueError("clone_url is required when source is public_url")
        elif self.source == "linked_account":
            if self.linked_account_id is None or not str(self.linked_account_id).strip():
                raise ValueError("linked_account_id is required when source is linked_account")
            if self.repository_full_name is None or not str(self.repository_full_name).strip():
                raise ValueError("repository_full_name is required when source is linked_account")
        return self


class TenantRepositoryRecord(BaseModel):
    """Single repository row returned to the UI (snake_case keys for the dashboard)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    full_name: str
    description: Optional[str] = None
    provider: str
    default_branch: str
    visibility: Optional[str] = None
    status: str
    clone_url: Optional[str] = None
    source: Optional[str] = None
    last_scanned_at: Optional[str] = None
    total_files: Optional[int] = None
    importable_count: Optional[int] = None
    branch_count: Optional[int] = None
    # Per-repo auto-refresh opt-out (RAR-3.3, #3524). True = sweep may refresh this
    # repo on its cadence; False = the sweep skips it. Defaults to True for repos
    # whose row predates the column.
    auto_refresh_enabled: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TenantRepositoryUpdate(BaseModel):
    """Dashboard: patch mutable settings on a registered repository (RAR-3.3).

    Only fields present in the request body are applied. Currently the per-repo
    auto-refresh toggle (``auto_refresh_enabled``); accepts both the snake_case and
    camelCase spellings so the UI can send either.
    """

    model_config = ConfigDict(populate_by_name=True)

    auto_refresh_enabled: Optional[bool] = Field(
        None,
        validation_alias=AliasChoices("autoRefreshEnabled", "auto_refresh_enabled"),
    )


class RepositoryRefreshNowRequest(BaseModel):
    """Dashboard: trigger a one-shot manual "Refresh Now" (RAR-5.2, #3533).

    Both fields are optional and accept snake_case or camelCase so the UI can
    send either:

    - omit both → refresh the whole repository (every branch with a stored spec);
    - ``branch`` only → refresh that branch;
    - ``path`` (with or without ``branch``) → refresh that single file.
    """

    model_config = ConfigDict(populate_by_name=True)

    path: Optional[str] = Field(None)
    branch: Optional[str] = Field(None)


class RepositoryRefreshNowResponse(BaseModel):
    """Result of a one-shot manual refresh (RAR-5.2)."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    enqueued: int
    skipped: int
    branches: List[str]


class TenantRepositoriesListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    repositories: List[TenantRepositoryRecord]


class TenantRepositoryCreateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    repository: TenantRepositoryRecord


class TenantRepositoryGetResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    repository: TenantRepositoryRecord


class TenantRepositoryFileRow(BaseModel):
    """One indexed file path for the repository Files browser."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    path: str
    name: str
    ext: Optional[str] = None
    size_bytes: Optional[int] = None
    blob_sha: Optional[str] = None
    detected_kind: Optional[str] = None
    display_kind: str
    confidence: str = "filename"


class TenantRepositoryFilesListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    branch: str
    branches: List[str]
    indexed_total: int
    match_count: int
    importable_match_count: int
    limit: int
    offset: int
    files: List[TenantRepositoryFileRow]


class TenantRepositoryFileContentResponse(BaseModel):
    """On-demand file body for the repository file detail UI (GitHub-backed repos)."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    path: str
    branch: str
    display_kind: str
    confidence: str = "filename"
    blob_sha: Optional[str] = None
    size_bytes: Optional[int] = None
    content: str
    truncated: bool = False


# --- CLI / session tenant discovery (#3198) ---


class TenantMembershipSchema(BaseModel):
    """One tenant the authenticated user may access."""

    slug: str
    name: str
    role: str


class TenantsMeResponse(BaseModel):
    """Paginated list of tenants for the current principal (JWT user or API key tenant)."""

    items: List[TenantMembershipSchema]
    total: int
    limit: int
    offset: int


class TenantInfoResponse(BaseModel):
    """Tenant summary for ``GET /v1/tenants/{slug}``."""

    slug: str
    name: str
    plan: Optional[str] = None
    created_at: Optional[str] = None
    members_count: int = 0
    projects_count: int = 0
    versions_count: int = 0
    published_versions_count: int = 0
    storage_used_bytes: Optional[int] = None
    storage_quota_bytes: Optional[int] = None


class BrowseDirectoryStats(BaseModel):
    """Aggregate counts for published public specs (browse directory home)."""

    tenant_count: int
    project_count: int
    version_count: int


class BrowsePublicTenantRow(BaseModel):
    """One tenant row in the public browse directory."""

    slug: str
    name: str
    project_count: int
    published_versions: int
    latest_version: Optional[str] = None
    latest_activity_at: Optional[datetime] = None


class BrowsePublicTenantsResponse(BaseModel):
    """Public tenant directory for CLI and integrations (no authentication)."""

    directory_stats: BrowseDirectoryStats
    tenants: List[BrowsePublicTenantRow]
    filtered_count: int


class BrowsePublicProjectRow(BaseModel):
    """One project row for public browse (per tenant)."""

    slug: str
    name: str
    domain: str
    published_versions: int
    latest_version: Optional[str] = None
    latest_published_at: Optional[datetime] = None


class BrowsePublicProjectsResponse(BaseModel):
    """Published-public projects for a tenant (anonymous), or full tenant project list for members."""

    tenant_slug: str
    tenant_name: str
    projects: List[BrowsePublicProjectRow]
    filtered_count: int


class BrowsePublicVersionRow(BaseModel):
    """One published version row for public browse (per project)."""

    id: str
    version_id: str
    published_at: Optional[datetime] = None
    tags: List[str]
    changes_summary: Optional[str] = None
    description: Optional[str] = None
    change_log: Optional[str] = None


class BrowsePublicVersionsResponse(BaseModel):
    """Published versions for browse parity (anonymous public slice or member-authenticated view)."""

    tenant_slug: str
    tenant_name: str
    project_slug: str
    project_name: str
    versions: List[BrowsePublicVersionRow]
    filtered_count: int


# ---------------------------------------------------------------------------
# Mock Server (#3615, RC1-2.2)
# ---------------------------------------------------------------------------


class MockScenarioRule(BaseModel):
    """One per-operation override inside a scenario: status code, latency, and/or response body.

    A rule targets an operation by ``operation`` ("METHOD /template", or "*" for every operation) or
    by separate ``method`` / ``path`` fields. Any subset of (``status``, ``latency_ms``, ``body``)
    may be set; unset axes fall back to the generated success response.
    """

    model_config = ConfigDict(populate_by_name=True)

    operation: Optional[str] = Field(
        default=None,
        description='Target operation as "METHOD /template" (e.g. "GET /pets/{petId}"), or "*".',
    )
    method: Optional[str] = None
    path: Optional[str] = None
    status: Optional[int] = Field(default=None, ge=100, le=599)
    latency_ms: Optional[int] = Field(
        default=None,
        ge=0,
        serialization_alias="latencyMs",
        validation_alias=AliasChoices("latencyMs", "latency_ms"),
    )
    body: Optional[Any] = Field(default=None, description="Verbatim response body override.")


class MockScenario(BaseModel):
    """A named, selectable set of per-operation overrides."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: Optional[str] = ""
    rules: List[MockScenarioRule] = Field(default_factory=list)


class MockProvisionRequest(BaseModel):
    """Request body to provision a mock instance from a published version."""

    model_config = ConfigDict(populate_by_name=True)

    project_slug: str = Field(validation_alias=AliasChoices("projectSlug", "project_slug"))
    version_slug: str = Field(validation_alias=AliasChoices("versionSlug", "version_slug"))
    name: Optional[str] = Field(default=None, description="Display name; defaults to the coordinates.")
    ttl_hours: Optional[int] = Field(
        default=None,
        ge=1,
        validation_alias=AliasChoices("ttlHours", "ttl_hours"),
        description="Auto-expiry in hours; clamped to the configured maximum.",
    )
    rate_limit_per_minute: Optional[int] = Field(
        default=None,
        ge=1,
        validation_alias=AliasChoices("rateLimitPerMinute", "rate_limit_per_minute"),
    )
    seed: Optional[int] = Field(default=None, description="Deterministic data-generation seed.")
    scenarios: Optional[List[MockScenario]] = None
    active_scenario: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("activeScenario", "active_scenario"),
    )


class MockScenarioSwitchRequest(BaseModel):
    """Request body to switch a mock instance's active scenario."""

    model_config = ConfigDict(populate_by_name=True)

    active_scenario: str = Field(validation_alias=AliasChoices("activeScenario", "active_scenario"))


class MockInstanceResponse(BaseModel):
    """Public view of a provisioned mock instance."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    base_url: str = Field(serialization_alias="baseUrl")
    tenant_slug: str = Field(serialization_alias="tenantSlug")
    project_slug: str = Field(serialization_alias="projectSlug")
    version_slug: str = Field(serialization_alias="versionSlug")
    status: str
    active_scenario: str = Field(serialization_alias="activeScenario")
    scenarios: List[str]
    operation_count: int = Field(serialization_alias="operationCount")
    rate_limit_per_minute: int = Field(serialization_alias="rateLimitPerMinute")
    request_count: int = Field(serialization_alias="requestCount")
    created_at: Optional[str] = Field(default=None, serialization_alias="createdAt")
    expires_at: Optional[str] = Field(default=None, serialization_alias="expiresAt")
    last_activity_at: Optional[str] = Field(default=None, serialization_alias="lastActivityAt")


# ---------------------------------------------------------------------------
# MCP Catalog — endpoint registration & management (V2-MCP-17.1 / MCAT-3.1, #3663)
# ---------------------------------------------------------------------------

# MCP transports a catalog endpoint may speak, mirroring the
# ``mcp_endpoints_transport_check`` constraint in V126 (and the MCP transports spec).
MCP_ENDPOINT_TRANSPORTS = ("streamable_http", "sse", "stdio")

# Transports whose ``endpoint_url`` is a network URL (and so must be http/https). ``stdio``
# is excluded: its ``endpoint_url`` is a local command target, not a URL, so the URL scheme
# rules below do not apply to it.
MCP_ENDPOINT_URL_TRANSPORTS = frozenset({"streamable_http", "sse"})

# Catalog visibility reuses the ``visibility_type`` enum (V006).
MCP_ENDPOINT_VISIBILITIES = ("private", "public")

# Cadence bounds for periodic re-discovery (seconds). The floor keeps the scheduler from
# hammering an external server faster than once a minute; the ceiling (30 days) keeps a
# cadence meaningful as "automatic" rather than effectively never. The DB only enforces
# ``> 0`` (V126); these tighten that at the API boundary.
MCP_DISCOVERY_CADENCE_MIN_SECONDS = 60
MCP_DISCOVERY_CADENCE_MAX_SECONDS = 30 * 24 * 60 * 60  # 2_592_000 (30 days)

# Hosts for which plaintext ``http`` is tolerated in development (loopback only).
_MCP_LOOPBACK_HOSTNAMES = frozenset({"localhost"})

# Upper bound on a stored endpoint URL; TEXT in the DB, but a multi-kilobyte URL is
# pathological and worth rejecting early.
_MCP_ENDPOINT_URL_MAX_LENGTH = 2048


def _is_loopback_host(hostname: Optional[str]) -> bool:
    """True when ``hostname`` is the local loopback (``localhost`` or a loopback IP)."""
    if not hostname:
        return False
    host = hostname.strip().lower()
    if host in _MCP_LOOPBACK_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def validate_mcp_endpoint_url(url: str, transport: Optional[str] = None) -> None:
    """Validate a catalog endpoint URL, raising ``ValueError`` when it is unacceptable.

    Two rules are enforced:

    * **Scheme by transport** — for an HTTP-family transport (``streamable_http`` / ``sse``)
      the value must be an ``http``/``https`` URL with a host. ``stdio`` (or an unknown
      ``transport`` on a partial update) targets a local command, so this check is skipped.
    * **No plaintext to remote hosts** — whenever the value *is* an ``http`` URL, it is
      rejected unless the host is loopback (``localhost``/``127.0.0.1``/``::1``) *and* the
      service is not running in production. ``https`` is always accepted. This guard runs
      regardless of ``transport`` so a URL-only PATCH cannot smuggle in plaintext.

    Args:
        url: The endpoint URL (or command target) to validate.
        transport: The endpoint's transport, when known. ``None`` on a partial update that
            does not change the transport — only the transport-independent plaintext guard
            then applies.

    Raises:
        ValueError: When the URL is blank, malformed for its transport, or uses plaintext
            ``http`` to a non-loopback host.
    """
    candidate = (url or "").strip()
    if not candidate:
        raise ValueError("endpoint_url must not be blank")

    parts = urlsplit(candidate)
    scheme = parts.scheme.lower()

    if transport in MCP_ENDPOINT_URL_TRANSPORTS:
        if scheme not in ("http", "https"):
            raise ValueError(
                f"endpoint_url must be an http(s) URL for the {transport} transport"
            )
        if not parts.hostname:
            raise ValueError("endpoint_url must include a host")

    if scheme == "http":
        if not parts.hostname:
            raise ValueError("endpoint_url must include a host")
        if settings.is_production or not _is_loopback_host(parts.hostname):
            raise ValueError(
                "endpoint_url must use https (plaintext http is allowed only for "
                "localhost in development)"
            )


def redact_url_credentials(url: Optional[str]) -> Optional[str]:
    """Mask any ``user:password@`` userinfo embedded in a URL's authority.

    Some MCP servers carry a token in the URL (``https://tok@host/...``). The catalog stores
    the URL verbatim for discovery to use, but the wire model must never echo the secret back
    to a client, so the userinfo is replaced with ``***`` while host, port, path, and query
    are preserved exactly. URLs without an authority/userinfo (e.g. ``stdio`` command targets)
    are returned unchanged.
    """
    if not url:
        return url
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    host_port = parts.netloc.rsplit("@", 1)[1]
    redacted_netloc = f"***@{host_port}"
    return urlunsplit(
        (parts.scheme, redacted_netloc, parts.path, parts.query, parts.fragment)
    )


class McpEndpointCreate(BaseModel):
    """Register an external MCP server in a tenant's catalog (MCAT-3.1).

    ``name`` and ``endpoint_url`` are required; ``transport`` defaults to
    ``streamable_http`` (the most common HTTP transport). ``slug`` is optional —
    when omitted it is auto-derived from ``name`` and made unique within the
    tenant. Accepts both camelCase and snake_case keys so UI and CLI can share
    this model.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., min_length=1, max_length=255)
    endpoint_url: str = Field(
        ...,
        min_length=1,
        max_length=_MCP_ENDPOINT_URL_MAX_LENGTH,
        validation_alias=AliasChoices("endpointUrl", "endpoint_url"),
    )
    transport: str = "streamable_http"
    slug: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=255)
    visibility: str = "private"
    discovery_cadence_seconds: Optional[int] = Field(
        default=None,
        ge=MCP_DISCOVERY_CADENCE_MIN_SECONDS,
        le=MCP_DISCOVERY_CADENCE_MAX_SECONDS,
        validation_alias=AliasChoices("discoveryCadenceSeconds", "discovery_cadence_seconds"),
    )

    @model_validator(mode="after")
    def _validate_enums(self) -> "McpEndpointCreate":
        if self.transport not in MCP_ENDPOINT_TRANSPORTS:
            raise ValueError(
                f"transport must be one of {list(MCP_ENDPOINT_TRANSPORTS)}"
            )
        if self.visibility not in MCP_ENDPOINT_VISIBILITIES:
            raise ValueError(
                f"visibility must be one of {list(MCP_ENDPOINT_VISIBILITIES)}"
            )
        if not self.name.strip():
            raise ValueError("name must not be blank")
        validate_mcp_endpoint_url(self.endpoint_url, self.transport)
        return self


class McpEndpointUpdate(BaseModel):
    """Patch mutable fields on a catalog endpoint (MCAT-3.1).

    Every field is optional; only the keys present in the request body are
    applied. ``slug`` is intentionally not patchable here — it is derived on
    create and stable thereafter so existing references do not break.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    endpoint_url: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=_MCP_ENDPOINT_URL_MAX_LENGTH,
        validation_alias=AliasChoices("endpointUrl", "endpoint_url"),
    )
    transport: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = Field(default=None, max_length=255)
    visibility: Optional[str] = None
    published: Optional[bool] = None
    enabled: Optional[bool] = None
    discovery_cadence_seconds: Optional[int] = Field(
        default=None,
        ge=MCP_DISCOVERY_CADENCE_MIN_SECONDS,
        le=MCP_DISCOVERY_CADENCE_MAX_SECONDS,
        validation_alias=AliasChoices("discoveryCadenceSeconds", "discovery_cadence_seconds"),
    )

    @model_validator(mode="after")
    def _validate_enums(self) -> "McpEndpointUpdate":
        if self.transport is not None and self.transport not in MCP_ENDPOINT_TRANSPORTS:
            raise ValueError(
                f"transport must be one of {list(MCP_ENDPOINT_TRANSPORTS)}"
            )
        if self.visibility is not None and self.visibility not in MCP_ENDPOINT_VISIBILITIES:
            raise ValueError(
                f"visibility must be one of {list(MCP_ENDPOINT_VISIBILITIES)}"
            )
        if self.name is not None and not self.name.strip():
            raise ValueError("name must not be blank")
        if self.endpoint_url is not None:
            # ``transport`` may be None here (URL-only PATCH); the helper then enforces only
            # the transport-independent plaintext-http guard.
            validate_mcp_endpoint_url(self.endpoint_url, self.transport)
        return self

    def has_any_field(self) -> bool:
        """True when at least one mutable field was supplied in the request."""
        return any(
            getattr(self, f) is not None
            for f in (
                "name",
                "endpoint_url",
                "transport",
                "description",
                "category",
                "visibility",
                "published",
                "enabled",
                "discovery_cadence_seconds",
            )
        )


class McpEndpointOut(BaseModel):
    """Wire representation of one catalog endpoint (snake_case keys for UI/CLI).

    ``endpoint_url`` is credential-redacted: any ``user:password@`` userinfo embedded in the
    stored URL is masked to ``***`` before it leaves the service (see
    :func:`mcp_endpoint_out_from_row`).
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    tenant_id: str
    name: str
    slug: str
    endpoint_url: str
    transport: str
    description: Optional[str] = None
    category: Optional[str] = None
    visibility: str
    published: bool
    enabled: bool
    discovery_cadence_seconds: Optional[int] = None
    last_discovered_at: Optional[str] = None
    last_discovery_status: Optional[str] = None
    current_version_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class McpEndpointListResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoints: List[McpEndpointOut]


class McpEndpointResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint: McpEndpointOut


class McpEndpointDeleteResponse(BaseModel):
    """Outcome of soft-deleting a catalog endpoint (V2-MCP-17.5 / MCAT-3.5).

    The endpoint row is retired with a ``deleted_at`` stamp (so it disappears
    from browse but keeps its slug reserved), while its child data is purged:
    ``credentials_purged`` reports whether a stored credential row was dropped —
    the security-critical part of the teardown — and ``versions_deleted`` /
    ``jobs_deleted`` count the version snapshots (with their cascaded capability
    items, change logs and scores) and discovery jobs removed.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    credentials_purged: bool = False
    versions_deleted: int = 0
    jobs_deleted: int = 0


def mcp_endpoint_out_from_row(row: Dict[str, Any]) -> McpEndpointOut:
    """Project an ``odb.mcp_endpoints`` row onto the wire model.

    Timestamps and UUIDs are normalized to strings so the response serializes
    cleanly regardless of the driver's native column types, and any credentials
    embedded in ``endpoint_url`` are redacted (:func:`redact_url_credentials`) so a
    stored secret never reaches a client.
    """

    def _ts(value: Any) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _s(value: Any) -> Optional[str]:
        return str(value) if value is not None else None

    cadence = row.get("discovery_cadence_seconds")
    return McpEndpointOut(
        id=str(row["id"]),
        tenant_id=str(row["tenant_id"]),
        name=str(row["name"]),
        slug=str(row["slug"]),
        endpoint_url=redact_url_credentials(str(row["endpoint_url"])),
        transport=str(row["transport"]),
        description=_s(row.get("description")),
        category=_s(row.get("category")),
        visibility=str(row["visibility"]),
        published=bool(row.get("published", False)),
        enabled=bool(row.get("enabled", True)),
        discovery_cadence_seconds=int(cadence) if isinstance(cadence, int) else None,
        last_discovered_at=_ts(row.get("last_discovered_at")),
        last_discovery_status=_s(row.get("last_discovery_status")),
        current_version_id=_s(row.get("current_version_id")),
        created_at=_ts(row.get("created_at")),
        updated_at=_ts(row.get("updated_at")),
    )


# ===========================================================================
# MCP Catalog — manual discovery trigger & async jobs (V2-MCP-17.2 / MCAT-3.2)
# ===========================================================================

# Terminal + in-flight states a discovery job can report, mirroring the
# ``mcp_discovery_jobs.state`` CHECK constraint (V130).
MCP_DISCOVERY_JOB_STATES = frozenset({"queued", "running", "completed", "failed"})


class McpDiscoveryJobOut(BaseModel):
    """Wire representation of one ``mcp_discovery_jobs`` row (snake_case keys).

    ``result`` is the job's JSONB payload — on a successful run it carries
    ``version_id`` / ``version_seq`` / ``changed`` so a poller can locate the
    snapshot the run produced; on failure it carries the classified discovery
    error. ``error`` is the short human-readable failure summary, if any.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    endpoint_id: str
    tenant_id: str
    state: str
    trigger: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    result: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None


class McpDiscoveryJobResponse(BaseModel):
    """Response envelope for a single discovery job (trigger + poll)."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    # True when an already-active job was returned instead of starting a new one
    # (concurrent discover on the same endpoint is de-duplicated). Absent on reads.
    deduplicated: Optional[bool] = None
    job: McpDiscoveryJobOut


class McpDiscoveryJobListResponse(BaseModel):
    """Response envelope listing an endpoint's discovery jobs (newest first)."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    jobs: List[McpDiscoveryJobOut]


def mcp_discovery_job_out_from_row(row: Dict[str, Any]) -> McpDiscoveryJobOut:
    """Project an ``odb.mcp_discovery_jobs`` row onto the wire model.

    Timestamps and UUIDs are normalized to strings, and a missing/None ``result``
    becomes an empty object so the field always serializes as a JSON object.
    """

    def _ts(value: Any) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _s(value: Any) -> Optional[str]:
        return str(value) if value is not None else None

    result = row.get("result")
    if not isinstance(result, dict):
        result = {}
    return McpDiscoveryJobOut(
        id=str(row["id"]),
        endpoint_id=str(row["endpoint_id"]),
        tenant_id=str(row["tenant_id"]),
        state=str(row["state"]),
        trigger=str(row["trigger"]),
        started_at=_ts(row.get("started_at")),
        finished_at=_ts(row.get("finished_at")),
        error=_s(row.get("error")),
        result=result,
        created_at=_ts(row.get("created_at")),
    )


# ===========================================================================
# MCP Catalog — discovery job status/polling API (V2-MCP-17.4 / MCAT-3.4, #3666)
# ===========================================================================
#
# The canonical "follow a discovery job to completion" contract consumed by the
# CLI poller (Epic-11) and the UI. It is a thin, ergonomic projection of an
# ``mcp_discovery_jobs`` row that lifts the fields a poller needs out of the
# free-form ``result`` blob: whether the job has reached a ``terminal`` state, the
# ``version_id`` the run produced (on success), the structured ``error_detail`` (on
# failure), the run ``duration_ms``, and a ``status_path`` to re-poll.

# A poller stops once a job reports one of these terminal states; ``queued`` and
# ``running`` mean "keep polling".
MCP_DISCOVERY_TERMINAL_STATES = frozenset({"completed", "failed"})


def _parse_job_timestamp(value: Any) -> Optional[datetime]:
    """Coerce a job timestamp (datetime or ISO-8601 string) to a datetime, else None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _job_duration_ms(started: Any, finished: Any) -> Optional[int]:
    """Whole-millisecond wall-clock duration between ``started_at`` and ``finished_at``.

    Returns None when either bound is missing/unparseable, or when the interval is
    negative (clock skew) — so a duration is only ever reported for a job that has
    actually run to a finish.
    """
    start = _parse_job_timestamp(started)
    finish = _parse_job_timestamp(finished)
    if start is None or finish is None:
        return None
    delta_ms = (finish - start).total_seconds() * 1000.0
    return int(delta_ms) if delta_ms >= 0 else None


class McpDiscoveryJobStatus(BaseModel):
    """Poll snapshot for one discovery job (MCAT-3.4).

    The status contract shared by the CLI poller and UI. ``state`` is the raw
    lifecycle state (``queued`` → ``running`` → ``completed`` | ``failed``);
    ``terminal`` is True once the job has reached a final state so a poller knows to
    stop. On a successful terminal run ``version_id`` points at the snapshot the run
    produced (present even when ``changed`` is False — the surface matched the prior
    version) and ``changed`` says whether a new version was written. On a failed run
    ``error`` is a short human summary and ``error_detail`` is the structured
    discovery-error taxonomy entry. ``result`` is the full raw payload for callers
    that need more than the lifted fields.
    """

    model_config = ConfigDict(populate_by_name=True)

    job_id: str
    endpoint_id: str
    tenant_id: str
    state: str
    trigger: str
    terminal: bool = False
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    # Lifted from ``result`` on a completed run; None until then.
    version_id: Optional[str] = None
    changed: Optional[bool] = None
    # Lifted on a failed run: short summary plus the structured error taxonomy entry.
    error: Optional[str] = None
    error_detail: Optional[Dict[str, Any]] = None
    result: Dict[str, Any] = Field(default_factory=dict)
    # Relative URL to re-poll this job; populated when a tenant slug is in scope.
    status_path: Optional[str] = None


class McpDiscoveryJobStatusResponse(BaseModel):
    """Response envelope for a single discovery-job status snapshot."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    job: McpDiscoveryJobStatus


class McpDiscoveryJobStatusListResponse(BaseModel):
    """Response envelope listing an endpoint's discovery-job snapshots (newest first)."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    jobs: List[McpDiscoveryJobStatus]


def mcp_discovery_job_status_from_row(
    row: Dict[str, Any], tenant_slug: Optional[str] = None
) -> McpDiscoveryJobStatus:
    """Project an ``odb.mcp_discovery_jobs`` row onto the poll-status contract.

    Reuses :func:`mcp_discovery_job_out_from_row` for the string/timestamp
    normalization, then lifts the poller-facing fields out of the ``result`` blob
    (``version_id`` / ``changed`` on success, the structured error on failure) and
    derives ``terminal`` and ``duration_ms``. ``status_path`` — the relative URL a
    poller re-fetches — is filled in only when ``tenant_slug`` is supplied.

    Args:
        row: The ``mcp_discovery_jobs`` row as a dict.
        tenant_slug: The catalog tenant slug from the request path, used to build
            ``status_path``; omitted in contexts that do not have one.

    Returns:
        The :class:`McpDiscoveryJobStatus` snapshot for the row.
    """
    base = mcp_discovery_job_out_from_row(row)
    result = base.result if isinstance(base.result, dict) else {}

    version_id = result.get("version_id")
    changed = result.get("changed")
    raw_error = result.get("error")

    status_path = None
    if tenant_slug is not None:
        status_path = (
            f"/v1/mcp/{tenant_slug}/endpoints/{base.endpoint_id}/jobs/{base.id}"
        )

    return McpDiscoveryJobStatus(
        job_id=base.id,
        endpoint_id=base.endpoint_id,
        tenant_id=base.tenant_id,
        state=base.state,
        trigger=base.trigger,
        terminal=base.state in MCP_DISCOVERY_TERMINAL_STATES,
        created_at=base.created_at,
        started_at=base.started_at,
        finished_at=base.finished_at,
        duration_ms=_job_duration_ms(row.get("started_at"), row.get("finished_at")),
        version_id=str(version_id) if version_id is not None else None,
        changed=changed if isinstance(changed, bool) else None,
        error=base.error,
        error_detail=raw_error if isinstance(raw_error, dict) else None,
        result=result,
        status_path=status_path,
    )
