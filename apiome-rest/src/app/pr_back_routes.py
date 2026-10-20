"""PR-back endpoints: Apiome → repository — REPO-5.8 (#2793).

```
GET|PUT  /v1/tenants/{t}/repositories/{repository_id}/pr-back-settings
GET      /v1/tenants/{t}/projects/{project}/pr-back/repositories
POST     /v1/tenants/{t}/projects/{project}/pr-back
```

**Settings belong to the repository.** Which projects may open pull requests into a repository,
the branch they target, the commit message template and the reviewers are the repository's
settings — governed, like every repository route, by ``imports`` (``imports:view`` to read,
``imports:edit`` to save). A repository without settings lets no project PR back.

**Syncing is the project's.** ``POST …/pr-back`` renders one version of the project and opens (or
refreshes) a pull request into the repository's source files. It writes into source control with
the repository's linked-account credential, so — like SDK-4.2 git delivery — it needs
``versions:publish``; a dry run (``dryRun: true``) writes nothing and needs only ``projects:view``.
The listing of repositories a project could PR back into needs ``projects:view``.

A request that cannot start (the project is not allowed, was not imported from the repository, …)
is an HTTP error with a stable ``code``; once started, a provider problem is a ``200`` outcome with
``status: failed`` and an actionable log. Each pull request opened or refreshed is audited by the
pipeline (``repository.pr_back_opened`` / ``repository.pr_back_updated``); saving settings is
audited as ``repository.pr_back_settings.update``.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import pr_back_store
from .auth import get_authenticated_user_id, validate_authentication
from .change_report_render import bundled_system_template_row
from .change_report_template_resolve import resolve_effective_change_report_template
from .comment_store import resolve_version
from .comments import CommentValidationError
from .compatibility_engine import openapi_for_revision
from .database import db
from .permissions import Action, Resource, enforce_permission
from .pr_back import (
    DEFAULT_COMMIT_MESSAGE_TEMPLATE,
    MAX_PROJECT_IDS,
    MAX_REVIEWERS,
    PrBackSettings,
    PrBackSettingsError,
    normalize_settings,
)
from .pr_back_pipeline import (
    PrBackOutcome,
    PrBackRefusalError,
    check_eligibility,
    prepare,
    run_pr_back,
)
from .revision_deprecation import is_uuid_string
from .sdk_publish_routes import resolve_project, tenant_id_of, write_audit

logger = logging.getLogger(__name__)

__all__ = ["router"]

router = APIRouter(prefix="/v1/tenants", tags=["pr-back"])

#: Audit action for saving a repository's PR-back settings.
AUDIT_SETTINGS_UPDATE = "repository.pr_back_settings.update"


# ===========================================================================
# Models
# ===========================================================================


class PrBackProjectRef(BaseModel):
    """A project a repository's policy lists."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    name: Optional[str] = Field(default=None, description="Null when the project was deleted.")


class PrBackSettingsResponse(BaseModel):
    """A repository's PR-back settings."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    repository_id: str = Field(alias="repositoryId")
    configured: bool = Field(
        description="False when the repository has no settings — no project may PR back."
    )
    project_policy: str = Field(
        alias="projectPolicy",
        description="`allow`: only the listed projects may PR back. `deny`: every project except them.",
    )
    projects: List[PrBackProjectRef] = Field(default_factory=list)
    target_branch: Optional[str] = Field(
        default=None,
        alias="targetBranch",
        description="Base branch of the pull requests; null for the branch the files were imported from.",
    )
    commit_message_template: Optional[str] = Field(
        default=None,
        alias="commitMessageTemplate",
        description="Mustache template; null for the default.",
    )
    default_commit_message_template: str = Field(
        default=DEFAULT_COMMIT_MESSAGE_TEMPLATE, alias="defaultCommitMessageTemplate"
    )
    reviewers: List[str] = Field(default_factory=list)
    updated_at: Optional[datetime] = Field(default=None, alias="updatedAt")


class PrBackSettingsPutRequest(BaseModel):
    """Body for saving a repository's PR-back settings (replaces them whole)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_policy: str = Field(default="allow", alias="projectPolicy", description="`allow` or `deny`.")
    project_ids: List[str] = Field(
        default_factory=list, alias="projectIds", max_length=MAX_PROJECT_IDS, description="Project ids."
    )
    target_branch: Optional[str] = Field(
        default=None, alias="targetBranch", max_length=255, description="Blank for the import branch."
    )
    commit_message_template: Optional[str] = Field(
        default=None,
        alias="commitMessageTemplate",
        max_length=2000,
        description=(
            "Mustache template with `{{project}}`, `{{version}}`, `{{repository}}`, `{{branch}}` and "
            "`{{fileCount}}`. Blank for the default."
        ),
    )
    reviewers: List[str] = Field(
        default_factory=list,
        max_length=MAX_REVIEWERS,
        description="GitHub logins (`octocat`) or teams (`acme/api-reviewers`).",
    )


