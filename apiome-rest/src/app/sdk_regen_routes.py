"""Auto-regen on publish endpoints — SDK-4.3 (#4497).

Seven routes over the two things watch mode needs: a way to say which SDKs regenerate on publish,
and a way to see — and recover — what each publish did.

```
GET              /v1/projects/{t}/{project}/sdk-regen-subscriptions
PUT|PATCH|DELETE /v1/projects/{t}/{project}/sdk-regen-subscriptions/{ecosystem}
GET              /v1/projects/{t}/{project}/sdk-regen-runs[/{run_id}]
POST             /v1/projects/{t}/{project}/sdk-regen-jobs/{job_id}/retry
```

**History reads as the ticket's chain: publish event → jobs → artifacts → deliveries.** A *run* is
one publish; its *jobs* are the subscriptions it expanded into; each job names the SDK-4.1 publish
run (package name, version, archive digest) and the SDK-4.2 delivery run (pull request) it produced,
with links to both ledgers and to the published version. ``?status=dead_letter`` is the dead letter.

**Permissions reuse what the orchestrated pipelines already require; no new RBAC resource.**
Reading subscriptions is ``projects:view``. Saving or enabling one is ``projects:edit`` **and**
``versions:publish``: a subscription publishes packages and opens pull requests on the tenant's
behalf on every later publish, which is exactly the authority SDK-4.1's publish and SDK-4.2's
delivery require. Disabling or deleting one only *stops* releases, so it needs ``projects:edit``
alone. History is ``versions:view``; retrying a dead letter is ``versions:publish``.

**Every mutation is audited.**
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .permissions import Action, Resource, enforce_permission
from .sdk_publish_routes import resolve_project, tenant_id_of, write_audit
from .sdk_regen_policy import (
    JOB_STATUS_DEAD_LETTER,
    JOB_STATUSES,
    MAX_ATTEMPTS,
    run_status,
)
from .sdk_regen_subscriptions import (
    DELIVERY_MODES,
    REGEN_ECOSYSTEMS,
    RegenSubscriptionError,
    RegenSubscriptionOut,
    delete_subscription,
    list_subscriptions,
    normalize_ecosystem,
    save_subscription,
    set_subscription_active,
)

logger = logging.getLogger(__name__)

__all__ = ["router"]

#: Shares the ``/v1/projects`` prefix; ``main`` registers it after ``projects_router`` for the same
#: reason SDK-3.4's, SDK-4.1's and SDK-4.2's routers are.
router = APIRouter(prefix="/v1/projects", tags=["sdk-regen"])

#: Audit actions this module writes.
AUDIT_SUBSCRIPTION_UPDATE = "sdk.regen_subscription.update"
AUDIT_SUBSCRIPTION_ENABLE = "sdk.regen_subscription.enable"
AUDIT_SUBSCRIPTION_DISABLE = "sdk.regen_subscription.disable"
AUDIT_SUBSCRIPTION_DELETE = "sdk.regen_subscription.delete"
AUDIT_JOB_RETRY = "sdk.regen_job.retry"

#: Largest history page.
MAX_HISTORY_LIMIT = 200

_SUBSCRIPTION_DESCRIPTION = (
    "A **regen subscription** makes one of a project's SDKs regenerate and ship every time the "
    "project publishes a version — no one has to remember to.\n\n"
    "`deliveryMode` says how it ships: `registry` publishes the package (SDK-4.1, using the "
    "project's registry credential), `git` opens or updates a pull request (SDK-4.2, using the "
    "project's git delivery target), and `registry_and_git` publishes first and then delivers the "
    "version that publish claimed. It has **no default**: publishing to a public registry is "
    "irreversible, so it is never done unless named.\n\n"
    "`options.dryRun` (registry modes only, default `false`) rehearses every release instead: the "
    "package is built and the credential resolved, and nothing is uploaded. Unknown options are "
    "refused.\n\n"
    f"Ecosystems: {', '.join('`' + e + '`' for e in REGEN_ECOSYSTEMS)} — one subscription per "
    "project per ecosystem."
)


# ===========================================================================
# Request / response models
# ===========================================================================


class RegenSubscriptionPutRequest(BaseModel):
    """Body for storing a subscription.

    Attributes:
        delivery_mode: ``registry``, ``git`` or ``registry_and_git``. Required.
        options: The options object (``{"dryRun": true}``), or omitted for the defaults.
        active: Whether publishes regenerate this SDK. Defaults to ``true``.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    delivery_mode: str = Field(
        alias="deliveryMode",
        description="`registry`, `git` or `registry_and_git`. No default.",
    )
    options: Optional[Dict[str, Any]] = Field(
        default=None,
        description="`{\"dryRun\": true}` rehearses registry releases. Registry modes only.",
    )
    active: bool = Field(default=True, description="Whether publishes regenerate this SDK.")


