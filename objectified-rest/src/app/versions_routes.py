"""
Versions API Routes

Provides CRUD endpoints for managing versions within projects.
All endpoints are tenant and project-scoped and require authentication via JWT token or API key.
"""

import re
from datetime import date as date_cls
from typing import Literal, Optional, List, Dict, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from .database import StaleHeadPushError, db
from .models import (
    VersionSchema,
    VersionCreateRequest,
    VersionForkRequest,
    VersionUpdateRequest,
    VersionPublishRequest,
    SunsetTimelineResponse,
    SunsetTimelineEntryOut,
)
from .auth import validate_authentication, get_authenticated_user_id
from .version_notes import (
    CommitPolicyViolation,
    commit_policy_http_exception,
    effective_commit_policy,
    enforce_max_commit_payload,
    validate_version_notes,
)
from .revision_deprecation import (
    coerce_metadata,
    parse_calendar_date,
    sunset_timeline_fields,
    warnings_for_revision,
)
from .revision_lifecycle import (
    LIFECYCLE_ARCHIVED,
    LIFECYCLE_VALUES,
    effective_lifecycle,
)

router = APIRouter(prefix="/v1/versions", tags=["versions"])


_DEFAULT_COMMIT_METADATA_MAX_CHARS = 10_000
_AUTHOR_OR_REF_MAX_CHARS = 500


