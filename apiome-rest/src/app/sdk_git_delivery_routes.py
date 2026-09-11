"""Git delivery endpoints — SDK-4.2 (#4496).

Six routes over the two things an SDK owner needs to receive their SDK as a pull request: somewhere
to say where it goes, and something to press.

```
GET            /v1/projects/{t}/{project}/sdk-git-delivery-targets
PUT|DELETE     /v1/projects/{t}/{project}/sdk-git-delivery-targets/{ecosystem}
POST           /v1/projects/{t}/{project}/sdk-git-delivery
GET            /v1/projects/{t}/{project}/sdk-git-delivery-runs[/{run_id}]
```

**A delivery is a run, and a failed delivery is a failed run.** ``POST …/sdk-git-delivery`` answers
``200`` with the run for every outcome once a target is configured — ``opened``, ``updated``,
``unchanged``, ``up_to_date`` *or* ``failed`` — because a revoked token or a rejected push is a
result worth recording and reading back, not a request error. The HTTP errors are reserved for
requests that cannot start a delivery at all: an unknown project or version, an unpublished
revision, an ecosystem git delivery does not support, or no target configured for it.

**No new credential, and no new RBAC resource.** A target names a repository already registered
with Apiome and a delivery pushes with that repository's existing linked-account integration.
Reading targets is ``projects:view``; delivering — like publishing to a registry — is
``versions:publish``; reading the history is ``versions:view``. **Saving a target needs
``projects:edit`` *and* ``imports:edit``**: pointing deliveries at a repository decides what Apiome
writes into it with that repository's credential, which is the same authority as editing the
repository's integration (repository routes are governed by ``imports``). Requiring both keeps a
project editor from turning someone else's linked account into a push credential for their project.

**Every mutation is audited**, and no audit row or response carries a token — none ever reaches
this module.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .sdk_git_delivery_pipeline import DeliveryOutcome, deliver, run_row_to_outcome
from .sdk_git_delivery_targets import (
    BRANCH_PREFIX,
    DELIVERY_ECOSYSTEMS,
    GitDeliveryTargetError,
    GitDeliveryTargetOut,
    delete_target,
    list_targets,
    normalize_ecosystem,
    resolve_target,
    save_target,
)
from .sdk_publish_pipeline import PublishContext
from .sdk_publish_routes import load_published_source, resolve_project, tenant_id_of, write_audit

logger = logging.getLogger(__name__)

__all__ = ["router"]

#: Shares the ``/v1/projects`` prefix; ``main`` registers it after ``projects_router`` for the same
#: reason SDK-3.4's and SDK-4.1's routers are: ``/{tenant}/{project}/…`` would otherwise also match
#: ``/{tenant}/by-slug/{project_slug}``.
router = APIRouter(prefix="/v1/projects", tags=["sdk-git-delivery"])

#: Audit actions this module writes.
AUDIT_TARGET_UPDATE = "sdk.git_delivery_target.update"
AUDIT_TARGET_CLEAR = "sdk.git_delivery_target.clear"
AUDIT_DELIVERY = "sdk.git_delivery"

#: Largest history page.
MAX_HISTORY_LIMIT = 200

_TARGET_DESCRIPTION = (
    "A **delivery target** says where one project's SDK for one ecosystem is delivered: a "
    "repository already registered with Apiome, the branch pull requests target (blank for the "
    "repository's default branch), and the directory inside the repository the SDK lives in (blank "
    "for the root).\n\n"
    "**No new credential.** A delivery pushes with the repository's existing linked-account "
    "integration, so the repository must have been registered through a linked GitHub account — "
    "one registered from a public URL holds no credential and is refused.\n\n"
    f"Ecosystems: {', '.join('`' + e + '`' for e in DELIVERY_ECOSYSTEMS)} — the SDK-4.1 package "
    f"layouts. Each delivery uses the branch `{BRANCH_PREFIX}<version>-<project>-<ecosystem>`."
)


# ===========================================================================
# Request / response models
# ===========================================================================


class GitDeliveryTargetPutRequest(BaseModel):
    """Body for configuring a delivery target.

    Attributes:
        repository_id: The registered repository to deliver into.
        base_branch: The branch pull requests target; blank for the repository's default branch.
        target_path: The directory inside the repository; blank for the root.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    repository_id: str = Field(
        alias="repositoryId",
        min_length=1,
        max_length=64,
        description="Id of a repository registered through a linked GitHub account.",
    )
    base_branch: Optional[str] = Field(
        default=None,
        alias="baseBranch",
        max_length=255,
        description="The pull request's base branch. Omit for the repository's default branch.",
    )
    target_path: Optional[str] = Field(
        default=None,
        alias="targetPath",
        max_length=1024,
        description="Directory inside the repository, e.g. `sdks/typescript`. Omit for the root.",
    )