class RegenSubscriptionPatchRequest(BaseModel):
    """Body for enabling or disabling a subscription.

    Attributes:
        active: The new state.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    active: bool = Field(description="`true` to enable, `false` to disable.")


class RegenSubscriptionListResponse(BaseModel):
    """A project's subscriptions.

    Attributes:
        ecosystems: Which ecosystems can be subscribed.
        delivery_modes: Which delivery modes exist.
        subscriptions: One entry per subscribed ecosystem.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    ecosystems: List[str]
    delivery_modes: List[str] = Field(serialization_alias="deliveryModes")
    subscriptions: List[RegenSubscriptionOut]


class RegenPublishStepModel(BaseModel):
    """What a job's registry step produced.

    Attributes:
        run_id: The SDK-4.1 publish run.
        status: Its status (``published``, ``already_published``, ``dry_run``, ``failed``…).
        package_name: The package.
        package_version: The version published (or rehearsed).
        artifact_sha256: The archive's digest.
        href: The publish run in the SDK-4.1 history.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: Optional[str] = Field(default=None, serialization_alias="runId")
    status: Optional[str] = None
    package_name: Optional[str] = Field(default=None, serialization_alias="packageName")
    package_version: Optional[str] = Field(default=None, serialization_alias="packageVersion")
    artifact_sha256: Optional[str] = Field(default=None, serialization_alias="artifactSha256")
    href: Optional[str] = None


class RegenDeliveryStepModel(BaseModel):
    """What a job's git step produced.

    Attributes:
        run_id: The SDK-4.2 delivery run.
        status: Its status (``opened``, ``updated``, ``unchanged``, ``up_to_date``, ``failed``…).
        pull_request_number: The pull request opened or updated.
        pull_request_url: Its web page.
        href: The delivery run in the SDK-4.2 history.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: Optional[str] = Field(default=None, serialization_alias="runId")
    status: Optional[str] = None
    pull_request_number: Optional[int] = Field(
        default=None, serialization_alias="pullRequestNumber"
    )
    pull_request_url: Optional[str] = Field(default=None, serialization_alias="pullRequestUrl")
    href: Optional[str] = None


class RegenJobErrorModel(BaseModel):
    """Why a job's latest attempt did not succeed (or, when cancelled, why it did not run).

    Attributes:
        step: ``generate``, ``registry``, ``git`` or ``worker``; ``null`` for a cancellation.
        code: A stable code.
        message: What happened and what to do about it.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    step: Optional[str] = None
    code: Optional[str] = None
    message: Optional[str] = None


class RegenJobModel(BaseModel):
    """One subscription's regeneration for one publish.

    Attributes:
        job_id: The job.
        run_id: The publish event it belongs to.
        subscription_id: The subscription it ran for; ``null`` once unsubscribed.
        subscription_active: Whether that subscription is enabled now; ``null`` once removed.
        ecosystem: ``npm`` or ``pypi``.
        delivery_mode: The mode the latest attempt ran with.
        options: The options the latest attempt ran with.
        status: ``pending``, ``running``, ``retrying``, ``succeeded``, ``dead_letter`` or
            ``cancelled``.
        attempt_count: Attempts in the current budget.
        max_attempts: The budget.
        next_attempt_at: When a retrying job is next due.
        retryable: Whether ``POST …/retry`` would accept it now.
        publish: The registry step's result, when it ran.
        delivery: The git step's result, when it ran.
        error: The latest failure (or cancellation reason).
        attempts: One record per attempt, each naming the runs it wrote.
        retry_href: Where to retry it, when it is retryable.
        retry_requested_by: Who last retried it.
        retry_requested_at: When.
        created_at: When the publish queued it.
        updated_at: When it last changed.
        finished_at: When it reached its current terminal status.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    job_id: str = Field(serialization_alias="jobId")
    run_id: str = Field(serialization_alias="runId")
    subscription_id: Optional[str] = Field(default=None, serialization_alias="subscriptionId")
    subscription_active: Optional[bool] = Field(
        default=None, serialization_alias="subscriptionActive"
    )
    ecosystem: str
    delivery_mode: str = Field(serialization_alias="deliveryMode")
    options: Dict[str, Any] = Field(default_factory=dict)
    status: str
    attempt_count: int = Field(serialization_alias="attemptCount")
    max_attempts: int = Field(default=MAX_ATTEMPTS, serialization_alias="maxAttempts")
    next_attempt_at: Optional[datetime] = Field(default=None, serialization_alias="nextAttemptAt")
    retryable: bool = False
    publish: Optional[RegenPublishStepModel] = None
    delivery: Optional[RegenDeliveryStepModel] = None
    error: Optional[RegenJobErrorModel] = None
    attempts: List[Dict[str, Any]] = Field(default_factory=list)
    retry_href: Optional[str] = Field(default=None, serialization_alias="retryHref")
    retry_requested_by: Optional[str] = Field(
        default=None, serialization_alias="retryRequestedBy"
    )
    retry_requested_at: Optional[datetime] = Field(
        default=None, serialization_alias="retryRequestedAt"
    )
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")
    finished_at: Optional[datetime] = Field(default=None, serialization_alias="finishedAt")