def _optional_commit_metadata_str(
    value: Optional[str],
    *,
    field_name: str = "value",
    max_length: int = _DEFAULT_COMMIT_METADATA_MAX_CHARS,
) -> Optional[str]:
    """Normalize optional commit metadata and reject overlong values (#2563)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    if len(s) > max_length:
        raise HTTPException(
            status_code=400,
            detail=f"{field_name} must be at most {max_length} characters",
        )
    return s


_SUCCESSOR_RESOLUTION_DESC = (
    "none: return the requested revision only. "
    "resolve: follow metadata.successorRevisionId (same project, #748); JSON body is the final revision; "
    "see X-Objectified-* response headers. "
    "redirect: HTTP 307 to this path with the final revision id and successorResolution=none."
)


def _successor_resolution_headers(
    *,
    requested_id: str,
    final_id: str,
    hops: List[str],
    status: str,
    missing_id: Optional[str],
) -> Dict[str, str]:
    h: Dict[str, str] = {"X-Objectified-Successor-Resolution-Status": status}
    if requested_id != final_id:
        h["X-Objectified-Resolved-From"] = requested_id
    if hops:
        h["X-Objectified-Successor-Chain"] = ",".join(hops)
    if missing_id:
        h["X-Objectified-Missing-Successor-Id"] = missing_id
    return h


def parse_semantic_version(version: str) -> Optional[Dict[str, int]]:
    """Parse a semantic version string into components."""
    match = re.match(r'^(\d+)\.(\d+)\.(\d+)$', version)
    if match:
        return {
            'major': int(match.group(1)),
            'minor': int(match.group(2)),
            'patch': int(match.group(3))
        }
    return None


def bump_patch_version(version: str) -> str:
    """Increment the patch version."""
    parsed = parse_semantic_version(version)
    if parsed:
        return f"{parsed['major']}.{parsed['minor']}.{parsed['patch'] + 1}"
    return '0.1.0'


def bump_minor_version(version: str) -> str:
    """Increment the minor version and reset patch to 0."""
    parsed = parse_semantic_version(version)
    if parsed:
        return f"{parsed['major']}.{parsed['minor'] + 1}.0"
    return '0.1.0'


def _push_stale_head_detail(*, tenant_id: str, head_revision_id: str) -> Dict[str, Any]:
    """
    409 body for optimistic push conflicts (#2566).
    P0-05 UI: read ``code`` == ``STALE_HEAD``, ``currentHeadRevisionId``, ``currentHead`` (subset).
    """
    head_ver = db.get_version_by_id(head_revision_id, tenant_id)
    out: Dict[str, Any] = {
        "message": "Branch tip does not match baseRevisionId (stale head or wrong base).",
        "code": "STALE_HEAD",
        "currentHeadRevisionId": head_revision_id,
    }
    if head_ver:
        out["currentHead"] = {
            "revisionId": str(head_ver["id"]),
            "versionId": head_ver.get("version_id"),
            "shortMessage": head_ver.get("description"),
            "createdAt": head_ver.get("created_at"),
        }
    return out


def _resolve_expected_push_head(
    project_id: str,
    tenant_id: str,
    branch_name: Optional[str],
) -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Expected head revision id before push, and optional branch row to advance.
    """
    branches = db.list_version_branches_for_project(project_id, tenant_id)
    bn = (branch_name or "").strip() or None

    if bn:
        b = db.get_version_branch_by_name(project_id, tenant_id, bn)
        if not b:
            raise HTTPException(status_code=404, detail=f"Branch not found: {bn}")
        return (str(b["tip_version_id"]), b)

    n = len(branches)
    if n == 0:
        tip = db.get_latest_revision_id_for_project(project_id, tenant_id)
        return (tip, None)
    if n == 1:
        b = branches[0]
        return (str(b["tip_version_id"]), b)

    raise HTTPException(
        status_code=400,
        detail={
            "message": "branchName is required when the project has multiple branches",
            "code": "BRANCH_NAME_REQUIRED",
        },
    )


@router.get("/{tenant_slug}/sunset-timeline", response_model=SunsetTimelineResponse)
async def get_sunset_timeline(
    tenant_slug: str,
    project_id: Optional[str] = Query(None, alias="projectId"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SunsetTimelineResponse:
    """
    Aggregate deprecation and sunset dates across projects (#508).
    Must be registered before ``/{tenant_slug}/{project_id}`` so ``sunset-timeline`` is not parsed as a project id.
    """
    tid = auth_data["tenant_id"]
    if project_id:
        proj = db.get_project_by_id(project_id, tid)
        if not proj:
            raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    rows = db.list_sunset_timeline_entries(tid, project_id)
    decorated: List[tuple] = []
    for row in rows:
        meta = row.get("metadata")
        t_status, life, norm = sunset_timeline_fields(meta)
        m = coerce_metadata(meta)
        raw_msg = m.get("deprecationMessage") or m.get("message")
        msg: Optional[str] = None
        if isinstance(raw_msg, str) and raw_msg.strip():
            msg = raw_msg.strip()
        succ = m.get("successorRevisionId") or m.get("successor_revision_id")
        succ_str = succ.strip() if isinstance(succ, str) and succ.strip() else None
        warns = warnings_for_revision(
            revision_id=row["id"],
            version_label=row["version_id"],
            role="head",
            metadata=meta,
        )
        sort_date = parse_calendar_date(norm) if norm else None
        decorated.append(
            (
                sort_date or date_cls(9999, 12, 31),
                row,
                t_status,
                life,
                norm,
                msg,
                succ_str,
                warns,
            )
        )

    decorated.sort(
        key=lambda x: (x[0], (x[1].get("project_name") or ""), (x[1].get("version_id") or ""))
    )

    entries: List[SunsetTimelineEntryOut] = []
    for _, row, t_status, life, norm, msg, succ_str, warns in decorated:
        entries.append(
            SunsetTimelineEntryOut(
                revision_id=row["id"],
                project_id=row["project_id"],
                project_name=row.get("project_name"),
                project_slug=row.get("project_slug"),
                version_line=row["version_id"],
                sunset_date=norm,
                sunset_at=norm,
                timeline_status=t_status,
                lifecycle_phase=life,
                deprecation_message=msg,
                successor_revision_id=succ_str,
                published=bool(row.get("published")),
                deprecation_warnings=warns,
            )
        )

    return SunsetTimelineResponse(entries=entries)


@router.get("/{tenant_slug}/{project_id}")
async def list_versions(
    tenant_slug: str,
    project_id: str,
    lifecycle: Optional[str] = Query(
        None,
        description="Filter catalog/history by revision lifecycle tag (#739): stable, beta, deprecated, archived.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> List[VersionSchema]:
    """
    List all versions for a project.

    Supports authentication via:
    - JWT token in Authorization header (Bearer token)
    - API key in X-API-Key header

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        auth_data: Authentication data (injected by dependency)

    Returns:
        List of versions for the project
    """
    # Verify project belongs to tenant
    project = db.get_project_by_id(project_id, auth_data['tenant_id'])
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_id}"
        )

    lc_filter: Optional[str] = None
    if lifecycle is not None and str(lifecycle).strip() != "":
        lc_norm = str(lifecycle).strip().lower()
        if lc_norm not in LIFECYCLE_VALUES:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid lifecycle filter; expected one of: {', '.join(sorted(LIFECYCLE_VALUES))}",
            )
        lc_filter = lc_norm

    versions = db.get_versions_for_project(project_id, auth_data["tenant_id"], lifecycle=lc_filter)

    return [VersionSchema(**v) for v in versions]


@router.get("/{tenant_slug}/{project_id}/{version_record_id}", response_model=VersionSchema)
async def get_version(
    request: Request,
    response: Response,
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    successor_resolution: Literal["none", "resolve", "redirect"] = Query(
        "none",
        alias="successorResolution",
        description=_SUCCESSOR_RESOLUTION_DESC,
    ),
    audit_successor_resolution: bool = Query(
        False,
        alias="auditSuccessorResolution",
        description="When true, emit version_protection_audit for successor resolution (#749).",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
):
    """
    Get a specific version by ID.

    Supports authentication via JWT token or API key.

    Successor resolution (#749): when ``successorResolution`` is ``resolve`` or ``redirect``, follows
    ``metadata.successorRevisionId`` (#748) within the project until a revision has no successor, hits a
    protected branch tip / protected tag target (#504), or errors. Loops return 409 ``SUCCESSOR_CYCLE``.
    """
    version = db.get_version_by_id(version_record_id, auth_data["tenant_id"])

    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {version_record_id}",
        )

    if version["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found in project: {project_id}",
        )

    if successor_resolution == "none":
        return VersionSchema(**version)

    final_id, hops, status, missing_id = db.resolve_successor_revision_chain(
        version_record_id,
        auth_data["tenant_id"],
        project_id,
    )

    if status == "cycle":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SUCCESSOR_CYCLE",
                "message": "Successor chain contains a cycle",
                "chain": hops,
            },
        )

    if status == "max_hops_exceeded":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SUCCESSOR_MAX_HOPS_EXCEEDED",
                "message": "Successor chain exceeds maximum allowed hops",
                "chain": hops,
            },
        )

    if status == "project_mismatch":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SUCCESSOR_PROJECT_MISMATCH",
                "message": "Successor revision is not in this project",
            },
        )

    final_row = db.get_version_by_id(final_id, auth_data["tenant_id"])
    if not final_row:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {final_id}",
        )

    _audit_resolution = bool(
        hops or status not in ("none", "resolved")
    )
    if audit_successor_resolution and successor_resolution != "none" and _audit_resolution:
        uid = get_authenticated_user_id(auth_data)
        db.insert_version_protection_audit(
            auth_data["tenant_id"],
            project_id,
            uid,
            "version.successor_resolution",
            "version",
            final_id,
            "allowed",
            {
                "fromRevisionId": version_record_id,
                "mode": successor_resolution,
                "chain": hops,
                "status": status,
            },
        )

    if successor_resolution == "redirect":
        if final_id == version_record_id:
            return VersionSchema(**version)
        base = request.url.path.rstrip("/").rsplit("/", 1)[0]
        loc = request.url.replace(path=f"{base}/{final_id}", query="successorResolution=none")
        return RedirectResponse(str(loc), status_code=307)

    for k, v in _successor_resolution_headers(
        requested_id=version_record_id,
        final_id=final_id,
        hops=hops,
        status=status,
        missing_id=missing_id,
    ).items():
        response.headers[k] = v

    return VersionSchema(**final_row)


