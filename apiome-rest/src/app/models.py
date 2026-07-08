import ipaddress
from datetime import datetime
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Union
from urllib.parse import urlsplit, urlunsplit

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from .config import settings
from .mcp_catalog_inventory import derive_health as derive_mcp_endpoint_health
from .mcp_change_severity import (
    SEVERITY_ADDITIVE,
    SEVERITY_BREAKING,
    SEVERITY_REVIEW,
    classify_change,
    severity_counts,
)
from .mcp_facets import (
    SAFETY_HAS_DESTRUCTIVE,
    SAFETY_READ_ONLY_ONLY,
    UNCATEGORIZED_VALUE,
    UNGRADED_VALUE,
    UNKNOWN_VALUE,
)
from .mcp_lifecycle_signals import STAGE_UNSPECIFIED, assess_capability_lifecycle
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


class TagCreateRequest(BaseModel):
    """Request model for creating a project class tag."""
    name: str
    color: str = "default"
    description: Optional[str] = None

    class Config:
        from_attributes = True


class TagUpdateRequest(BaseModel):
    """Request model for updating a project class tag."""
    name: Optional[str] = None
    color: Optional[str] = None
    description: Optional[str] = None

    class Config:
        from_attributes = True


class ClassTagAssignRequest(BaseModel):
    """Request model for assigning a tag to a class."""
    tag_id: str

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
    # to the resolved apiome.primitives row plus the stored registry $ref string.
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
    ``apiome-db`` connection backing ``apiome.primitives`` — is reachable.
    """
    status: str  # 'healthy' | 'unhealthy'
    service: str = 'primitives-registry'
    database: str = 'apiome-db'
    connection: str  # 'connected' | 'disconnected'
    storage_present: bool = False  # whether the apiome.primitives registry table is reachable
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
    import_id: Optional[str] = None  # The recorded apiome.primitive_imports row id.
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
    resolution_base_url: str = "https://api.apiome.app/types/"
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
    here mirror the ``apiome.type_registry_settings`` CHECK constraints so an invalid value is
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
# Today the dashboard runs imports via Next.js server actions (see apiome-ui/lib/db/import-helper.ts).
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
    input_kind: Optional[Literal["file", "url", "paste", "discovery", "fileset"]] = Field(
        None,
        description=(
            "How the source document reached the importer — file upload, a fetched URL, or "
            "pasted text (MFI-26.2). Recorded verbatim on the catalog revision's format metadata "
            "as 'inputKind' so the source-material badge reflects the intake method; defaults to "
            "'file' when omitted."
        ),
    )
    import_target: Optional[Literal["catalog", "types", "project"]] = Field(
        None,
        description=(
            "Explicit destination for a JSON Schema import when the MFI-26.7 prompt asked the "
            "user (MFI-26.8): 'catalog' (the default) stores a non-publishable, schemas-only "
            "catalog item kept verbatim for later conversion, while 'types'/'project' import the "
            "schema as a **current** type/schema into the type registry. Consulted only for JSON "
            "Schema sources — OpenAPI/Swagger/Arazzo always create publishable Projects and every "
            "other format always routes to the catalog, regardless of this value."
        ),
    )
    archive_root: Optional[str] = Field(
        None,
        description=(
            "When the uploaded document is a .zip/.tar.gz archive, the module-relative path of "
            "the root document inside the archive (MFI-29.1). Required when auto-detection is "
            "ambiguous; optional when a single root candidate is found."
        ),
    )


# Current envelope version for a persisted repository import spec. Bumped by
# RAR-1.4 when the stored option shape changes; readers use it to migrate older
# rows forward without losing data.
REPOSITORY_IMPORT_SPEC_SCHEMA_VERSION = 1


class RepositoryImportSpec(BaseModel):
    """Persisted import specification for one imported repository file (RAR-1.1).

    Mirrors the ``apiome.repository_import_spec`` row. Keyed to the imported-file
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
    columns the read DAO joins from ``apiome.tenant_repository_files`` — against the
    ``last_imported_*`` anchors, overlaid with the operational flags
    (``is_refreshing`` / ``last_refresh_failed`` / ``diverged``) carried on the
    row when the sweep (RAR-3/RAR-4) and divergence check (RAR-4.4) populate them.
    Deriving on read means the status is recomputed whenever its inputs change —
    the scan refreshes the remote recency columns and a finished refresh updates
    the anchors — so it is always current without a separate stored column.

    Args:
        row: A ``apiome.repository_import_spec`` row as a dict, optionally joined to
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
    captures the commit signals on the ``apiome.tenant_repository_refresh_jobs`` row;
    this model carries them from the executor through to version creation so they
    land on the new ``apiome.versions`` row.
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
    # Mean quality score across the project's non-deleted versions (#3609 follow-up). Populated from
    # scores persisted onto revisions at import; NULL when the project has no scored versions.
    quality_score: Optional[int] = Field(None, serialization_alias="qualityScore")
    quality_grade: Optional[str] = Field(None, serialization_alias="qualityGrade")
    # Count of non-deleted versions in the project (0 = empty project — no score orbs in the UI).
    versions_count: int = Field(0, serialization_alias="versionsCount")
    # Project-vs-Catalog boundary (MFI-23.1): true for publishable OpenAPI/Swagger Projects,
    # false for non-publishable catalog items. Existing projects default to publishable.
    publishable: bool = True
    # Cross-format identity group (MFI-6.4, #4410).
    identity_group_id: Optional[str] = Field(None, serialization_alias="identityGroupId")
    related_artifacts: List["RelatedArtifactRef"] = Field(
        default_factory=list, serialization_alias="relatedArtifacts"
    )
    creator_name: Optional[str] = None
    creator_email: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class CatalogConversionRef(BaseModel):
    """The latest catalog → OpenAPI conversion of a catalog item (MFI-23.11), or absent when it has
    never been converted.

    Projected from the ``apiome.conversion_provenance`` ledger (MFI-22.5): once a catalog item has been
    converted it carries a back-link to the publishable **Project** the convert job produced, so the
    Catalog card/detail can show **"Converted → {project}"**. ``reconverted`` is ``True`` when the
    latest conversion superseded a prior one (the source changed and was re-converted, appending a new
    version rather than minting a duplicate Project). ``projectName`` / ``projectSlug`` come from the
    target Project row (``None`` if it was since deleted, which ``projectDeleted`` flags), so the UI can
    render a friendly label and decide whether the link is still live.
    """

    project_id: str = Field(
        serialization_alias="projectId", description="Id of the publishable Project this item was converted into."
    )
    project_name: Optional[str] = Field(
        None, serialization_alias="projectName", description="Name of the converted Project (None if it was deleted)."
    )
    project_slug: Optional[str] = Field(
        None, serialization_alias="projectSlug", description="Slug of the converted Project (None if it was deleted)."
    )
    project_deleted: bool = Field(
        False, serialization_alias="projectDeleted", description="True when the converted Project has since been deleted."
    )
    version_id: Optional[str] = Field(
        None, serialization_alias="versionId", description="Semantic version label of the produced revision (e.g. '1.0.0')."
    )
    version_record_id: Optional[str] = Field(
        None, serialization_alias="versionRecordId", description="Row id (versions.id) of the produced revision."
    )
    reconverted: bool = Field(
        False, description="True when the latest conversion superseded a prior conversion of the source."
    )
    converted_at: Optional[Union[datetime, str]] = Field(
        None, serialization_alias="convertedAt", description="When the latest conversion was committed."
    )
    fidelity_grade: Optional[str] = Field(
        None, serialization_alias="fidelityGrade", description="A-F fidelity grade the conversion achieved (MFI-22.3)."
    )
    fidelity_tier: Optional[str] = Field(
        None, serialization_alias="fidelityTier", description="Coarse fidelity tier (high/medium/low) of the conversion."
    )

    class Config:
        from_attributes = True


class RelatedArtifactRef(BaseModel):
    """One related artifact in a cross-format API identity group (MFI-6.4, #4410).

    Projects linked manually or via conversion provenance share an ``api_identity`` group; each member
    carries enough catalog/project metadata for the Related artifacts panel (format pills, name, link
    target) without a second round-trip.
    """

    project_id: str = Field(serialization_alias="projectId")
    name: str
    slug: str
    publishable: bool = False
    source_format: Optional[str] = Field(None, serialization_alias="sourceFormat")
    protocol: Optional[str] = None
    link_source: str = Field("manual", serialization_alias="linkSource")
    deleted: bool = False

    class Config:
        from_attributes = True


class IdentitySuggestionRef(BaseModel):
    """A heuristic suggestion to link two artifacts (MFI-6.4, #4410).

    Suggestions are never auto-applied — the user must confirm a link action.
    """

    project_id: str = Field(serialization_alias="projectId")
    name: str
    slug: str
    publishable: bool = False
    source_format: Optional[str] = Field(None, serialization_alias="sourceFormat")
    protocol: Optional[str] = None
    reason: str
    score: int = Field(description="Relative ranking score (higher = stronger match).")

    class Config:
        from_attributes = True


class LinkArtifactsRequest(BaseModel):
    """Link two projects into the same cross-format API identity group."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_id: str = Field(validation_alias=AliasChoices("projectId", "project_id"))
    related_project_id: str = Field(
        validation_alias=AliasChoices("relatedProjectId", "related_project_id")
    )


class UnlinkArtifactsRequest(BaseModel):
    """Remove one project from a shared identity group (pairwise unlink)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_id: str = Field(validation_alias=AliasChoices("projectId", "project_id"))
    related_project_id: str = Field(
        validation_alias=AliasChoices("relatedProjectId", "related_project_id")
    )


class CatalogItemSchema(BaseModel):
    """A catalog item (MFI-23.1): an OpenAPI-worthy non-OpenAPI import that is *not* a publishable
    Project.

    A catalog item is a projection over the same ``projects`` + ``versions`` tables a Project uses —
    it is simply the ``publishable = false`` slice — so the Catalog screen can clone the Projects
    dashboard. Alongside the project-compatible fields (id/name/slug/description/timestamps/creator/
    qualityScore/qualityGrade) it carries the format/protocol/provenance the import recorded onto its
    latest revision (MFI-7.1/7.2): ``sourceFormat``, ``protocol``, ``formatMetadata``, and
    ``toolVersions``. ``publishable`` is always ``False`` for a catalog item, by construction.
    """

    id: str
    tenant_id: str
    creator_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    slug: str
    enabled: bool = True
    deleted_at: Optional[Union[datetime, str]] = None
    metadata: Optional[Dict[str, Any]] = None
    # Captured lint score/grade of the catalog item's latest revision (parity with ProjectSchema).
    quality_score: Optional[int] = Field(None, serialization_alias="qualityScore")
    quality_grade: Optional[str] = Field(None, serialization_alias="qualityGrade")
    # The non-publishable invariant: a catalog item is never a publish candidate.
    publishable: bool = False
    # Imported-file format + paradigm/protocol + format-specific metadata + tool provenance, read off
    # the latest revision (apiome.versions, MFI-7.1/7.2). Sparse until populated by the import path.
    source_format: Optional[str] = Field(None, serialization_alias="sourceFormat")
    protocol: Optional[str] = None
    format_metadata: Optional[Dict[str, Any]] = Field(None, serialization_alias="formatMetadata")
    tool_versions: Optional[Dict[str, Any]] = Field(None, serialization_alias="toolVersions")
    creator_name: Optional[str] = None
    creator_email: Optional[str] = None
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None
    # The convert-to-OpenAPI back-link (MFI-23.11): present once the item has been converted into a
    # publishable Project, so the card/detail can show "Converted → {project}". None until converted.
    conversion: Optional[CatalogConversionRef] = None
    # Cross-format identity group (MFI-6.4, #4410): present when this artifact is linked to others.
    identity_group_id: Optional[str] = Field(None, serialization_alias="identityGroupId")
    related_artifacts: List["RelatedArtifactRef"] = Field(
        default_factory=list, serialization_alias="relatedArtifacts"
    )

    class Config:
        from_attributes = True


class CatalogNormalizedSummary(BaseModel):
    """Normalized-content summary for a catalog item (MFI-23.9): how many services, operations,
    types and event channels the imported source normalized to.

    Each count is Optional — ``None`` means the import has not (yet) recorded that figure onto the
    revision's ``format_metadata`` (the persistence is wired by a later format epic), so the detail
    view can distinguish "zero" from "not captured".
    """

    services: Optional[int] = None
    operations: Optional[int] = None
    types: Optional[int] = None
    channels: Optional[int] = None

    class Config:
        from_attributes = True


class CatalogSourceDescriptor(BaseModel):
    """The source-material descriptor for a catalog item (MFI-23.9): where the import came from.

    Mirrors the UI's ``resolveCatalogSource`` — an input kind (file/url/paste/discovery), a display
    label, an optional source URL, and whether a raw source is retrievable. ``downloadable`` is the
    single signal the detail view needs to enable its view/download affordance (true when inline
    content was captured *or* a source URL is recorded); ``hasContent`` distinguishes "stream the
    captured bytes" from "open the URL".
    """

    kind: Optional[str] = None
    label: Optional[str] = None
    uri: Optional[str] = None
    has_content: bool = Field(False, serialization_alias="hasContent")
    downloadable: bool = False

    class Config:
        from_attributes = True


class CatalogParsedField(BaseModel):
    """One field row of a parsed entity (MFI-25.2): a named member with its type and doc.

    The leaf of the ``parsed`` tree — a record/message field, a GraphQL argument, an enum value, or
    a union member. ``type`` is a compact, presentation-agnostic rendering of the canonical type
    (lists nest with ``[...]``; a protobuf field number is appended as ``#N``); ``required`` carries
    the outer nullability so the renderer, not the API, decides how to mark optionality.
    """

    name: str
    type: str = ""
    description: Optional[str] = None
    required: bool = False

    class Config:
        from_attributes = True


class CatalogParsedEntity(BaseModel):
    """One parsed entity (MFI-25.2): a named, paradigm-tagged unit with its field rows.

    A GraphQL operation/type, a gRPC service/message, an AsyncAPI channel/operation/message, etc.
    ``tag`` is the paradigm-specific kind (QUERY/OBJECT/SERVICE/MESSAGE/CHANNEL/SEND/…); ``meta`` is a
    short human hint (a return type, a channel binding, a ``N fields`` count) or ``None``.
    """

    name: str
    tag: str
    meta: Optional[str] = None
    fields: List[CatalogParsedField] = Field(default_factory=list)

    class Config:
        from_attributes = True


class CatalogParsedGroup(BaseModel):
    """A group of parsed entities (MFI-25.2): the top level of the ``parsed`` tree.

    Entities are grouped in the way each paradigm reads most naturally (GraphQL by operations/types,
    gRPC by services/messages, AsyncAPI by channels/operations/messages). ``title`` names the block
    (e.g. "Operations", "Messages") and ``subtitle`` is an optional sub-line.
    """

    title: str
    subtitle: Optional[str] = None
    entities: List[CatalogParsedEntity] = Field(default_factory=list)

    class Config:
        from_attributes = True


class CatalogItemDetailSchema(CatalogItemSchema):
    """A catalog item with the MFI-23.9 detail enrichments layered onto the MFI-23.2 list shape.

    Returned by ``GET /v1/catalog/{tenant_slug}/{item_id}``: the same envelope as
    :class:`CatalogItemSchema` plus a normalized-content ``summary``, a ``source`` material
    descriptor (both derived from the latest revision's ``format_metadata``, see ``catalog_detail.py``)
    and, from MFI-25.2, a ``parsed`` list of paradigm-tagged entity groups derived from the canonical
    model (see ``catalog_parsed_model.py``). ``parsed`` is ``[]`` when no model can be reconstructed
    from the item's captured source. Sparse until the import path records that provenance.
    """

    summary: CatalogNormalizedSummary = Field(default_factory=CatalogNormalizedSummary)
    source: CatalogSourceDescriptor = Field(default_factory=CatalogSourceDescriptor)
    parsed: List[CatalogParsedGroup] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ConversionDefaultsRequest(BaseModel):
    """User-supplied defaults that close cheap gaps *before* a catalog → OpenAPI conversion commits
    (MFI-22.6).

    All optional; each is applied to the emitted document only where the source model left the
    corresponding construct empty (a default never overwrites a value the source declared). Mirrors
    the inline defaults the preview screen (MFI-22.4) collects and the ``ConversionDefaults`` the job
    (MFI-22.5) consumes.
    """

    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, description="Fallback API title when the source has none.")
    version: Optional[str] = Field(
        default=None, description="Fallback API version when the source declares none."
    )
    servers: List[str] = Field(
        default_factory=list,
        description="Fallback server URLs when the source declares no servers.",
    )