class PrBackFileRef(BaseModel):
    """One source file of the project in a repository."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    path: str
    branch: str
    precedence: int


class PrBackRepositoryEntry(BaseModel):
    """A repository the project was imported from, and whether it can PR back into it."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    repository_id: str = Field(alias="repositoryId")
    repository_full_name: Optional[str] = Field(default=None, alias="repositoryFullName")
    files: List[PrBackFileRef] = Field(default_factory=list)
    eligible: bool
    base_branch: Optional[str] = Field(default=None, alias="baseBranch")
    reason_code: Optional[str] = Field(default=None, alias="reasonCode")
    reason: Optional[str] = Field(default=None, description="Why the project cannot PR back.")


class PrBackRepositoriesResponse(BaseModel):
    """The repositories a project was imported from."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_id: str = Field(alias="projectId")
    repositories: List[PrBackRepositoryEntry] = Field(default_factory=list)


class PrBackRequest(BaseModel):
    """Body for a PR-back."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    repository_id: str = Field(alias="repositoryId", min_length=1, max_length=64)
    version: Optional[str] = Field(
        default=None, max_length=128, description="Revision id or version label; the newest when omitted."
    )
    dry_run: bool = Field(default=False, alias="dryRun", description="Compare and describe; write nothing.")


class PrBackFileReport(BaseModel):
    """One rendered file and its change report."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    path: str
    status: str = Field(description="`added`, `modified` or `unchanged`.")
    paths: int
    schemas: int
    counts: Dict[str, int] = Field(default_factory=dict)
    foreign_refs: List[str] = Field(default_factory=list, alias="foreignRefs")
    notes: List[str] = Field(default_factory=list)


class PrBackOutcomeModel(BaseModel):
    """What a PR-back did."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: str = Field(description="`preview`, `opened`, `updated`, `unchanged`, `up_to_date` or `failed`.")
    dry_run: bool = Field(alias="dryRun")
    project_id: str = Field(alias="projectId")
    version_id: str = Field(alias="versionId")
    version_label: Optional[str] = Field(default=None, alias="versionLabel")
    repository_id: str = Field(alias="repositoryId")
    repository_full_name: Optional[str] = Field(default=None, alias="repositoryFullName")
    base_branch: Optional[str] = Field(default=None, alias="baseBranch")
    branch_name: Optional[str] = Field(default=None, alias="branchName")
    base_sha: Optional[str] = Field(default=None, alias="baseSha")
    commit_sha: Optional[str] = Field(default=None, alias="commitSha")
    pull_request_number: Optional[int] = Field(default=None, alias="pullRequestNumber")
    pull_request_url: Optional[str] = Field(default=None, alias="pullRequestUrl")
    title: Optional[str] = None
    body: Optional[str] = Field(default=None, description="The pull request description (change report).")
    commit_message: Optional[str] = Field(default=None, alias="commitMessage")
    reviewers: List[str] = Field(default_factory=list)
    files: List[PrBackFileReport] = Field(default_factory=list)
    skipped: List[str] = Field(default_factory=list)
    log: List[Dict[str, Any]] = Field(default_factory=list)
    error_code: Optional[str] = Field(default=None, alias="errorCode")
    error_message: Optional[str] = Field(default=None, alias="errorMessage")


# ===========================================================================
# Helpers
# ===========================================================================


def _refusal(exc: PrBackRefusalError) -> HTTPException:
    """Turn a refusal into its HTTP error."""
    return HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message})