@router.get("/{tenant_slug}/{project_id}/by-version/{version_id}", response_model=VersionSchema)
async def get_version_by_version_id(
    request: Request,
    response: Response,
    tenant_slug: str,
    project_id: str,
    version_id: str,
    successor_resolution: Literal["none", "resolve", "redirect"] = Query(
        "none",
        alias="successorResolution",
        description=_SUCCESSOR_RESOLUTION_DESC,
    ),
    audit_successor_resolution: bool = Query(
        False,
        alias="auditSuccessorResolution",
        description="When true, emit version_protection_audit for successor resolution (#749).",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
):
    """
    Get a specific version by version ID string (e.g., '1.0.0').

    Supports authentication via JWT token or API key.
    Successor resolution (#749) matches ``GET .../{version_record_id}``.
    """
    version = db.get_version_by_version_id(project_id, version_id, auth_data["tenant_id"])

    if not version:
        raise HTTPException(
            status_code=404,
            detail=f"Version '{version_id}' not found in project",
        )

    version_record_id = str(version["id"])

    if successor_resolution == "none":
        return VersionSchema(**version)

    final_id, hops, status, missing_id = db.resolve_successor_revision_chain(
        version_record_id,
        auth_data["tenant_id"],
        project_id,
    )

    if status == "cycle":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SUCCESSOR_CYCLE",
                "message": "Successor chain contains a cycle",
                "chain": hops,
            },
        )

    if status == "max_hops_exceeded":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SUCCESSOR_MAX_HOPS_EXCEEDED",
                "message": "Successor chain exceeds maximum allowed hops",
                "chain": hops,
            },
        )

    if status == "project_mismatch":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SUCCESSOR_PROJECT_MISMATCH",
                "message": "Successor revision is not in this project",
            },
        )

    final_row = db.get_version_by_id(final_id, auth_data["tenant_id"])
    if not final_row:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {final_id}",
        )

    _audit_resolution = bool(
        hops or status not in ("none", "resolved")
    )
    if audit_successor_resolution and successor_resolution != "none" and _audit_resolution:
        uid = get_authenticated_user_id(auth_data)
        db.insert_version_protection_audit(
            auth_data["tenant_id"],
            project_id,
            uid,
            "version.successor_resolution",
            "version",
            final_id,
            "allowed",
            {
                "fromRevisionId": version_record_id,
                "mode": successor_resolution,
                "chain": hops,
                "status": status,
            },
        )

    if successor_resolution == "redirect":
        if final_id == version_record_id:
            return VersionSchema(**version)
        base = request.url.path.rstrip("/").rsplit("/", 1)[0]
        loc = request.url.replace(
            path=f"{base}/{final_row['version_id']}",
            query="successorResolution=none",
        )
        return RedirectResponse(str(loc), status_code=307)

    for k, v in _successor_resolution_headers(
        requested_id=version_record_id,
        final_id=final_id,
        hops=hops,
        status=status,
        missing_id=missing_id,
    ).items():
        response.headers[k] = v

    return VersionSchema(**final_row)