class ConvertCatalogItemRequest(BaseModel):
    """Request body for ``POST /v1/catalog/{tenant_slug}/{item_id}/convert`` (MFI-22.6).

    Carries the conversion target (``openapi`` is the only one today, but the verb is target-generic
    for future emitters), the ``dryRun`` flag (the query param is authoritative for the side-effect
    decision; this mirrors it so a body-only caller still works), and the optional user defaults.
    """

    model_config = ConfigDict(extra="forbid")

    target: str = Field(default="openapi", description="Conversion target format (only 'openapi' today).")
    dry_run: bool = Field(
        default=True,
        validation_alias=AliasChoices("dry_run", "dryRun"),
        serialization_alias="dryRun",
        description="When true, return the fidelity report with no side effects; when false, commit.",
    )
    defaults: Optional[ConversionDefaultsRequest] = Field(
        default=None, description="Optional user-supplied fallbacks applied only where the source is empty."
    )


class ConvertDryRunResponse(BaseModel):
    """The ``dryRun=true`` response: the fidelity report + the would-be OpenAPI document, no side
    effects (MFI-22.6).

    Backs the preview screen (MFI-22.4) and the CLI ``convert --dry-run`` summary. ``report`` is the
    serialized MFI-22.3 :class:`~app.fidelity.FidelityReport`; ``openapi`` is the document a commit
    would emit, for the collapsible raw preview and the CLI ``--out`` write-out.
    """

    model_config = ConfigDict(populate_by_name=True)

    report: Dict[str, Any] = Field(description="The serialized fidelity report (MFI-22.3).")
    openapi: Dict[str, Any] = Field(description="The OpenAPI 3.1 document the conversion would emit.")
    source_format: Optional[str] = Field(
        default=None,
        serialization_alias="sourceFormat",
        description="The source format that was converted (e.g. 'graphql'), echoed for display.",
    )
    target: str = Field(default="openapi", description="The conversion target (only 'openapi' today).")


class ConvertCommitResponse(BaseModel):
    """The ``dryRun=false`` response: the ids of the Project/version the conversion created, plus its
    fidelity report (MFI-22.5/22.6).

    Mirrors the UI's ``ConversionCommitResult`` (``projectId`` / ``versionId`` / ``report``) while also
    surfacing the richer job outcome (the revision row id, whether a new Project was minted vs.
    re-versioned, and the provenance row id) for CLI/API consumers.
    """

    model_config = ConfigDict(populate_by_name=True)

    project_id: str = Field(serialization_alias="projectId", description="Created/updated Project id.")
    project_slug: Optional[str] = Field(
        default=None, serialization_alias="projectSlug", description="Created/updated Project slug."
    )
    version_id: str = Field(
        serialization_alias="versionId", description="Semantic version label of the created revision."
    )
    version_record_id: str = Field(
        serialization_alias="versionRecordId", description="Row id (versions.id) of the created revision."
    )
    created_project: bool = Field(
        serialization_alias="createdProject", description="True when a new Project was minted (first convert)."
    )
    reconverted: bool = Field(description="True when this superseded a prior conversion of the source.")
    provenance_id: str = Field(
        serialization_alias="provenanceId", description="Id of the persisted conversion_provenance row."
    )
    report: Dict[str, Any] = Field(description="The serialized fidelity report (MFI-22.3).")


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


