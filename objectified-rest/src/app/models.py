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
    change_report_template_version_id: Optional[str] = Field(
        None,
        serialization_alias="changeReportTemplateVersionId",
    )
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


# ==================== Version Quality Models ====================


class VersionQualityScoreSchema(BaseModel):
    """A single quality snapshot for a version (one row per `Compute quality` run)."""

    id: str
    tenant_id: str
    project_id: str
    version_id: str
    overall: int
    completeness: int
    consistency: int
    descriptions: int
    examples: int
    class_count: int
    property_count: int
    computed_by: Optional[str] = None
    computed_at: Optional[Union[datetime, str]] = None
    detail: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class VersionQualityRunResponse(BaseModel):
    """Response from POST /run: the freshly persisted snapshot, plus the prior
    snapshot (when one exists) so the UI can show a delta without a follow-up
    request."""

    snapshot: VersionQualityScoreSchema
    previous: Optional[VersionQualityScoreSchema] = None


# ==================== Version Lint Models ====================


class LintRuleSchema(BaseModel):
    """Static metadata for a registered lint rule. Returned by the rule-list
    endpoint so the UI can surface rule descriptions next to findings."""

    id: str
    severity: Literal["error", "warning", "info"]
    title: str
    description: str
    target_kind: Literal["class", "property", "schema"]

    class Config:
        from_attributes = True


class VersionLintFindingSchema(BaseModel):
    """One finding emitted by a rule during a lint run."""

    id: str
    result_id: str
    version_id: str
    rule_id: str
    severity: Literal["error", "warning", "info"]
    target_kind: Literal["class", "property", "schema"]
    target_id: Optional[str] = None
    target_path: str
    message: str
    suggestion: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None
    created_at: Optional[Union[datetime, str]] = None

    class Config:
        from_attributes = True


class VersionLintResultSchema(BaseModel):
    """Header row for a lint run; the UI's scorecard reads this directly."""

    id: str
    tenant_id: str
    project_id: str
    version_id: str
    grade: Literal["A", "B", "C", "D", "F"]
    error_count: int
    warning_count: int
    info_count: int
    rules_applied: int
    duration_ms: Optional[int] = None
    computed_by: Optional[str] = None
    computed_at: Optional[Union[datetime, str]] = None
    detail: Optional[Dict[str, Any]] = None

    class Config:
        from_attributes = True


class VersionLintRunResponse(BaseModel):
    """Response from POST /run: the freshly persisted result + every finding it
    produced (so callers can render the scorecard in one round-trip)."""

    result: VersionLintResultSchema
    findings: List[VersionLintFindingSchema]
    previous: Optional[VersionLintResultSchema] = None


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