@router.post("/{tenant_slug}/{project_id}")
async def create_version(
    tenant_slug: str,
    project_id: str,
    request: VersionCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> VersionSchema:
    """
    Create a new version (push).

    Supports authentication via JWT token or API key.
    When using JWT, the creator_id field will be set to the authenticated user.

    **Optimistic locking (#2566):** ``baseRevisionId`` is required. It must match the server head
    (branch tip, or latest revision when there are no branches) before this push. If another client
    advanced the head, the API returns **409** with ``code: STALE_HEAD`` and ``currentHead`` metadata.

    If version_id is not provided, it will be auto-generated by bumping the latest version.
    Use bump_strategy='minor' for minor version bump, or 'patch' (default) for patch bump.

    If source_version_id is provided, classes will be copied from that version.

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        request: Version creation data
        auth_data: Authentication data (injected by dependency)

    Returns:
        The created version
    """
    tenant_id = auth_data["tenant_id"]
    # Verify project belongs to tenant
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail=f"Project not found: {project_id}"
        )

    # Determine version_id
    version_id = request.version_id
    if not version_id or not version_id.strip():
        # Auto-generate by bumping latest version
        latest_version = db.get_latest_version_for_project(project_id, tenant_id)
        if latest_version:
            if request.bump_strategy == 'minor':
                version_id = bump_minor_version(latest_version)
            else:
                version_id = bump_patch_version(latest_version)
        else:
            version_id = '0.1.0'
    else:
        version_id = version_id.strip()

    # Validate semantic versioning format
    if not parse_semantic_version(version_id):
        raise HTTPException(
            status_code=400,
            detail="Version ID must follow semantic versioning format (e.g., 1.0.0)"
        )

    try:
        # Get creator_id from auth data (will be None for API key auth)
        creator_id = get_authenticated_user_id(auth_data)

        limits = effective_commit_policy(tenant_id, project.get("metadata"))
        try:
            enforce_max_commit_payload(request, limits)
            sm, cl = validate_version_notes(
                request.short_message,
                request.changelog,
                limits,
                require_short_message=limits.require_short_message,
            )
        except CommitPolicyViolation as pe:
            raise commit_policy_http_exception(pe) from pe

        # Validate and normalize commit metadata before DB call so 400s surface correctly
        commit_author = _optional_commit_metadata_str(
            request.author, field_name="author", max_length=_AUTHOR_OR_REF_MAX_CHARS
        )
        commit_message = _optional_commit_metadata_str(request.message, field_name="message")
        commit_external_ref = _optional_commit_metadata_str(
            request.external_ref, field_name="externalRef", max_length=_AUTHOR_OR_REF_MAX_CHARS
        )

        base = (request.base_revision_id or "").strip()
        expected_tip, branch_row = _resolve_expected_push_head(
            project_id, tenant_id, request.branch_name
        )

        if expected_tip is None:
            if base:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": "baseRevisionId must be empty when there is no current revision",
                        "code": "INVALID_BASE",
                    },
                )
            parent_version_id: Optional[str] = None
        else:
            if base != expected_tip:
                raise HTTPException(
                    status_code=409,
                    detail=_push_stale_head_detail(tenant_id=tenant_id, head_revision_id=expected_tip),
                )
            parent_version_id = expected_tip

        copy_source_id: Optional[str] = None
        copy_warning: Optional[str] = None
        if request.source_version_id and request.source_version_id.strip():
            copy_source_id = request.source_version_id.strip()
            source_version = db.get_version_by_id(copy_source_id, tenant_id)
            if not source_version:
                copy_warning = f"Source version not found: {copy_source_id}"
                copy_source_id = None

        try:
            version, copied_count = db.create_version_push_transaction(
                project_id=project_id,
                tenant_id=tenant_id,
                creator_id=creator_id,
                version_id=version_id,
                description=sm,
                change_log=cl,
                commit_author=commit_author,
                commit_message=commit_message,
                external_ref=commit_external_ref,
                parent_version_id=parent_version_id,
                source_version_id=copy_source_id,
                branch_row=branch_row,
                client_base_revision_id=base,
            )
        except StaleHeadPushError as sh:
            raise HTTPException(
                status_code=409,
                detail=_push_stale_head_detail(
                    tenant_id=tenant_id, head_revision_id=sh.current_tip_revision_id
                ),
            ) from sh

        response_data = {**version}
        if copy_warning:
            response_data["copy_warning"] = copy_warning
        elif copied_count > 0:
            response_data["copied_classes"] = copied_count

        return VersionSchema(**response_data)
    except HTTPException:
        raise
    except Exception as e:
        # Check for unique constraint violation
        if "unique constraint" in str(e).lower() or "23505" in str(e):
            raise HTTPException(
                status_code=409,
                detail=f"A version with ID '{version_id}' already exists in this project"
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant_slug}/{project_id}/fork")
async def fork_version_from_revision(
    tenant_slug: str,
    project_id: str,
    request: VersionForkRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionSchema:
    """
    Fork a schema version line into this project from a source revision in another project (sandbox / provenance).

    Not the same as a named branch within one project (#500): fork is cross-project isolation with recorded lineage.
    """
    target_project = db.get_project_by_id(project_id, auth_data["tenant_id"])
    if not target_project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    src_id = (request.source_revision_id or "").strip()
    if not src_id:
        raise HTTPException(status_code=400, detail="sourceRevisionId is required")

    version_id = (request.version_id or "").strip() if request.version_id else ""
    if not version_id:
        latest_version = db.get_latest_version_for_project(project_id, auth_data["tenant_id"])
        if latest_version:
            if request.bump_strategy == "minor":
                version_id = bump_minor_version(latest_version)
            else:
                version_id = bump_patch_version(latest_version)
        else:
            version_id = "0.1.0"
    else:
        version_id = version_id.strip()

    if not parse_semantic_version(version_id):
        raise HTTPException(
            status_code=400,
            detail="Version ID must follow semantic versioning format (e.g., 1.0.0)",
        )

    creator_id = get_authenticated_user_id(auth_data)
    if not creator_id:
        raise HTTPException(status_code=403, detail="Forking requires user authentication (JWT token)")

    limits = effective_commit_policy(auth_data["tenant_id"], target_project.get("metadata"))
    try:
        enforce_max_commit_payload(request, limits)
        sm, cl = validate_version_notes(
            request.short_message,
            request.changelog,
            limits,
            require_short_message=limits.require_short_message,
        )
    except CommitPolicyViolation as pe:
        raise commit_policy_http_exception(pe) from pe

    upstream_opt = (request.upstream_project_id or "").strip() or None

    result = db.create_forked_version(
        target_project_id=project_id,
        tenant_id=auth_data["tenant_id"],
        creator_id=creator_id,
        version_id=version_id,
        description=sm,
        change_log=cl,
        source_revision_id=src_id,
        upstream_project_id=upstream_opt,
        commit_author=_optional_commit_metadata_str(
            request.author, field_name="author", max_length=_AUTHOR_OR_REF_MAX_CHARS
        ),
        commit_message=_optional_commit_metadata_str(request.message, field_name="message"),
        external_ref=_optional_commit_metadata_str(
            request.external_ref, field_name="externalRef", max_length=_AUTHOR_OR_REF_MAX_CHARS
        ),
    )

    if not result.get("success"):
        err = result.get("error", "Fork failed")
        if "different target project" in err or "Branch from here" in err:
            raise HTTPException(status_code=400, detail=err)
        if "not found" in err.lower():
            raise HTTPException(status_code=404, detail=err)
        raise HTTPException(status_code=400, detail=err)

    version = result["version"]
    return VersionSchema(**version)


@router.put("/{tenant_slug}/{project_id}/{version_record_id}")
async def update_version(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    request: VersionUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> VersionSchema:
    """
    Update an existing version.

    Supports authentication via JWT token or API key.
    Published versions cannot be updated (they are frozen).

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        version_record_id: The version record ID
        request: Version update data
        auth_data: Authentication data (injected by dependency)

    Returns:
        The updated version
    """
    # Check if version exists
    existing = db.get_version_by_id(version_record_id, auth_data['tenant_id'])
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {version_record_id}"
        )

    # Verify version belongs to the specified project
    if existing['project_id'] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found in project: {project_id}"
        )

    try:
        proj_row = db.get_project_by_id(project_id, auth_data["tenant_id"])
        limits = effective_commit_policy(auth_data["tenant_id"], proj_row.get("metadata") if proj_row else None)
        try:
            enforce_max_commit_payload(request, limits)
        except CommitPolicyViolation as pe:
            raise commit_policy_http_exception(pe) from pe

        existing_lc = effective_lifecycle(existing.get("metadata"))
        tenant_id = auth_data["tenant_id"]
        uid_session = get_authenticated_user_id(auth_data)
        tenant_admin = bool(uid_session and db.is_user_tenant_admin(tenant_id, uid_session))

        if existing_lc == LIFECYCLE_ARCHIVED:
            if not tenant_admin:
                raise HTTPException(
                    status_code=403,
                    detail="Archived revisions are read-only (#739). Tenant admins may update lifecycle or revision lock only.",
                )
            if request.enabled is not None and request.enabled != existing.get("enabled"):
                raise HTTPException(
                    status_code=403,
                    detail="Cannot change enabled on an archived revision.",
                )
            note_keys_block = {"short_message", "changelog"}
            if request.model_fields_set & note_keys_block:
                raise HTTPException(
                    status_code=403,
                    detail="Cannot edit version notes on an archived revision.",
                )

        updates: Dict[str, Any] = {}
        if request.enabled is not None:
            updates["enabled"] = request.enabled

        if "revision_locked" in request.model_fields_set:
            uid_lock = get_authenticated_user_id(auth_data)
            if not uid_lock or not db.is_user_tenant_admin(auth_data["tenant_id"], uid_lock):
                raise HTTPException(
                    status_code=403,
                    detail="Only tenant administrators can lock or unlock revisions",
                )
            updates["revision_locked"] = bool(request.revision_locked)

        note_keys = {"short_message", "changelog"}
        if request.model_fields_set & note_keys:
            merged_sm = existing.get("description")
            merged_cl = existing.get("change_log")
            if "short_message" in request.model_fields_set:
                merged_sm = request.short_message
            if "changelog" in request.model_fields_set:
                merged_cl = request.changelog
            try:
                merged_sm, merged_cl = validate_version_notes(
                    merged_sm,
                    merged_cl,
                    limits,
                    require_short_message=limits.require_short_message,
                )
            except CommitPolicyViolation as pe:
                raise commit_policy_http_exception(pe) from pe
            if "short_message" in request.model_fields_set:
                updates["description"] = merged_sm
            if "changelog" in request.model_fields_set:
                updates["change_log"] = merged_cl

        if "metadata" in request.model_fields_set and request.metadata is not None:
            if existing.get("published"):
                uid_meta = get_authenticated_user_id(auth_data)
                if not uid_meta or not db.is_user_tenant_admin(
                    auth_data["tenant_id"], uid_meta
                ):
                    raise HTTPException(
                        status_code=403,
                        detail="Only tenant administrators can update revision metadata on published versions",
                    )
            updates["metadata"] = request.metadata

        # Update version
        version = db.update_version(
            version_record_id,
            auth_data["tenant_id"],
            updates,
            lifecycle_admin=tenant_admin,
        )

        if not version:
            raise HTTPException(
                status_code=404,
                detail=f"Version not found: {version_record_id}"
            )

        if "revision_locked" in request.model_fields_set:
            uid_audit = get_authenticated_user_id(auth_data)
            db.insert_version_protection_audit(
                auth_data["tenant_id"],
                existing.get("project_id"),
                uid_audit,
                "version.revision_lock",
                "version",
                version_record_id,
                "policy_change",
                {"revision_locked": bool(request.revision_locked)},
            )

        return VersionSchema(**version)
    except HTTPException:
        raise
    except CommitPolicyViolation as pe:
        raise commit_policy_http_exception(pe) from pe
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception as e:
        if "published" in str(e).lower() and "frozen" in str(e).lower():
            raise HTTPException(
                status_code=403,
                detail="Cannot edit a published version. Published versions are frozen."
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{tenant_slug}/{project_id}/{version_record_id}/publish")
async def publish_version(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    request: VersionPublishRequest = Body(default_factory=VersionPublishRequest),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> VersionSchema:
    """
    Publish a version.

    Only the version creator or a tenant administrator can publish a version.
    Published versions are frozen and cannot be modified.

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        version_record_id: The version record ID
        request: Optional publish options (visibility)
        auth_data: Authentication data (injected by dependency)

    Returns:
        The published version
    """
    # Check if version exists
    existing = db.get_version_by_id(version_record_id, auth_data['tenant_id'])
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {version_record_id}"
        )

    # Verify version belongs to the specified project
    if existing['project_id'] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found in project: {project_id}"
        )

    if existing.get('published'):
        raise HTTPException(
            status_code=400,
            detail="Version is already published"
        )

    # Get user_id from auth data
    user_id = get_authenticated_user_id(auth_data)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Publishing requires user authentication (JWT token)"
        )

    visibility = request.visibility if request.visibility is not None else "private"
    if visibility not in ("public", "private"):
        visibility = "private"

    proj_pub = db.get_project_by_id(project_id, auth_data["tenant_id"])
    limits = effective_commit_policy(auth_data["tenant_id"], proj_pub.get("metadata") if proj_pub else None)
    try:
        enforce_max_commit_payload(request, limits)
        merged_sm = existing.get("description")
        merged_cl = existing.get("change_log")
        note_keys = {"short_message", "changelog"}
        if request.model_fields_set & note_keys:
            if "short_message" in request.model_fields_set:
                merged_sm = request.short_message
            if "changelog" in request.model_fields_set:
                merged_cl = request.changelog
        merged_sm, merged_cl = validate_version_notes(
            merged_sm,
            merged_cl,
            limits,
            require_short_message=limits.require_short_message,
        )
    except CommitPolicyViolation as pe:
        raise commit_policy_http_exception(pe) from pe

    version = db.publish_version(
        version_record_id,
        auth_data["tenant_id"],
        user_id,
        visibility,
        description=merged_sm,
        change_log=merged_cl,
    )

    if not version:
        raise HTTPException(
            status_code=403,
            detail="Only the version creator or a tenant administrator can publish this version"
        )

    return VersionSchema(**version)