class RegenRunModel(BaseModel):
    """One publish event and the jobs it expanded into.

    Attributes:
        run_id: The run.
        status: ``in_progress``, ``succeeded``, ``dead_letter`` or ``cancelled``, read off its jobs.
        version_id: The published revision; ``null`` once deleted.
        version_line: Its version label.
        version_href: The revision.
        published_by: Who published it.
        created_at: When it was published.
        jobs: One per subscription that was active at the time.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: str = Field(serialization_alias="runId")
    status: str
    version_id: Optional[str] = Field(default=None, serialization_alias="versionId")
    version_line: Optional[str] = Field(default=None, serialization_alias="versionLine")
    version_href: Optional[str] = Field(default=None, serialization_alias="versionHref")
    published_by: Optional[str] = Field(default=None, serialization_alias="publishedBy")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")
    jobs: List[RegenJobModel] = Field(default_factory=list)


class RegenRunListResponse(BaseModel):
    """A page of regen history.

    Attributes:
        runs: The runs, newest first.
        total: How many runs match.
        limit: The page size used.
        offset: The offset used.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    runs: List[RegenRunModel]
    total: int
    limit: int
    offset: int


# ===========================================================================
# Projections
# ===========================================================================


def _project_base(tenant_slug: str, project_id: str) -> str:
    """The URL prefix every link in a response shares."""
    return f"/v1/projects/{tenant_slug}/{project_id}"