def _repository_or_404(tenant_id: str, repository_id: str) -> Dict[str, Any]:
    """Load a live repository of the tenant, or refuse."""
    row = db.get_tenant_repository(tenant_id, repository_id) if is_uuid_string(repository_id) else None
    if not row:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "pr-back-repository-not-found",
                "message": f"No repository {repository_id!r} is registered in this workspace.",
            },
        )
    return dict(row)


def _settings_response(tenant_id: str, repository_id: str, row: Optional[Dict[str, Any]]) -> PrBackSettingsResponse:
    """Describe stored settings (or their absence)."""
    settings = PrBackSettings.from_row(row) or PrBackSettings()
    names = pr_back_store.project_names(tenant_id, list(settings.project_ids))
    return PrBackSettingsResponse(
        repository_id=repository_id,
        configured=row is not None,
        project_policy=settings.project_policy,
        projects=[PrBackProjectRef(id=p, name=names.get(p.lower())) for p in settings.project_ids],
        target_branch=settings.target_branch,
        commit_message_template=settings.commit_message_template,
        reviewers=list(settings.reviewers),
        updated_at=(row or {}).get("updated_at"),
    )


def _template_row(tenant_id: str, project_id: str) -> Dict[str, Any]:
    """The project's effective change report template, or the bundled default."""
    try:
        return resolve_effective_change_report_template(db, tenant_id, project_id, None)
    except Exception:  # noqa: BLE001 - a template lookup fault falls back to the bundled default
        logger.warning("Change report template lookup failed for %s", project_id, exc_info=True)
        return bundled_system_template_row()


def _outcome_model(outcome: PrBackOutcome, project_id: str, version: Dict[str, Any]) -> PrBackOutcomeModel:
    """Project an outcome onto its response."""
    return PrBackOutcomeModel(
        status=outcome.status,
        dry_run=outcome.dry_run,
        project_id=project_id,
        version_id=str(version["id"]),
        version_label=version.get("version_id"),
        repository_id=outcome.repository_id,
        repository_full_name=outcome.repository_full_name,
        base_branch=outcome.base_branch,
        branch_name=outcome.branch_name,
        base_sha=outcome.base_sha,
        commit_sha=outcome.commit_sha,
        pull_request_number=outcome.pull_request_number,
        pull_request_url=outcome.pull_request_url,
        title=outcome.title,
        body=outcome.body,
        commit_message=outcome.commit_message,
        reviewers=outcome.reviewers,
        files=[
            PrBackFileReport(
                path=f.path,
                status=f.status,
                paths=f.paths,
                schemas=f.schemas,
                counts=f.counts,
                foreign_refs=f.foreign_refs,
                notes=f.notes,
            )
            for f in outcome.files
        ],
        skipped=outcome.skipped,
        log=outcome.log,
        error_code=outcome.error_code,
        error_message=outcome.error_message,
    )


# ===========================================================================
# Settings
# ===========================================================================