class GitDeliveryTargetListResponse(BaseModel):
    """A project's delivery targets.

    Attributes:
        ecosystems: Which ecosystems can be delivered.
        targets: One entry per configured ecosystem.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ecosystems: List[str]
    targets: List[GitDeliveryTargetOut]


class SdkGitDeliveryRequest(BaseModel):
    """Body for a delivery.

    Attributes:
        ecosystem: ``npm`` or ``pypi``.
        version: The revision to deliver — a revision UUID or a version label. Defaults to the
            project's latest revision.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ecosystem: str = Field(description="`npm` or `pypi`.")
    version: Optional[str] = Field(
        default=None,
        description="Revision UUID or version label. Defaults to the latest revision.",
    )


class SdkGitDeliveryRunModel(BaseModel):
    """One delivery run.

    Attributes:
        run_id: The ledger row.
        status: ``in_progress``, ``opened``, ``updated``, ``unchanged``, ``up_to_date`` or
            ``failed``.
        ecosystem: ``npm`` or ``pypi``.
        version_line: The API version delivered.
        release_series: The series the package version was derived under.
        regen_counter: The counter the package version carries.
        package_name: The committed package's name.
        package_version: The committed package's version.
        repository_id: The registered repository.
        repository_full_name: ``owner/repo``.
        base_branch: The base branch used.
        target_path: The directory the SDK was committed under.
        branch_name: The delivery branch.
        base_sha: The base commit.
        commit_sha: The commit the branch points at.
        pull_request_number: The pull request opened or updated.
        pull_request_url: Its web page.
        changes: The changed-files overview.
        provenance: The provenance embedded in the committed package.
        log: The delivery event log, redacted of secrets.
        error_code: Set when the run failed.
        error_message: Set when the run failed.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: Optional[str] = Field(default=None, serialization_alias="runId")
    status: str
    ecosystem: str
    version_line: Optional[str] = Field(default=None, serialization_alias="versionLine")
    release_series: Optional[str] = Field(default=None, serialization_alias="releaseSeries")
    regen_counter: Optional[int] = Field(default=None, serialization_alias="regenCounter")
    package_name: Optional[str] = Field(default=None, serialization_alias="packageName")
    package_version: Optional[str] = Field(default=None, serialization_alias="packageVersion")
    repository_id: Optional[str] = Field(default=None, serialization_alias="repositoryId")
    repository_full_name: Optional[str] = Field(
        default=None, serialization_alias="repositoryFullName"
    )
    base_branch: Optional[str] = Field(default=None, serialization_alias="baseBranch")
    target_path: Optional[str] = Field(default=None, serialization_alias="targetPath")
    branch_name: Optional[str] = Field(default=None, serialization_alias="branchName")
    base_sha: Optional[str] = Field(default=None, serialization_alias="baseSha")
    commit_sha: Optional[str] = Field(default=None, serialization_alias="commitSha")
    pull_request_number: Optional[int] = Field(
        default=None, serialization_alias="pullRequestNumber"
    )
    pull_request_url: Optional[str] = Field(default=None, serialization_alias="pullRequestUrl")
    changes: Dict[str, Any] = Field(default_factory=dict)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    log: List[Dict[str, Any]] = Field(default_factory=list)
    error_code: Optional[str] = Field(default=None, serialization_alias="errorCode")
    error_message: Optional[str] = Field(default=None, serialization_alias="errorMessage")


class SdkGitDeliveryRunListResponse(BaseModel):
    """A page of delivery history.

    Attributes:
        runs: The rows, newest first.
        total: How many rows match.
        limit: The page size used.
        offset: The offset used.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    runs: List[SdkGitDeliveryRunModel]
    total: int
    limit: int
    offset: int