@router.post("/{tenant_slug}/{project_id}/{version_record_id}/unpublish")
async def unpublish_version(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> VersionSchema:
    """
    Unpublish a version.

    Only the version creator or a tenant administrator can unpublish a version.

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        version_record_id: The version record ID
        auth_data: Authentication data (injected by dependency)

    Returns:
        The unpublished version
    """
    # Check if version exists
    existing = db.get_version_by_id(version_record_id, auth_data['tenant_id'])
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {version_record_id}"
        )

    # Verify version belongs to the specified project
    if existing['project_id'] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found in project: {project_id}"
        )

    if not existing.get('published'):
        raise HTTPException(
            status_code=400,
            detail="Version is not published"
        )

    # Block unpublish if any data_record exists for this version's class schemas
    if db.version_has_data_records(version_record_id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "VERSION_HAS_DATA",
                "message": "This version has data records and cannot be unpublished. Create a new version or a new minor version to make changes."
            }
        )

    # Get user_id from auth data
    user_id = get_authenticated_user_id(auth_data)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Unpublishing requires user authentication (JWT token)"
        )

    version = db.unpublish_version(version_record_id, auth_data['tenant_id'], user_id)

    if not version:
        raise HTTPException(
            status_code=403,
            detail="Only the version creator or a tenant administrator can unpublish this version"
        )

    return VersionSchema(**version)


