"""
Repository registration endpoints (REPO-1.4).

Provides tenant-scoped endpoints to register source-code repositories and
trigger an initial scan job.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .auth import validate_authentication
from .repositories.manifest import parse_repo_manifest

router = APIRouter(prefix="/v1/repositories", tags=["repositories"])


class RepositoryBranchInput(BaseModel):
    branch: str = Field(min_length=1)
    subpathGlob: str | None = None
    pollIntervalSec: int | None = Field(default=None, ge=15, le=86400)


class RepositoryRegisterRequest(BaseModel):
    linkedAccountId: str
    provider: Literal["github"]
    owner: str = Field(min_length=1)
    name: str = Field(min_length=1)
    branches: List[RepositoryBranchInput] = Field(min_length=1)
    manifest: str | None = None


class RepositoryBranchesUpdateRequest(BaseModel):
    branches: List[RepositoryBranchInput] = Field(min_length=1)


class RepositoryEditRequest(BaseModel):
    owner: str | None = None
    name: str | None = None
    manifest: str | None = None


class RepositoryDeleteRequest(BaseModel):
    confirmFullName: str = Field(min_length=1)


RepositoryScanTrigger = Literal["manual", "scheduled", "webhook", "register"]
RepositoryScanStatus = Literal[
    "pending",
    "walking",
    "sniffing",
    "complete",
    "failed",
    "skipped_unchanged",
]
RepositoryFileStatus = Literal[
    "new",
    "unchanged",
    "modified",
    "removed",
    "parse_error",
    "manifest_error",
]


class RepositoryScanTimelineEntry(BaseModel):
    id: str
    type: Literal["scan"]
    status: Literal["in_progress", "completed", "failed"]
    message: str
    createdAt: str


class RepositoryBranchRecord(BaseModel):
    branch: str
    subpathGlob: str | None = None
    pollIntervalSec: int | None = None


class RepositoryRecord(BaseModel):
    id: str
    tenantId: str
    linkedAccountId: str
    provider: Literal["github"]
    owner: str
    name: str
    fullName: str
    status: Literal["healthy", "warnings", "error", "scan_in_progress", "archived"] = "scan_in_progress"
    branches: List[RepositoryBranchRecord]
    manifest: str | None = None
    createdAt: str
    updatedAt: str
    archivedAt: str | None = None
    timeline: List[RepositoryScanTimelineEntry]


class RegisterRepositoryResponse(BaseModel):
    repository: RepositoryRecord
    initialScanJobId: str


class RepositoryScanRecord(BaseModel):
    id: str
    repositoryId: str
    branch: str
    commitSha: str
    trigger: RepositoryScanTrigger
    status: RepositoryScanStatus
    startedAt: str
    finishedAt: str | None = None
    durationMs: int | None = None
    filesSeen: int
    filesClassified: int
    filesUnknown: int
    filesFailed: int
    eventLog: List[Dict[str, Any]] = Field(default_factory=list)
    diffSummary: Dict[str, Any] = Field(default_factory=dict)
    errorCode: str | None = None
    errorDetail: str | None = None
    createdAt: str


class RepositoryFileRecord(BaseModel):
    id: str
    repositoryId: str
    scanId: str
    path: str
    blobSha: str | None = None
    sizeBytes: int | None = None
    format: str | None = None
    confidence: float | None = None
    discriminator: str | None = None
    tracked: bool
    projectSlug: str | None = None
    versionStrategy: str | None = None
    status: RepositoryFileStatus
    qualityScore: int | None = None
    lastImportJobId: str | None = None
    createdAt: str


class RepositoryScanCreateRequest(BaseModel):
    branch: str = Field(min_length=1)
    force: bool = False


class RepositoryScanPage(BaseModel):
    items: List[RepositoryScanRecord]
    limit: int
    nextCursor: str | None = None


class RepositoryScanFilePage(BaseModel):
    items: List[RepositoryFileRecord]
    limit: int
    nextCursor: str | None = None


_REPO_STORE: Dict[str, Dict[str, RepositoryRecord]] = {}
_REPO_BRANCH_STORE: Dict[str, List[RepositoryBranchRecord]] = {}
_REPO_SCAN_STORE: Dict[str, List[RepositoryScanTimelineEntry]] = {}
_REPO_FILE_STORE: Dict[str, List[Dict[str, Any]]] = {}
_REPO_SCAN_HISTORY_STORE: Dict[str, List[RepositoryScanRecord]] = {}
_REPO_SCAN_FILE_HISTORY_STORE: Dict[str, List[RepositoryFileRecord]] = {}
_REPO_CREDENTIAL_REF_STORE: Dict[str, List[Dict[str, Any]]] = {}
_REPO_AUDIT_STORE: List[Dict[str, Any]] = []
_STORE_LOCK = Lock()

_DEFAULT_SCAN_PAGE_SIZE = 50
_MAX_SCAN_PAGE_SIZE = 200


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_uuid(raw: str, field_name: str) -> None:
    try:
        UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{field_name} must be a valid UUID") from exc


def _parse_iso8601(raw: Optional[str], label: str) -> Optional[datetime]:
    if raw is None:
        return None
    normalized = raw.strip().replace("Z", "+00:00")
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {label}; expected ISO 8601 datetime") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _encode_cursor(created_at: str, row_id: str) -> str:
    payload = json.dumps({"createdAt": created_at, "id": row_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(token: str) -> Tuple[datetime, str]:
    raw = token.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Invalid cursor")
    padding = "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw + padding).decode("utf-8")
        parsed = json.loads(decoded)
    except (binascii.Error, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="Invalid cursor")
    created_at = parsed.get("createdAt")
    row_id = parsed.get("id")
    if not isinstance(created_at, str) or not isinstance(row_id, str):
        raise HTTPException(status_code=400, detail="Invalid cursor")
    _validate_uuid(row_id, "cursor.id")
    parsed_time = _parse_iso8601(created_at, "cursor.createdAt")
    if parsed_time is None:
        raise HTTPException(status_code=400, detail="Invalid cursor")
    return parsed_time, row_id


def _find_repository_for_tenant(tenant_id: str, repository_id: str) -> RepositoryRecord:
    repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repository_id}")
    return repository


def _to_sort_key(created_at: str, row_id: str) -> Tuple[datetime, str]:
    parsed = _parse_iso8601(created_at, "createdAt")
    if parsed is None:
        raise HTTPException(status_code=500, detail="scan row missing createdAt")
    return parsed, row_id


def _make_pending_scan(
    *,
    repository_id: str,
    branch: str,
    trigger: RepositoryScanTrigger,
    force: bool,
) -> RepositoryScanRecord:
    now = _utc_now_iso()
    return RepositoryScanRecord(
        id=str(uuid4()),
        repositoryId=repository_id,
        branch=branch,
        commitSha=f"pending-{uuid4().hex[:12]}",
        trigger=trigger,
        status="pending",
        startedAt=now,
        filesSeen=0,
        filesClassified=0,
        filesUnknown=0,
        filesFailed=0,
        eventLog=[{"type": "repository.scan.queued", "at": now, "force": force}],
        diffSummary={},
        createdAt=now,
    )


def _make_skipped_unchanged_scan(
    *,
    repository_id: str,
    branch: str,
    trigger: RepositoryScanTrigger,
    baseline_commit_sha: str | None,
) -> RepositoryScanRecord:
    now = _utc_now_iso()
    return RepositoryScanRecord(
        id=str(uuid4()),
        repositoryId=repository_id,
        branch=branch,
        commitSha=baseline_commit_sha or f"skipped-{uuid4().hex[:12]}",
        trigger=trigger,
        status="skipped_unchanged",
        startedAt=now,
        finishedAt=now,
        durationMs=0,
        filesSeen=0,
        filesClassified=0,
        filesUnknown=0,
        filesFailed=0,
        eventLog=[
            {
                "type": "repository.scan.skipped_unchanged",
                "at": now,
                "reason": "force=false and no detected changes",
            }
        ],
        diffSummary={"changed": 0},
        createdAt=now,
    )


def _normalize_branch(record: RepositoryBranchInput) -> RepositoryBranchRecord:
    stripped_subpath = record.subpathGlob.strip() if record.subpathGlob else ""
    normalized_subpath = stripped_subpath if stripped_subpath else "**/*"
    return RepositoryBranchRecord(
        branch=record.branch.strip(),
        subpathGlob=normalized_subpath,
        pollIntervalSec=record.pollIntervalSec,
    )


def _normalize_branches(branches: List[RepositoryBranchInput]) -> List[RepositoryBranchRecord]:
    normalized_branches = [_normalize_branch(branch) for branch in branches]
    if any(not branch.branch for branch in normalized_branches):
        raise HTTPException(status_code=400, detail="branches[].branch is required")
    dedupe_key_count = len({branch.branch for branch in normalized_branches})
    if dedupe_key_count != len(normalized_branches):
        raise HTTPException(status_code=400, detail="branches[].branch must be unique")
    return normalized_branches


def _to_summary(repo: RepositoryRecord) -> Dict[str, Any]:
    return {
        "id": repo.id,
        "provider": repo.provider,
        "owner": repo.owner,
        "name": repo.name,
        "fullName": repo.fullName,
        "status": repo.status,
        "branches": [b.branch for b in repo.branches],
        "createdAt": repo.createdAt,
        "updatedAt": repo.updatedAt,
    }


def _write_audit_row(tenant_id: str, repository_id: str, event_type: Literal["repository.archived", "repository.unarchived", "repository.removed"]) -> None:
    _REPO_AUDIT_STORE.append(
        {
            "id": str(uuid4()),
            "tenantId": tenant_id,
            "repositoryId": repository_id,
            "eventType": event_type,
            "createdAt": _utc_now_iso(),
        }
    )


def _list_poll_targets_for_tenant(tenant_id: str) -> List[Dict[str, str]]:
    poll_targets: List[Dict[str, str]] = []
    for repository in _REPO_STORE.get(tenant_id, {}).values():
        if repository.status == "archived":
            continue
        for branch in _REPO_BRANCH_STORE.get(repository.id, repository.branches):
            poll_targets.append({"repositoryId": repository.id, "branch": branch.branch})
    return poll_targets


@router.post("/{tenant_slug}", status_code=201, response_model=RegisterRepositoryResponse)
async def register_repository(
    tenant_slug: str,
    request: RepositoryRegisterRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegisterRepositoryResponse:
    tenant_id = auth_data["tenant_id"]

    _validate_uuid(request.linkedAccountId, "linkedAccountId")
    owner = request.owner.strip()
    name = request.name.strip()
    if not owner or not name:
        raise HTTPException(status_code=400, detail="owner and name are required")

    normalized_branches = _normalize_branches(request.branches)

    now = _utc_now_iso()
    repository_id = str(uuid4())
    initial_scan_job_id = str(uuid4())
    timeline_entry = RepositoryScanTimelineEntry(
        id=str(uuid4()),
        type="scan",
        status="in_progress",
        message="Scan in progress...",
        createdAt=now,
    )
    repository = RepositoryRecord(
        id=repository_id,
        tenantId=tenant_id,
        linkedAccountId=request.linkedAccountId,
        provider="github",
        owner=owner,
        name=name,
        fullName=f"{owner}/{name}",
        status="scan_in_progress",
        branches=normalized_branches,
        manifest=request.manifest,
        createdAt=now,
        updatedAt=now,
        timeline=[timeline_entry],
    )

    manifest_outcome = parse_repo_manifest(request.manifest)
    initial_file_rows: List[Dict[str, Any]] = []
    initial_scan_files: List[RepositoryFileRecord] = []
    if manifest_outcome.manifest_error_row is not None:
        row = manifest_outcome.manifest_error_row
        initial_file_rows.append(
            {
                "path": row.path,
                "format": row.format,
                "tracked": row.tracked,
                "pollIntervalSec": row.poll_interval_sec,
                "status": row.status,
                "metadata": row.metadata,
            }
        )
        initial_scan_files.append(
            RepositoryFileRecord(
                id=str(uuid4()),
                repositoryId=repository_id,
                scanId=initial_scan_job_id,
                path=row.path,
                format=row.format,
                tracked=row.tracked,
                status="manifest_error",
                discriminator=row.metadata["error"] if row.metadata and "error" in row.metadata else None,
                createdAt=now,
            )
        )

    initial_scan = RepositoryScanRecord(
        id=initial_scan_job_id,
        repositoryId=repository_id,
        branch=normalized_branches[0].branch,
        commitSha=f"pending-{uuid4().hex[:12]}",
        trigger="register",
        status="pending",
        startedAt=now,
        filesSeen=0,
        filesClassified=0,
        filesUnknown=0,
        filesFailed=0,
        eventLog=[{"type": "repository.scan.queued", "at": now, "trigger": "register"}],
        diffSummary={},
        createdAt=now,
    )

    with _STORE_LOCK:
        tenant_repos = _REPO_STORE.setdefault(tenant_id, {})
        _REPO_BRANCH_STORE[repository.id] = list(normalized_branches)
        _REPO_SCAN_STORE[repository.id] = [timeline_entry]
        _REPO_FILE_STORE[repository.id] = initial_file_rows
        _REPO_SCAN_HISTORY_STORE[repository.id] = [initial_scan]
        _REPO_SCAN_FILE_HISTORY_STORE[initial_scan.id] = initial_scan_files
        _REPO_CREDENTIAL_REF_STORE[repository.id] = [{"linkedAccountId": request.linkedAccountId}]
        tenant_repos[repository.id] = repository

    return RegisterRepositoryResponse(
        repository=repository,
        initialScanJobId=initial_scan_job_id,
    )


@router.get("/{tenant_slug}")
async def list_repositories(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, List[Dict[str, Any]]]:
    tenant_id = auth_data["tenant_id"]
    with _STORE_LOCK:
        tenant_repos = list(_REPO_STORE.get(tenant_id, {}).values())
    tenant_repos.sort(key=lambda repo: repo.updatedAt, reverse=True)
    return {"repositories": [_to_summary(repo) for repo in tenant_repos]}


@router.get("/{tenant_slug}/{repository_id}", response_model=RepositoryRecord)
async def get_repository(
    tenant_slug: str,
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryRecord:
    tenant_id = auth_data["tenant_id"]
    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
    if repository is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repository_id}")
    return repository


@router.patch("/{tenant_slug}/{repository_id}/branches", response_model=RepositoryRecord)
async def update_repository_branches(
    tenant_slug: str,
    repository_id: str,
    request: RepositoryBranchesUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryRecord:
    tenant_id = auth_data["tenant_id"]
    normalized_branches = _normalize_branches(request.branches)

    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail=f"Repository not found: {repository_id}")
        _REPO_BRANCH_STORE[repository.id] = list(normalized_branches)
        repository.branches = list(normalized_branches)
        repository.updatedAt = _utc_now_iso()
        return repository


@router.patch("/{tenant_slug}/{repository_id}", response_model=RepositoryRecord)
async def edit_repository(
    tenant_slug: str,
    repository_id: str,
    request: RepositoryEditRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryRecord:
    tenant_id = auth_data["tenant_id"]
    if request.owner is None and request.name is None and request.manifest is None:
        raise HTTPException(status_code=400, detail="At least one editable field is required")

    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail=f"Repository not found: {repository_id}")

        if request.owner is not None:
            owner = request.owner.strip()
            if not owner:
                raise HTTPException(status_code=400, detail="owner must not be empty")
            repository.owner = owner

        if request.name is not None:
            name = request.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="name must not be empty")
            repository.name = name

        if request.owner is not None or request.name is not None:
            repository.fullName = f"{repository.owner}/{repository.name}"

        if request.manifest is not None:
            repository.manifest = request.manifest

        repository.updatedAt = _utc_now_iso()
        return repository


@router.post("/{tenant_slug}/{repository_id}/archive", response_model=RepositoryRecord)
async def archive_repository(
    tenant_slug: str,
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryRecord:
    tenant_id = auth_data["tenant_id"]
    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail=f"Repository not found: {repository_id}")

        now = _utc_now_iso()
        repository.status = "archived"
        repository.archivedAt = now
        repository.updatedAt = now
        _write_audit_row(tenant_id, repository_id, "repository.archived")
        return repository


@router.post("/{tenant_slug}/{repository_id}/unarchive", response_model=RepositoryRecord)
async def unarchive_repository(
    tenant_slug: str,
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryRecord:
    tenant_id = auth_data["tenant_id"]
    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail=f"Repository not found: {repository_id}")

        repository.status = "healthy"
        repository.archivedAt = None
        repository.updatedAt = _utc_now_iso()
        _write_audit_row(tenant_id, repository_id, "repository.unarchived")
        return repository


@router.delete("/{tenant_slug}/{repository_id}", status_code=204)
async def delete_repository(
    tenant_slug: str,
    repository_id: str,
    request: RepositoryDeleteRequest = Body(...),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    tenant_id = auth_data["tenant_id"]
    with _STORE_LOCK:
        tenant_repos = _REPO_STORE.get(tenant_id, {})
        repository = tenant_repos.get(repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail=f"Repository not found: {repository_id}")
        if request.confirmFullName.strip() != repository.fullName:
            raise HTTPException(status_code=400, detail="confirmFullName must match repository fullName")

        tenant_repos.pop(repository_id, None)
        _REPO_BRANCH_STORE.pop(repository_id, None)
        _REPO_SCAN_STORE.pop(repository_id, None)
        _REPO_FILE_STORE.pop(repository_id, None)
        scan_history = _REPO_SCAN_HISTORY_STORE.pop(repository_id, [])
        for scan in scan_history:
            _REPO_SCAN_FILE_HISTORY_STORE.pop(scan.id, None)
        _REPO_CREDENTIAL_REF_STORE.pop(repository_id, None)
        _write_audit_row(tenant_id, repository_id, "repository.removed")

    return Response(status_code=204)


@router.get("/{repository_id}/scans", response_model=RepositoryScanPage)
async def list_repository_scans(
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    status: RepositoryScanStatus | None = Query(default=None),
    branch: str | None = Query(default=None),
    from_timestamp: str | None = Query(default=None, alias="from"),
    to_timestamp: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=_DEFAULT_SCAN_PAGE_SIZE, ge=1, le=_MAX_SCAN_PAGE_SIZE),
    cursor: str | None = Query(default=None),
) -> RepositoryScanPage:
    tenant_id = auth_data["tenant_id"]
    from_dt = _parse_iso8601(from_timestamp, "from")
    to_dt = _parse_iso8601(to_timestamp, "to")
    cursor_key: Tuple[datetime, str] | None = None
    if cursor:
        cursor_dt, cursor_id = _decode_cursor(cursor)
        cursor_key = (cursor_dt, cursor_id)

    with _STORE_LOCK:
        _find_repository_for_tenant(tenant_id, repository_id)
        scans = list(_REPO_SCAN_HISTORY_STORE.get(repository_id, []))

    filtered: List[RepositoryScanRecord] = []
    for scan in scans:
        if status is not None and scan.status != status:
            continue
        if branch is not None and scan.branch != branch:
            continue
        scan_dt = _parse_iso8601(scan.createdAt, "createdAt")
        if scan_dt is None:
            continue
        if from_dt is not None and scan_dt < from_dt:
            continue
        if to_dt is not None and scan_dt > to_dt:
            continue
        if cursor_key is not None and (scan_dt, scan.id) >= cursor_key:
            continue
        filtered.append(scan)

    filtered.sort(key=lambda item: _to_sort_key(item.createdAt, item.id), reverse=True)
    page_rows = filtered[: limit + 1]
    has_more = len(page_rows) > limit
    page_items = page_rows[:limit]
    next_cursor = None
    if has_more and page_items:
        tail = page_items[-1]
        next_cursor = _encode_cursor(tail.createdAt, tail.id)

    return RepositoryScanPage(items=page_items, limit=limit, nextCursor=next_cursor)


@router.get("/{repository_id}/scans/{scan_id}", response_model=RepositoryScanRecord)
async def get_repository_scan(
    repository_id: str,
    scan_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryScanRecord:
    tenant_id = auth_data["tenant_id"]
    with _STORE_LOCK:
        _find_repository_for_tenant(tenant_id, repository_id)
        scans = _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
        for scan in scans:
            if scan.id == scan_id:
                return scan
    raise HTTPException(status_code=404, detail=f"Scan not found: {scan_id}")


@router.get("/{repository_id}/scans/{scan_id}/files", response_model=RepositoryScanFilePage)
async def list_repository_scan_files(
    repository_id: str,
    scan_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    format: str | None = Query(default=None),
    status: RepositoryFileStatus | None = Query(default=None),
    limit: int = Query(default=_DEFAULT_SCAN_PAGE_SIZE, ge=1, le=_MAX_SCAN_PAGE_SIZE),
    cursor: str | None = Query(default=None),
) -> RepositoryScanFilePage:
    tenant_id = auth_data["tenant_id"]
    cursor_key: Tuple[datetime, str] | None = None
    if cursor:
        cursor_dt, cursor_id = _decode_cursor(cursor)
        cursor_key = (cursor_dt, cursor_id)

    with _STORE_LOCK:
        _find_repository_for_tenant(tenant_id, repository_id)
        scans = _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
        if not any(scan.id == scan_id for scan in scans):
            raise HTTPException(status_code=404, detail=f"Scan not found: {scan_id}")
        files = list(_REPO_SCAN_FILE_HISTORY_STORE.get(scan_id, []))

    filtered: List[RepositoryFileRecord] = []
    for file_row in files:
        if format is not None and file_row.format != format:
            continue
        if status is not None and file_row.status != status:
            continue
        file_dt = _parse_iso8601(file_row.createdAt, "createdAt")
        if file_dt is None:
            continue
        if cursor_key is not None and (file_dt, file_row.id) >= cursor_key:
            continue
        filtered.append(file_row)

    filtered.sort(key=lambda item: _to_sort_key(item.createdAt, item.id), reverse=True)
    page_rows = filtered[: limit + 1]
    has_more = len(page_rows) > limit
    page_items = page_rows[:limit]
    next_cursor = None
    if has_more and page_items:
        tail = page_items[-1]
        next_cursor = _encode_cursor(tail.createdAt, tail.id)
    return RepositoryScanFilePage(items=page_items, limit=limit, nextCursor=next_cursor)


@router.post("/{repository_id}/scans", response_model=RepositoryScanRecord)
async def create_repository_scan(
    repository_id: str,
    request: RepositoryScanCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryScanRecord:
    tenant_id = auth_data["tenant_id"]
    branch_name = request.branch.strip()
    if not branch_name:
        raise HTTPException(status_code=400, detail="branch is required")

    with _STORE_LOCK:
        _find_repository_for_tenant(tenant_id, repository_id)
        history = _REPO_SCAN_HISTORY_STORE.setdefault(repository_id, [])
        latest_for_branch = next((scan for scan in history if scan.branch == branch_name), None)
        if latest_for_branch is not None and not request.force:
            scan = _make_skipped_unchanged_scan(
                repository_id=repository_id,
                branch=branch_name,
                trigger="manual",
                baseline_commit_sha=latest_for_branch.commitSha,
            )
        else:
            scan = _make_pending_scan(
                repository_id=repository_id,
                branch=branch_name,
                trigger="manual",
                force=request.force,
            )
        history.insert(0, scan)
        _REPO_SCAN_FILE_HISTORY_STORE[scan.id] = []
        return scan


def _reset_repository_state_for_tests() -> None:
    with _STORE_LOCK:
        _REPO_STORE.clear()
        _REPO_BRANCH_STORE.clear()
        _REPO_SCAN_STORE.clear()
        _REPO_FILE_STORE.clear()
        _REPO_SCAN_HISTORY_STORE.clear()
        _REPO_SCAN_FILE_HISTORY_STORE.clear()
        _REPO_CREDENTIAL_REF_STORE.clear()
        _REPO_AUDIT_STORE.clear()


def _seed_repository_relations_for_tests(repository_id: str) -> None:
    with _STORE_LOCK:
        now = _utc_now_iso()
        seeded_scan = RepositoryScanRecord(
            id=str(uuid4()),
            repositoryId=repository_id,
            branch="main",
            commitSha=f"seeded-{uuid4().hex[:12]}",
            trigger="manual",
            status="complete",
            startedAt=now,
            finishedAt=now,
            durationMs=0,
            filesSeen=1,
            filesClassified=1,
            filesUnknown=0,
            filesFailed=0,
            eventLog=[{"type": "repository.scan.seeded", "at": now}],
            diffSummary={"changed": 1},
            createdAt=now,
        )
        _REPO_SCAN_STORE[repository_id] = [RepositoryScanTimelineEntry(id=str(uuid4()), type="scan", status="completed", message="done", createdAt=now)]
        _REPO_SCAN_HISTORY_STORE[repository_id] = [seeded_scan]
        _REPO_SCAN_FILE_HISTORY_STORE[seeded_scan.id] = [
            RepositoryFileRecord(
                id=str(uuid4()),
                repositoryId=repository_id,
                scanId=seeded_scan.id,
                path="README.md",
                tracked=True,
                status="new",
                createdAt=now,
            )
        ]
        _REPO_FILE_STORE[repository_id] = [{"path": "README.md"}]
        _REPO_CREDENTIAL_REF_STORE[repository_id] = [{"linkedAccountId": str(uuid4())}]


def _get_repository_audit_rows_for_tests(repository_id: str) -> List[Dict[str, Any]]:
    with _STORE_LOCK:
        return [row for row in _REPO_AUDIT_STORE if row["repositoryId"] == repository_id]


def _get_repository_relations_exist_for_tests(repository_id: str) -> Dict[str, bool]:
    with _STORE_LOCK:
        return {
            "repository_branch": repository_id in _REPO_BRANCH_STORE,
            "repository_scan": repository_id in _REPO_SCAN_STORE,
            "repository_file": repository_id in _REPO_FILE_STORE,
            "repository_credential_ref": repository_id in _REPO_CREDENTIAL_REF_STORE,
        }


def _list_poll_targets_for_tests(tenant_id: str) -> List[Dict[str, str]]:
    with _STORE_LOCK:
        return _list_poll_targets_for_tenant(tenant_id)