def _run_model(outcome: DeliveryOutcome) -> SdkGitDeliveryRunModel:
    """Project a pipeline outcome onto its wire model.

    Args:
        outcome: What the pipeline produced (or a stored run read back).

    Returns:
        The response model.
    """
    return SdkGitDeliveryRunModel(
        run_id=outcome.run_id,
        status=outcome.status,
        ecosystem=outcome.ecosystem,
        version_line=outcome.version_line,
        release_series=outcome.release_series,
        regen_counter=outcome.regen_counter,
        package_name=outcome.package_name,
        package_version=outcome.package_version,
        repository_id=outcome.repository_id,
        repository_full_name=outcome.repository_full_name,
        base_branch=outcome.base_branch,
        target_path=outcome.target_path,
        branch_name=outcome.branch_name,
        base_sha=outcome.base_sha,
        commit_sha=outcome.commit_sha,
        pull_request_number=outcome.pull_request_number,
        pull_request_url=outcome.pull_request_url,
        changes=dict(outcome.changes),
        provenance=dict(outcome.provenance),
        log=list(outcome.log),
        error_code=outcome.error_code,
        error_message=outcome.error_message,
    )


def _target_error(exc: GitDeliveryTargetError) -> HTTPException:
    """Map a target refusal onto ``422``, listing every problem.

    Args:
        exc: The refusal.

    Returns:
        The exception to raise. ``code`` names an ineligible repository specifically; ordinary field
        problems share ``sdk-git-delivery-target-invalid``.
    """
    return HTTPException(
        status_code=422,
        detail={
            "code": exc.code or "sdk-git-delivery-target-invalid",
            "errors": list(exc.errors),
        },
    )


def _ecosystem_or_400(ecosystem: str) -> str:
    """Normalise an ecosystem in a delivery request, or refuse with 400.

    Args:
        ecosystem: The requested ecosystem.

    Returns:
        The normalised key.

    Raises:
        HTTPException: 400 ``sdk-git-delivery-ecosystem-unsupported``.
    """
    try:
        return normalize_ecosystem(ecosystem)
    except GitDeliveryTargetError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "sdk-git-delivery-ecosystem-unsupported",
                "message": "; ".join(exc.errors),
                "ecosystems": list(DELIVERY_ECOSYSTEMS),
            },
        ) from exc


# ===========================================================================
# Targets
# ===========================================================================


@router.get(
    "/{tenant_slug}/{project_ref}/sdk-git-delivery-targets",
    response_model=GitDeliveryTargetListResponse,
    tags=["sdk-git-delivery"],
    summary="List where a project's SDKs are delivered",
    description=_TARGET_DESCRIPTION
    + "\n\nEach target reports `deliverable` and, when it is false, the `problem` a delivery would "
    "hit (the repository was removed, or registered without a linked account).\n\n"
    "Requires `projects:view`.",
    responses={404: {"description": "Project not found in this tenant."}},
)
async def list_git_delivery_targets(
    tenant_slug: str,
    project_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> GitDeliveryTargetListResponse:
    """Describe a project's delivery targets.

    Args:
        tenant_slug: Tenant in the URL (the auth tenant scopes every read).
        project_ref: The project's id or slug.
        auth_data: Authenticated principal.

    Returns:
        The configured targets.

    Raises:
        HTTPException: 403 without ``projects:view``; 404 when the project is unknown.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    return GitDeliveryTargetListResponse(
        ecosystems=list(DELIVERY_ECOSYSTEMS),
        targets=list_targets(
            tenant_id, str(project["id"]), project_slug=str(project.get("slug") or "")
        ),
    )


@router.put(
    "/{tenant_slug}/{project_ref}/sdk-git-delivery-targets/{ecosystem}",
    response_model=GitDeliveryTargetOut,
    tags=["sdk-git-delivery"],
    summary="Configure where a project's SDK for one ecosystem is delivered",
    description=_TARGET_DESCRIPTION
    + "\n\nReplaces any existing target for this project and ecosystem.\n\n"
    "Requires `projects:edit` **and** `imports:edit` — a target decides what Apiome pushes into a "
    "repository with that repository's credential. Audited as `sdk.git_delivery_target.update`.",
    responses={
        404: {"description": "Project not found in this tenant."},
        422: {
            "description": (
                "A field is invalid, or the repository cannot receive a delivery "
                "(`sdk-git-delivery-repository-missing`, `…-provider-unsupported`, "
                "`…-repository-unlinked`)."
            )
        },
    },
)
async def put_git_delivery_target(
    tenant_slug: str,
    project_ref: str,
    ecosystem: str,
    body: GitDeliveryTargetPutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> GitDeliveryTargetOut:
    """Store or replace a project's delivery target for one ecosystem.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        ecosystem: ``npm`` or ``pypi``.
        body: The repository, base branch and target path.
        auth_data: Authenticated principal.

    Returns:
        The stored target.

    Raises:
        HTTPException: 403 without ``projects:edit`` and ``imports:edit``; 404 for an unknown
            project; 422 for an invalid field or an ineligible repository.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    try:
        stored = save_target(
            tenant_id,
            str(project["id"]),
            ecosystem=ecosystem,
            repository_id=body.repository_id,
            base_branch=body.base_branch,
            target_path=body.target_path,
            project_slug=str(project.get("slug") or ""),
            actor_id=get_authenticated_user_id(auth_data),
        )
    except GitDeliveryTargetError as exc:
        raise _target_error(exc) from exc

    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_TARGET_UPDATE,
        auth_data=auth_data,
        target=str(project["id"]),
        detail={
            "ecosystem": stored.ecosystem,
            "repositoryId": stored.repository_id,
            "repositoryFullName": stored.repository_full_name,
            "baseBranch": stored.base_branch,
            "targetPath": stored.target_path,
        },
    )
    return stored