@router.post("/{tenant_slug}/{project_id}/{version_record_id}/freeze-schema")
async def freeze_version_schema(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> VersionSchema:
    """
    Freeze (capture) class schemas into odb.class_schema for this version.
    Only available when the version has no class_schema rows yet (e.g. published before schema capture existed).
    Only the version creator or a tenant administrator can freeze schema.
    """
    existing = db.get_version_by_id(version_record_id, auth_data["tenant_id"])
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {version_record_id}"
        )
    if existing["project_id"] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found in project: {project_id}"
        )
    if db.version_has_class_schema(version_record_id):
        raise HTTPException(
            status_code=400,
            detail="Schema already frozen for this version. Class schemas are already captured."
        )
    user_id = get_authenticated_user_id(auth_data)
    if not user_id:
        raise HTTPException(
            status_code=403,
            detail="Freeze schema requires user authentication (JWT token)"
        )
    version = db.freeze_version_schema(version_record_id, auth_data["tenant_id"], user_id)
    if not version:
        raise HTTPException(
            status_code=403,
            detail="Only the version creator or a tenant administrator can freeze schema for this version"
        )
    return VersionSchema(**version)


@router.delete("/{tenant_slug}/{project_id}/{version_record_id}")
async def delete_version(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication)
) -> Dict[str, str]:
    """
    Delete a version (soft delete).

    Supports authentication via JWT token or API key.

    Args:
        tenant_slug: The tenant slug
        project_id: The project ID
        version_record_id: The version record ID
        auth_data: Authentication data (injected by dependency)

    Returns:
        Success message
    """
    # Check if version exists
    existing = db.get_version_by_id(version_record_id, auth_data['tenant_id'])
    if not existing:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {version_record_id}"
        )

    # Verify version belongs to the specified project
    if existing['project_id'] != project_id:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found in project: {project_id}"
        )

    uid = get_authenticated_user_id(auth_data)
    success, err = db.delete_version(version_record_id, auth_data["tenant_id"], uid)

    if not success:
        if err == "not_found":
            raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
        if err == "forbidden":
            raise HTTPException(
                status_code=403,
                detail="Only the version creator or a tenant admin can delete this version",
            )
        if err == "revision_locked":
            raise HTTPException(
                status_code=403,
                detail="This revision is locked by policy and cannot be deleted",
            )
        raise HTTPException(status_code=500, detail="Failed to delete version")

    return {"message": f"Version '{existing['version_id']}' deleted successfully"}
