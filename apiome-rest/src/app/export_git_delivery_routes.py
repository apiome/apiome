"""Export git delivery routes — MFX-38.1 (#4328).

``POST /v1/export/{tenant_slug}/jobs/{job_id}/deliveries/git`` delivers a **completed** export job's
bundle into a registered repository — a pull request (``mode=pr``, default) or a direct commit
(``mode=commit``) — and ``GET`` on the same path lists that job's deliveries. The delivery itself is
:func:`app.export_git_delivery_pipeline.deliver_export`.

Where the bundle comes from: the job's retained emit result when this instance ran it, otherwise
the job's stored download artifact (any instance can read it; a zip is unpacked). An artifact past its
retention window answers ``410`` — export again, then deliver.

**Permissions.** Delivering writes to a repository with the workspace's linked-account credential,
so it needs ``versions:publish`` — as opening a PR-back pull request (REPO-5.8) or an SDK delivery
(SDK-4.2) does. Listing deliveries needs ``projects:view``. Every delivery is audited as
``export.git_delivery``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .auth import get_authenticated_user_id, validate_authentication
from .config import settings
from .database import db
from .export_git_delivery import (
    BundleFile,
    DeliverySubject,
    ExportGitDeliveryRequestError,
    GitDeliveryRequest,
    bundle_files_from_artifact,
    bundle_files_from_emit,
    fidelity_summary,
    normalize_request,
    report_url,
)
from .export_git_delivery_pipeline import ExportDeliveryOutcome, deliver_export, run_row_to_outcome
from .export_job_engine import (
    ExportJobResult,
    get_export_job_emit_result,
    get_export_job_status,
    resolve_export_download,
    serialize_file_content,
)
from .permissions import Action, Resource, enforce_permission
from .sdk_publish_routes import tenant_id_of, write_audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/export", tags=["export-delivery"])

AUDIT_DELIVERY = "export.git_delivery"


class ExportGitDeliveryRunModel(BaseModel):
    """One export git delivery.

    Attributes:
        run_id: The run record.
        status: ``in_progress``, ``opened``, ``updated``, ``unchanged``, ``up_to_date``, ``committed``
            or ``failed``.
        mode: ``pr`` or ``commit``.
        job_id: The export job delivered.
        repository_id: The registered repository.
        repository_full_name: ``owner/repo``.
        base_branch: The base branch used.
        target_path: The directory the bundle was written under.
        branch_name: The delivery branch (the base branch in commit mode).
        base_sha: The base commit.
        commit_sha: The commit the branch points at.
        pull_request_number: The pull request opened or updated.
        pull_request_url: Its web page.
        changes: The changed-files overview.
        fidelity: The fidelity summary the pull request carried.
        log: The delivery event log, redacted of secrets.
        error_code: Set when the run failed.
        error_message: Set when the run failed.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    run_id: Optional[str] = Field(default=None, serialization_alias="runId")
    status: str
    mode: str
    job_id: str = Field(serialization_alias="jobId")
    repository_id: Optional[str] = Field(default=None, serialization_alias="repositoryId")
    repository_full_name: Optional[str] = Field(default=None, serialization_alias="repositoryFullName")
    base_branch: Optional[str] = Field(default=None, serialization_alias="baseBranch")
    target_path: str = Field(default="", serialization_alias="targetPath")
    branch_name: Optional[str] = Field(default=None, serialization_alias="branchName")
    base_sha: Optional[str] = Field(default=None, serialization_alias="baseSha")
    commit_sha: Optional[str] = Field(default=None, serialization_alias="commitSha")
    pull_request_number: Optional[int] = Field(default=None, serialization_alias="pullRequestNumber")
    pull_request_url: Optional[str] = Field(default=None, serialization_alias="pullRequestUrl")
    changes: Dict[str, Any] = Field(default_factory=dict)
    fidelity: Dict[str, Any] = Field(default_factory=dict)
    log: List[Dict[str, Any]] = Field(default_factory=list)
    error_code: Optional[str] = Field(default=None, serialization_alias="errorCode")
    error_message: Optional[str] = Field(default=None, serialization_alias="errorMessage")


class ExportGitDeliveryRunListResponse(BaseModel):
    """A job's deliveries, newest first."""

    model_config = ConfigDict(extra="forbid")

    runs: List[ExportGitDeliveryRunModel] = Field(default_factory=list)