@router.get(
    "/{tenant_slug}/repositories/{repository_id}/pr-back-settings",
    response_model=PrBackSettingsResponse,
    summary="Read a repository's PR-back settings",
    description=(
        "Which Apiome projects may open pull requests into the repository (`allow` list or `deny` "
        "list), the pull requests' target branch, the commit message template and the reviewers. "
        "`configured: false` means the repository has no settings, so no project may PR back.\n\n"
        "Requires `imports:view`."
    ),
)
async def get_pr_back_settings(
    tenant_slug: str,
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PrBackSettingsResponse:
    """Read a repository's PR-back settings.

    Args:
        tenant_slug: The tenant in the URL (the credential's tenant scopes the read).
        repository_id: The registered repository.
        auth_data: The authenticated principal.

    Returns:
        The settings, or the defaults with ``configured: false``.

    Raises:
        HTTPException: 403 without ``imports:view``; 404 for an unknown repository.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _repository_or_404(tenant_id, repository_id)
    return _settings_response(tenant_id, repository_id, pr_back_store.get_settings_row(tenant_id, repository_id))


@router.put(
    "/{tenant_slug}/repositories/{repository_id}/pr-back-settings",
    response_model=PrBackSettingsResponse,
    summary="Save a repository's PR-back settings",
    description=(
        "Replaces the repository's PR-back settings. `projectPolicy: allow` lets only `projectIds` "
        "open pull requests into the repository; `deny` lets every project except them. "
        "`targetBranch` blank uses the branch the files were imported from. "
        "`commitMessageTemplate` is Mustache over `project`, `version`, `repository`, `branch` and "
        "`fileCount`; blank uses the default. `reviewers` are GitHub logins or `org/team` slugs, "
        "requested on every pull request PR-back opens.\n\n"
        "Requires `imports:edit`. Audited as `repository.pr_back_settings.update`."
    ),
    responses={
        404: {"description": "Unknown repository."},
        422: {"description": "Invalid policy, branch, template, reviewer or project id."},
    },
)
async def put_pr_back_settings(
    tenant_slug: str,
    repository_id: str,
    body: PrBackSettingsPutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PrBackSettingsResponse:
    """Save a repository's PR-back settings.

    Args:
        tenant_slug: The tenant in the URL.
        repository_id: The registered repository.
        body: The settings.
        auth_data: The authenticated principal.

    Returns:
        The stored settings.

    Raises:
        HTTPException: 403 without ``imports:edit``; 404 for an unknown repository; 422 for
            invalid settings or a project id that names no project of the tenant.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    _repository_or_404(tenant_id, repository_id)
    try:
        settings = normalize_settings(
            project_policy=body.project_policy,
            project_ids=body.project_ids,
            target_branch=body.target_branch,
            commit_message_template=body.commit_message_template,
            reviewers=body.reviewers,
        )
    except PrBackSettingsError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message}) from exc
    malformed = [p for p in settings.project_ids if not is_uuid_string(p)]
    unknown = malformed or pr_back_store.unknown_project_ids(tenant_id, list(settings.project_ids))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "pr-back-project-unknown",
                "message": f"No project of this workspace has id {unknown[0]!r}.",
                "projectIds": unknown,
            },
        )
    row = pr_back_store.save_settings(tenant_id, repository_id, settings, get_authenticated_user_id(auth_data))
    if row is None:
        raise HTTPException(status_code=404, detail="repository not found")
    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_SETTINGS_UPDATE,
        auth_data=auth_data,
        target=repository_id,
        detail={
            "repositoryId": repository_id,
            "projectPolicy": settings.project_policy,
            "projectIds": list(settings.project_ids),
            "targetBranch": settings.target_branch,
            "commitMessageTemplate": settings.commit_message_template,
            "reviewers": list(settings.reviewers),
        },
    )
    return _settings_response(tenant_id, repository_id, row)


# ===========================================================================
# Project side
# ===========================================================================