def job_model(row: Mapping[str, Any], *, tenant_slug: str) -> RegenJobModel:
    """Project a stored job row onto its wire model, with links into the SDK-4.1/4.2 ledgers.

    Args:
        row: A job row, with ``subscription_active`` when the read joined it.
        tenant_slug: The tenant in the request URL, for links.

    Returns:
        The job.
    """
    base = _project_base(tenant_slug, str(row.get("project_id") or ""))
    publish_run_id = row.get("publish_run_id")
    delivery_run_id = row.get("delivery_run_id")
    publish = None
    if publish_run_id or row.get("publish_status"):
        publish = RegenPublishStepModel(
            run_id=publish_run_id,
            status=row.get("publish_status"),
            package_name=row.get("package_name"),
            package_version=row.get("package_version"),
            artifact_sha256=row.get("artifact_sha256"),
            href=f"{base}/sdk-publish-runs/{publish_run_id}" if publish_run_id else None,
        )
    delivery = None
    if delivery_run_id or row.get("delivery_status"):
        delivery = RegenDeliveryStepModel(
            run_id=delivery_run_id,
            status=row.get("delivery_status"),
            pull_request_number=row.get("pull_request_number"),
            pull_request_url=row.get("pull_request_url"),
            href=f"{base}/sdk-git-delivery-runs/{delivery_run_id}" if delivery_run_id else None,
        )
    error = None
    if row.get("error_code") or row.get("error_message"):
        error = RegenJobErrorModel(
            step=row.get("error_step"),
            code=row.get("error_code"),
            message=row.get("error_message"),
        )
    subscription_active = row.get("subscription_active")
    retryable = row.get("status") == JOB_STATUS_DEAD_LETTER and subscription_active is True
    attempts = row.get("attempts")
    options = row.get("options")
    return RegenJobModel(
        job_id=str(row.get("id") or ""),
        run_id=str(row.get("run_id") or ""),
        subscription_id=row.get("subscription_id"),
        subscription_active=subscription_active,
        ecosystem=str(row.get("ecosystem") or ""),
        delivery_mode=str(row.get("delivery_mode") or ""),
        options=dict(options) if isinstance(options, Mapping) else {},
        status=str(row.get("status") or ""),
        attempt_count=int(row.get("attempt_count") or 0),
        next_attempt_at=row.get("next_attempt_at"),
        retryable=retryable,
        publish=publish,
        delivery=delivery,
        error=error,
        attempts=list(attempts) if isinstance(attempts, list) else [],
        retry_href=f"{base}/sdk-regen-jobs/{row.get('id')}/retry" if retryable else None,
        retry_requested_by=row.get("retry_requested_by"),
        retry_requested_at=row.get("retry_requested_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        finished_at=row.get("finished_at"),
    )


def run_model(
    row: Mapping[str, Any], jobs: List[Mapping[str, Any]], *, tenant_slug: str
) -> RegenRunModel:
    """Project a stored run and its jobs onto the wire model.

    Args:
        row: A run row.
        jobs: That run's job rows.
        tenant_slug: The tenant in the request URL, for links.

    Returns:
        The run.
    """
    version_id = row.get("version_id")
    project_id = str(row.get("project_id") or "")
    return RegenRunModel(
        run_id=str(row.get("id") or ""),
        status=run_status(str(job.get("status") or "") for job in jobs),
        version_id=version_id,
        version_line=row.get("version_line"),
        version_href=(
            f"/v1/versions/{tenant_slug}/{project_id}/{version_id}" if version_id else None
        ),
        published_by=row.get("published_by"),
        created_at=row.get("created_at"),
        jobs=[job_model(job, tenant_slug=tenant_slug) for job in jobs],
    )


def _subscription_error(exc: RegenSubscriptionError) -> HTTPException:
    """Map a subscription refusal onto ``422``, listing every problem."""
    return HTTPException(
        status_code=422,
        detail={"code": "sdk-regen-subscription-invalid", "errors": list(exc.errors)},
    )


def _ecosystem_or_422(ecosystem: str) -> str:
    """Normalise an ecosystem path parameter, or refuse with 422."""
    try:
        return normalize_ecosystem(ecosystem)
    except RegenSubscriptionError as exc:
        raise _subscription_error(exc) from exc


def _subscription_missing(ecosystem: str) -> HTTPException:
    """The 404 for a project with no subscription for an ecosystem."""
    return HTTPException(
        status_code=404,
        detail={
            "code": "sdk-regen-subscription-not-found",
            "message": f"This project has no {ecosystem} regen subscription.",
        },
    )


# ===========================================================================
# Subscriptions
# ===========================================================================


@router.get(
    "/{tenant_slug}/{project_ref}/sdk-regen-subscriptions",
    response_model=RegenSubscriptionListResponse,
    tags=["sdk-regen"],
    summary="List which of a project's SDKs regenerate on publish",
    description=_SUBSCRIPTION_DESCRIPTION + "\n\nRequires `projects:view`.",
    responses={404: {"description": "Project not found in this tenant."}},
)
async def list_regen_subscriptions(
    tenant_slug: str,
    project_ref: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegenSubscriptionListResponse:
    """Describe a project's regen subscriptions.

    Args:
        tenant_slug: Tenant in the URL (the auth tenant scopes every read).
        project_ref: The project's id or slug.
        auth_data: Authenticated principal.

    Returns:
        The subscriptions.

    Raises:
        HTTPException: 403 without ``projects:view``; 404 when the project is unknown.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    return RegenSubscriptionListResponse(
        ecosystems=list(REGEN_ECOSYSTEMS),
        delivery_modes=list(DELIVERY_MODES),
        subscriptions=list_subscriptions(tenant_id, str(project["id"])),
    )


@router.put(
    "/{tenant_slug}/{project_ref}/sdk-regen-subscriptions/{ecosystem}",
    response_model=RegenSubscriptionOut,
    tags=["sdk-regen"],
    summary="Subscribe a project's SDK for one ecosystem to its publish events",
    description=_SUBSCRIPTION_DESCRIPTION
    + "\n\nReplaces any existing subscription for this project and ecosystem. Jobs already queued "
    "run with the subscription as it is when they start.\n\n"
    "Requires `projects:edit` **and** `versions:publish` — a subscription publishes and delivers on "
    "the tenant's behalf on every later publish. Audited as `sdk.regen_subscription.update`.",
    responses={
        404: {"description": "Project not found in this tenant."},
        422: {"description": "An invalid ecosystem, delivery mode or option."},
    },
)
async def put_regen_subscription(
    tenant_slug: str,
    project_ref: str,
    ecosystem: str,
    body: RegenSubscriptionPutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegenSubscriptionOut:
    """Store or replace a project's regen subscription for one ecosystem.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        ecosystem: ``npm`` or ``pypi``.
        body: The delivery mode, options and state.
        auth_data: Authenticated principal.

    Returns:
        The stored subscription.

    Raises:
        HTTPException: 403 without ``projects:edit`` and ``versions:publish``; 404 for an unknown
            project; 422 for an invalid field.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    try:
        stored = save_subscription(
            tenant_id,
            str(project["id"]),
            ecosystem=ecosystem,
            delivery_mode=body.delivery_mode,
            options=body.options,
            active=body.active,
            actor_id=get_authenticated_user_id(auth_data),
        )
    except RegenSubscriptionError as exc:
        raise _subscription_error(exc) from exc

    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_SUBSCRIPTION_UPDATE,
        auth_data=auth_data,
        target=str(project["id"]),
        detail={
            "ecosystem": stored.ecosystem,
            "deliveryMode": stored.delivery_mode,
            "options": dict(stored.options),
            "active": stored.active,
        },
    )
    return stored


@router.patch(
    "/{tenant_slug}/{project_ref}/sdk-regen-subscriptions/{ecosystem}",
    response_model=RegenSubscriptionOut,
    tags=["sdk-regen"],
    summary="Enable or disable a project's regen subscription",
    description=(
        "Disabling keeps the subscription's configuration and stops future runs: jobs already "
        "queued for it are cancelled when the worker reaches them, and nothing already published "
        "or delivered is touched. Enabling resumes it from the next publish.\n\n"
        "Disabling requires `projects:edit`; enabling also requires `versions:publish`. Audited as "
        "`sdk.regen_subscription.enable` / `sdk.regen_subscription.disable`."
    ),
    responses={
        404: {"description": "Project or subscription not found."},
        422: {"description": "The ecosystem is not one a subscription can name."},
    },
)
async def patch_regen_subscription(
    tenant_slug: str,
    project_ref: str,
    ecosystem: str,
    body: RegenSubscriptionPatchRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegenSubscriptionOut:
    """Enable or disable a project's regen subscription for one ecosystem.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        ecosystem: ``npm`` or ``pypi``.
        body: The new state.
        auth_data: Authenticated principal.

    Returns:
        The updated subscription.

    Raises:
        HTTPException: 403 without the permissions above; 404 for an unknown project or
            subscription; 422 for an unknown ecosystem.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    if body.active:
        enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    key = _ecosystem_or_422(ecosystem)
    updated = set_subscription_active(
        tenant_id,
        str(project["id"]),
        key,
        active=body.active,
        actor_id=get_authenticated_user_id(auth_data),
    )
    if updated is None:
        raise _subscription_missing(key)

    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_SUBSCRIPTION_ENABLE if body.active else AUDIT_SUBSCRIPTION_DISABLE,
        auth_data=auth_data,
        target=str(project["id"]),
        detail={"ecosystem": key, "deliveryMode": updated.delivery_mode, "active": updated.active},
    )
    return updated


@router.delete(
    "/{tenant_slug}/{project_ref}/sdk-regen-subscriptions/{ecosystem}",
    tags=["sdk-regen"],
    summary="Unsubscribe a project's SDK from its publish events",
    description=(
        "Removes the subscription. Future publishes no longer regenerate this SDK, and jobs still "
        "queued for it are cancelled. Past runs, jobs, published packages and pull requests are "
        "kept.\n\nRequires `projects:edit`. Audited as `sdk.regen_subscription.delete`."
    ),
    responses={
        404: {"description": "Project not found in this tenant."},
        422: {"description": "The ecosystem is not one a subscription can name."},
    },
)
async def delete_regen_subscription(
    tenant_slug: str,
    project_ref: str,
    ecosystem: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, Any]:
    """Remove a project's regen subscription for one ecosystem.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        ecosystem: ``npm`` or ``pypi``.
        auth_data: Authenticated principal.

    Returns:
        ``{"deleted": true}`` when a subscription existed.

    Raises:
        HTTPException: 403 without ``projects:edit``; 404 for an unknown project; 422 for an
            unknown ecosystem.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.EDIT)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    key = _ecosystem_or_422(ecosystem)
    deleted = delete_subscription(tenant_id, str(project["id"]), key)
    if deleted:
        write_audit(
            tenant_id=tenant_id,
            action=AUDIT_SUBSCRIPTION_DELETE,
            auth_data=auth_data,
            target=str(project["id"]),
            detail={"ecosystem": key},
        )
    return {"deleted": deleted}


# ===========================================================================
# History
# ===========================================================================


def _runs_with_jobs(
    tenant_id: str, rows: List[Dict[str, Any]], *, tenant_slug: str
) -> List[RegenRunModel]:
    """Attach each run's jobs, read in one query.

    Args:
        tenant_id: The caller's tenant.
        rows: The run rows.
        tenant_slug: The tenant in the request URL, for links.

    Returns:
        The runs, in the order given.
    """
    jobs = db.list_sdk_regen_jobs_for_runs(tenant_id, [str(row["id"]) for row in rows])
    by_run: Dict[str, List[Dict[str, Any]]] = {}
    for job in jobs:
        by_run.setdefault(str(job.get("run_id")), []).append(job)
    return [
        run_model(row, by_run.get(str(row["id"]), []), tenant_slug=tenant_slug) for row in rows
    ]


@router.get(
    "/{tenant_slug}/{project_ref}/sdk-regen-runs",
    response_model=RegenRunListResponse,
    tags=["sdk-regen"],
    summary="List what each publish regenerated and delivered",
    description=(
        "One entry per publish that had an active subscription, newest first, each with its jobs: "
        "what the job did, the SDK-4.1 publish run it wrote (package, version, archive digest) and "
        "the SDK-4.2 delivery run (pull request), with links to both, and every attempt.\n\n"
        "`status=dead_letter` lists the dead letter: runs with at least one job that failed "
        "permanently or spent its attempts, each retryable with `POST …/sdk-regen-jobs/{jobId}/"
        "retry`.\n\nRequires `versions:view`."
    ),
    responses={
        404: {"description": "Project not found in this tenant."},
        422: {"description": "An unknown job status filter."},
    },
)
async def list_regen_runs(
    tenant_slug: str,
    project_ref: str,
    status: Optional[str] = Query(
        default=None,
        description=f"Only runs with a job in this status: {', '.join(JOB_STATUSES)}.",
    ),
    limit: int = Query(default=50, ge=1, le=MAX_HISTORY_LIMIT),
    offset: int = Query(default=0, ge=0),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegenRunListResponse:
    """Return a page of a project's regen history.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        status: Narrow to runs with a job in this status.
        limit: Page size.
        offset: Runs to skip.
        auth_data: Authenticated principal.

    Returns:
        The page, newest first.

    Raises:
        HTTPException: 403 without ``versions:view``; 404 when the project is unknown; 422 for an
            unknown status.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    key = status.strip().lower() if status else None
    if key and key not in JOB_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "sdk-regen-status-invalid",
                "message": f"status must be one of {', '.join(JOB_STATUSES)}.",
            },
        )
    rows = db.list_sdk_regen_runs(tenant_id, project_id, job_status=key, limit=limit, offset=offset)
    return RegenRunListResponse(
        runs=_runs_with_jobs(tenant_id, rows, tenant_slug=tenant_slug),
        total=db.count_sdk_regen_runs(tenant_id, project_id, job_status=key),
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{tenant_slug}/{project_ref}/sdk-regen-runs/{run_id}",
    response_model=RegenRunModel,
    tags=["sdk-regen"],
    summary="Read what one publish regenerated and delivered",
    description="The run and every job in it.\n\nRequires `versions:view`.",
    responses={404: {"description": "Project or run not found in this tenant."}},
)
async def get_regen_run(
    tenant_slug: str,
    project_ref: str,
    run_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegenRunModel:
    """Return one regen run with its jobs.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        run_id: The run.
        auth_data: Authenticated principal.

    Returns:
        The run.

    Raises:
        HTTPException: 403 without ``versions:view``; 404 when the project or run is unknown.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    row = db.get_sdk_regen_run(tenant_id, str(project["id"]), run_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "sdk-regen-run-not-found",
                "message": f"No regen run {run_id!r} belongs to this project.",
            },
        )
    [run] = _runs_with_jobs(tenant_id, [row], tenant_slug=tenant_slug)
    return run


@router.post(
    "/{tenant_slug}/{project_ref}/sdk-regen-jobs/{job_id}/retry",
    response_model=RegenJobModel,
    tags=["sdk-regen"],
    summary="Retry a dead-lettered regen job",
    description=(
        "Puts a `dead_letter` job back on the queue with a fresh attempt budget. It runs with the "
        "subscription as it is now, and skips any step that already succeeded — a job that "
        "published its package and then failed to open its pull request only delivers on the "
        "retry, pinned to the version it already published.\n\n"
        "Refused with `409` when the job is not dead-lettered, or when its subscription was "
        "removed or disabled (unsubscribing stops future runs, retries included).\n\n"
        "Requires `versions:publish`. Audited as `sdk.regen_job.retry`."
    ),
    responses={
        404: {"description": "Project or job not found in this tenant."},
        409: {"description": "The job is not dead-lettered, or its subscription is not active."},
    },
)
async def retry_regen_job(
    tenant_slug: str,
    project_ref: str,
    job_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegenJobModel:
    """Re-queue one dead-lettered job.

    Args:
        tenant_slug: Tenant in the URL.
        project_ref: The project's id or slug.
        job_id: The job.
        auth_data: Authenticated principal.

    Returns:
        The re-queued job.

    Raises:
        HTTPException: 403 without ``versions:publish``; 404 for an unknown project or job; 409
            when the job is not dead-lettered or its subscription is not active.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = tenant_id_of(auth_data)
    project = resolve_project(tenant_id, project_ref)
    project_id = str(project["id"])
    job = db.get_sdk_regen_job(tenant_id, job_id)
    if not job or str(job.get("project_id")) != project_id:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "sdk-regen-job-not-found",
                "message": f"No regen job {job_id!r} belongs to this project.",
            },
        )
    if job.get("status") != JOB_STATUS_DEAD_LETTER:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "sdk-regen-job-not-dead-lettered",
                "message": (
                    f"Only a dead-lettered job can be retried; this one is {job.get('status')!r}."
                ),
            },
        )
    if job.get("subscription_active") is not True:
        removed = job.get("subscription_active") is None
        raise HTTPException(
            status_code=409,
            detail={
                "code": "sdk-regen-unsubscribed" if removed else "sdk-regen-subscription-disabled",
                "message": (
                    f"The project's {job.get('ecosystem')} SDK is no longer subscribed, so this job "
                    "will not run again. Subscribe it again to regenerate future publishes."
                    if removed
                    else f"The project's {job.get('ecosystem')} regen subscription is disabled. "
                    "Enable it, then retry the job."
                ),
            },
        )

    requeued = db.retry_sdk_regen_job(
        tenant_id, project_id, job_id, actor_id=get_authenticated_user_id(auth_data)
    )
    if requeued is None:
        # Lost a race with another retry (or the job changed state in between).
        raise HTTPException(
            status_code=409,
            detail={
                "code": "sdk-regen-job-not-dead-lettered",
                "message": "The job is no longer dead-lettered; it may already have been retried.",
            },
        )

    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_JOB_RETRY,
        auth_data=auth_data,
        target=project_id,
        detail={
            "jobId": job_id,
            "runId": requeued.get("run_id"),
            "ecosystem": requeued.get("ecosystem"),
            "previousErrorCode": job.get("error_code"),
        },
    )
    return job_model({**requeued, "subscription_active": True}, tenant_slug=tenant_slug)
