from datetime import datetime
from pydantic import BaseModel, Field, AliasChoices, ConfigDict, model_validator
from typing import Optional, Dict, Any, List, Union, Literal


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

    class Config:
        from_attributes = True


class PrimitiveUpdateRequest(BaseModel):
    """Request model for updating a primitive."""
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    schema: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None

    class Config:
        from_attributes = True


class PrimitiveImportRequest(BaseModel):
    """Request model for importing primitives from JSON Schema."""
    schema: Dict[str, Any]  # Full JSON Schema document
    import_all: bool = False  # If True, import all definitions; if False, select specific ones
    selected_definitions: Optional[List[str]] = None  # List of definition keys to import

    class Config:
        from_attributes = True


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
    metadata: Optional[Dict[str, Any]] = None
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
    enabled: bool = True
    parent_version_id: Optional[str] = None
    merge_parent_version_id: Optional[str] = None
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
    bump_strategy: Optional[str] = None  # 'patch' or 'minor' for auto-versioning


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


class CompatibilityCheckResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    overall: str
    base_revision_id: str = Field(serialization_alias="baseRevisionId")
    head_revision_id: str = Field(serialization_alias="headRevisionId")
    findings: List[CompatibilityFindingOut]
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