@router.get(
    "/{tenant_slug}/projects/{project_ref}/pr-back/repositories",
    response_model=PrBackRepositoriesResponse,
    summary="List the repositories a project can PR back into",
    description=(
        "Every repository the project was imported from, with its source files, whether the "
        "project may open pull requests into it (`eligible`) and, when it may not, why "
        "(`reasonCode`, `reason`).\n\nRequires `projects:view`."
    ),
)
async def list_pr_back_repositories(
    tenant_slug: str,
    project_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PrBackRepositoriesResponse:
    """List the repositories a project was imported from, and whether it can PR back into each.

    Args:
        tenant_slug: The tenant in the URL.
        project_ref: Project slug or id.
        auth_data: The authenticated principal.

    Returns:
        One entry per repository, in the order its first file contributes.

    Raises:
        HTTPException: 403 without ``projects:view``; 404 for an unknown project.
    """
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    sources = pr_back_store.project_sources(tenant_id, project_id)

    entries: List[PrBackRepositoryEntry] = []
    for repository_id in dict.fromkeys(s.repository_id for s in sources):
        files = [
            PrBackFileRef(path=s.path, branch=s.branch, precedence=s.precedence)
            for s in sources
            if s.repository_id == repository_id
        ]
        row = db.get_tenant_repository(tenant_id, repository_id)
        if not row:
            continue
        entry = PrBackRepositoryEntry(
            repository_id=repository_id,
            repository_full_name=row.get("repository_full_name"),
            files=files,
            eligible=False,
        )
        try:
            _, base = check_eligibility(
                project=project,
                repository=row,
                settings=pr_back_store.get_settings(tenant_id, repository_id),
                sources=sources,
            )
            entry.eligible, entry.base_branch = True, base
        except PrBackRefusalError as exc:
            entry.reason_code, entry.reason = exc.code, exc.message
        entries.append(entry)
    return PrBackRepositoriesResponse(project_id=project_id, repositories=entries)


@router.post(
    "/{tenant_slug}/projects/{project_ref}/pr-back",
    response_model=PrBackOutcomeModel,
    summary="Open a pull request syncing a project version back to its repository",
    description=(
        "Renders one version of the project and opens a pull request into the repository's source "
        "files on `apiome/pr-back-<project>-<base>`, built on the latest base branch. Each file "
        "gets back only the paths and schemas it defines (multi-repository projects); content no "
        "file defines belongs to the precedence-1 file. The description is each file's change "
        "report (the project's change report templates), and new pull requests get the "
        "repository's reviewers.\n\n"
        "**Idempotent.** One pull request per project and base branch: `updated` when the open one "
        "was refreshed, `unchanged` when it already carries exactly this sync, `up_to_date` when "
        "the base branch already holds the rendered files (nothing written), `opened` otherwise. "
        "`dryRun: true` answers `preview` with the title, description and commit message, writing "
        "nothing.\n\n"
        "**Failures are outcomes.** A revoked token, a refused push or a rate limit answers `200` "
        "with `status: failed`, an `errorCode` and an actionable log.\n\n"
        "Requires `versions:publish` (`projects:view` for a dry run). Every pull request opened is "
        "audited as `repository.pr_back_opened`, every one refreshed as `repository.pr_back_updated`."
    ),
    responses={
        403: {"description": "The repository's settings do not let the project PR back."},
        404: {"description": "Unknown project, version or repository."},
        409: {"description": "The project has no source file the repository can receive."},
    },
)
async def pr_back_project(
    tenant_slug: str,
    project_ref: str,
    body: PrBackRequest,
    request: Request,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PrBackOutcomeModel:
    """Sync one version of a project back to a repository as a pull request.

    Args:
        tenant_slug: The tenant in the URL (used to render the spec's server URLs).
        project_ref: Project slug or id.
        body: The repository, the version and whether this is a dry run.
        request: For the running API version, named in the description.
        auth_data: The authenticated principal.

    Returns:
        The outcome — whatever it is, once the sync could start.

    Raises:
        HTTPException: 403 without the permission or when the repository does not allow the
            project; 404 for an unknown project, version or repository; 409 when the project has
            nothing the repository can receive.
    """
    enforce_permission(
        db, auth_data, Resource.PROJECTS if body.dry_run else Resource.VERSIONS,
        Action.VIEW if body.dry_run else Action.PUBLISH,
    )
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    repository = _repository_or_404(tenant_id, body.repository_id)

    version_ref = (body.version or "").strip() or pr_back_store.latest_version_id(project_id)
    try:
        if not version_ref:
            raise CommentValidationError("comment-version-not-found", "the project has no versions")
        version = resolve_version(tenant_id, project_id, version_ref)
    except CommentValidationError as exc:
        raise HTTPException(
            status_code=404, detail={"code": "pr-back-version-not-found", "message": str(exc)}
        ) from exc

    settings = pr_back_store.get_settings(tenant_id, body.repository_id)
    sources = pr_back_store.project_sources(tenant_id, project_id)
    try:
        check_eligibility(project=project, repository=repository, settings=settings, sources=sources)
        spec = openapi_for_revision(version, str(tenant_slug or ""), tenant_id)
        plan = prepare(
            spec=spec,
            project=project,
            repository=repository,
            settings=settings,
            sources=sources,
            entity_sources=pr_back_store.entity_sources(str(version["id"])),
        )
    except PrBackRefusalError as exc:
        raise _refusal(exc) from exc

    def audit(action: str, detail: Dict[str, Any]) -> None:
        write_audit(
            tenant_id=tenant_id,
            action=action,
            auth_data=auth_data,
            target=body.repository_id,
            detail={**detail, "versionId": str(version["id"])},
        )

    outcome = run_pr_back(
        plan,
        project=project,
        version_label=str(version.get("version_id") or version["id"]),
        repository=repository,
        settings=settings or PrBackSettings(),
        template_row=_template_row(tenant_id, project_id),
        dry_run=body.dry_run,
        apiome_version=getattr(request.app, "version", None),
        audit=audit,
    )
    return _outcome_model(outcome, project_id, version)