class VersionBranchCreateRequest(BaseModel):
    """Create a named branch whose tip is an existing revision."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., description="Branch name; unique per project.")
    from_version_id: str = Field(
        ...,
        validation_alias=AliasChoices("fromVersionId", "from_version_id"),
        description="Existing revision (version row id) to use as the branch tip.",
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


class LintCategoryScoreOut(BaseModel):
    """A per-category 0-100 rollup score (MFI-25.6, #4091).

    Lets the inline lint panel drive its category bars with real per-category scores instead of a
    severity tally. ``score`` uses the same capped-penalty formula as the headline score, scoped to
    the category's findings, so a clean category is 100 and a noisy one is low.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(description="Category name (e.g. naming, documentation, structure).")
    score: int = Field(ge=0, le=100, description="Deterministic 0-100 score for this category.")


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
    categories: List[LintCategoryScoreOut] = Field(
        default_factory=list,
        serialization_alias="categories",
        description=(
            "Per-category 0-100 rollup scores (MFI-25.6), sorted by name — drives the UI's category "
            "bars with real values. Empty when no categories apply."
        ),
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
    captured_score: Optional[int] = Field(
        default=None,
        serialization_alias="capturedScore",
        description="Score persisted on the version at import time (MFI-4.2), if any.",
    )
    captured_grade: Optional[str] = Field(
        default=None,
        serialization_alias="capturedGrade",
        description="A-F grade persisted on the version at import time, if any.",
    )
    captured_report_fingerprint: Optional[str] = Field(
        default=None,
        serialization_alias="capturedReportFingerprint",
        description="Report fingerprint persisted on the version at import time, if any.",
    )
    score_is_stale: bool = Field(
        default=False,
        serialization_alias="scoreIsStale",
        description=(
            "True when a captured fingerprint exists and differs from this live report's "
            "fingerprint, signalling the persisted score is out of date. Always False when a "
            "base revision is compared (the live report folds in extra findings) or when no "
            "score has been captured."
        ),
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
    """Pydantic model for apiome.class_schema (frozen JSON Schema 2020-12 per class per version)."""
    id: str
    version_id: str
    class_id: str
    schema: Dict[str, Any]
    created_at: Optional[Union[datetime, str]] = None
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class DataRecordModel(BaseModel):
    """Pydantic model for apiome.data_record (event log: created/updated/deleted/restored per logical record)."""
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
    """Pydantic model for apiome.data_snapshot (current state per logical record)."""
    record_id: str
    class_schema_id: str
    data: Dict[str, Any]
    tenant_id: str
    updated_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


# ==================== Workflow audit (git-like ledger, #2578) ====================


class WorkflowAuditEntryOut(BaseModel):
    """One row from apiome.workflow_audit (newest-first list endpoint)."""

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
    """One row from apiome.registry_audit (newest-first list endpoint)."""

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
    """One refresh-cycle audit row, projected from ``apiome.workflow_audit`` (RAR-5.3).

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

    id: str
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


#: Placeholder a redacted value is replaced with in a persisted test-invocation log. Fixed and
#: content-free so the log never leaks the secret's length or value (cf. ``MCP_CREDENTIAL_SECRET_MASK``).
MCP_INVOCATION_REDACTION_MASK = "***redacted***"

#: Substrings that, when found in an argument key (case-insensitive), mark its value as secret-bearing
#: and so redacted before the call's arguments are logged. Deliberately broad — a false positive only
#: masks a non-secret value in the *log* (the real value is still sent to the server), whereas a miss
#: would persist a secret. Covers the common credential nouns and their underscore/camel spellings.
_MCP_SECRET_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "apikey",
    "api_key",
    "authorization",
    "auth",
    "credential",
    "private_key",
    "privatekey",
    "access_key",
    "accesskey",
    "client_secret",
    "bearer",
    "session",
    "cookie",
    "passphrase",
)


def _is_secret_key(key: str) -> bool:
    """Return True when an argument key name looks like it carries a secret value."""
    folded = key.lower().replace("-", "_")
    return any(fragment in folded for fragment in _MCP_SECRET_KEY_FRAGMENTS)


def redact_sensitive_args(value: Any) -> Any:
    """Deep-copy ``value`` with secret-bearing values masked, for safe logging.

    Walks an arguments / response object and replaces the value of any mapping key whose name
    looks like a credential (see :data:`_MCP_SECRET_KEY_FRAGMENTS`) with
    :data:`MCP_INVOCATION_REDACTION_MASK`, recursing into nested mappings and sequences. The
    input is never mutated — a fresh structure is returned — so the redaction only affects what
    is persisted to ``mcp_test_invocations`` (#3689), never what is sent to the MCP server.

    Non-container values pass through unchanged; only a *mapping value under a secret-looking key*
    is masked, so ordinary scalar arguments (a city, a count) are logged verbatim.

    Args:
        value: Any JSON-shaped value (mapping, sequence, or scalar) to redact for logging.

    Returns:
        A redaction-masked deep copy of ``value``.
    """
    if isinstance(value, Mapping):
        redacted: Dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(key, str) and _is_secret_key(key):
                redacted[key] = MCP_INVOCATION_REDACTION_MASK
            else:
                redacted[key] = redact_sensitive_args(item)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_sensitive_args(item) for item in value]
    return value


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
    # Failure handling, backoff & quarantine status (V2-MCP-19.3 / MCAT-5.3).
    consecutive_failures: int = 0
    next_discovery_after: Optional[str] = None
    quarantined: bool = False
    quarantined_at: Optional[str] = None
    quarantine_reason: Optional[str] = None
    current_version_id: Optional[str] = None
    # Latest host/transport facts observed at discovery — host, TLS cert summary, notable response
    # headers, connect timing (V2-MCP-34.1); null until the first successful discovery.
    transport_metadata: Optional[Dict[str, Any]] = None
    transport_metadata_at: Optional[str] = None
    # How the endpoint entered the catalog — manual / registry / import (V2-MCP-34.5).
    added_via: str = "manual"
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


def mcp_endpoint_host(url: Optional[str]) -> str:
    """Extract the host a catalog endpoint lives on, for private-browse grouping (MCAT-9.1).

    Returns the lowercased hostname of an ``http(s)`` endpoint URL. ``stdio`` command targets
    and any URL without a parseable host fall back to ``"(local)"`` so every endpoint lands in
    exactly one host bucket. The host carries no secret (any ``user:password@`` userinfo lives
    in the *authority* before the host), so this is safe to compute from the stored URL.
    """
    if not url:
        return "(local)"
    host = urlsplit(url).hostname
    return host.lower() if host else "(local)"


class McpServerBranding(BaseModel):
    """The validated branding a server advertised in its ``initialize`` ``serverInfo`` (#4656).

    A recognizable-catalog aid (V2-MCP-34.2): the server's website and a display icon, if any.
    Every field is optional and independently present — the capture layer
    (:mod:`app.mcp_client.branding`) drops any value that fails its guards (https-only,
    SSRF-safe host, length-bounded), so a field here is always a safe, *referenceable* URL. The
    whole object is ``None`` on a snapshot when the server advertised no usable branding, and the
    card falls back to its text form.
    """

    model_config = ConfigDict(populate_by_name=True)

    website_url: Optional[str] = None
    icon_url: Optional[str] = None
    icon_mime_type: Optional[str] = None


class McpBrowseEndpointOut(BaseModel):
    """One endpoint as it appears in the private browse view (V2-MCP-23.1 / MCAT-9.1).

    A browse-oriented projection of a catalog endpoint: identity, the ``host`` it is grouped
    under, its current snapshot's capability counts (``tool_count`` / ``resource_count`` /
    ``resource_template_count`` / ``prompt_count`` and their ``capability_count`` total), its
    quality ``score`` / ``grade`` (NULL until scored), and when it was ``last_discovered_at`` —
    exactly the fields a browse card renders. ``endpoint_url`` is credential-redacted like
    :class:`McpEndpointOut`.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    slug: str
    host: str
    endpoint_url: str
    transport: str
    description: Optional[str] = None
    category: Optional[str] = None
    visibility: str
    published: bool
    enabled: bool
    quarantined: bool = False
    last_discovered_at: Optional[str] = None
    last_discovery_status: Optional[str] = None
    current_version_id: Optional[str] = None
    score: Optional[int] = None
    grade: Optional[str] = None
    server_branding: Optional[McpServerBranding] = None
    tool_count: int = 0
    resource_count: int = 0
    resource_template_count: int = 0
    prompt_count: int = 0
    capability_count: int = 0
    # Facet fields (V2-MCP-35.1 / MCAT-21.1): the current snapshot's protocol version, the
    # derived discovery-health label, the safety-posture flags, and the complexity band — the
    # queryable dimensions of the faceted catalog search, carried on every browse/faceted row so
    # the grid can facet without a second read.
    protocol_version: Optional[str] = None
    health: str = "undiscovered"
    has_destructive: bool = False
    read_only_only: bool = False
    complexity_band: str = "unknown"
    # Freshness (V2-MCP-36.2 / MCAT-22.2): cadence/backoff/quarantine/failure staleness for cards.
    freshness: str = "fresh"
    last_known_good_at: Optional[str] = None


class McpBrowseHostGroup(BaseModel):
    """A host bucket in the browse view: every cataloged endpoint sharing one host (MCAT-9.1)."""

    model_config = ConfigDict(populate_by_name=True)

    host: str
    endpoint_count: int
    capability_count: int
    endpoints: List[McpBrowseEndpointOut]


class McpBrowseResponse(BaseModel):
    """Response envelope for the private browse view — endpoints grouped by host (MCAT-9.1)."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    host_count: int
    endpoint_count: int
    groups: List[McpBrowseHostGroup]


def mcp_browse_endpoint_out_from_row(row: Dict[str, Any]) -> McpBrowseEndpointOut:
    """Project a :meth:`Database.browse_mcp_endpoints` row onto the browse wire model.

    Normalizes timestamps/UUIDs to strings, derives the grouping ``host`` from the stored URL
    (:func:`mcp_endpoint_host`), redacts any embedded credentials from ``endpoint_url``
    (:func:`redact_url_credentials`), and rolls the four per-kind capability tallies into
    ``capability_count``.
    """

    def _ts(value: Any) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _s(value: Any) -> Optional[str]:
        return str(value) if value is not None else None

    raw_url = str(row["endpoint_url"])
    tool = int(row.get("tool_count") or 0)
    resource = int(row.get("resource_count") or 0)
    resource_template = int(row.get("resource_template_count") or 0)
    prompt = int(row.get("prompt_count") or 0)
    score = row.get("score")
    from .mcp_freshness_report import derive_freshness_status, resolve_last_known_good_at

    last_known = row.get("last_known_good_at")
    if last_known is not None and hasattr(last_known, "isoformat"):
        last_known_good_at = last_known.isoformat()
    elif last_known is not None:
        last_known_good_at = str(last_known)
    else:
        last_known_good_at = resolve_last_known_good_at(row)

    return McpBrowseEndpointOut(
        id=str(row["id"]),
        name=str(row["name"]),
        slug=str(row["slug"]),
        host=mcp_endpoint_host(raw_url),
        endpoint_url=redact_url_credentials(raw_url),
        transport=str(row["transport"]),
        description=_s(row.get("description")),
        category=_s(row.get("category")),
        visibility=str(row["visibility"]),
        published=bool(row.get("published", False)),
        enabled=bool(row.get("enabled", True)),
        quarantined=row.get("quarantined_at") is not None,
        last_discovered_at=_ts(row.get("last_discovered_at")),
        last_discovery_status=_s(row.get("last_discovery_status")),
        current_version_id=_s(row.get("current_version_id")),
        score=int(score) if score is not None else None,
        grade=_s(row.get("grade")),
        server_branding=_mcp_server_branding(row.get("server_branding")),
        tool_count=tool,
        resource_count=resource,
        resource_template_count=resource_template,
        prompt_count=prompt,
        capability_count=tool + resource + resource_template + prompt,
        protocol_version=_s(row.get("protocol_version")),
        # Rows from the enriched queries carry the derived facet fields; older row shapes fall
        # back to deriving health from the columns present (same labels/precedence) and to the
        # facet NULL buckets, so the projection is total over both.
        health=str(row.get("health") or derive_mcp_endpoint_health(row)),
        has_destructive=bool(row.get("has_destructive") or False),
        read_only_only=bool(row.get("read_only_only") or False),
        complexity_band=str(row.get("complexity_band") or "unknown"),
        freshness=str(
            row.get("freshness")
            or derive_freshness_status(
                row,
                default_cadence_seconds=int(
                    row.get("_default_cadence_seconds") or settings.mcp_discovery_default_cadence_seconds
                ),
            )
        ),
        last_known_good_at=last_known_good_at,
    )


def group_mcp_browse_endpoints(rows: List[Dict[str, Any]]) -> McpBrowseResponse:
    """Group enriched browse rows by host into the browse response (MCAT-9.1).

    Buckets endpoints by their derived :func:`mcp_endpoint_host`, ordering the host groups
    alphabetically (so the view is stable across requests) while preserving the by-name order
    of endpoints within each group that the DB query produced. Each group carries its endpoint
    and rolled-up capability counts.

    Args:
        rows: Rows from :meth:`Database.browse_mcp_endpoints` (one per live endpoint).

    Returns:
        A :class:`McpBrowseResponse` with per-host groups plus host/endpoint totals.
    """
    endpoints = [mcp_browse_endpoint_out_from_row(r) for r in rows]
    buckets: Dict[str, List[McpBrowseEndpointOut]] = {}
    for endpoint in endpoints:
        buckets.setdefault(endpoint.host, []).append(endpoint)
    groups = [
        McpBrowseHostGroup(
            host=host,
            endpoint_count=len(buckets[host]),
            capability_count=sum(e.capability_count for e in buckets[host]),
            endpoints=buckets[host],
        )
        for host in sorted(buckets)
    ]
    return McpBrowseResponse(
        success=True,
        host_count=len(groups),
        endpoint_count=len(endpoints),
        groups=groups,
    )


# ===========================================================================
# MCP Catalog — capability search index & query (V2-MCP-23.2 / MCAT-9.2, #3692)
# ===========================================================================
#
# Free-text search over a tenant's cataloged MCP surface, backed by the V127 capability-item
# ``tsvector`` GIN index. ``scope`` picks what is searched: a single capability kind
# (``tool`` / ``resource`` / ``resource_template`` / ``prompt``), every capability kind (the
# default when ``scope`` is omitted), or the endpoints themselves (``endpoint``). Hits are ranked
# by full-text relevance then quality score, and the host / category / grade / visibility filters
# compose on top. Like every catalog route the search is scoped to the caller's token tenant, so a
# search never crosses into another tenant's catalog (the public-directory variant waits on the
# MCAT-1.6 public read view).

#: The kinds a search can target: one of the four capability item types, or the endpoints
#: themselves. Omitting ``scope`` searches across all four capability kinds.
McpSearchScope = Literal["tool", "resource", "resource_template", "prompt", "endpoint"]

#: Visibility values a search may be filtered to (matches the ``visibility_type`` enum). The search
#: is always tenant-scoped, so this narrows the caller's *own* catalog to its private or public
#: endpoints — it does not expose another tenant's public endpoints.
McpSearchVisibility = Literal["public", "private"]


class McpSearchHit(BaseModel):
    """One search result — a matched capability item, or a matched endpoint (MCAT-9.2).

    Every hit carries its owning endpoint's browse context (``host``, ``category``, quality
    ``score`` / ``grade``, ``visibility``) so a result can be rendered and ranked without a second
    lookup. ``kind`` discriminates the two shapes: for a capability hit it is the item type
    (``tool`` / ``resource`` / ``resource_template`` / ``prompt``) and the ``item_*`` fields plus
    ``description`` describe the matched item; for an endpoint hit it is ``endpoint`` and the
    ``item_*`` fields are ``None`` while ``description`` is the endpoint's own description.
    ``endpoint_url`` is credential-redacted like every other catalog projection, and ``relevance``
    is the full-text rank the ordering used.
    """

    model_config = ConfigDict(populate_by_name=True)

    kind: str
    endpoint_id: str
    endpoint_name: str
    endpoint_slug: str
    host: str
    endpoint_url: str
    category: Optional[str] = None
    visibility: str
    current_version_id: Optional[str] = None
    score: Optional[int] = None
    grade: Optional[str] = None
    item_id: Optional[str] = None
    item_name: Optional[str] = None
    item_title: Optional[str] = None
    description: Optional[str] = None
    relevance: float = 0.0


class McpSearchResponse(BaseModel):
    """Response envelope for a catalog search — ranked hits plus the echoed query/scope (MCAT-9.2)."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    query: str
    scope: Optional[str] = None
    limit: int
    offset: int
    count: int
    hits: List[McpSearchHit]


def mcp_search_hit_from_row(row: Dict[str, Any]) -> McpSearchHit:
    """Project a search row (capability-item or endpoint) onto the :class:`McpSearchHit` wire model.

    Both DB search queries (:meth:`Database.search_mcp_capability_items` and
    :meth:`Database.search_mcp_endpoints`) return the same column set discriminated by ``kind``, so a
    single projection serves both. The grouping ``host`` is derived from the stored URL
    (:func:`mcp_endpoint_host`), credentials are redacted from ``endpoint_url``
    (:func:`redact_url_credentials`), UUIDs/timestamps are normalized to strings, and the per-row
    ``relevance`` rank is carried through for transparency into the ordering.
    """

    def _s(value: Any) -> Optional[str]:
        return str(value) if value is not None else None

    raw_url = str(row["endpoint_url"])
    score = row.get("score")
    relevance = row.get("relevance")
    return McpSearchHit(
        kind=str(row["kind"]),
        endpoint_id=str(row["endpoint_id"]),
        endpoint_name=str(row["endpoint_name"]),
        endpoint_slug=str(row["endpoint_slug"]),
        host=mcp_endpoint_host(raw_url),
        endpoint_url=redact_url_credentials(raw_url),
        category=_s(row.get("category")),
        visibility=str(row["visibility"]),
        current_version_id=_s(row.get("current_version_id")),
        score=int(score) if score is not None else None,
        grade=_s(row.get("grade")),
        item_id=_s(row.get("item_id")),
        item_name=_s(row.get("item_name")),
        item_title=_s(row.get("item_title")),
        description=_s(row.get("description")),
        relevance=float(relevance) if relevance is not None else 0.0,
    )


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
    """Project an ``apiome.mcp_endpoints`` row onto the wire model.

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
        consecutive_failures=int(row.get("consecutive_failures") or 0),
        next_discovery_after=_ts(row.get("next_discovery_after")),
        quarantined=row.get("quarantined_at") is not None,
        quarantined_at=_ts(row.get("quarantined_at")),
        quarantine_reason=_s(row.get("quarantine_reason")),
        current_version_id=_s(row.get("current_version_id")),
        transport_metadata=row.get("transport_metadata")
        if isinstance(row.get("transport_metadata"), dict)
        else None,
        transport_metadata_at=_ts(row.get("transport_metadata_at")),
        added_via=str(row.get("added_via") or "manual"),
        created_at=_ts(row.get("created_at")),
        updated_at=_ts(row.get("updated_at")),
    )


# ===========================================================================
# MCP Catalog — outbound credentials (set / clear / redacted status) (MCAT-6.5)
# ===========================================================================
#
# Tenants set, replace and clear the secret used to reach a protected MCP server. The plaintext
# secret is sealed by the encryption-at-rest layer (MCAT-6.2) before storage and is NEVER returned
# by any response: every read projects through :func:`mcp_credential_status_from_row`, which strips
# the ciphertext and the secret and reports only a redacted status.

#: Auth types acceptable on a credential PUT — every secret-bearing scheme. The anonymous ``none``
#: state is reached by DELETE-ing the credential, not by setting one, so it is excluded here.
MCP_CREDENTIAL_AUTH_TYPES = ("bearer", "header", "oauth2", "env")

#: Fixed placeholder returned in place of a stored secret. A constant — not derived from the
#: secret's length or content — so the redacted status leaks nothing about the underlying value.
MCP_CREDENTIAL_SECRET_MASK = "********"


class McpCredentialUpsert(BaseModel):
    """Set or replace an endpoint's outbound credential (MCAT-6.5).

    The plaintext ``payload`` is sealed server-side (MCAT-6.2) before it is stored and is NEVER
    echoed back by any response. ``auth_type`` must be a secret-bearing scheme
    (:data:`MCP_CREDENTIAL_AUTH_TYPES`) — to remove a credential entirely (the anonymous ``none``
    state) DELETE the resource instead. ``oauth_metadata`` is non-secret OAuth2 discovery metadata
    persisted as cleartext. Accepts both camelCase and snake_case keys so UI and CLI can share it.

    Expected ``payload`` shape per ``auth_type`` (validated against the auth-type model at the route):

    * ``bearer`` — ``{"token": "<secret>"}``
    * ``header`` — ``{"name": "<Header-Name>", "value": "<secret>"}``
    * ``oauth2`` — ``{"access_token": "<token>", "token_type": "Bearer"?}``
    * ``env``    — ``{"vars": {"NAME": "value", ...}}``
    """

    model_config = ConfigDict(populate_by_name=True)

    auth_type: str = Field(..., validation_alias=AliasChoices("authType", "auth_type"))
    payload: Dict[str, Any] = Field(default_factory=dict)
    oauth_metadata: Optional[Dict[str, Any]] = Field(
        default=None, validation_alias=AliasChoices("oauthMetadata", "oauth_metadata")
    )

    @model_validator(mode="after")
    def _validate_auth_type(self) -> "McpCredentialUpsert":
        if self.auth_type not in MCP_CREDENTIAL_AUTH_TYPES:
            raise ValueError(
                f"auth_type must be one of {list(MCP_CREDENTIAL_AUTH_TYPES)} "
                "(clear a credential with DELETE rather than setting 'none')"
            )
        return self


class McpCredentialStatusOut(BaseModel):
    """Redacted view of an endpoint's stored credential (MCAT-6.5).

    Carries only non-secret status: which ``auth_type`` is configured, whether a sealed secret is
    present (``configured``) and a fixed ``masked_secret`` placeholder when it is, the sealing
    ``key_version``, the non-secret ``oauth_metadata``, and audit timestamps. The ciphertext and the
    decrypted secret are NEVER included — there is no field that could carry them.
    """

    model_config = ConfigDict(populate_by_name=True)

    endpoint_id: str
    auth_type: str
    configured: bool
    masked_secret: Optional[str] = None
    key_version: Optional[int] = None
    oauth_metadata: Dict[str, Any] = Field(default_factory=dict)
    last_refreshed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class McpCredentialStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    credential: McpCredentialStatusOut


class McpCredentialDeleteResponse(BaseModel):
    """Outcome of clearing an endpoint's credential (MCAT-6.5).

    ``removed`` is ``True`` when a stored credential row was actually deleted, and ``False`` when
    the endpoint had no credential to begin with (the clear is idempotent — both are ``200``).
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    removed: bool = False


def mcp_credential_status_from_row(
    endpoint_id: str, row: Optional[Dict[str, Any]]
) -> McpCredentialStatusOut:
    """Project a credential row onto the redacted status model (secret + ciphertext stripped).

    A ``None`` row (no credential configured) reports the anonymous ``none`` status with
    ``configured=False`` and no mask. A present row reports its ``auth_type``, a fixed
    :data:`MCP_CREDENTIAL_SECRET_MASK` when ciphertext is stored, the sealing ``key_version``, the
    non-secret ``oauth_metadata``, and timestamps — never the secret, and never the ciphertext.

    Args:
        endpoint_id: The endpoint the status is for (echoed into the model).
        row: The ``apiome.mcp_endpoint_credentials`` row, or ``None`` when none is configured.

    Returns:
        The redacted :class:`McpCredentialStatusOut`.
    """

    def _ts(value: Any) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    if row is None:
        return McpCredentialStatusOut(
            endpoint_id=endpoint_id, auth_type="none", configured=False
        )

    has_secret = row.get("encrypted_payload") is not None
    key_version = row.get("key_version")
    metadata = row.get("oauth_metadata")
    return McpCredentialStatusOut(
        endpoint_id=endpoint_id,
        auth_type=str(row.get("auth_type") or "none"),
        configured=has_secret,
        masked_secret=MCP_CREDENTIAL_SECRET_MASK if has_secret else None,
        key_version=int(key_version) if isinstance(key_version, int) else None,
        oauth_metadata=metadata if isinstance(metadata, dict) else {},
        last_refreshed_at=_ts(row.get("last_refreshed_at")),
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
    snapshot the run produced, plus ``counts`` (per-kind capability tallies:
    ``tool`` / ``resource`` / ``resource_template`` / ``prompt`` / ``total``) for a
    completion summary; on failure it carries the classified discovery error.
    ``error`` is the short human-readable failure summary, if any.
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
    """Project an ``apiome.mcp_discovery_jobs`` row onto the wire model.

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
    """Project an ``apiome.mcp_discovery_jobs`` row onto the poll-status contract.

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


# ===========================================================================
# MCP Catalog — version history, change report & compare (V2-MCP-18.5 / MCAT-4.5)
# ===========================================================================
#
# Wire models for the four read surfaces that let a UI/CLI render an endpoint's
# version timeline (``…/versions``), one version's full surface (``…/versions/{vid}``),
# the stored ``previous → this`` diff a version introduced (``…/versions/{vid}/changes``),
# and an on-demand diff between any two versions (``…/versions/compare``). The compare
# result is computed by the canonical surface diff engine (MCAT-4.2), so a live compare
# of two adjacent versions matches that newer version's stored change record exactly.


def _mcp_ts(value: Any) -> Optional[str]:
    """Normalize a timestamp column to an ISO-8601 string (or None)."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _mcp_str(value: Any) -> Optional[str]:
    """Stringify a value, preserving None."""
    return str(value) if value is not None else None


def _mcp_int(value: Any) -> Optional[int]:
    """Coerce a numeric column to int, preserving None (e.g. an unscored snapshot)."""
    return int(value) if value is not None else None


class McpVersionChangeCounts(BaseModel):
    """Per-direction tally of surface changes (a version's diff, or a compare result).

    ``total`` is always ``added + removed + modified`` — the three diff directions the
    ``mcp_version_changes.change_type`` CHECK constraint admits.
    """

    model_config = ConfigDict(populate_by_name=True)

    added: int = 0
    removed: int = 0
    modified: int = 0
    total: int = 0


def mcp_change_counts(added: int, removed: int, modified: int) -> McpVersionChangeCounts:
    """Build a :class:`McpVersionChangeCounts`, deriving ``total`` from the three parts."""
    return McpVersionChangeCounts(
        added=int(added),
        removed=int(removed),
        modified=int(modified),
        total=int(added) + int(removed) + int(modified),
    )


def _mcp_change_counts_from_row(row: Dict[str, Any]) -> McpVersionChangeCounts:
    """Build change counts from a version row's ``*_count`` aggregate columns."""
    return mcp_change_counts(
        row.get("added_count") or 0,
        row.get("removed_count") or 0,
        row.get("modified_count") or 0,
    )


class McpChangeSeverityCounts(BaseModel):
    """Per-severity tally of surface changes (V2-MCP-30.3 / MCAT-16.3).

    The breaking-change classification of a set of ``mcp_version_changes`` — the churn a
    snapshot introduced, split by how disruptive it is rather than by direction.
    ``total`` is always ``breaking + additive + review`` and equals the tally's
    :class:`McpVersionChangeCounts` ``total`` for the same set of changes.
    """

    model_config = ConfigDict(populate_by_name=True)

    breaking: int = 0
    additive: int = 0
    review: int = 0
    total: int = 0


def _mcp_severity_counts(changes: List[Dict[str, Any]]) -> McpChangeSeverityCounts:
    """Classify each change row and roll the verdicts up into a :class:`McpChangeSeverityCounts`."""
    counts = severity_counts(changes)
    return McpChangeSeverityCounts(
        breaking=counts[SEVERITY_BREAKING],
        additive=counts[SEVERITY_ADDITIVE],
        review=counts[SEVERITY_REVIEW],
        total=counts["total"],
    )


def _mcp_server_branding(value: Any) -> Optional[McpServerBranding]:
    """Project a stored ``server_branding`` JSON object onto the wire model, or ``None``.

    The column is written by :mod:`app.mcp_client.branding` as a dict of already-validated,
    safe URLs (or SQL ``NULL``). A non-dict/empty value — or one with no recognized field —
    reads back as ``None`` so the card falls back to its text form; unknown keys are ignored.
    """
    if not isinstance(value, dict):
        return None
    branding = McpServerBranding(
        website_url=_mcp_str(value.get("website_url")),
        icon_url=_mcp_str(value.get("icon_url")),
        icon_mime_type=_mcp_str(value.get("icon_mime_type")),
    )
    if (
        branding.website_url is None
        and branding.icon_url is None
        and branding.icon_mime_type is None
    ):
        return None
    return branding


class McpEndpointVersionSummary(BaseModel):
    """One row of an endpoint's version history (the timeline / "what changed when" view).

    Carries the snapshot's sequence and human-readable date/time ``version_tag``, its server
    identity, ``surface_fingerprint`` and advertised ``server_branding``, the quality ``score`` /
    ``grade`` (NULL until the snapshot is scored), and the per-direction ``change_counts`` it
    introduced relative to the prior version. ``is_current`` flags the snapshot the endpoint's
    ``current_version_id`` points at. ``discovery_trigger`` / ``discovery_job_id`` are the
    snapshot's provenance — what enqueued the run that produced it (V2-MCP-34.5); ``None`` means
    unrecorded (a pre-provenance snapshot), never any concrete origin.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    endpoint_id: str
    version_seq: int
    version_tag: Optional[str] = None
    protocol_version: Optional[str] = None
    server_name: Optional[str] = None
    server_title: Optional[str] = None
    server_version: Optional[str] = None
    surface_fingerprint: Optional[str] = None
    server_branding: Optional[McpServerBranding] = None
    score: Optional[int] = None
    grade: Optional[str] = None
    scored_at: Optional[str] = None
    change_counts: McpVersionChangeCounts
    is_current: bool = False
    discovery_trigger: Optional[str] = None
    discovery_job_id: Optional[str] = None
    discovered_at: Optional[str] = None
    created_at: Optional[str] = None


class McpLifecycleSignalOut(BaseModel):
    """One lifecycle signal a capability's own text or annotations carry (V2-MCP-34.4).

    Mirrors :meth:`app.mcp_lifecycle_signals.LifecycleSignal.as_dict`: the asserted
    ``stage``, what kind of match it was, where it was found, the verbatim match, and a
    bounded context excerpt. ``id`` is the detector's stable hash for the signal.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    stage: str
    kind: str
    source: str
    matched: str
    excerpt: str = ""


class McpCapabilityLifecycleOut(BaseModel):
    """A capability's lifecycle assessment — what the capability-list badge renders.

    ``stage`` is the detector's roll-up: ``deprecated`` / ``experimental`` / ``beta`` /
    ``stable`` (explicitly declared only) / ``unspecified``. ``unspecified`` means the
    server said nothing — deliberately never presented as "stable" (V2-MCP-34.4 AC).
    """

    model_config = ConfigDict(populate_by_name=True)

    stage: str = STAGE_UNSPECIFIED
    signals: List[McpLifecycleSignalOut] = Field(default_factory=list)
    signals_truncated: int = 0


class McpCapabilityItemOut(BaseModel):
    """One normalized capability item (tool/resource/resource_template/prompt) of a surface."""

    model_config = ConfigDict(populate_by_name=True)

    item_type: str
    name: str
    title: Optional[str] = None
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    output_schema: Optional[Dict[str, Any]] = None
    annotations: Optional[Dict[str, Any]] = None
    uri: Optional[str] = None
    uri_template: Optional[str] = None
    ordinal: int = 0
    lifecycle: Optional[McpCapabilityLifecycleOut] = None


class McpEndpointVersionDetail(McpEndpointVersionSummary):
    """A version snapshot's full surface: summary identity + declared capabilities + items.

    Extends :class:`McpEndpointVersionSummary` with the heavier fields the list view omits —
    the server ``instructions``, the declared ``capabilities`` toggle blob, and every
    normalized capability ``items`` entry in deterministic (kind, ordinal) order.
    """

    instructions: Optional[str] = None
    capabilities: Optional[Dict[str, Any]] = None
    items: List[McpCapabilityItemOut] = Field(default_factory=list)


class McpEndpointVersionListResponse(BaseModel):
    """Response envelope for an endpoint's version history (newest first)."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    versions: List[McpEndpointVersionSummary]


class McpEndpointVersionResponse(BaseModel):
    """Response envelope for a single version's full surface."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    version: McpEndpointVersionDetail


class McpLintReportResponse(BaseModel):
    """Server-computed lint score + itemized findings for one MCP version snapshot (#3686).

    The MCP catalog analogue of :class:`LintReportResponse`: the deterministic 0-100 ``score``,
    its A-F ``grade``, the per-rule/per-severity tallies, the stable ``report_fingerprint``, and
    every itemized finding for a discovery snapshot's normalized surface. ``source`` records
    whether the report was served from the persisted ``mcp_version_scores`` row (``stored``) or
    computed live for this request (``computed``); ``scored_at`` is the persisted timestamp (only
    present when the report came from / was written to storage).
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str = Field(serialization_alias="endpointId")
    version_id: str = Field(
        serialization_alias="versionId",
        description="The version snapshot's id (mcp_endpoint_versions.id).",
    )
    version_seq: int = Field(
        serialization_alias="versionSeq",
        description="The snapshot's monotonic sequence number under its endpoint.",
    )
    version_tag: Optional[str] = Field(
        default=None,
        serialization_alias="versionTag",
        description="Human-readable date/time tag for the snapshot, when present.",
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
        description="Stable hash over score, grade, and findings for a fixed surface.",
    )
    source: str = Field(
        description="Where the report came from: 'stored' (persisted) or 'computed' (live).",
    )
    scored_at: Optional[str] = Field(
        default=None,
        serialization_alias="scoredAt",
        description="When the persisted score was last (re)computed, when applicable.",
    )


def mcp_lint_report_from_report(
    endpoint_id: str,
    version: Dict[str, Any],
    report: Dict[str, Any],
    *,
    source: str,
    scored_at: Any = None,
) -> McpLintReportResponse:
    """Build a :class:`McpLintReportResponse` from a scoring ``report`` dict.

    The single shaping path for both lint surfaces: a *stored* report (the ``report`` JSONB of an
    ``mcp_version_scores`` row) and a *computed* one (``MCPScoreResult.report_dict()``) carry the
    same key set, so both flow through here. The ``version`` row supplies the snapshot's identity
    (id / sequence / tag); the ``report`` supplies the score, grade, tallies, fingerprint, and
    itemized findings.

    Args:
        endpoint_id: The owning endpoint id (echoed for the caller's convenience).
        version: The ``mcp_endpoint_versions`` row the report is for.
        report: The scoring report dict (score/grade/report_fingerprint/rule_hits/
            severity_counts/findings).
        source: ``"stored"`` when served from persistence, ``"computed"`` when computed live.
        scored_at: Persisted ``scored_at`` timestamp, when applicable.

    Returns:
        The fully shaped lint report response.
    """
    findings = [LintFindingOut(**f) for f in (report.get("findings") or [])]
    return McpLintReportResponse(
        endpoint_id=str(endpoint_id),
        version_id=str(version["id"]),
        version_seq=int(version["version_seq"]),
        version_tag=version.get("version_tag"),
        score=int(report.get("score") or 0),
        grade=str(report.get("grade") or "F"),
        findings=findings,
        rule_hits=dict(report.get("rule_hits") or {}),
        severity_counts=dict(report.get("severity_counts") or {}),
        report_fingerprint=str(report.get("report_fingerprint") or ""),
        source=source,
        scored_at=_mcp_ts(scored_at),
    )


class McpVersionChangeOut(BaseModel):
    """One add / remove / modify entry — a stored change row or a computed compare entry.

    Mirrors an ``mcp_version_changes`` row (and the dicts produced by the diff engine's
    :meth:`SurfaceDiff.to_change_rows`): ``detail`` carries the before/after payload (a
    removal has ``before``, an addition ``after``, a modification both plus a per-field
    ``fields`` breakdown for capability items). ``severity`` is the deterministic
    breaking-change classification (V2-MCP-30.3) of this change: ``breaking`` /
    ``additive`` / ``review``, computed purely from the row by
    :func:`app.mcp_change_severity.classify_change`.
    """

    model_config = ConfigDict(populate_by_name=True)

    change_type: str
    item_type: str
    item_name: str
    detail: Dict[str, Any] = Field(default_factory=dict)
    severity: str = SEVERITY_REVIEW


class McpVersionChangesResponse(BaseModel):
    """Response envelope for a version's stored ``previous → this`` change report."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    version_id: str
    version_seq: int
    counts: McpVersionChangeCounts
    changes: List[McpVersionChangeOut]


class McpVersionRef(BaseModel):
    """Lightweight reference to one side of a compare (identity, no full surface)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    version_seq: int
    version_tag: Optional[str] = None
    surface_fingerprint: Optional[str] = None


class McpVersionCompareResponse(BaseModel):
    """On-demand structured diff between any two versions, normalized older→newer.

    ``base``/``target`` are returned in chronological order regardless of the order they were
    requested, so ``added``/``removed`` always read relative to the older surface.
    ``fingerprint_changed`` is ``False`` exactly when the two surfaces are semantically
    identical (equal fingerprints) — including ``base == target``, which yields an empty diff.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    base: McpVersionRef
    target: McpVersionRef
    fingerprint_changed: bool
    counts: McpVersionChangeCounts
    changes: List[McpVersionChangeOut]


def mcp_version_summary_from_row(
    row: Dict[str, Any], current_version_id: Optional[str] = None
) -> McpEndpointVersionSummary:
    """Project a version-history row (with score + ``*_count`` aggregates) onto the wire model.

    Args:
        row: A row from :meth:`Database.list_mcp_endpoint_versions` /
            :meth:`Database.get_mcp_endpoint_version`.
        current_version_id: The owning endpoint's ``current_version_id`` (to set
            ``is_current``); omitted when not known.

    Returns:
        The :class:`McpEndpointVersionSummary` for the row.
    """
    version_id = str(row["id"])
    return McpEndpointVersionSummary(
        id=version_id,
        endpoint_id=str(row["endpoint_id"]),
        version_seq=int(row["version_seq"]),
        version_tag=_mcp_str(row.get("version_tag")),
        protocol_version=_mcp_str(row.get("protocol_version")),
        server_name=_mcp_str(row.get("server_name")),
        server_title=_mcp_str(row.get("server_title")),
        server_version=_mcp_str(row.get("server_version")),
        surface_fingerprint=_mcp_str(row.get("surface_fingerprint")),
        server_branding=_mcp_server_branding(row.get("server_branding")),
        score=_mcp_int(row.get("score")),
        grade=_mcp_str(row.get("grade")),
        scored_at=_mcp_ts(row.get("scored_at")),
        change_counts=_mcp_change_counts_from_row(row),
        is_current=current_version_id is not None
        and str(current_version_id) == version_id,
        discovery_trigger=_mcp_str(row.get("discovery_trigger")),
        discovery_job_id=_mcp_str(row.get("discovery_job_id")),
        discovered_at=_mcp_ts(row.get("discovered_at")),
        created_at=_mcp_ts(row.get("created_at")),
    )


def mcp_capability_item_out_from_row(row: Dict[str, Any]) -> McpCapabilityItemOut:
    """Project an ``apiome.mcp_capability_items`` row onto the wire model.

    The ``lifecycle`` assessment (V2-MCP-34.4) is computed here by the pure detector — it
    is derived entirely from the row's own fields, so it needs no persistence and every
    consumer of the item wire model gets the same badges for the same stored surface.
    """

    def _obj(value: Any) -> Optional[Dict[str, Any]]:
        return value if isinstance(value, dict) else None

    item_type = str(row["item_type"])
    name = str(row["name"])
    title = _mcp_str(row.get("title"))
    description = _mcp_str(row.get("description"))
    annotations = _obj(row.get("annotations"))
    lifecycle = assess_capability_lifecycle(
        item_type=item_type,
        name=name,
        title=title,
        description=description,
        annotations=annotations,
    )
    return McpCapabilityItemOut(
        item_type=item_type,
        name=name,
        title=title,
        description=description,
        input_schema=_obj(row.get("input_schema")),
        output_schema=_obj(row.get("output_schema")),
        annotations=annotations,
        uri=_mcp_str(row.get("uri")),
        uri_template=_mcp_str(row.get("uri_template")),
        ordinal=int(row.get("ordinal") or 0),
        lifecycle=McpCapabilityLifecycleOut(
            stage=lifecycle.stage,
            signals=[McpLifecycleSignalOut(**s.as_dict()) for s in lifecycle.signals],
            signals_truncated=lifecycle.signals_truncated,
        ),
    )


def mcp_version_detail_from_row(
    row: Dict[str, Any],
    item_rows: List[Dict[str, Any]],
    current_version_id: Optional[str] = None,
) -> McpEndpointVersionDetail:
    """Project a version row + its capability items onto the full-surface wire model."""
    summary = mcp_version_summary_from_row(row, current_version_id)
    capabilities = row.get("capabilities")
    return McpEndpointVersionDetail(
        **summary.model_dump(),
        instructions=_mcp_str(row.get("instructions")),
        capabilities=capabilities if isinstance(capabilities, dict) else None,
        items=[mcp_capability_item_out_from_row(r) for r in item_rows],
    )


def mcp_version_change_out_from_row(row: Dict[str, Any]) -> McpVersionChangeOut:
    """Project a change record onto the wire model.

    Accepts both a persisted ``mcp_version_changes`` row and a dict produced by the diff
    engine's :meth:`SurfaceDiff.to_change_rows` (the keys are identical).
    """
    detail = row.get("detail")
    return McpVersionChangeOut(
        change_type=str(row["change_type"]),
        item_type=str(row["item_type"]),
        item_name=str(row["item_name"]),
        detail=detail if isinstance(detail, dict) else {},
        severity=classify_change(row),
    )


# ===========================================================================
# Test harness — invoke one cataloged capability and report the outcome
# (V2-MCP-22.2 / MCAT-8.2, #3688)
# ===========================================================================

#: The capability kinds the test harness can invoke. ``resource_template`` is excluded
#: deliberately: a template needs URI expansion before it is a concrete read target,
#: which is out of this ticket's scope (it mirrors ``mcp_invoke.INVOCATION_METHODS``).
MCP_TESTABLE_ITEM_TYPES = ("tool", "resource", "prompt")


class McpAuthOverride(BaseModel):
    """An ephemeral credential to use for a single test call, in place of the stored one.

    Lets a tenant try an endpoint with a *throwaway* secret — a personal token, a not-yet-saved
    credential — without ever persisting it. The shape mirrors :class:`McpCredentialUpsert`
    (``auth_type`` + plaintext ``payload``), is validated against the same auth-type model at the
    route, and is used only to build request headers for this one invocation. It is **never** written
    to ``mcp_endpoint_credentials`` and never echoed back in any response.

    Unlike the stored-credential model, ``auth_type`` ``none`` is accepted here: it means "test this
    call anonymously", explicitly overriding any stored credential for this one request.

    Expected ``payload`` shape per ``auth_type`` (same as :class:`McpCredentialUpsert`):

    * ``none``   — payload ignored (anonymous test call)
    * ``bearer`` — ``{"token": "<secret>"}``
    * ``header`` — ``{"name": "<Header-Name>", "value": "<secret>"}``
    * ``oauth2`` — ``{"access_token": "<token>", "token_type": "Bearer"?}``
    * ``env``    — ``{"vars": {"NAME": "value", ...}}`` (contributes no HTTP headers)
    """

    model_config = ConfigDict(populate_by_name=True)

    auth_type: str = Field(..., validation_alias=AliasChoices("authType", "auth_type"))
    payload: Dict[str, Any] = Field(default_factory=dict)


class McpEndpointTestRequest(BaseModel):
    """Invoke one cataloged capability against its live MCP server and report the result.

    Names the capability to exercise on the endpoint's *current* discovered surface and the
    arguments to call it with. ``item_type`` selects the invocation method
    (``tool`` → ``tools/call``, ``resource`` → ``resources/read``, ``prompt`` → ``prompts/get``);
    ``item_name`` is the capability's discovered name (for a resource, its name — the route resolves
    it to the stored concrete ``uri``). ``arguments`` is validated against a tool's stored
    ``inputSchema`` (and a prompt's required arguments) before the call leaves the server.

    ``auth_override`` supplies an ephemeral credential for this one call only (never persisted);
    when omitted the endpoint's stored credential is used. ``timeout_seconds`` bounds each request
    in the connect → handshake → invoke sequence.
    """

    model_config = ConfigDict(populate_by_name=True)

    item_type: str = Field(
        ...,
        validation_alias=AliasChoices("itemType", "item_type"),
        description="The capability kind to invoke: 'tool', 'resource', or 'prompt'.",
    )
    item_name: str = Field(
        ...,
        validation_alias=AliasChoices("itemName", "item_name"),
        description="The discovered capability name (a resource's name resolves to its uri).",
    )
    arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Call arguments; validated against a tool's stored inputSchema.",
    )
    auth_override: Optional[McpAuthOverride] = Field(
        default=None,
        validation_alias=AliasChoices("authOverride", "auth_override"),
        description="Ephemeral credential for this call only (never persisted).",
    )
    timeout_seconds: float = Field(
        default=30.0,
        ge=1.0,
        le=120.0,
        validation_alias=AliasChoices("timeoutSeconds", "timeout_seconds"),
        description="Per-request timeout in seconds for the test call (1-120).",
    )
    confirm: bool = Field(
        default=False,
        description=(
            "Explicit acknowledgement required to invoke a tool whose annotations flag it as "
            "destructive (destructiveHint) or open-world (openWorldHint). Ignored for safe tools."
        ),
    )

    @model_validator(mode="after")
    def _validate_item_type(self) -> "McpEndpointTestRequest":
        if self.item_type not in MCP_TESTABLE_ITEM_TYPES:
            raise ValueError(
                f"item_type must be one of {list(MCP_TESTABLE_ITEM_TYPES)} "
                "(resource_template is not directly invocable)"
            )
        if not self.item_name.strip():
            raise ValueError("item_name must be a non-empty string")
        return self


class McpEndpointTestResponse(BaseModel):
    """The outcome of one test-harness invocation: content, error, and latency.

    A single shape covers the three outcomes the invocation service distinguishes, branchable on two
    booleans (see :class:`app.mcp_invoke.InvocationResult`):

    * ``completed=True,  is_error=False`` — the call ran and succeeded; ``content`` holds the result.
    * ``completed=True,  is_error=True``  — the call ran but the tool reported a tool-level error
      (``tools/call`` only); ``content`` holds the error payload the tool produced.
    * ``completed=False`` — the call failed (a JSON-RPC protocol error or a transport/handshake
      failure); ``error`` carries the classified reason and ``content`` is empty.

    ``auth_override_applied`` records whether the call used an ephemeral override (``True``) or the
    endpoint's stored credential (``False``); the secret itself is never included either way.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str = Field(serialization_alias="endpointId")
    item_type: str = Field(serialization_alias="itemType")
    item_name: str = Field(serialization_alias="itemName")
    method: str = Field(description="The JSON-RPC method invoked (e.g. 'tools/call').")
    target: str = Field(description="What was invoked: a tool/prompt name, or a resource uri.")
    completed: bool = Field(
        description="True when the server returned a JSON-RPC result (success or tool error)."
    )
    is_error: bool = Field(
        serialization_alias="isError",
        description="True when a tool ran but reported a tool-level error (tools/call only).",
    )
    content: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Returned payload items (tool content / resource contents / prompt messages).",
    )
    structured_content: Optional[Dict[str, Any]] = Field(
        default=None,
        serialization_alias="structuredContent",
        description="A tool's optional structuredContent object, when present.",
    )
    latency_ms: float = Field(
        serialization_alias="latencyMs",
        description="Round-trip wall-clock in ms (connect + handshake + invoke).",
    )
    error: Optional[Dict[str, Any]] = Field(
        default=None,
        description="The classified failure when completed is False; null otherwise.",
    )
    auth_override_applied: bool = Field(
        default=False,
        serialization_alias="authOverrideApplied",
        description="True when an ephemeral auth override was used instead of stored credentials.",
    )
    invocation_id: Optional[str] = Field(
        default=None,
        serialization_alias="invocationId",
        description="Id of the persisted mcp_test_invocations log row, or null if logging failed.",
    )


def mcp_endpoint_test_response_from_result(
    endpoint_id: str,
    item_type: str,
    item_name: str,
    result: Dict[str, Any],
    *,
    auth_override_applied: bool,
    invocation_id: Optional[str] = None,
) -> McpEndpointTestResponse:
    """Shape an :meth:`app.mcp_invoke.InvocationResult.as_dict` payload into the wire response.

    Args:
        endpoint_id: The owning endpoint id (echoed for the caller's convenience).
        item_type: The capability kind that was invoked.
        item_name: The capability name that was invoked (echoes the request).
        result: The ``InvocationResult.as_dict()`` payload (method/target/completed/is_error/
            content/structured_content/latency_ms/error).
        auth_override_applied: Whether an ephemeral override was used for this call.
        invocation_id: Id of the persisted ``mcp_test_invocations`` row, or ``None`` if the
            best-effort log write failed (the call result is still returned).

    Returns:
        The fully shaped :class:`McpEndpointTestResponse`.
    """
    return McpEndpointTestResponse(
        endpoint_id=str(endpoint_id),
        item_type=item_type,
        item_name=item_name,
        method=str(result.get("method") or ""),
        target=str(result.get("target") or ""),
        completed=bool(result.get("completed")),
        is_error=bool(result.get("is_error")),
        content=list(result.get("content") or []),
        structured_content=result.get("structured_content"),
        latency_ms=float(result.get("latency_ms") or 0.0),
        error=result.get("error"),
        auth_override_applied=auth_override_applied,
        invocation_id=str(invocation_id) if invocation_id is not None else None,
    )


# ===========================================================================
# MCP Catalog — insight aggregation endpoints (V2-MCP-28.2 / MCAT-14.2, #4628)
# ===========================================================================
#
# Typed, pre-aggregated response models for the read-only insight surfaces the browser renders
# without running N queries or holding raw rows. `surface` projects the deterministic
# `app.mcp_surface_metrics` roll-up for a version; `evolution` is the per-version time series;
# `reliability` folds discovery-job and test-invocation telemetry (aggregated by the pure
# `app.mcp_insight_aggregation` layer) into rates and latency percentiles; `catalog` is the
# tenant-wide roll-up that feeds 18.1.


def _mcp_insight_iso(value: Any) -> Optional[str]:
    """Normalize a timestamp (datetime or string) to an ISO-8601 string, or ``None``."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


class McpTypeCountsOut(BaseModel):
    """Per-kind capability item counts of a surface (tools/resources/templates/prompts + total)."""

    model_config = ConfigDict(populate_by_name=True)

    tools: int = 0
    resources: int = 0
    resource_templates: int = 0
    prompts: int = 0
    total: int = 0


class McpToolComplexityOut(BaseModel):
    """One tool's ``input_schema`` complexity profile (mirrors ``mcp_surface_metrics.ToolComplexity``)."""

    model_config = ConfigDict(populate_by_name=True)

    name: str
    property_count: int = 0
    required_count: int = 0
    optional_count: int = 0
    documented_property_count: int = 0
    max_nesting_depth: int = 0
    uses_enum: bool = False
    uses_one_of: bool = False
    has_output_schema: bool = False


class McpAnnotationCoverageOut(BaseModel):
    """Per-hint behavioural-annotation coverage over a surface's tools."""

    model_config = ConfigDict(populate_by_name=True)

    tool_count: int = 0
    annotated_tools: int = 0
    read_only_hint: int = 0
    destructive_hint: int = 0
    idempotent_hint: int = 0
    open_world_hint: int = 0


class McpDocumentationCoverageOut(BaseModel):
    """Item- and parameter-level documentation coverage of a surface (counts + 0-100 percentages)."""

    model_config = ConfigDict(populate_by_name=True)

    item_count: int = 0
    described_items: int = 0
    titled_items: int = 0
    description_pct: float = 0.0
    title_pct: float = 0.0
    tool_param_count: int = 0
    documented_tool_params: int = 0
    tool_param_description_pct: float = 0.0


class McpSurfaceMetricsOut(BaseModel):
    """The full :class:`app.mcp_surface_metrics.SurfaceMetrics` roll-up as a typed response body."""

    model_config = ConfigDict(populate_by_name=True)

    type_counts: McpTypeCountsOut
    tool_complexity: List[McpToolComplexityOut] = Field(default_factory=list)
    output_schema_count: int = 0
    annotation_coverage: McpAnnotationCoverageOut
    documentation_coverage: McpDocumentationCoverageOut
    metrics_fingerprint: str


def mcp_surface_metrics_out(metrics: Dict[str, Any]) -> McpSurfaceMetricsOut:
    """Build :class:`McpSurfaceMetricsOut` from a ``SurfaceMetrics.as_dict()`` payload.

    Takes the plain dict the pure metrics engine emits (rather than the dataclass) so ``models``
    stays free of a hard import on the metrics module; the field names line up one-to-one.
    """
    return McpSurfaceMetricsOut.model_validate(metrics)


class McpInsightSurfaceResponse(BaseModel):
    """Response envelope for the capability-surface metrics of one version snapshot.

    Carries the resolved snapshot identity (``version_id`` / ``version_seq`` / ``version_tag`` and
    whether it is the endpoint's ``is_current`` surface) alongside the deterministic ``metrics``
    roll-up for that surface.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    version_id: str
    version_seq: int
    version_tag: Optional[str] = None
    is_current: bool = False
    metrics: McpSurfaceMetricsOut


class McpGraphNodeOut(BaseModel):
    """One capability rendered as a node in the relationship graph (V2-MCP-29.2)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    item_type: str
    name: str
    title: Optional[str] = None
    label: str
    degree: int = 0


class McpGraphEdgeOut(BaseModel):
    """One inferred relationship edge between two graph nodes (V2-MCP-29.2)."""

    model_config = ConfigDict(populate_by_name=True)

    source: str
    target: str
    kind: str
    directed: bool = True
    label: str = ""
    signals: List[str] = Field(default_factory=list)


class McpCapabilityGraphOut(BaseModel):
    """The full :class:`app.mcp_capability_graph.CapabilityGraph` as a typed response body."""

    model_config = ConfigDict(populate_by_name=True)

    nodes: List[McpGraphNodeOut] = Field(default_factory=list)
    edges: List[McpGraphEdgeOut] = Field(default_factory=list)
    node_count: int = 0
    edge_count: int = 0
    isolated_count: int = 0
    graph_fingerprint: str


def mcp_capability_graph_out(graph: Dict[str, Any]) -> McpCapabilityGraphOut:
    """Build :class:`McpCapabilityGraphOut` from a ``CapabilityGraph.as_dict()`` payload.

    Takes the plain dict the pure graph engine emits (rather than the dataclass) so ``models`` stays
    free of a hard import on the graph module; the field names line up one-to-one.
    """
    return McpCapabilityGraphOut.model_validate(graph)


class McpInsightGraphResponse(BaseModel):
    """Response envelope for the capability relationship graph of one version snapshot.

    Carries the resolved snapshot identity (``version_id`` / ``version_seq`` / ``version_tag`` and
    whether it is the endpoint's ``is_current`` surface) alongside the inferred ``graph`` (nodes and
    concrete-signal edges) for that surface.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    version_id: str
    version_seq: int
    version_tag: Optional[str] = None
    is_current: bool = False
    graph: McpCapabilityGraphOut


class McpEvolutionPoint(BaseModel):
    """One point of an endpoint's per-version evolution series.

    Carries the snapshot identity, its per-kind capability ``type_counts``, the quality
    ``score`` / ``grade`` (NULL until scored), the ``change_counts`` (churn by direction)
    the snapshot introduced relative to the prior version, and — classifying that same
    churn by disruptiveness — the ``severity_counts`` (V2-MCP-30.3): how many of those
    changes are ``breaking`` / ``additive`` / ``review``.
    """

    model_config = ConfigDict(populate_by_name=True)

    version_id: str
    version_seq: int
    version_tag: Optional[str] = None
    discovered_at: Optional[str] = None
    is_current: bool = False
    type_counts: McpTypeCountsOut
    score: Optional[int] = None
    grade: Optional[str] = None
    change_counts: McpVersionChangeCounts
    severity_counts: McpChangeSeverityCounts = Field(default_factory=McpChangeSeverityCounts)


class McpInsightEvolutionResponse(BaseModel):
    """Response envelope for an endpoint's evolution series (oldest snapshot first)."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    series: List[McpEvolutionPoint] = Field(default_factory=list)


def mcp_evolution_point_from_row(
    row: Dict[str, Any],
    current_version_id: Optional[str],
    change_rows: Optional[List[Dict[str, Any]]] = None,
) -> McpEvolutionPoint:
    """Project a ``get_mcp_evolution_series`` row onto a :class:`McpEvolutionPoint`.

    Args:
        row: One evolution-series row (snapshot identity, capability ``*_count`` columns,
            score/grade, and per-direction change ``*_count`` aggregates).
        current_version_id: The endpoint's ``current_version_id`` (sets ``is_current``).
        change_rows: This snapshot's ``mcp_version_changes`` rows, used to classify the
            churn into ``severity_counts``. When ``None`` (or empty) the severity tally is
            all-zero — the first snapshot introduces no diff, so an empty list is correct.
    """
    version_id = str(row["id"])
    score = row.get("score")
    return McpEvolutionPoint(
        version_id=version_id,
        version_seq=int(row["version_seq"]),
        version_tag=row.get("version_tag"),
        discovered_at=_mcp_insight_iso(row.get("discovered_at")),
        is_current=current_version_id is not None and version_id == str(current_version_id),
        type_counts=McpTypeCountsOut(
            tools=int(row.get("tool_count") or 0),
            resources=int(row.get("resource_count") or 0),
            resource_templates=int(row.get("resource_template_count") or 0),
            prompts=int(row.get("prompt_count") or 0),
            total=int(row.get("tool_count") or 0)
            + int(row.get("resource_count") or 0)
            + int(row.get("resource_template_count") or 0)
            + int(row.get("prompt_count") or 0),
        ),
        score=int(score) if score is not None else None,
        grade=row.get("grade"),
        change_counts=_mcp_change_counts_from_row(row),
        severity_counts=_mcp_severity_counts(change_rows or []),
    )


# ===========================================================================
# "Changed since last view" digest — per-user seen-marker (V2-MCP-30.5 / MCAT-16.5, #4640)
# ===========================================================================


class McpEndpointDigestResponse(BaseModel):
    """The "changed since last view" digest for one user + endpoint (V2-MCP-30.5 / MCAT-16.5).

    Summarizes what changed on the endpoint's surface between the version the user *last saw*
    (their ``mcp_endpoint_views`` seen-marker) and its *current* version, and how breaking that
    change is:

    * ``new_to_you`` — the user has no recorded marker (first visit), or the version they last saw
      has since been pruned (a ``NULL`` pointer). There is no "since" point to diff from, so
      ``changes`` is empty and ``current_type_counts`` describes the surface they are seeing fresh.
    * ``has_changes`` — a marker exists and points at an older snapshot than the current one, so
      ``changes`` / ``change_counts`` / ``severity_counts`` describe the delta since it.
    * Neither flag set — the user has already seen the current version; the endpoint is up to date.

    Reading the digest does **not** advance the marker; a separate view-record call
    (``POST …/views``) does, so the digest reflects the pre-advance state on load.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    new_to_you: bool = False
    has_changes: bool = False
    last_seen_version_id: Optional[str] = None
    last_seen_version_seq: Optional[int] = None
    last_seen_at: Optional[str] = None
    current_version_id: Optional[str] = None
    current_version_seq: Optional[int] = None
    current_version_tag: Optional[str] = None
    current_type_counts: McpTypeCountsOut = Field(default_factory=McpTypeCountsOut)
    change_counts: McpVersionChangeCounts = Field(default_factory=McpVersionChangeCounts)
    severity_counts: McpChangeSeverityCounts = Field(default_factory=McpChangeSeverityCounts)
    changes: List[McpVersionChangeOut] = Field(default_factory=list)


def mcp_endpoint_digest_response(
    *,
    endpoint_id: str,
    current_version: Optional[Dict[str, Any]],
    current_type_counts: McpTypeCountsOut,
    view_row: Optional[Dict[str, Any]],
    change_rows: List[Dict[str, Any]],
) -> McpEndpointDigestResponse:
    """Assemble the digest from the current version, the user's marker, and the computed delta.

    Pure shaping — the ``change_rows`` diff is computed by the route (it needs DB access to
    reconstruct both surfaces); this only tallies and projects. ``change_counts`` is tallied
    from ``change_rows`` by direction, so it can never disagree with the ``changes`` list.

    Args:
        endpoint_id: The endpoint the digest is for.
        current_version: The endpoint's current ``mcp_endpoint_versions`` row, or ``None`` when it
            has never been discovered (no current surface to summarize).
        current_type_counts: Per-kind counts of the current surface (for the "new to you" summary).
        view_row: The user's seen-marker row (:meth:`Database.get_mcp_endpoint_view`), or ``None``
            when the user has never viewed the endpoint.
        change_rows: The changes between the last-seen and current version
            (:meth:`SurfaceDiff.to_change_rows`); empty when there is nothing to diff (first
            visit, up to date, or no current version).

    Returns:
        The populated :class:`McpEndpointDigestResponse`.
    """
    last_seen_version_id = (
        _mcp_str(view_row.get("last_seen_version_id")) if view_row else None
    )
    # "New to you": no marker at all, or a marker whose remembered version was pruned (NULL pointer).
    new_to_you = view_row is None or last_seen_version_id is None
    has_changes = bool(change_rows)

    added = sum(1 for r in change_rows if r.get("change_type") == "added")
    removed = sum(1 for r in change_rows if r.get("change_type") == "removed")
    modified = sum(1 for r in change_rows if r.get("change_type") == "modified")

    return McpEndpointDigestResponse(
        endpoint_id=str(endpoint_id),
        new_to_you=new_to_you,
        has_changes=has_changes,
        last_seen_version_id=last_seen_version_id,
        last_seen_version_seq=(
            _mcp_int(view_row.get("last_seen_version_seq")) if view_row else None
        ),
        last_seen_at=_mcp_ts(view_row.get("seen_at")) if view_row else None,
        current_version_id=_mcp_str(current_version.get("id")) if current_version else None,
        current_version_seq=(
            _mcp_int(current_version.get("version_seq")) if current_version else None
        ),
        current_version_tag=(
            _mcp_str(current_version.get("version_tag")) if current_version else None
        ),
        current_type_counts=current_type_counts,
        change_counts=mcp_change_counts(added, removed, modified),
        severity_counts=_mcp_severity_counts(change_rows),
        changes=[mcp_version_change_out_from_row(r) for r in change_rows],
    )


class McpEndpointViewMarkRequest(BaseModel):
    """Body for advancing a user's seen-marker (V2-MCP-30.5 / MCAT-16.5).

    ``version_id`` is the snapshot the client acknowledges having seen — normally the endpoint's
    current version, passed explicitly so the marker records exactly what the user saw even if a
    discovery advances "current" between the digest read and this call. When omitted the server
    marks the endpoint's current version.
    """

    model_config = ConfigDict(populate_by_name=True)

    version_id: Optional[str] = None


class McpEndpointViewResponse(BaseModel):
    """Response for a recorded view: the advanced seen-marker (V2-MCP-30.5 / MCAT-16.5)."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    last_seen_version_id: Optional[str] = None
    seen_at: Optional[str] = None


def mcp_endpoint_view_response(
    endpoint_id: str, row: Dict[str, Any]
) -> McpEndpointViewResponse:
    """Project a recorded-view row (:meth:`Database.record_mcp_endpoint_view`) onto the wire model."""
    return McpEndpointViewResponse(
        endpoint_id=str(endpoint_id),
        last_seen_version_id=_mcp_str(row.get("last_seen_version_id")),
        seen_at=_mcp_ts(row.get("seen_at")),
    )


class McpLatencyStatsOut(BaseModel):
    """Summary latency statistics over a sample of millisecond durations.

    All statistics are ``None`` for an empty sample (nothing to average or rank); ``count`` is the
    number of non-null latencies the statistics were computed from.
    """

    model_config = ConfigDict(populate_by_name=True)

    count: int = 0
    avg_ms: Optional[float] = None
    min_ms: Optional[float] = None
    max_ms: Optional[float] = None
    p50_ms: Optional[float] = None
    p95_ms: Optional[float] = None
    p99_ms: Optional[float] = None


class McpDiscoveryReliabilityOut(BaseModel):
    """Discovery-job reliability: state tallies, success rate, and run-latency statistics."""

    model_config = ConfigDict(populate_by_name=True)

    job_count: int = 0
    completed_count: int = 0
    failed_count: int = 0
    running_count: int = 0
    queued_count: int = 0
    success_rate: float = 0.0
    latency: McpLatencyStatsOut


class McpInvocationReliabilityOut(BaseModel):
    """Test-invocation reliability: call/error tallies, error rate, and latency statistics."""

    model_config = ConfigDict(populate_by_name=True)

    call_count: int = 0
    error_count: int = 0
    success_count: int = 0
    error_rate: float = 0.0
    latency: McpLatencyStatsOut


class McpToolReliabilityOut(BaseModel):
    """One tool's reliability over the window: call/error tallies, error rate, and latency stats.

    ``error_rate`` is ``error_count / call_count``; ``latency`` carries the p50/p95/p99 (and
    count/avg/min/max) over the calls that recorded a round-trip latency. A single-call tool renders
    percentiles equal to that one sample — no divide-by-zero.
    """

    model_config = ConfigDict(populate_by_name=True)

    tool_name: str
    call_count: int = 0
    error_count: int = 0
    success_count: int = 0
    error_rate: float = 0.0
    latency: McpLatencyStatsOut


class McpLatencyBucketOut(BaseModel):
    """One bar of the tool-latency distribution: a labelled range and how many calls fell in it.

    ``upper_ms`` is the exclusive upper bound of the range in milliseconds, or ``None`` for the
    open-ended top bucket.
    """

    model_config = ConfigDict(populate_by_name=True)

    label: str
    upper_ms: Optional[float] = None
    count: int = 0


class McpToolInvocationReliabilityOut(BaseModel):
    """Per-tool test-invocation reliability over a recent window (MCAT-17.2).

    ``tools`` is the per-tool breakdown (busiest first); the browser re-ranks it into "slowest" (by
    p95) and "flakiest" (by error rate) views. The scalar fields are the endpoint-wide totals over
    every tool call in the window; ``latency_distribution`` is a histogram of every tool call's
    latency for the distribution chart. ``window_days`` echoes the trailing window the rows were
    selected over. An endpoint never tool-tested yields an empty ``tools`` list and zero totals.
    """

    model_config = ConfigDict(populate_by_name=True)

    tools: List[McpToolReliabilityOut] = Field(default_factory=list)
    tool_count: int = 0
    call_count: int = 0
    error_count: int = 0
    success_count: int = 0
    error_rate: float = 0.0
    latency_distribution: List[McpLatencyBucketOut] = Field(default_factory=list)
    window_days: int = 0


class McpDiscoveryEventOut(BaseModel):
    """One discovery-job outcome on the health timeline (MCAT-17.1).

    ``outcome`` is the single value the timeline colours by — ``ok`` for a completed run, the
    specific discovery error code (``connect_error`` / ``auth_required`` / …) for a failed one, or
    ``pending`` while still in flight. ``error_code`` is the raw failure classification (``None``
    unless the job failed with a recorded code). Timestamps are ISO-8601 strings.
    """

    model_config = ConfigDict(populate_by_name=True)

    job_id: str
    state: str
    trigger: str
    outcome: str
    error_code: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[float] = None


class McpDiscoveryHealthOut(BaseModel):
    """Discovery health over a recent window: the outcome timeline, availability %, and quarantine.

    ``timeline`` is the recent per-job outcomes (newest-first, capped at ``window``);
    ``availability_pct`` is ``ok / (ok + failed)`` over the *terminal* jobs in that window as a
    ``0``–``100`` percentage, or ``None`` when the window holds no terminal job. The quarantine /
    backoff block mirrors the endpoint's live failure-handling state (V133): ``quarantined`` and its
    ``quarantined_at`` / ``quarantine_reason`` when the endpoint tripped the consecutive-failure
    threshold, the current ``consecutive_failures`` streak, and ``next_discovery_after`` (the backoff
    anchor the sweep is holding off until). ``last_status`` / ``last_discovered_at`` are the most
    recent attempt's outcome and time.
    """

    model_config = ConfigDict(populate_by_name=True)

    timeline: List[McpDiscoveryEventOut] = Field(default_factory=list)
    window: int = 0
    event_count: int = 0
    ok_count: int = 0
    failed_count: int = 0
    pending_count: int = 0
    terminal_count: int = 0
    availability_pct: Optional[float] = None
    truncated: bool = False
    quarantined: bool = False
    quarantined_at: Optional[str] = None
    quarantine_reason: Optional[str] = None
    consecutive_failures: int = 0
    next_discovery_after: Optional[str] = None
    last_status: Optional[str] = None
    last_discovered_at: Optional[str] = None


class McpInsightReliabilityResponse(BaseModel):
    """Response envelope folding an endpoint's discovery and invocation reliability together.

    ``discovery`` / ``invocation`` are the aggregate roll-ups (state tallies, success/error rates,
    latency); ``health`` adds the MCAT-17.1 discovery health timeline — the recent per-job outcome
    events, a windowed availability percentage, and the endpoint's quarantine / backoff state;
    ``tools`` adds the MCAT-17.2 per-tool latency & error-rate breakdown (p50/p95/p99 and error rate
    per tool, a latency distribution, and the endpoint-wide totals) over a recent window.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    discovery: McpDiscoveryReliabilityOut
    invocation: McpInvocationReliabilityOut
    health: McpDiscoveryHealthOut
    tools: McpToolInvocationReliabilityOut


def mcp_discovery_health_out(
    timeline: Dict[str, Any], endpoint: Dict[str, Any]
) -> McpDiscoveryHealthOut:
    """Fold a discovery-timeline aggregate + the endpoint's failure-handling state into the model.

    ``timeline`` is the ``as_dict()`` of a
    :class:`~app.mcp_insight_aggregation.DiscoveryTimeline` (its per-job events and windowed
    availability tallies); ``endpoint`` is the tenant-scoped endpoint row, which carries the live
    quarantine / backoff columns (V133) and the last-attempt outcome. The two are merged here so the
    route stays declarative and the projection is unit-testable without a database.

    Args:
        timeline: The discovery-timeline aggregate dict (events + availability window).
        endpoint: The endpoint row (quarantine, backoff, and last-discovery fields).

    Returns:
        The combined :class:`McpDiscoveryHealthOut` the reliability response embeds.
    """

    def _ts(value: Any) -> Optional[str]:
        if value is None:
            return None
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return str(value)

    def _s(value: Any) -> Optional[str]:
        return str(value) if value is not None else None

    return McpDiscoveryHealthOut(
        timeline=[McpDiscoveryEventOut.model_validate(e) for e in timeline.get("events", [])],
        window=int(timeline.get("window", 0)),
        event_count=int(timeline.get("event_count", 0)),
        ok_count=int(timeline.get("ok_count", 0)),
        failed_count=int(timeline.get("failed_count", 0)),
        pending_count=int(timeline.get("pending_count", 0)),
        terminal_count=int(timeline.get("terminal_count", 0)),
        availability_pct=timeline.get("availability_pct"),
        truncated=bool(timeline.get("truncated", False)),
        quarantined=endpoint.get("quarantined_at") is not None,
        quarantined_at=_ts(endpoint.get("quarantined_at")),
        quarantine_reason=_s(endpoint.get("quarantine_reason")),
        consecutive_failures=int(endpoint.get("consecutive_failures") or 0),
        next_discovery_after=_ts(endpoint.get("next_discovery_after")),
        last_status=_s(endpoint.get("last_discovery_status")),
        last_discovered_at=_ts(endpoint.get("last_discovered_at")),
    )


class McpTrustAxisOut(BaseModel):
    """One normalized 0-100 axis of the composite trust profile (V2-MCP-31.4 / MCAT-17.4).

    ``value`` is the axis score in ``[0, 100]`` when ``available``; ``None`` when the input the axis
    needs is missing — an explicit *gap* the radar renders as such, never a misleading zero.
    ``detail`` is the always-shown one-line basis for the score; ``methodology`` is the longer
    "how this is computed" text the panel reveals on hover.
    """

    model_config = ConfigDict(populate_by_name=True)

    key: str
    label: str
    value: Optional[float] = None
    available: bool = False
    detail: str = ""
    methodology: str = ""


class McpTrustProfileOut(BaseModel):
    """The five-axis composite trust profile — a heuristic glance, not an official rating.

    ``axes`` are the five normalized dimensions in canonical (clockwise) radar order — quality,
    safety, documentation, stability, responsiveness — some of which may be gaps. ``overall`` is the
    mean of only the *available* axes (gaps excluded), or ``None`` when none could be computed;
    ``available_count`` / ``axis_count`` back the panel's "N of 5 signals measured" caption.
    """

    model_config = ConfigDict(populate_by_name=True)

    axes: List[McpTrustAxisOut] = Field(default_factory=list)
    overall: Optional[float] = None
    available_count: int = 0
    axis_count: int = 0


class McpInsightTrustResponse(BaseModel):
    """Response envelope for an endpoint's composite trust profile radar (MCAT-17.4).

    ``profile`` carries the five normalized axes (quality, safety, documentation, stability,
    responsiveness), each 0-100 or an explicit gap, plus the mean of the available axes. It is an
    explicitly heuristic composite — a synthesized "trust glance", not an official rating.
    ``version_id`` is the current snapshot the surface-derived axes (quality / safety /
    documentation) were read from, or ``None`` when the endpoint has never been discovered;
    ``auth_type`` is the endpoint's configured scheme the safety axis cross-references.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    version_id: Optional[str] = None
    auth_type: Optional[str] = None
    profile: McpTrustProfileOut


class McpPeerAxisPercentileOut(BaseModel):
    """One axis of a server's peer ranking within its category (V2-MCP-32.3 / MCAT-18.3).

    ``value`` is the server's own 0-100 axis value; ``percentile`` is the share of the category cohort
    at or below it (higher = better, ``100`` = category leader); ``rank`` is its position (``1`` = best)
    of ``cohort_size`` peers measured on this axis; ``top_percent`` is the "top N%" the badge renders.
    An axis the server does not have measured is a *gap*: ``available`` is false and the ranked fields
    are ``null``, while ``cohort_size`` still reports how many peers *do* have it.
    """

    model_config = ConfigDict(populate_by_name=True)

    key: str
    label: str
    value: Optional[float] = None
    percentile: Optional[float] = None
    rank: Optional[int] = None
    top_percent: Optional[int] = None
    cohort_size: int = 0
    available: bool = False
    detail: str = ""


class McpPeerPercentileOut(BaseModel):
    """A server's peer ranking across the four axes within its catalog category (MCAT-18.3).

    ``category`` is the cohort's category (``None`` for the uncategorized cohort); ``cohort_size`` is
    the total number of live endpoints in the category (including this one). ``axes`` are the four
    rankings — grade, safety, documentation, latency — some of which may be gaps.
    """

    model_config = ConfigDict(populate_by_name=True)

    category: Optional[str] = None
    cohort_size: int = 0
    axes: List[McpPeerAxisPercentileOut] = Field(default_factory=list)


class McpInsightPercentileResponse(BaseModel):
    """Response envelope for an endpoint's peer percentile & category ranking (MCAT-18.3).

    Ranks the endpoint against the other live endpoints in its catalog ``category`` on four axes
    (grade, safety, documentation, latency), so the UI can render "top 10% for documentation"-style
    badges — a *peer baseline*, not an absolute grade. A single-member category yields a coherent
    profile (the sole server is the category leader), and any axis the server has not measured is an
    explicit gap, so an undiscovered or never-tested endpoint returns a ``200``, never a ``500``.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    profile: McpPeerPercentileOut


class McpSimilarOverlapNeighborOut(BaseModel):
    """One capability-overlap similar server — a peer ranked by shared capability names (MCAT-18.4).

    ``similarity`` is the Jaccard index (``0``-``1``) of the two servers' capability-name sets;
    ``shared_capabilities`` lists the names in common (normalized, sorted), ``shared_count`` its size;
    ``target_capability_count`` / ``candidate_capability_count`` are the two servers' distinct-name
    counts, so the UI can render "8 of 12 capabilities shared".
    """

    model_config = ConfigDict(populate_by_name=True)

    endpoint_id: str
    name: str
    slug: Optional[str] = None
    category: Optional[str] = None
    similarity: float = 0.0
    shared_count: int = 0
    target_capability_count: int = 0
    candidate_capability_count: int = 0
    shared_capabilities: List[str] = Field(default_factory=list)


class McpSimilarEmbeddingNeighborOut(BaseModel):
    """One semantic-embedding similar server — a peer ranked by cosine similarity (MCAT-18.4).

    ``similarity`` is the cosine similarity (``-1``-``1``, higher = nearer) of the two snapshots'
    capability embeddings. Only present when semantic embeddings are enabled and backfilled.
    """

    model_config = ConfigDict(populate_by_name=True)

    endpoint_id: str
    name: str
    slug: Optional[str] = None
    category: Optional[str] = None
    similarity: float = 0.0


class McpSimilarServersResponse(BaseModel):
    """Response envelope for an endpoint's "similar servers" discovery (MCAT-18.4).

    Surfaces "servers like this one" from two independent signals, each ranked against the caller's own
    live catalog: ``overlap`` — always present — ranks peers by capability-name Jaccard overlap;
    ``semantic`` ranks peers by cosine nearest-neighbour over a capability embedding, and is only
    populated when ``embeddings_enabled`` is true (the flag is on and both this endpoint and at least one
    peer have a backfilled embedding). When embeddings are disabled or unbackfilled, ``embeddings_enabled``
    is false and ``semantic`` is empty — the feature gracefully falls back to overlap-only, never a
    ``500``. ``target_capability_count`` is this endpoint's own distinct capability-name count (``0`` when
    it was never discovered, in which case ``overlap`` is empty too).
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    embeddings_enabled: bool = False
    target_capability_count: int = 0
    overlap: List[McpSimilarOverlapNeighborOut] = Field(default_factory=list)
    semantic: List[McpSimilarEmbeddingNeighborOut] = Field(default_factory=list)


class McpSimilarReindexResponse(BaseModel):
    """Response envelope for the similar-servers embedding backfill (MCAT-18.4).

    Records the outcome of (re)computing and storing this endpoint's current-snapshot capability
    embedding for the semantic similarity signal. ``embeddings_enabled`` reflects the feature flag;
    ``reindexed`` is true only when an embedding was actually generated and stored. When the flag is off,
    the endpoint has no discovered surface, or the embedding service / pgvector is unavailable,
    ``reindexed`` is false and ``detail`` explains why — always a ``200`` describing the no-op, never an
    error.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    embeddings_enabled: bool = False
    reindexed: bool = False
    version_id: Optional[str] = None
    detail: str = ""


class McpToolExampleOut(BaseModel):
    """One tool's schema-derived example call for the server digest (MCAT-18.5).

    ``arguments`` is a sample argument object synthesized deterministically from the tool's
    ``input_schema`` — a payload a caller *could* send, never the result of invoking the tool (no tool is
    executed to build it). ``arguments`` is ``{}`` for a tool that declares no input schema.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str
    title: Optional[str] = None
    description: Optional[str] = None
    arguments: Dict[str, Any] = Field(default_factory=dict)


class McpServerDigestResponse(BaseModel):
    """Response envelope for an endpoint's natural-language digest + usage examples (MCAT-18.5).

    Pairs an **AI-generated** plain-language summary of the server (``digest`` — clearly labelled AI
    content, ``null`` until generated) with one **deterministic, schema-derived example call per tool**
    (``examples`` — always present, computed offline from the current surface, never requiring the model
    or tool execution). ``ai_digest_enabled`` reflects the ``APIOME_MCP_AI_DIGEST_ENABLED`` feature flag
    so the UI knows whether a "generate" action is available. The digest is cached per
    ``surface_fingerprint`` and regenerated when the surface changes; ``model`` / ``generated_at`` record
    the provenance of a cached digest. A never-discovered endpoint yields empty ``examples`` and a ``null``
    digest — a ``200``, never a ``500``.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_id: str
    version_id: Optional[str] = None
    surface_fingerprint: Optional[str] = None
    ai_digest_enabled: bool = False
    ai_generated: bool = True
    digest: Optional[str] = None
    model: Optional[str] = None
    generated_at: Optional[str] = None
    tool_count: int = 0
    examples: List[McpToolExampleOut] = Field(default_factory=list)


class McpServerDigestGenerateResponse(McpServerDigestResponse):
    """Response envelope for the gated digest generation step (MCAT-18.5).

    Extends :class:`McpServerDigestResponse` with the outcome of a ``POST …/insight/digest/generate``:
    ``generated`` is true only when the model actually produced (and cached) a digest on this call;
    ``from_cache`` is true when an already-cached digest for the current surface was returned without
    calling the model. When the feature flag is off, no API key is configured, the surface has nothing to
    summarize, or the model call fails, ``generated`` is false and ``detail`` explains why — always a
    ``200`` describing the no-op, never an error.
    """

    generated: bool = False
    from_cache: bool = False
    detail: str = ""


class McpCatalogBucketOut(BaseModel):
    """One labelled slice of a catalog composition breakdown — a bucket and its endpoint count.

    Backs the category, transport, protocol-version, tool-count, and discovery-health distributions
    of the catalog analytics dashboard (18.1). ``label`` is always a display string: a NULL source
    value (uncategorized endpoint, undiscovered protocol, never-run discovery) is resolved to a
    friendly placeholder in the projection, never emitted as ``null``.
    """

    model_config = ConfigDict(populate_by_name=True)

    label: str
    count: int = 0


class McpCatalogLeaderOut(BaseModel):
    """One change-frequency leader — an endpoint and how many surface changes it has recorded (18.1)."""

    model_config = ConfigDict(populate_by_name=True)

    endpoint_id: str
    name: str
    change_count: int = 0


class McpCatalogCapabilityOut(BaseModel):
    """One widely-exposed capability — its kind, name, and how many endpoints expose it (18.1).

    A real aggregate that stands in for "most-searched capabilities" (there is no search-query log to
    rank by): ``endpoint_count`` is the number of distinct live endpoints whose current surface
    exposes a capability of this ``item_type`` / ``item_name``.
    """

    model_config = ConfigDict(populate_by_name=True)

    item_type: str
    item_name: str
    endpoint_count: int = 0


class McpInsightCatalogResponse(BaseModel):
    """Response envelope for the tenant-wide catalog insight roll-up (feeds 18.1).

    Spans every live endpoint the caller's tenant owns: how many there are, how many are published
    / discovered, the per-kind capability ``type_counts`` summed across every endpoint's current
    surface, the ``average_score`` over scored current versions, and the A-F ``grade_distribution``.

    The composition breakdowns power the catalog analytics dashboard's tiles: ``category_distribution``
    / ``transport_distribution`` / ``protocol_version_distribution`` / ``discovery_health`` (labelled
    buckets, busiest first), ``tool_count_distribution`` (a fixed-bucket histogram of per-endpoint tool
    counts), ``change_leaders`` (the most-churned endpoints), and ``top_capabilities`` (the most widely
    exposed capability names). All default to empty, so an empty catalog yields an all-empty — never a
    500 — body.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    endpoint_count: int = 0
    published_count: int = 0
    public_count: int = 0
    private_count: int = 0
    discovered_count: int = 0
    scored_count: int = 0
    average_score: Optional[float] = None
    type_counts: McpTypeCountsOut
    grade_distribution: Dict[str, int] = Field(default_factory=dict)
    category_distribution: List[McpCatalogBucketOut] = Field(default_factory=list)
    transport_distribution: List[McpCatalogBucketOut] = Field(default_factory=list)
    protocol_version_distribution: List[McpCatalogBucketOut] = Field(default_factory=list)
    tool_count_distribution: List[McpCatalogBucketOut] = Field(default_factory=list)
    discovery_health: List[McpCatalogBucketOut] = Field(default_factory=list)
    change_leaders: List[McpCatalogLeaderOut] = Field(default_factory=list)
    top_capabilities: List[McpCatalogCapabilityOut] = Field(default_factory=list)


def _catalog_buckets(
    rows: Any, *, null_label: str
) -> List[McpCatalogBucketOut]:
    """Project ``{label, count}`` aggregate rows onto :class:`McpCatalogBucketOut`.

    A NULL ``label`` (an uncategorized endpoint, an undiscovered protocol, a never-run discovery) is
    resolved to ``null_label`` so the wire model never carries a ``null`` slice label. Row order is
    preserved (the SQL already sorts busiest-first).
    """
    projected: List[McpCatalogBucketOut] = []
    for row in rows or []:
        raw = row.get("label")
        label = str(raw) if raw is not None else null_label
        projected.append(McpCatalogBucketOut(label=label, count=int(row.get("count") or 0)))
    return projected


def mcp_catalog_insight_from_row(row: Dict[str, Any]) -> McpInsightCatalogResponse:
    """Project a ``get_mcp_catalog_insight`` aggregate onto the wire model.

    The scalar tallies, ``type_counts``, and ``grade_distribution`` come straight from the summary
    row; the composition breakdowns are projected from their respective aggregate row lists, with the
    per-endpoint ``tool_count_rows`` folded into the fixed tool-count histogram by the pure
    :func:`~app.mcp_insight_aggregation.compute_tool_count_histogram`. Every breakdown defaults to
    empty when its rows are absent, so an empty catalog projects cleanly.
    """
    from .mcp_insight_aggregation import compute_tool_count_histogram

    avg_score = row.get("avg_score")
    tools = int(row.get("tool_count") or 0)
    resources = int(row.get("resource_count") or 0)
    templates = int(row.get("resource_template_count") or 0)
    prompts = int(row.get("prompt_count") or 0)
    grade_distribution = row.get("grade_distribution") or {}
    tool_count_histogram = compute_tool_count_histogram(
        r.get("tool_count") for r in (row.get("tool_count_rows") or [])
    )
    return McpInsightCatalogResponse(
        endpoint_count=int(row.get("endpoint_count") or 0),
        published_count=int(row.get("published_count") or 0),
        public_count=int(row.get("public_count") or 0),
        private_count=int(row.get("private_count") or 0),
        discovered_count=int(row.get("discovered_count") or 0),
        scored_count=int(row.get("scored_count") or 0),
        average_score=round(float(avg_score), 2) if avg_score is not None else None,
        type_counts=McpTypeCountsOut(
            tools=tools,
            resources=resources,
            resource_templates=templates,
            prompts=prompts,
            total=tools + resources + templates + prompts,
        ),
        grade_distribution={str(k): int(v) for k, v in grade_distribution.items()},
        category_distribution=_catalog_buckets(
            row.get("category_rows"), null_label="Uncategorized"
        ),
        transport_distribution=_catalog_buckets(
            row.get("transport_rows"), null_label="Unknown"
        ),
        protocol_version_distribution=_catalog_buckets(
            row.get("protocol_rows"), null_label="Unknown"
        ),
        discovery_health=_catalog_buckets(
            row.get("discovery_rows"), null_label="never"
        ),
        tool_count_distribution=[
            McpCatalogBucketOut(label=bucket.label, count=bucket.count)
            for bucket in tool_count_histogram
        ],
        change_leaders=[
            McpCatalogLeaderOut(
                endpoint_id=str(r.get("endpoint_id")),
                name=str(r.get("name") or ""),
                change_count=int(r.get("change_count") or 0),
            )
            for r in (row.get("change_leader_rows") or [])
        ],
        top_capabilities=[
            McpCatalogCapabilityOut(
                item_type=str(r.get("item_type") or ""),
                item_name=str(r.get("item_name") or ""),
                endpoint_count=int(r.get("endpoint_count") or 0),
            )
            for r in (row.get("top_capability_rows") or [])
        ],
    )


# ===========================================================================
# MCP Catalog — faceted catalog search (V2-MCP-35.1 / MCAT-21.1, #4660)
# ===========================================================================
#
# The catalog's rich metrics become queryable facets: ``GET /v1/mcp/{tenant}/facets`` filters
# endpoints by grade / transport / category / safety posture / complexity band / protocol version
# / discovery health (multi-facet AND, within-facet OR) and returns the matching page together
# with live per-dimension bucket counts aggregated over the same filtered set. Bucket labels
# double as filter values — the NULL buckets surface under their sentinel labels (``ungraded`` /
# ``uncategorized`` / ``unknown``), so any bucket a count reports can be clicked back into a
# filter.


class McpCatalogFacetsOut(BaseModel):
    """Live bucket counts per facet dimension, over the current filtered result set (MCAT-21.1).

    Each dimension is a busiest-first list of :class:`McpCatalogBucketOut`; every ``label`` is a
    valid filter value for that dimension (NULL buckets use their sentinel labels). ``safety``
    always lists both postures — ``has_destructive`` and ``read_only_only`` — even at zero, so a
    client can render the full control; the postures are independent flags, so their counts can
    overlap and need not sum to the endpoint total. All dimensions default to empty, so an empty
    result projects cleanly.
    """

    model_config = ConfigDict(populate_by_name=True)

    grade: List[McpCatalogBucketOut] = Field(default_factory=list)
    transport: List[McpCatalogBucketOut] = Field(default_factory=list)
    category: List[McpCatalogBucketOut] = Field(default_factory=list)
    safety: List[McpCatalogBucketOut] = Field(default_factory=list)
    complexity: List[McpCatalogBucketOut] = Field(default_factory=list)
    protocol_version: List[McpCatalogBucketOut] = Field(default_factory=list)
    health: List[McpCatalogBucketOut] = Field(default_factory=list)


class McpFacetedSearchResponse(BaseModel):
    """Response envelope of the faceted catalog search (MCAT-21.1).

    ``endpoints`` is the requested page of matches (browse-shaped rows, each carrying its facet
    fields), ``count`` its length, and ``total`` the full match count across pages. ``facets``
    holds the live bucket counts over the same filtered set, so the counts always describe
    exactly the result the filters produced. An empty match is a valid response — empty page,
    zero total, empty buckets — never an error.
    """

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    total: int = 0
    count: int = 0
    limit: int
    offset: int
    endpoints: List[McpBrowseEndpointOut] = Field(default_factory=list)
    facets: McpCatalogFacetsOut = Field(default_factory=McpCatalogFacetsOut)


def _facet_buckets(rows: Any, *, null_label: str) -> List[McpCatalogBucketOut]:
    """Project ``{label, count}`` facet rows, folding the NULL bucket into ``null_label``.

    Like :func:`_catalog_buckets`, but merging: SQL emits the NULL bucket as a separate row, and
    a raw label equal to the sentinel could in principle coexist with it, so rows folding to the
    same label are summed rather than duplicated. Row order (busiest first) is preserved.
    """
    projected: List[McpCatalogBucketOut] = []
    index: Dict[str, int] = {}
    for row in rows or []:
        raw = row.get("label")
        label = str(raw) if raw is not None and str(raw) != "" else null_label
        count = int(row.get("count") or 0)
        if label in index:
            projected[index[label]].count += count
        else:
            index[label] = len(projected)
            projected.append(McpCatalogBucketOut(label=label, count=count))
    return projected


def mcp_faceted_search_response_from_bundle(
    bundle: Dict[str, Any], *, limit: int, offset: int
) -> McpFacetedSearchResponse:
    """Project a :meth:`Database.search_mcp_catalog_faceted` bundle onto the wire model.

    Endpoint rows reuse the browse projection (host derivation, credential redaction, facet
    fields); the per-dimension bucket rows are projected with their NULL buckets folded into the
    matching sentinel filter values, and the safety tallies become the two fixed posture buckets
    (always present, ordered ``has_destructive`` then ``read_only_only``).
    """
    endpoints = [
        mcp_browse_endpoint_out_from_row(r) for r in (bundle.get("endpoints") or [])
    ]
    safety_counts = bundle.get("safety_counts") or {}
    facets = McpCatalogFacetsOut(
        grade=_facet_buckets(bundle.get("grade_rows"), null_label=UNGRADED_VALUE),
        transport=_facet_buckets(bundle.get("transport_rows"), null_label=UNKNOWN_VALUE),
        category=_facet_buckets(
            bundle.get("category_rows"), null_label=UNCATEGORIZED_VALUE
        ),
        safety=[
            McpCatalogBucketOut(
                label=SAFETY_HAS_DESTRUCTIVE,
                count=int(safety_counts.get("has_destructive") or 0),
            ),
            McpCatalogBucketOut(
                label=SAFETY_READ_ONLY_ONLY,
                count=int(safety_counts.get("read_only_only") or 0),
            ),
        ],
        complexity=_facet_buckets(bundle.get("complexity_rows"), null_label=UNKNOWN_VALUE),
        protocol_version=_facet_buckets(
            bundle.get("protocol_rows"), null_label=UNKNOWN_VALUE
        ),
        health=_facet_buckets(bundle.get("health_rows"), null_label="undiscovered"),
    )
    return McpFacetedSearchResponse(
        success=True,
        total=int(bundle.get("total") or 0),
        count=len(endpoints),
        limit=limit,
        offset=offset,
        endpoints=endpoints,
        facets=facets,
    )


# ===========================================================================
# MCP Catalog — cross-server capability search (V2-MCP-35.2 / MCAT-21.2, #4661)
# ===========================================================================
#
# Keyword (V127 FTS) + semantic (V149 pgvector) search across every capability item in the caller's
# accessible catalog, with matches grouped by owning server. Ranking follows the MCAT-9.7 decision:
# relevance-first (``max(fts_rank, cosine_similarity)`` per item), grade-led tie-break (A first,
# ungraded last), then score, then endpoint name. Server groups paginate via ``limit``/``offset``;
# capabilities within a group are ordered by relevance desc, then ordinal.

McpCrossServerCapabilityMatchSource = Literal["keyword", "semantic", "both"]


class McpCrossServerCapabilityHit(BaseModel):
    """One matched capability inside a cross-server search server group (MCAT-21.2)."""

    model_config = ConfigDict(populate_by_name=True)

    kind: str
    item_id: str
    item_name: str
    item_title: Optional[str] = None
    description: Optional[str] = None
    relevance: float = 0.0
    fts_relevance: float = 0.0
    semantic_similarity: float = 0.0
    match_source: McpCrossServerCapabilityMatchSource


class McpCrossServerCapabilityServerGroup(BaseModel):
    """Matching capabilities from one cataloged server (MCAT-21.2)."""

    model_config = ConfigDict(populate_by_name=True)

    endpoint_id: str
    endpoint_name: str
    endpoint_slug: str
    host: str
    endpoint_url: str
    category: Optional[str] = None
    visibility: str
    current_version_id: Optional[str] = None
    score: Optional[int] = None
    grade: Optional[str] = None
    max_relevance: float = 0.0
    capabilities: List[McpCrossServerCapabilityHit] = Field(default_factory=list)


class McpCrossServerCapabilitySearchResponse(BaseModel):
    """Grouped cross-server capability search results (MCAT-21.2)."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    query: str
    scope: Optional[str] = None
    semantic_enabled: bool = False
    limit: int
    offset: int
    total: int
    count: int
    groups: List[McpCrossServerCapabilityServerGroup] = Field(default_factory=list)


def mcp_cross_server_capability_hit_from_row(row: Dict[str, Any]) -> McpCrossServerCapabilityHit:
    """Project a merged capability row onto :class:`McpCrossServerCapabilityHit`."""
    fts = row.get("fts_relevance", row.get("relevance"))
    semantic = row.get("semantic_similarity", 0.0)
    source = str(row.get("match_source") or "keyword")
    if source not in ("keyword", "semantic", "both"):
        source = "keyword"
    return McpCrossServerCapabilityHit(
        kind=str(row["kind"]),
        item_id=str(row["item_id"]),
        item_name=str(row["item_name"]),
        item_title=str(row["item_title"]) if row.get("item_title") is not None else None,
        description=str(row["description"]) if row.get("description") is not None else None,
        relevance=float(row.get("relevance") or 0.0),
        fts_relevance=float(fts or 0.0),
        semantic_similarity=float(semantic or 0.0),
        match_source=source,  # type: ignore[arg-type]
    )


def mcp_cross_server_capability_search_response_from_groups(
    *,
    query: str,
    scope: Optional[str],
    semantic_enabled: bool,
    limit: int,
    offset: int,
    total: int,
    groups: Sequence[Dict[str, Any]],
) -> McpCrossServerCapabilitySearchResponse:
    """Project grouped DB/aggregation rows onto the cross-server search wire model."""
    wire_groups: List[McpCrossServerCapabilityServerGroup] = []
    for group in groups:
        raw_url = str(group.get("endpoint_url") or "")
        score = group.get("score")
        wire_groups.append(
            McpCrossServerCapabilityServerGroup(
                endpoint_id=str(group["endpoint_id"]),
                endpoint_name=str(group.get("endpoint_name") or ""),
                endpoint_slug=str(group.get("endpoint_slug") or ""),
                host=mcp_endpoint_host(raw_url),
                endpoint_url=redact_url_credentials(raw_url),
                category=str(group["category"]) if group.get("category") is not None else None,
                visibility=str(group.get("visibility") or "private"),
                current_version_id=(
                    str(group["current_version_id"])
                    if group.get("current_version_id") is not None
                    else None
                ),
                score=int(score) if score is not None else None,
                grade=str(group["grade"]) if group.get("grade") is not None else None,
                max_relevance=float(group.get("max_relevance") or 0.0),
                capabilities=[
                    mcp_cross_server_capability_hit_from_row(cap)
                    for cap in (group.get("capabilities") or [])
                ],
            )
        )
    return McpCrossServerCapabilitySearchResponse(
        success=True,
        query=query,
        scope=scope,
        semantic_enabled=semantic_enabled,
        limit=limit,
        offset=offset,
        total=total,
        count=len(wire_groups),
        groups=wire_groups,
    )


# ===========================================================================
# MCP Catalog — capability directory (V2-MCP-35.4 / MCAT-21.4, #4663)
# ===========================================================================
#
# Browsable, paginated index of every live capability item across the caller's accessible catalog,
# filterable by name pattern, type, and owning server. Each row carries enough endpoint context to
# link back to the server without a second read.

McpCapabilityDirectorySort = Literal["server", "name", "type"]
McpCapabilityDirectoryType = Literal["tool", "resource", "resource_template", "prompt"]


class McpCapabilityDirectoryEntry(BaseModel):
    """One capability in the cross-server directory (MCAT-21.4)."""

    model_config = ConfigDict(populate_by_name=True)

    kind: str
    item_id: str
    item_name: str
    item_title: Optional[str] = None
    description: Optional[str] = None
    endpoint_id: str
    endpoint_name: str
    endpoint_slug: str
    host: str
    endpoint_url: str
    category: Optional[str] = None
    visibility: str
    current_version_id: Optional[str] = None
    score: Optional[int] = None
    grade: Optional[str] = None


class McpCapabilityDirectoryResponse(BaseModel):
    """Paginated capability directory envelope (MCAT-21.4)."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    limit: int
    offset: int
    total: int
    count: int
    items: List[McpCapabilityDirectoryEntry] = Field(default_factory=list)


def mcp_capability_directory_entry_from_row(row: Dict[str, Any]) -> McpCapabilityDirectoryEntry:
    """Project a directory row onto :class:`McpCapabilityDirectoryEntry`."""

    def _s(value: Any) -> Optional[str]:
        return str(value) if value is not None else None

    raw_url = str(row["endpoint_url"])
    score = row.get("score")
    return McpCapabilityDirectoryEntry(
        kind=str(row["kind"]),
        item_id=str(row["item_id"]),
        item_name=str(row["item_name"]),
        item_title=_s(row.get("item_title")),
        description=_s(row.get("description")),
        endpoint_id=str(row["endpoint_id"]),
        endpoint_name=str(row["endpoint_name"]),
        endpoint_slug=str(row["endpoint_slug"]),
        host=mcp_endpoint_host(raw_url),
        endpoint_url=redact_url_credentials(raw_url),
        category=_s(row.get("category")),
        visibility=str(row["visibility"]),
        current_version_id=_s(row.get("current_version_id")),
        score=int(score) if score is not None else None,
        grade=_s(row.get("grade")),
    )


def mcp_capability_directory_response_from_rows(
    *,
    rows: Sequence[Dict[str, Any]],
    total: int,
    limit: int,
    offset: int,
) -> McpCapabilityDirectoryResponse:
    """Project directory DB rows onto the wire envelope."""
    items = [mcp_capability_directory_entry_from_row(r) for r in rows]
    return McpCapabilityDirectoryResponse(
        success=True,
        limit=limit,
        offset=offset,
        total=total,
        count=len(items),
        items=items,
    )


# ===========================================================================
# MCP Catalog — duplicate / near-duplicate detection (V2-MCP-36.1 / MCAT-22.1, #4664)
# ===========================================================================


McpDuplicateKind = Literal["exact_url", "same_host", "identical_surface"]


class McpDuplicateEndpointOut(BaseModel):
    """One endpoint in a duplicate review group — advisory context only."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    slug: str
    host: str
    endpoint_url: str
    transport: str
    published: bool
    visibility: str
    surface_fingerprint: Optional[str] = None


class McpDuplicateGroup(BaseModel):
    """Endpoints that likely describe the same MCP server (advisory; no auto-merge)."""

    model_config = ConfigDict(populate_by_name=True)

    kind: McpDuplicateKind
    match_key: str
    reason: str
    endpoint_count: int
    endpoints: List[McpDuplicateEndpointOut]


class McpDuplicateCrossTenantHint(BaseModel):
    """Published endpoint elsewhere that matches a local duplicate key."""

    model_config = ConfigDict(populate_by_name=True)

    kind: McpDuplicateKind
    match_key: str
    local_endpoint_ids: List[str]
    foreign_tenant_slug: str
    foreign_endpoint_slug: str
    foreign_endpoint_name: str


class McpDuplicateReportResponse(BaseModel):
    """Advisory duplicate review list for the caller's catalog."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    advisory: bool = True
    group_count: int
    flagged_endpoint_count: int
    groups: List[McpDuplicateGroup]
    cross_tenant_hints: List[McpDuplicateCrossTenantHint] = Field(default_factory=list)


def mcp_duplicate_endpoint_out_from_row(row: Dict[str, Any]) -> McpDuplicateEndpointOut:
    """Project a duplicate-candidate row onto the wire model."""
    raw_url = str(row["endpoint_url"])
    return McpDuplicateEndpointOut(
        id=str(row["id"]),
        name=str(row["name"]),
        slug=str(row["slug"]),
        host=mcp_endpoint_host(raw_url),
        endpoint_url=redact_url_credentials(raw_url) or "",
        transport=str(row["transport"]),
        published=bool(row.get("published", False)),
        visibility=str(row["visibility"]),
        surface_fingerprint=(
            str(row["surface_fingerprint"]) if row.get("surface_fingerprint") is not None else None
        ),
    )


# ===========================================================================
# MCP Catalog — staleness & freshness reporting (V2-MCP-36.2 / MCAT-22.2, #4665)
# ===========================================================================

McpFreshnessStatus = Literal["fresh", "stale", "failing", "backoff", "quarantined"]


class McpFreshnessEndpointOut(BaseModel):
    """One endpoint flagged by the freshness report."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    slug: str
    host: str
    endpoint_url: str
    transport: str
    published: bool
    visibility: str
    enabled: bool
    freshness: McpFreshnessStatus
    reason: str
    last_known_good_at: Optional[str] = None
    last_discovered_at: Optional[str] = None
    last_discovery_status: Optional[str] = None
    discovery_cadence_seconds: Optional[int] = None
    consecutive_failures: int = 0
    next_discovery_after: Optional[str] = None
    quarantined: bool = False
    quarantine_reason: Optional[str] = None


class McpFreshnessReportResponse(BaseModel):
    """Freshness report over the caller's catalog — only non-fresh endpoints are listed."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    default_cadence_seconds: int
    flagged_endpoint_count: int
    endpoints: List[McpFreshnessEndpointOut]


# ===========================================================================
# MCP Catalog — saved searches (V2-MCP-35.3 / MCAT-21.3, #4662)
# ===========================================================================
#
# Named filter bundles per user/tenant: save, list, run, and delete catalog searches; optionally
# pin as catalog "views". Filters mirror the ADE catalog toolbar (``McpCatalogFilters``).


class McpSavedSearchFiltersOut(BaseModel):
    """Composable catalog filter state persisted with a saved search."""

    model_config = ConfigDict(populate_by_name=True)

    hosts: List[str] = Field(default_factory=list)
    grades: List[str] = Field(default_factory=list)
    transports: List[str] = Field(default_factory=list)
    visibilities: List[str] = Field(default_factory=list)
    auths: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    safeties: List[str] = Field(default_factory=list)
    complexities: List[str] = Field(default_factory=list)
    protocols: List[str] = Field(default_factory=list)
    healths: List[str] = Field(default_factory=list)


class McpSavedSearchOut(BaseModel):
    """One saved catalog search owned by the caller."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    filters: McpSavedSearchFiltersOut
    query: str = ""
    sort: str = "grade"
    is_pinned: bool = Field(default=False, alias="isPinned")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")


class McpSavedSearchListResponse(BaseModel):
    """Envelope for listing saved searches."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    searches: List[McpSavedSearchOut] = Field(default_factory=list)


class McpSavedSearchCreate(BaseModel):
    """Request body for creating a saved search."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    filters: McpSavedSearchFiltersOut = Field(default_factory=McpSavedSearchFiltersOut)
    query: str = ""
    sort: str = "grade"
    is_pinned: bool = Field(default=False, alias="isPinned")


class McpSavedSearchUpdate(BaseModel):
    """Request body for patching a saved search (all fields optional)."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: Optional[str] = None
    filters: Optional[McpSavedSearchFiltersOut] = None
    query: Optional[str] = None
    sort: Optional[str] = None
    is_pinned: Optional[bool] = Field(default=None, alias="isPinned")


class McpSavedSearchRunResponse(BaseModel):
    """Saved search definition plus the faceted result of running its facet-compatible filters."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    search: McpSavedSearchOut
    result: McpFacetedSearchResponse


def mcp_saved_search_out_from_row(row: Dict[str, Any]) -> McpSavedSearchOut:
    """Project a ``mcp_saved_searches`` row onto the wire model."""
    raw_filters = row.get("filters") or {}
    if not isinstance(raw_filters, dict):
        raw_filters = {}
    return McpSavedSearchOut(
        id=str(row["id"]),
        name=str(row["name"]),
        filters=McpSavedSearchFiltersOut.model_validate(raw_filters),
        query=str(row.get("query") or ""),
        sort=str(row.get("sort") or "grade"),
        is_pinned=bool(row.get("is_pinned")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class McpEndpointNoteOut(BaseModel):
    """One cataloger note on an MCP endpoint (human commentary, not server-reported data)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    endpoint_id: str = Field(serialization_alias="endpointId")
    body: str
    created_by: str = Field(serialization_alias="createdBy")
    created_by_name: Optional[str] = Field(default=None, serialization_alias="createdByName")
    created_by_email: Optional[str] = Field(default=None, serialization_alias="createdByEmail")
    updated_by: Optional[str] = Field(default=None, serialization_alias="updatedBy")
    updated_by_name: Optional[str] = Field(default=None, serialization_alias="updatedByName")
    updated_by_email: Optional[str] = Field(default=None, serialization_alias="updatedByEmail")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class McpEndpointNoteListResponse(BaseModel):
    """Envelope for a cataloger-notes list."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    notes: List[McpEndpointNoteOut] = Field(default_factory=list)


class McpEndpointNoteCreate(BaseModel):
    """Body for creating a cataloger note."""

    model_config = ConfigDict(populate_by_name=True)

    body: str


class McpEndpointNoteUpdate(BaseModel):
    """Patch body for updating a cataloger note."""

    model_config = ConfigDict(populate_by_name=True)

    body: Optional[str] = None


def mcp_endpoint_note_out_from_row(row: Dict[str, Any]) -> McpEndpointNoteOut:
    """Project a ``mcp_endpoint_notes`` row (with author joins) onto the wire model."""
    return McpEndpointNoteOut(
        id=str(row["id"]),
        endpoint_id=str(row["endpoint_id"]),
        body=str(row["body"]),
        created_by=str(row["created_by"]),
        created_by_name=row.get("created_by_name"),
        created_by_email=row.get("created_by_email"),
        updated_by=str(row["updated_by"]) if row.get("updated_by") else None,
        updated_by_name=row.get("updated_by_name"),
        updated_by_email=row.get("updated_by_email"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class McpCollectionMemberOut(BaseModel):
    """One endpoint membership row in a curated collection."""

    model_config = ConfigDict(populate_by_name=True)

    endpoint_id: str = Field(serialization_alias="endpointId")
    position: int = 0
    name: str
    slug: str
    host: str
    grade: Optional[str] = None
    visibility: str
    published: bool
    added_at: datetime = Field(serialization_alias="addedAt")


class McpCollectionOut(BaseModel):
    """One tenant-scoped curated collection of MCP endpoints."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    slug: str
    description: Optional[str] = None
    is_published: bool = Field(default=False, serialization_alias="isPublished")
    member_count: int = Field(default=0, serialization_alias="memberCount")
    created_by: str = Field(serialization_alias="createdBy")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")
    members: Optional[List[McpCollectionMemberOut]] = None


class McpCollectionListResponse(BaseModel):
    """Envelope for listing curated collections."""

    model_config = ConfigDict(populate_by_name=True)

    success: bool = True
    collections: List[McpCollectionOut] = Field(default_factory=list)


class McpCollectionCreate(BaseModel):
    """Body for creating a curated collection."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    is_published: bool = Field(default=False, alias="isPublished")
    endpoint_ids: List[str] = Field(default_factory=list, alias="endpointIds")


class McpCollectionUpdate(BaseModel):
    """Patch body for updating a curated collection."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: Optional[str] = None
    slug: Optional[str] = None
    description: Optional[str] = None
    is_published: Optional[bool] = Field(default=None, alias="isPublished")


class McpCollectionMembersReplace(BaseModel):
    """Replace the full membership list for a collection."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    endpoint_ids: List[str] = Field(default_factory=list, alias="endpointIds")


class McpCollectionMembersAdd(BaseModel):
    """Append endpoints to a collection."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    endpoint_ids: List[str] = Field(alias="endpointIds")


def mcp_collection_member_out_from_row(row: Dict[str, Any]) -> McpCollectionMemberOut:
    """Project a collection-member join row onto the wire model."""
    return McpCollectionMemberOut(
        endpoint_id=str(row["endpoint_id"]),
        position=int(row.get("position") or 0),
        name=str(row["name"]),
        slug=str(row["slug"]),
        host=str(row.get("host") or ""),
        grade=row.get("grade"),
        visibility=str(row.get("visibility") or "private"),
        published=bool(row.get("published")),
        added_at=row["added_at"],
    )


def mcp_collection_out_from_row(
    row: Dict[str, Any],
    *,
    members: Optional[List[McpCollectionMemberOut]] = None,
) -> McpCollectionOut:
    """Project a ``mcp_collections`` row onto the wire model."""
    return McpCollectionOut(
        id=str(row["id"]),
        name=str(row["name"]),
        slug=str(row["slug"]),
        description=row.get("description"),
        is_published=bool(row.get("is_published")),
        member_count=int(row.get("member_count") or 0),
        created_by=str(row["created_by"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        members=members,
    )