def _run_model(outcome: ExportDeliveryOutcome) -> ExportGitDeliveryRunModel:
    """Project an outcome (or a stored run read back) onto the wire model."""
    return ExportGitDeliveryRunModel(
        run_id=outcome.run_id, status=outcome.status, mode=outcome.mode, job_id=outcome.job_id,
        repository_id=outcome.repository_id, repository_full_name=outcome.repository_full_name,
        base_branch=outcome.base_branch, target_path=outcome.target_path, branch_name=outcome.branch_name,
        base_sha=outcome.base_sha, commit_sha=outcome.commit_sha,
        pull_request_number=outcome.pull_request_number, pull_request_url=outcome.pull_request_url,
        changes=outcome.changes, fidelity=outcome.fidelity, log=outcome.log, error_code=outcome.error_code,
        error_message=outcome.error_message,
    )


def _check_tenant(tenant_slug: str, tenant_id: str) -> None:
    """The URL's tenant must be the caller's: export jobs are scoped by slug, credentials by id."""
    try:
        row = db.get_tenant_row_by_slug(tenant_slug)
    except Exception:  # noqa: BLE001 - treat an unreadable tenant like an unknown one
        row = None
    if not row or str(row.get("id")) != str(tenant_id):
        raise HTTPException(status_code=404, detail="Export job not found")


def _completed_result(status: Any) -> ExportJobResult:
    """The result of a job that can be delivered, or refuse (409)."""
    result = status.result
    if status.state != "completed" or result is None:
        raise HTTPException(status_code=409, detail={
            "code": "export-git-delivery-job-not-completed",
            "message": f"The export job is {status.state}; only a completed export can be delivered.",
        })
    if result.dry_run:
        raise HTTPException(status_code=409, detail={
            "code": "export-git-delivery-dry-run",
            "message": "A dry-run export has no files to deliver. Run the export for real, then deliver it.",
        })
    return result


def _fidelity(result: ExportJobResult) -> Dict[str, Any]:
    """The fidelity summary a delivery carries: the job's, or a multi-target job's weakest target's."""
    if result.fidelity is not None:
        return fidelity_summary(result.fidelity.model_dump(mode="json"))
    targets = result.targets or []
    summaries: List[Tuple[str, Dict[str, Any]]] = [
        (t.target, fidelity_summary(t.fidelity.model_dump(mode="json"))) for t in targets
    ]
    if not summaries:
        return {}
    target, weakest = min(summaries, key=lambda pair: pair[1].get("preservedPercent", 100))
    out = dict(weakest)
    out["headline"] = (f"{len(summaries)} targets; the weakest, {target}, is shown. "
                       + str(weakest.get("headline") or "")).strip()
    return out


def _bundle(tenant_slug: str, job_id: str, result: ExportJobResult) -> List[BundleFile]:
    """The job's files: the retained emit result on this instance, else the stored artifact."""
    emitted = get_export_job_emit_result(tenant_slug, job_id)
    if emitted is not None:
        return bundle_files_from_emit((f.path, serialize_file_content(f.content)) for f in emitted.files)
    artifact = resolve_export_download(tenant_slug, job_id)  # 409 / 410 propagate
    try:
        return bundle_files_from_artifact(
            artifact.body, media_type=artifact.media_type, listed_paths=[f.path for f in result.files],
            multi_target=bool(result.targets),
        )
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=409, detail={
            "code": "export-git-delivery-artifact-unreadable",
            "message": f"The export's stored bundle could not be read ({exc}). Export again, then deliver.",
        }) from exc


def _subject(tenant_slug: str, tenant_id: str, job_id: str, result: ExportJobResult) -> DeliverySubject:
    """What is being delivered, for the manifest, the branch and the pull request."""
    project: Optional[Dict[str, Any]] = None
    try:
        project = db.get_project_by_id(result.artifact, tenant_id)
    except Exception:  # noqa: BLE001 - a catalog item, or an unreadable row: name it by id
        project = None
    targets = tuple(t.target for t in (result.targets or []))
    target = result.target or ("multi" if targets else "export")
    return DeliverySubject(
        tenant_slug=tenant_slug,
        job_id=job_id,
        artifact_id=result.artifact,
        artifact_slug=(project or {}).get("slug"),
        artifact_name=(project or {}).get("name"),
        version_record_id=result.version_record_id,
        version_label=result.version_label,
        target="multi" if targets else target,
        targets=targets,
        snapshot_hash=result.snapshot_hash,
        fidelity=_fidelity(result),
        report_url=report_url(settings.ui_public_url, result.artifact, result.version_record_id,
                              None if targets else target),
    )