@router.delete(
    "/{tenant_slug}/{project_ref}/sdk-git-delivery-targets/{ecosystem}",
    tags=["sdk-git-delivery"],
    summary="Stop delivering a project's SDK for one ecosystem",
    description=(
        "Removes the target. Past runs are kept, and nothing is changed in the repository — an "
        "open pull request stays open.\n\n"
        "Requires `projects:edit`. Audited as `sdk.git_delivery_target.clear`."
    ),
    responses={
        404: {"description": "Project not found in this tenant."},
        422: {"description": "The ecosystem is not one git delivery supports."},
    },
)
async def delete_git_delivery_target(
    tenant_slug: str,
    project_ref: str,
    ecosystem: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Remove a project's delivery target for one ecosystem.

    Removing a target only *stops* pushes, so it needs no repository permission.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        ecosystem: ``npm`` or ``pypi``.
        auth_data: Authenticated principal.

    Returns:
        ``{"cleared": true}`` when a target was configured.

    Raises:
        HTTPException: 403 without ``projects:edit``; 404 for an unknown project; 422 for an
            unknown ecosystem.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    try:
        cleared = delete_target(tenant_id, str(project["id"]), ecosystem)
    except GitDeliveryTargetError as exc:
        raise _target_error(exc) from exc
    if cleared:
        write_audit(
            tenant_id=tenant_id,
            action=AUDIT_TARGET_CLEAR,
            auth_data=auth_data,
            target=str(project["id"]),
            detail={"ecosystem": ecosystem.strip().lower()},
        )
    return {"cleared": cleared}


# ===========================================================================
# Delivery
# ===========================================================================


@router.post(
    "/{tenant_slug}/{project_ref}/sdk-git-delivery",
    response_model=SdkGitDeliveryRunModel,
    tags=["sdk-git-delivery"],
    summary="Deliver a version's SDK to its repository as a pull request",
    description=(
        "Regenerates the SDK-4.1 package for one **published** revision and delivers it to the "
        "project's configured repository: a commit on `apiome/sdk-regen-<version>-<project>-"
        "<ecosystem>`, built on the latest base branch, and a pull request whose description "
        "carries the spec version, the generator version, a changed-files overview and the "
        "provenance.\n\n"
        "**Idempotent.** Re-running for the same version updates the same pull request rather than "
        "opening another: `unchanged` when the open pull request already carries exactly this SDK, "
        "`updated` when its branch was rebuilt, `up_to_date` when the base branch already contains "
        "it (nothing is written), `opened` when a new pull request was needed.\n\n"
        "**Failures are runs.** A missing or revoked credential, a token without write access, a "
        "rejected push or a refused pull request answers `200` with `status: failed`, a stable "
        "`errorCode` and an actionable log.\n\n"
        "Requires `versions:publish`. Audited as `sdk.git_delivery`."
    ),
    responses={
        400: {"description": "Unsupported ecosystem, or the revision is not published."},
        404: {"description": "Project, version or delivery target not found."},
    },
)
async def deliver_project_sdk(
    tenant_slug: str,
    project_ref: str,
    body: SdkGitDeliveryRequest,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkGitDeliveryRunModel:
    """Deliver one published revision's SDK as a pull request.

    Args:
        tenant_slug: Tenant in the URL; also what ``{tenant}`` resolves to in the package pattern.
        project_ref: The project's id or slug.
        body: Which ecosystem and revision.
        request: Used only for the running API version, recorded as provenance.
        auth_data: Authenticated principal.

    Returns:
        The run — whatever its outcome.

    Raises:
        HTTPException: 403 without ``versions:publish``; 400 for an unsupported ecosystem or an
            unpublished revision; 404 for an unknown project, version or target.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    ecosystem = _ecosystem_or_400(body.ecosystem)

    target = resolve_target(tenant_id, project_id, ecosystem)
    if target is None:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "sdk-git-delivery-target-missing",
                "message": (
                    f"No {ecosystem} delivery target is configured for this project. Configure one "
                    "(a registered repository, a base branch and a path) before delivering."
                ),
                "ecosystem": ecosystem,
            },
        )

    source = load_published_source(
        tenant_id,
        project_id,
        body.version,
        code_prefix="sdk-git-delivery",
        refusal=(
            "Only a published revision can be delivered as an SDK. Publish the version first, then "
            "deliver its SDK."
        ),
    )
    context = PublishContext(
        tenant_id=tenant_id,
        tenant_slug=str(tenant_slug or ""),
        project_id=project_id,
        project_slug=str(project.get("slug") or ""),
        version_record_id=source.version_record_id,
        version_line=source.version_label,
        actor_id=get_authenticated_user_id(auth_data),
    )

    outcome = deliver(
        source.api,
        context=context,
        target=target,
        source_text=source.source_text,
        source_format=source.source_format,
        apiome_version=getattr(request.app, "version", None),
    )

    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_DELIVERY,
        auth_data=auth_data,
        target=project_id,
        detail={
            "runId": outcome.run_id,
            "status": outcome.status,
            "ecosystem": outcome.ecosystem,
            "versionRecordId": context.version_record_id,
            "packageName": outcome.package_name,
            "packageVersion": outcome.package_version,
            "repositoryFullName": outcome.repository_full_name,
            "branchName": outcome.branch_name,
            "commitSha": outcome.commit_sha,
            "pullRequestNumber": outcome.pull_request_number,
            "errorCode": outcome.error_code,
        },
    )
    return _run_model(outcome)


@router.get(
    "/{tenant_slug}/{project_ref}/sdk-git-delivery-runs",
    response_model=SdkGitDeliveryRunListResponse,
    tags=["sdk-git-delivery"],
    summary="List a project's SDK delivery history",
    description=(
        "Every delivery attempt, newest first — failed ones included, because a failed run is the "
        "record of why a pull request did not arrive.\n\nRequires `versions:view`."
    ),
    responses={404: {"description": "Project not found in this tenant."}},
)
async def list_git_delivery_runs(
    tenant_slug: str,
    project_ref: str,
    ecosystem: Optional[str] = Query(
        default=None, description="Narrow to one ecosystem (`npm` or `pypi`)."
    ),
    limit: int = Query(default=50, ge=1, le=MAX_HISTORY_LIMIT),
    offset: int = Query(default=0, ge=0),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkGitDeliveryRunListResponse:
    """Return a page of a project's delivery history.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        ecosystem: Narrow to one ecosystem.
        limit: Page size.
        offset: Rows to skip.
        auth_data: Authenticated principal.

    Returns:
        The page, newest first.

    Raises:
        HTTPException: 403 without ``versions:view``; 404 when the project is unknown.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    key = ecosystem.strip().lower() if ecosystem else None
    rows = db.list_sdk_git_delivery_runs(
        tenant_id, project_id, ecosystem=key, limit=limit, offset=offset
    )
    return SdkGitDeliveryRunListResponse(
        runs=[_run_model(run_row_to_outcome(row)) for row in rows],
        total=db.count_sdk_git_delivery_runs(tenant_id, project_id, ecosystem=key),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{tenant_slug}/{project_ref}/sdk-git-delivery-runs/{run_id}",
    response_model=SdkGitDeliveryRunModel,
    tags=["sdk-git-delivery"],
    summary="Read one SDK delivery run",
    description=(
        "The run's outcome, the branch, commit and pull request it wrote, the changed-files "
        "overview and its event log. The log is stored redacted — a provider error quoting the "
        "repository token is replaced before it is written.\n\nRequires `versions:view`."
    ),
    responses={404: {"description": "Project or run not found in this tenant."}},
)
async def get_git_delivery_run(
    tenant_slug: str,
    project_ref: str,
    run_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SdkGitDeliveryRunModel:
    """Return one delivery run.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        run_id: The run to read.
        auth_data: Authenticated principal.

    Returns:
        The run.

    Raises:
        HTTPException: 403 without ``versions:view``; 404 when the project or run is unknown, or
            the run belongs to another project.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    row = db.get_sdk_git_delivery_run(run_id, tenant_id)
    if not row or str(row.get("project_id")) != str(project["id"]):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "sdk-git-delivery-run-not-found",
                "message": f"No delivery run {run_id!r} belongs to this project.",
            },
        )
    return _run_model(run_row_to_outcome(row))