@router.post(
    "/{tenant_slug}/jobs/{job_id}/deliveries/git",
    response_model=ExportGitDeliveryRunModel,
    response_model_by_alias=True,
    summary="Deliver a completed export to a git repository",
    description=(
        "Writes a **completed** export job's bundle into a repository registered in this workspace "
        "through a linked GitHub account, under `targetPath` (a multi-file bundle keeps its directory "
        "tree), with a delivery manifest at `<targetPath>/.apiome/export-delivery.json`.\n\n"
        "**`mode: pr`** (default): a commit on `apiome/export-<artifact>-<target>` built on the latest "
        "base branch, and one pull request whose description carries the export's fidelity summary and a "
        "link to the full report. A re-export updates the same branch and pull request: `opened`, "
        "`updated`, `unchanged` (nothing written) or `up_to_date` (the base already holds it).\n\n"
        "**`mode: commit`**: one commit straight onto the base branch, fast-forward only — `committed`, or "
        "`failed` when the branch moved or is protected.\n\n"
        "**Failures are runs.** A missing or revoked credential, a token without write access or a refused "
        "push answers `200` with `status: failed`, a stable `errorCode` and an actionable log.\n\n"
        "Requires `versions:publish`. Audited as `export.git_delivery`."
    ),
    responses={
        400: {"description": "Invalid repository, path or base branch."},
        404: {"description": "Unknown export job for this tenant."},
        409: {"description": "The job is not completed, is a dry run, or its bundle cannot be read."},
        410: {"description": "The export's artifact has expired; export again, then deliver."},
    },
)
async def deliver_export_job_to_git(
    tenant_slug: str,
    job_id: str,
    body: GitDeliveryRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportGitDeliveryRunModel:
    """Deliver one completed export job's bundle to a repository.

    Args:
        tenant_slug: The tenant the job was submitted under.
        job_id: The export job.
        body: Where, and how.
        auth_data: Authenticated principal.

    Returns:
        The run — whatever its outcome.

    Raises:
        HTTPException: 403 without ``versions:publish``; 400 for an invalid request; 404 for an
            unknown job; 409 for a job that cannot be delivered; 410 for an expired artifact.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.PUBLISH)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    try:
        request = normalize_request(body)
    except ExportGitDeliveryRequestError as exc:
        raise HTTPException(status_code=400, detail={"code": "export-git-delivery-request-invalid",
                                                     "errors": exc.errors}) from exc

    status = await get_export_job_status(tenant_slug, job_id)
    result = _completed_result(status)
    files = await asyncio.to_thread(_bundle, tenant_slug, job_id, result)
    subject = await asyncio.to_thread(_subject, tenant_slug, tenant_id, job_id, result)
    outcome = await asyncio.to_thread(
        deliver_export, tenant_id=tenant_id, actor_id=get_authenticated_user_id(auth_data), subject=subject,
        request=request, files=files,
    )
    write_audit(
        tenant_id=tenant_id,
        action=AUDIT_DELIVERY,
        auth_data=auth_data,
        target=result.artifact,
        detail={
            "runId": outcome.run_id,
            "status": outcome.status,
            "mode": outcome.mode,
            "jobId": job_id,
            "exportTarget": subject.target,
            "repositoryFullName": outcome.repository_full_name,
            "branchName": outcome.branch_name,
            "commitSha": outcome.commit_sha,
            "pullRequestNumber": outcome.pull_request_number,
            "errorCode": outcome.error_code,
        },
    )
    return _run_model(outcome)


@router.get(
    "/{tenant_slug}/jobs/{job_id}/deliveries/git",
    response_model=ExportGitDeliveryRunListResponse,
    response_model_by_alias=True,
    summary="List a job's git deliveries",
    description="Every git delivery of one export job, newest first. Requires `projects:view`.",
)
async def list_export_job_git_deliveries(
    tenant_slug: str,
    job_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ExportGitDeliveryRunListResponse:
    """List one export job's git deliveries.

    Args:
        tenant_slug: The tenant the job was submitted under.
        job_id: The export job.
        auth_data: Authenticated principal.

    Returns:
        The runs, newest first.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = tenant_id_of(auth_data)
    _check_tenant(tenant_slug, tenant_id)
    rows = await asyncio.to_thread(db.list_export_git_delivery_runs, tenant_id, job_id)
    return ExportGitDeliveryRunListResponse(runs=[_run_model(run_row_to_outcome(row)) for row in rows])
