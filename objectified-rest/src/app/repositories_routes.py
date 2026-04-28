"""
Repository registration endpoints (REPO-1.4).

Provides tenant-scoped endpoints to register source-code repositories and
trigger an initial scan job.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import time
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
import logging
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict, Iterator, List, Literal, Optional, Sequence, Set, Tuple
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field

from .auth import validate_authentication
from .database import db
from .openapi_change_report import build_change_report
from .repositories.import_notifications import emit_repository_import_notifications
from .repositories.manifest import (
    RepoManifest,
    initial_auto_import_enabled_for_path,
    initial_import_enabled_for_path,
    manifest_duplicate_spec_paths,
    manifest_project_slug_map_from_manifest,
    parse_repo_manifest,
    resolve_repository_file_mapping,
)
from .repositories.repository_source import validate_repository_source_payload
from .repositories.spec_detail import (
    MAX_INLINE_PREVIEW_BYTES,
    _count_change_report_categories,
    derive_lint_summary,
    empty_lint_summary,
    provider_blob_url,
    provider_raw_url,
)
from .repositories.attention import (
    AttentionComputeInput,
    AttentionFileInput,
    compute_attention_detail,
)

router = APIRouter(prefix="/v1/repositories", tags=["repositories"])
_logger = logging.getLogger(__name__)


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


class RepositoryAttentionReasonDetail(BaseModel):
    reason: str
    paths: List[str] = Field(default_factory=list)


class RepositoryAttentionDetailResponse(BaseModel):
    reasons: List[str] = Field(default_factory=list)
    items: List[RepositoryAttentionReasonDetail] = Field(default_factory=list)
    openCount: int = 0
    attentionScore: int = 0
    lastChangeAt: str = ""
    refreshedAt: str = ""


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
    "unchanged_checksum",
    "modified",
    "removed",
    "discovered",
    "ready_to_promote",
    "parse_error",
    "manifest_error",
    "mapping_required",
]
ImportJobPromotion = Literal["auto", "manual"]
ImportJobOperation = Literal["import", "removal"]
ImportJobStatus = Literal["pending_review", "committed", "failed"]
ImportConflictKind = Literal[
    "duplicate_schema",
    "property_conflict",
    "reference_conflict",
    "type_mismatch",
    "semantic_conflict",
]
ImportConflictResolutionChoice = Literal["merge", "replace", "keep", "rename"]


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
    status: Literal["healthy", "warnings", "error", "scan_in_progress", "archived", "paused"] = "scan_in_progress"
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
    contentAlgo: str | None = None
    contentChecksum: str | None = None
    sizeBytes: int | None = None
    format: str | None = None
    confidence: float | None = None
    discriminator: str | None = None
    tracked: bool
    importEnabled: bool = False
    autoImportEnabled: bool = False
    projectSlug: str | None = None
    versionStrategy: str | None = None
    settingsJson: Dict[str, Any] | None = None
    promote: ImportJobPromotion | None = None
    status: RepositoryFileStatus
    qualityScore: int | None = None
    lastImportJobId: str | None = None
    lastImportedContentChecksum: str | None = None
    staleMismatchAt: str | None = None
    createdAt: str
    importSelectionActorId: str | None = None


RepositoryImportJobSourceKind = Literal[
    "git",
    "repository_sync",
    "repository_auto_import",
    "repository_manual_import",
]


class RepositoryImportJobRecord(BaseModel):
    id: str
    repositoryId: str
    repositoryFileId: str
    scanId: str
    branch: str
    sourceType: Literal["git"]
    sourceKind: RepositoryImportJobSourceKind = "repository_auto_import"
    sourceUri: str
    operation: ImportJobOperation
    format: str | None = None
    settingsJson: Dict[str, Any] = Field(default_factory=dict)
    dryRun: bool = True
    state: ImportJobStatus
    diffSnapshot: Dict[str, Any] = Field(default_factory=dict)
    conflictRecords: List[Dict[str, Any]] = Field(default_factory=list)
    eventLog: List[Dict[str, Any]] = Field(default_factory=list)
    errorDetail: str | None = None
    targetProjectSlug: str | None = None
    targetVersionId: str | None = None
    changeReportId: str | None = None
    createdAt: str


class RepositorySyncChangeReportRecord(BaseModel):
    id: str
    sourceKind: Literal["repository_sync"]
    repositoryId: str
    importJobId: str
    scanId: str
    changeModelJson: Dict[str, Any] = Field(default_factory=dict)
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


class RepositoryImportJobPage(BaseModel):
    items: List[RepositoryImportJobRecord]
    limit: int
    nextCursor: str | None = None


class RepositorySyncConflictResolutionRequest(BaseModel):
    schemaName: str = Field(min_length=1)
    choice: ImportConflictResolutionChoice
    conflictKinds: List[ImportConflictKind] = Field(min_length=1)
    note: str | None = None


class RepositoryFileImportEnabledRequest(BaseModel):
    importEnabled: bool
    source: Literal["ui", "api", "manifest"] = "api"


class RepositoryFileAutoImportEnabledRequest(BaseModel):
    autoImportEnabled: bool
    source: Literal["ui", "api", "manifest"] = "api"


RepositorySpecSelectionStatus = Literal[
    "importing",
    "imported",
    "parse_error",
    "manifest_error",
    "not_imported",
    "unchanged_checksum",
    "mapping_required",
]


class RepositorySpecRecord(BaseModel):
    fileId: str
    repositoryId: str
    scanId: str
    branch: str
    path: str
    format: str | None = None
    confidence: float | None = None
    discriminator: str | None = None
    status: RepositorySpecSelectionStatus
    importEnabled: bool
    autoImportEnabled: bool
    projectSlug: str | None = None
    versionStrategy: str | None = None
    mappingConflictKind: str | None = None
    lastImportedVersionId: str | None = None
    lastImportedAt: str | None = None
    createdAt: str


class RepositorySpecPage(BaseModel):
    items: List[RepositorySpecRecord]
    limit: int
    nextCursor: str | None = None


class RepositorySpecUpdateRequest(BaseModel):
    importEnabled: bool | None = None
    autoImportEnabled: bool | None = None


class RepositorySpecBulkUpdateRequest(BaseModel):
    fileIds: List[str] = Field(min_length=1, max_length=500, validation_alias="file_ids")
    importEnabled: bool | None = None
    autoImportEnabled: bool | None = None


class RepositorySpecBulkUpdateResponse(BaseModel):
    updatedCount: int
    items: List[RepositorySpecRecord]


class RepositorySpecImportNowRequest(BaseModel):
    branch: str | None = None
    force: bool = False


class RepositorySpecImportNowResponse(BaseModel):
    importJobId: str


class RepositorySpecMappingResolveRequest(BaseModel):
    decision: Literal["map_existing", "create_new", "defer"]
    projectSlug: str | None = None
    versionStrategy: str | None = None
    branch: str | None = None


class RepositorySpecLintSummary(BaseModel):
    errors: int = 0
    warnings: int = 0
    info: int = 0
    sourceImportJobId: str | None = None
    derivedFrom: Literal["none", "import_job", "import_job_change_report"] = "none"


class RepositorySpecImportSummary(BaseModel):
    id: str
    state: ImportJobStatus
    sourceKind: RepositoryImportJobSourceKind
    operation: ImportJobOperation
    branch: str
    createdAt: str
    conflictCount: int
    targetVersionId: str | None = None
    targetProjectSlug: str | None = None
    changeReportId: str | None = None
    lintSummary: RepositorySpecLintSummary


class RepositorySpecDetailResponse(BaseModel):
    spec: RepositorySpecRecord
    branch: str
    path: str
    fullName: str
    provider: Literal["github"]
    providerWebUrl: str | None = None
    providerRawUrl: str | None = None
    recentImports: List[RepositorySpecImportSummary]
    lintSummary: RepositorySpecLintSummary


class RepositorySpecContentResponse(BaseModel):
    fileId: str
    repositoryId: str
    branch: str
    path: str
    format: str | None = None
    encoding: Literal["utf-8", "base64"]
    content: str | None = None
    sizeBytes: int | None = None
    truncated: bool = False
    tooLargeForPreview: bool = False
    maxInlineBytes: int = MAX_INLINE_PREVIEW_BYTES
    contentChecksum: str | None = None
    providerRawUrl: str | None = None
    fetchedAt: str


class RepositoryScanReportListItem(BaseModel):
    repositoryId: str
    fullName: str
    provider: str
    owner: str
    name: str
    branchCount: int
    lastScanAt: str | None
    lastScanId: str | None
    lastReportId: str | None
    totals: Dict[str, Any] | None
    attentionScore: int
    stale: bool


class RepositoryScanReportListResponse(BaseModel):
    items: List[RepositoryScanReportListItem]
    total: int
    page: int
    pageSize: int


class RepositoryPerRepoScanReportListItem(BaseModel):
    id: str
    scanId: str
    generatedAt: str
    attentionScore: int
    totals: Dict[str, Any]


class RepositoryPerRepoScanReportListResponse(BaseModel):
    items: List[RepositoryPerRepoScanReportListItem]
    total: int


class RepositoryScanReportMetadata(BaseModel):
    """Snapshot metadata for the underlying repository_scan row."""

    commitSha: str
    trigger: str
    startedAt: str
    finishedAt: str | None
    status: str


class RepositoryScanReportCompareToPrevious(BaseModel):
    otherReportId: str
    totalsDelta: Dict[str, int]
    filePathsAdded: int
    filePathsRemoved: int
    filePathsInBoth: int


class RepositoryScanReportDetailResponse(BaseModel):
    id: str
    scanId: str
    repositoryId: str
    generatedAt: str
    attentionScore: int
    totals: Dict[str, Any]
    payload: List[Dict[str, Any]]
    errors: List[Dict[str, Any]]
    scan: RepositoryScanReportMetadata | None
    previousReportId: str | None
    compareToPrevious: RepositoryScanReportCompareToPrevious | None


class RepositoryScanReportPairTotals(BaseModel):
    id: str
    generatedAt: str
    scanId: str
    totals: Dict[str, Any]


class RepositoryScanReportDiffResponse(BaseModel):
    left: RepositoryScanReportPairTotals
    right: RepositoryScanReportPairTotals
    totalsDelta: Dict[str, int]
    filePathsOnlyInLeft: List[str]
    filePathsOnlyInRight: List[str]
    filePathsInBoth: int


class RepositoryResolvedProjectRecord(BaseModel):
    id: str
    tenantId: str
    slug: str
    name: str
    createdAt: str
    origin: Literal["manifest_auto", "manual", "mapped"] = "manual"
    createdFromRepositoryId: str | None = None
    defaultVersionStrategy: str | None = None


class RepositoryResolvedVersionRecord(BaseModel):
    id: str
    tenantId: str
    projectSlug: str
    commitSha: str
    versionId: str
    metadata: Dict[str, Any]
    createdAt: str


_REPO_STORE: Dict[str, Dict[str, RepositoryRecord]] = {}
_REPO_BRANCH_STORE: Dict[str, List[RepositoryBranchRecord]] = {}
_REPO_SCAN_STORE: Dict[str, List[RepositoryScanTimelineEntry]] = {}
_REPO_FILE_STORE: Dict[str, List[Dict[str, Any]]] = {}
_REPO_SCAN_HISTORY_STORE: Dict[str, List[RepositoryScanRecord]] = {}
_REPO_SCAN_FILE_HISTORY_STORE: Dict[str, List[RepositoryFileRecord]] = {}
_REPO_CREDENTIAL_REF_STORE: Dict[str, List[Dict[str, Any]]] = {}
_REPO_IMPORT_JOB_STORE: Dict[str, List[RepositoryImportJobRecord]] = {}
_REPO_CHANGE_REPORT_STORE: Dict[str, List[RepositorySyncChangeReportRecord]] = {}
_REPO_AUDIT_STORE: List[Dict[str, Any]] = []
_REPO_IMPORT_POLICY_STORE: Dict[str, Dict[str, bool]] = {}
_REPO_PROJECT_STORE: Dict[str, Dict[str, RepositoryResolvedProjectRecord]] = {}
_REPO_VERSION_STORE: Dict[str, Dict[str, Dict[str, RepositoryResolvedVersionRecord]]] = {}
# (repository_id, file_id, branch) -> (import_job_id, monotonic_timestamp) for 30s idempotency (REPO-9.5)
_REPO_IMPORT_NOW_IDEMPOTENCY: Dict[Tuple[str, str, str], Tuple[str, float]] = {}
# (repository_id, file_id) -> raw bytes used by the spec-detail content
# endpoint (REPO-9.6). Tests seed entries here via
# ``_seed_repository_file_content_for_tests`` so unit tests don't need to
# stub the GitHub Contents API; production path falls back to the live
# provider fetch when no entry is present.
_REPO_FILE_CONTENT_STORE: Dict[Tuple[str, str], bytes] = {}
# Latest materialized scan reports (REPO-10.1 / REPO-12.4). One row is appended
# per completed or failed scan; list views read the latest per repository.
_REPO_SCAN_REPORT_STORE: Dict[str, List[Dict[str, Any]]] = {}
# Per-tenant roll-up of corpus metrics for REPO-10.3 / #2949, refreshed on scan
# report append, repository register, and repository delete.
_REPO_CORPUS_ROLLUP: Dict[str, Dict[str, Any]] = {}
# Per-repo snapshot of the latest scan report totals, updated in _append_scan_report_row
# (under _STORE_LOCK). Used by _refresh_repository_corpus_rollup_unsafe to avoid
# scanning the full scan-report list on every rollup, reducing lock hold time.
_REPO_LATEST_REPORT_TOTALS: Dict[str, Dict[str, Any]] = {}
# REPO-11.1 / #2941: last pause was from auto-failure (vs user pause); in-memory + DB rollup.
_REPO_AUTO_PAUSED: Set[str] = set()
_REPO_ATTENTION: Dict[str, Dict[str, Any]] = {}
_STORE_LOCK = Lock()
_SYSTEM_ACTOR_ID = "00000000-0000-0000-0000-000000000000"
# Per-repository serialization for scan dispatch (REPO-12.1); parallels PG advisory
# lock on repository.id within a single Python process only. Keep a bounded registry
# so long-running processes do not accumulate one Lock per historical repository_id.
_MAX_REPO_DISPATCH_ADVISORY_LOCKS = 1024
_REPO_DISPATCH_ADVISORY_LOCKS: Dict[str, Tuple[Lock, float]] = {}
_DISPATCH_ADVISORY_REGISTRY_LOCK = Lock()


def _prune_repository_dispatch_advisory_locks_locked(
    active_repository_id: Optional[str] = None,
) -> None:
    """Remove oldest unlocked entries when registry exceeds the cap.

    Must be called with *_DISPATCH_ADVISORY_REGISTRY_LOCK* already held.
    *active_repository_id* is never evicted even if it is the oldest entry.
    """
    if len(_REPO_DISPATCH_ADVISORY_LOCKS) <= _MAX_REPO_DISPATCH_ADVISORY_LOCKS:
        return

    for candidate_repository_id, (candidate_lock, _) in sorted(
        _REPO_DISPATCH_ADVISORY_LOCKS.items(),
        key=lambda item: item[1][1],
    ):
        if len(_REPO_DISPATCH_ADVISORY_LOCKS) <= _MAX_REPO_DISPATCH_ADVISORY_LOCKS:
            break
        if candidate_repository_id == active_repository_id:
            continue
        if candidate_lock.locked():
            continue
        _REPO_DISPATCH_ADVISORY_LOCKS.pop(candidate_repository_id, None)


def _repository_dispatch_advisory_lock(repository_id: str) -> Lock:
    with _DISPATCH_ADVISORY_REGISTRY_LOCK:
        now = time.monotonic()
        existing_entry = _REPO_DISPATCH_ADVISORY_LOCKS.get(repository_id)
        if existing_entry is None:
            existing = Lock()
        else:
            existing, _ = existing_entry
        _REPO_DISPATCH_ADVISORY_LOCKS[repository_id] = (existing, now)
        _prune_repository_dispatch_advisory_locks_locked(repository_id)
        return existing


RepositoryAuditEvent = Literal[
    "repository.registered",
    "repository.scanned",
    "repository.scan.skipped_checksum",
    "repository.spec.selection_changed",
    "repository.sync_committed",
    "repository.sync_pending_review",
    "repository.sync_failed",
    "repository.removed",
    "repository.archived",
    "repository.unarchived",
    "repository.paused",
    "repository.auto_paused",
    "repository.token_resolved",
    "repository.polled",
    "repository.spec.import_now_triggered",
    "repository.auto_imported",
    "repository.spec.mapping_required",
    "repository.spec.mapping_resolved",
]

_DEFAULT_SCAN_PAGE_SIZE = 50
_MAX_SCAN_PAGE_SIZE = 200
_CONTENT_CHECKSUM_ALGO = "sha256"
_CONTENT_CHECKSUM_SHORT_LEN = 12
_SLUG_SANITIZER = re.compile(r"[^a-z0-9]+")
_VERSION_SHA_SANITIZER = re.compile(r"[^a-z0-9]+")
_REPOSITORY_SCOPE_READ = "repository.read"
_REPOSITORY_SCOPE_WRITE = "repository.write"
_REPOSITORY_SELECTION_ERROR_CODE = "SELECTION_INVARIANT_VIOLATION"
_MANIFEST_PROJECT_AUTO_CREATE_FLAG_KEYS = (
    "repoManifestProjectAutoCreate",
    "repo_manifest_project_auto_create",
)

_IMPORT_WITH_PROVENANCE_KINDS: frozenset[str] = frozenset({"repository_auto_import", "repository_sync"})


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


def _find_tenant_id_for_repository(repository_id: str) -> str:
    for tenant_id, repositories in _REPO_STORE.items():
        if repository_id in repositories:
            return tenant_id
    raise ValueError(f"Repository not found: {repository_id}")


def _to_sort_key(created_at: str, row_id: str) -> Tuple[datetime, str]:
    parsed = _parse_iso8601(created_at, "createdAt")
    if parsed is None:
        raise HTTPException(status_code=500, detail="scan row missing createdAt")
    return parsed, row_id


def _empty_scan_diff_summary() -> Dict[str, int]:
    return {"added": 0, "modified": 0, "removed": 0, "unchanged": 0, "skipped_unchanged_by_checksum": 0}


def _scan_force_enabled(scan: RepositoryScanRecord) -> bool:
    for event in scan.eventLog:
        if not isinstance(event, dict):
            continue
        if event.get("force") is True:
            return True
    return False


def _normalize_content_checksum(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    normalized = raw.strip().lower()
    if len(normalized) != 64:
        return None
    if not all(ch in "0123456789abcdef" for ch in normalized):
        return None
    return normalized


def _normalize_content_algo(raw: Any, *, has_checksum: bool) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    if has_checksum:
        return _CONTENT_CHECKSUM_ALGO
    return None


def _short_checksum(checksum: str | None, length: int = _CONTENT_CHECKSUM_SHORT_LEN) -> str | None:
    if not checksum:
        return None
    normalized = checksum.strip().lower()
    if not normalized:
        return None
    return normalized[:length]


def _build_hashed_event_log_entries(files: Sequence[RepositoryFileRecord], *, at: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for file_row in files:
        if file_row.status == "removed":
            continue
        short_checksum = _short_checksum(file_row.contentChecksum)
        if short_checksum is None:
            continue
        rows.append(
            {
                "type": "repository.scan.hashed",
                "at": at,
                "path": file_row.path,
                "content_algo": file_row.contentAlgo or _CONTENT_CHECKSUM_ALGO,
                "content_checksum_short": short_checksum,
            }
        )
    return rows


def _reuse_checksum_from_previous_scan(current: RepositoryFileRecord, previous: RepositoryFileRecord) -> RepositoryFileRecord:
    if current.contentChecksum:
        return current
    if not current.blobSha or current.blobSha != previous.blobSha:
        return current
    if not previous.contentChecksum:
        return current
    return current.model_copy(
        update={
            "contentAlgo": previous.contentAlgo or _CONTENT_CHECKSUM_ALGO,
            "contentChecksum": previous.contentChecksum,
        }
    )


def _first_duplicate(items: List[str]) -> Optional[str]:
    """Return the first duplicate value in *items*, or ``None`` if all are unique."""
    seen: set[str] = set()
    for item in items:
        if item in seen:
            return item
        seen.add(item)
    return None


def _classify_scan_files_against_previous(
    *,
    repository_id: str,
    scan_id: str,
    created_at: str,
    current_files: Sequence[RepositoryFileRecord],
    previous_files: Sequence[RepositoryFileRecord],
) -> Tuple[List[RepositoryFileRecord], Dict[str, int]]:
    summary = _empty_scan_diff_summary()

    previous_filtered = [
        row for row in previous_files
        if row.repositoryId == repository_id and row.status != "removed"
    ]
    previous_paths = [row.path for row in previous_filtered]
    previous_dup = _first_duplicate(previous_paths)
    if previous_dup is not None:
        raise ValueError(f"Duplicate path in previous scan files: {previous_dup!r}")
    previous_by_path = {row.path: row for row in previous_filtered}

    current_filtered = [
        row for row in current_files
        if row.repositoryId == repository_id
    ]
    current_paths = [row.path for row in current_filtered]
    current_dup = _first_duplicate(current_paths)
    if current_dup is not None:
        raise ValueError(f"Duplicate path in current scan files: {current_dup!r}")
    current_by_path = {row.path: row for row in current_filtered}
    rows: List[RepositoryFileRecord] = []

    for path in sorted(current_by_path):
        current = current_by_path[path]
        previous = previous_by_path.get(path)
        if previous is not None:
            current = current.model_copy(
                update={
                    "importEnabled": previous.importEnabled,
                    "autoImportEnabled": previous.autoImportEnabled if previous.importEnabled else False,
                }
            )
        if previous is None:
            next_status: RepositoryFileStatus = "new"
            summary["added"] += 1
        elif current.blobSha and current.blobSha == previous.blobSha:
            next_status = "unchanged"
            summary["unchanged"] += 1
            current = _reuse_checksum_from_previous_scan(current, previous)
        else:
            next_status = "modified"
            summary["modified"] += 1

        rows.append(
            current.model_copy(
                update={
                    "scanId": scan_id,
                    "status": next_status,
                    "createdAt": created_at,
                }
            )
        )

    removed_paths = sorted(set(previous_by_path) - set(current_by_path))
    for path in removed_paths:
        previous = previous_by_path[path]
        summary["removed"] += 1
        rows.append(
            previous.model_copy(
                update={
                    "id": str(uuid4()),
                    "scanId": scan_id,
                    "status": "removed",
                    "createdAt": created_at,
                }
            )
        )

    return rows, summary


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
        diffSummary=_empty_scan_diff_summary(),
        createdAt=now,
    )


def _github_api_get_json(url: str, access_token: str) -> Any:
    request = urllib_request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        with urllib_request.urlopen(request, timeout=20) as response:
            payload = response.read()
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API error {exc.code}: {detail[:500]}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"GitHub API unavailable: {exc.reason}") from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("GitHub API returned invalid JSON payload") from exc


def _load_linked_account_access_token(linked_account_id: str | None) -> str:
    if not linked_account_id:
        raise RuntimeError("Repository is missing linked account reference")
    rows = db.execute_query(
        "SELECT access_token FROM odb.external_auth_providers WHERE id = %s::uuid LIMIT 1",
        (linked_account_id,),
    )
    if not rows:
        raise RuntimeError("Linked account not found")
    token = rows[0].get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("Linked account has no usable access token")
    return token.strip()


def _guess_scan_format(path: str) -> str | None:
    lower = path.lower()
    if lower.endswith((".yaml", ".yml", ".json")):
        if "asyncapi" in lower:
            return "asyncapi_2"
        if "openapi" in lower or "swagger" in lower:
            return "openapi_3_1"
        return "json_schema"
    if lower.endswith(".graphql") or lower.endswith(".gql"):
        return "graphql_sdl"
    if lower.endswith(".proto"):
        return "protobuf"
    if lower.endswith(".avsc"):
        return "avro"
    return None


def _fetch_github_scan_inputs(repository: RepositoryRecord, branch: str) -> Tuple[str, List[Dict[str, Any]]]:
    access_token = _load_linked_account_access_token(repository.linkedAccountId)
    owner = urllib_parse.quote(repository.owner, safe="")
    name = urllib_parse.quote(repository.name, safe="")
    branch_ref = urllib_parse.quote(branch, safe="")
    commit_payload = _github_api_get_json(
        f"https://api.github.com/repos/{owner}/{name}/commits/{branch_ref}",
        access_token,
    )
    if not isinstance(commit_payload, dict) or not isinstance(commit_payload.get("sha"), str):
        raise RuntimeError("Could not resolve branch head commit SHA")
    commit_sha = str(commit_payload["sha"])
    tree_payload = _github_api_get_json(
        f"https://api.github.com/repos/{owner}/{name}/git/trees/{commit_sha}?recursive=1",
        access_token,
    )
    raw_tree = tree_payload.get("tree") if isinstance(tree_payload, dict) else None
    if not isinstance(raw_tree, list):
        raise RuntimeError("Could not list repository tree")
    file_rows: List[Dict[str, Any]] = []
    for entry in raw_tree:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "blob":
            continue
        path = entry.get("path")
        if not isinstance(path, str) or not path.strip():
            continue
        file_rows.append(
            {
                "path": path,
                "blobSha": entry.get("sha") if isinstance(entry.get("sha"), str) else None,
                "contentAlgo": None,
                "contentChecksum": None,
                "sizeBytes": entry.get("size") if isinstance(entry.get("size"), int) else None,
            }
        )
    return commit_sha, file_rows


def _build_scan_file_rows(
    *,
    repository: RepositoryRecord,
    scan_id: str,
    discovered_files: Sequence[Dict[str, Any]],
    created_at: str,
) -> List[RepositoryFileRecord]:
    manifest_outcome = parse_repo_manifest(repository.manifest)
    manifest_specs_by_path: Dict[str, Any] = {}
    if manifest_outcome.manifest is not None:
        manifest_specs_by_path = {spec.path: spec for spec in manifest_outcome.manifest.specs}

    rows: List[RepositoryFileRecord] = []
    for item in discovered_files:
        path = item["path"]
        manifest_spec = manifest_specs_by_path.get(path)
        mapping = resolve_repository_file_mapping(path, manifest_spec)
        import_enabled = initial_import_enabled_for_path(
            manifest=manifest_outcome.manifest,
            spec=manifest_spec,
        )
        auto_import_enabled = initial_auto_import_enabled_for_path(
            manifest=manifest_outcome.manifest,
            spec=manifest_spec,
        )
        settings_json = dict(mapping.settings_json or {})
        content_checksum = _normalize_content_checksum(item.get("contentChecksum"))
        content_algo = _normalize_content_algo(item.get("contentAlgo"), has_checksum=content_checksum is not None)
        if mapping.on_breaking_change is not None:
            settings_json["onBreakingChange"] = mapping.on_breaking_change
        rows.append(
            RepositoryFileRecord(
                id=str(uuid4()),
                repositoryId=repository.id,
                scanId=scan_id,
                path=path,
                blobSha=item.get("blobSha"),
                contentChecksum=content_checksum,
                contentAlgo=content_algo,
                sizeBytes=item.get("sizeBytes"),
                format=_guess_scan_format(path),
                confidence=0.9 if _guess_scan_format(path) else 0.2,
                discriminator=None,
                tracked=mapping.tracked,
                importEnabled=import_enabled,
                autoImportEnabled=auto_import_enabled,
                projectSlug=mapping.project_slug if mapping.tracked else None,
                versionStrategy=mapping.version_strategy,
                settingsJson=settings_json or None,
                promote=mapping.promote,
                status="new",
                qualityScore=None,
                createdAt=created_at,
            )
        )
    return rows


def _process_single_pending_repository_scan(
    tenant_id: str,
    repository_id: str,
    scan_id: str,
) -> Tuple[bool, List[Dict[str, Any]]]:
    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        history = _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
        if repository is None or not history:
            return False, []
        scan = next((row for row in history if row.id == scan_id and row.status == "pending"), None)
        if scan is None:
            return False, []
        branch = scan.branch

    try:
        commit_sha, discovered_files = _fetch_github_scan_inputs(repository, branch)
    except Exception as exc:
        now = _utc_now_iso()
        with _STORE_LOCK:
            repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
            history = _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
            if repository is None or not history:
                return False, []
            scan_index = next((idx for idx, row in enumerate(history) if row.id == scan_id and row.status == "pending"), None)
            if scan_index is None:
                return False, []
            failed_scan = history[scan_index].model_copy(
                update={
                    "status": "failed",
                    "finishedAt": now,
                    "durationMs": 0,
                    "eventLog": [*history[scan_index].eventLog, {"type": "repository.scan.failed", "at": now}],
                    "errorDetail": str(exc),
                }
            )
            history[scan_index] = failed_scan
            timeline = _REPO_SCAN_STORE.setdefault(repository_id, repository.timeline)
            timeline.insert(
                0,
                RepositoryScanTimelineEntry(
                    id=str(uuid4()),
                    type="scan",
                    status="failed",
                    message="Scan failed.",
                    createdAt=now,
                ),
            )
            repository.timeline = list(timeline)
            if repository.status not in {"archived", "paused"}:
                repository.status = "error"
            repository.updatedAt = now
            audit = _append_audit_row(
                tenant_id,
                repository_id,
                "repository.scanned",
                actor_id=_SYSTEM_ACTOR_ID,
                outcome="failure",
                detail={
                    "scanId": failed_scan.id,
                    "branch": failed_scan.branch,
                    "trigger": failed_scan.trigger,
                    "status": failed_scan.status,
                    "error": str(exc),
                },
            )
            _append_scan_report_row(
                repository_id,
                failed_scan.id,
                generated_at=now,
                classified_files=None,
                scan_failed=True,
                scan=failed_scan,
            )
        return True, [audit]

    now = _utc_now_iso()
    # Phase 3a: classify files under lock (read-heavy, no DB calls).
    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        history = _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
        if repository is None or not history:
            return False, []
        scan_index = next((idx for idx, row in enumerate(history) if row.id == scan_id and row.status == "pending"), None)
        if scan_index is None:
            return False, []

        current_files = _build_scan_file_rows(
            repository=repository,
            scan_id=scan_id,
            discovered_files=discovered_files,
            created_at=now,
        )
        previous_completed_scan = next(
            (
                row
                for idx, row in enumerate(history)
                if idx != scan_index and row.branch == branch and row.status == "complete"
            ),
            None,
        )
        previous_files: Sequence[RepositoryFileRecord] = []
        if previous_completed_scan is not None:
            previous_files = _REPO_SCAN_FILE_HISTORY_STORE.get(previous_completed_scan.id, [])

        classified_files, diff_summary = _classify_scan_files_against_previous(
            repository_id=repository_id,
            scan_id=scan_id,
            created_at=now,
            current_files=current_files,
            previous_files=previous_files,
        )
        force = _scan_force_enabled(history[scan_index])

    # Phase 3b: precompute checksums outside lock (blocking DB lookups).
    precomputed_checksums = _precompute_latest_checksums(
        tenant_id=tenant_id,
        repository_id=repository_id,
        scan_files=classified_files,
        force=force,
    )

    # Phase 4: dispatch import jobs and commit scan state under lock.
    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        history = _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
        if repository is None or not history:
            return False, []
        scan_index = next((idx for idx, row in enumerate(history) if row.id == scan_id and row.status == "pending"), None)
        if scan_index is None:
            return False, []

        _REPO_SCAN_FILE_HISTORY_STORE[scan_id] = classified_files

        pending_audit_rows = _dispatch_import_jobs_for_scan(
            tenant_id=tenant_id,
            repository_id=repository_id,
            scan_id=scan_id,
            branch=branch,
            commit_sha=commit_sha,
            scan_files=classified_files,
            actor_id=_SYSTEM_ACTOR_ID,
            force=force,
            diff_summary=diff_summary,
            precomputed_checksums=precomputed_checksums,
        )

        completed_scan = history[scan_index].model_copy(
            update={
                "commitSha": commit_sha,
                "status": "complete",
                "finishedAt": now,
                "durationMs": 0,
                "filesSeen": len(discovered_files),
                "filesClassified": len(classified_files),
                "filesUnknown": sum(1 for row in classified_files if not row.format),
                "filesFailed": 0,
                "eventLog": [
                    *history[scan_index].eventLog,
                    *_build_hashed_event_log_entries(classified_files, at=now),
                    {"type": "repository.scan.complete", "at": now},
                ],
                "diffSummary": diff_summary,
            }
        )
        history[scan_index] = completed_scan
        timeline = _REPO_SCAN_STORE.setdefault(repository_id, repository.timeline)
        timeline.insert(
            0,
            RepositoryScanTimelineEntry(
                id=str(uuid4()),
                type="scan",
                status="completed",
                message="Scan completed.",
                createdAt=now,
            ),
        )
        repository.timeline = list(timeline)
        if repository.status not in {"archived", "paused"}:
            repository.status = "healthy"
        repository.updatedAt = now
        pending_audit_rows.append(
            _append_audit_row(
                tenant_id,
                repository_id,
                "repository.scanned",
                actor_id=_SYSTEM_ACTOR_ID,
                detail={
                    "scanId": completed_scan.id,
                    "branch": completed_scan.branch,
                    "trigger": completed_scan.trigger,
                    "status": completed_scan.status,
                    "diffSummary": completed_scan.diffSummary,
                },
            )
        )
        _append_scan_report_row(
            repository_id,
            completed_scan.id,
            generated_at=now,
            classified_files=classified_files,
            scan_failed=False,
            scan=completed_scan,
        )
    return True, pending_audit_rows


def process_pending_repository_scans(max_scans: int = 25) -> int:
    """Process queued repository scans and persist scan results."""
    if max_scans <= 0:
        return 0
    with _STORE_LOCK:
        pending_targets: List[Tuple[str, str, str]] = []
        for tenant_id, repositories in _REPO_STORE.items():
            for repository in repositories.values():
                history = _REPO_SCAN_HISTORY_STORE.get(repository.id, [])
                for scan in history:
                    if scan.status == "pending":
                        pending_targets.append((tenant_id, repository.id, scan.id))
                        if len(pending_targets) >= max_scans:
                            break
                if len(pending_targets) >= max_scans:
                    break
            if len(pending_targets) >= max_scans:
                break

    processed = 0
    pending_audit_rows: List[Dict[str, Any]] = []
    for tenant_id, repository_id, scan_id in pending_targets:
        handled, rows = _process_single_pending_repository_scan(tenant_id, repository_id, scan_id)
        if handled:
            processed += 1
            pending_audit_rows.extend(rows)
            _recompute_repository_attention(tenant_id, repository_id)

    for audit_row in pending_audit_rows:
        _persist_audit_row(audit_row)
    return processed


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
        diffSummary=_empty_scan_diff_summary(),
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


def _get_repository_last_scan(repository_id: str) -> Optional[RepositoryScanRecord]:
    """Most recent scan record for the repository, or None when no history exists."""
    with _STORE_LOCK:
        history = list(_REPO_SCAN_HISTORY_STORE.get(repository_id, []))
    if not history:
        return None
    return max(
        history,
        key=lambda scan: scan.createdAt or scan.startedAt or scan.finishedAt or "",
    )


def _get_repository_last_scan_at(repository_id: str) -> Optional[str]:
    last_scan = _get_repository_last_scan(repository_id)
    if last_scan is None:
        return None
    return last_scan.createdAt or last_scan.startedAt or last_scan.finishedAt


def _get_last_complete_scan_in_memory(repository_id: str) -> Optional[RepositoryScanRecord]:
    with _STORE_LOCK:
        history = list(_REPO_SCAN_HISTORY_STORE.get(repository_id, []))
    if not history:
        return None
    complete = [s for s in history if s.status == "complete"]
    if not complete:
        return None
    return max(complete, key=lambda s: (s.finishedAt or s.startedAt or s.createdAt or ""))


def _sync_stale_mismatch_markers(now_iso: str, files: Sequence[RepositoryFileRecord]) -> None:
    """Update stale_mismatch_at for the ready-to-promote (import on, auto-import off) bucket. Call under lock."""
    for f in files:
        if not f.importEnabled or f.autoImportEnabled:
            f.staleMismatchAt = None
            continue
        c = _normalize_content_checksum(f.contentChecksum)
        li = _normalize_content_checksum(f.lastImportedContentChecksum)
        if c is None or li is None or c == li:
            f.staleMismatchAt = None
            continue
        if f.staleMismatchAt is None:
            f.staleMismatchAt = now_iso


def _attention_compute_input_for_repository(
    tenant_id: str, repository_id: str,
) -> Optional[Tuple[datetime, str, AttentionComputeInput, Optional[Dict[str, Any]]]]:
    """
    Build AttentionComputeInput plus timestamps / prior rollup row.
    Returns None when the repository is not registered for this tenant.
    """
    now_iso = _utc_now_iso()
    now_dt = datetime.now(timezone.utc)
    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        if repository is None:
            return None
        repo_status = repository.status
        is_auto = repository_id in _REPO_AUTO_PAUSED
        last = _get_last_complete_scan_in_memory(repository_id)
        files: List[RepositoryFileRecord] = list(_REPO_SCAN_FILE_HISTORY_STORE.get(last.id, [])) if last else []
        if files:
            _sync_stale_mismatch_markers(now_iso, files)
        j_by: Dict[str, RepositoryImportJobRecord] = {}
        if last is not None:
            j_by = _latest_import_jobs_by_path(repository_id, last.branch)
        vfiles: List[AttentionFileInput] = []
        for f in files:
            j = j_by.get(f.path)
            jst = j.state if j is not None else None
            csum = _normalize_content_checksum(f.contentChecksum)
            lis = _normalize_content_checksum(f.lastImportedContentChecksum)
            vfiles.append(
                AttentionFileInput(
                    path=f.path,
                    status=f.status,
                    import_enabled=bool(f.importEnabled),
                    auto_import_enabled=bool(f.autoImportEnabled),
                    content_checksum=csum,
                    last_imported_checksum=lis,
                    stale_mismatch_at=f.staleMismatchAt,
                    last_import_job_state=jst,
                )
            )
        prev = _REPO_ATTENTION.get(repository_id)
    if "PYTEST_CURRENT_TEST" in os.environ:
        _max_cf, _any_rev = 0, False
    else:
        try:
            _max_cf = int(db.max_consecutive_failures_for_repository(repository_id))
        except Exception:
            _max_cf = 0
        try:
            _any_rev = bool(db.any_repository_credential_revoked(repository_id))
        except Exception:
            _any_rev = False
    inp = AttentionComputeInput(
        now=now_dt,
        repository_status=repo_status,
        is_auto_paused=is_auto,
        last_scan_files=vfiles,
        max_consecutive_failures=_max_cf,
        any_credential_revoked=_any_rev,
    )
    return now_dt, now_iso, inp, prev


def _recompute_repository_attention(tenant_id: str, repository_id: str) -> None:
    """REPO-11.1 / #2941: recompute in-memory and optional PostgreSQL row, then NOTIFY."""
    ctx = _attention_compute_input_for_repository(tenant_id, repository_id)
    if ctx is None:
        return
    _now_dt, now_iso, inp, prev = ctx
    rsn, ocnt, score, _ = compute_attention_detail(inp)
    reasons_list = sorted(rsn)
    p_reasons: Optional[List[str]] = None
    p_oc: Optional[int] = None
    p_sc: Optional[int] = None
    p_lca: Optional[str] = None
    if prev and isinstance(prev.get("reasons"), list):
        p_reasons = [str(x) for x in prev.get("reasons", [])]  # type: ignore[assignment]
    if prev is not None and isinstance(prev.get("openCount"), (int, float, str)):
        p_oc = int(prev.get("openCount", -1) or 0)  # type: ignore[assignment, arg-type]
    if prev is not None and isinstance(prev.get("attentionScore"), (int, float, str)):
        p_sc = int(prev.get("attentionScore", -1) or 0)  # type: ignore[assignment, arg-type]
    p_lca = str(prev.get("lastChangeAt")) if prev and prev.get("lastChangeAt") else None  # type: ignore[union-attr]
    unchanged = (
        prev is not None
        and p_reasons == reasons_list
        and p_oc == ocnt
        and p_sc == score
    )
    last_change_at = p_lca if (unchanged and p_lca) else now_iso
    row: Dict[str, Any] = {
        "repositoryId": repository_id,
        "tenantId": tenant_id,
        "computedAt": now_iso,
        "reasons": reasons_list,
        "openCount": ocnt,
        "attentionScore": score,
        "lastChangeAt": last_change_at,
    }
    with _STORE_LOCK:
        _REPO_ATTENTION[repository_id] = row
    if "PYTEST_CURRENT_TEST" not in os.environ and not unchanged:
        try:
            wrote = db.upsert_repository_attention(
                repository_id=repository_id,
                computed_at=now_iso,
                reasons=reasons_list,
                open_count=ocnt,
                attention_score=score,
                last_change_at=last_change_at,
            )
            if wrote:
                db.notify_repository_attention(repository_id)
        except Exception as e:
            _logger.debug("repository attention persist skipped: %s", e)


def recompute_all_repositories_attention() -> int:
    """Hourly safety sweep: reconcile every in-memory repository (O(repos) total). Returns repo count."""
    targets: List[Tuple[str, str]] = []
    with _STORE_LOCK:
        for tid, repos in _REPO_STORE.items():
            for rid in repos:
                targets.append((tid, rid))
    for tid, rid in targets:
        _recompute_repository_attention(tid, rid)
    return len(targets)


def _to_summary(repo: RepositoryRecord) -> Dict[str, Any]:
    timeline_created_at = [entry.createdAt for entry in repo.timeline if entry.createdAt]
    timeline_last_scan_at = max(timeline_created_at) if timeline_created_at else None
    last_scan = _get_repository_last_scan(repo.id)
    last_scan_at = (
        (last_scan.createdAt or last_scan.startedAt or last_scan.finishedAt)
        if last_scan
        else None
    ) or timeline_last_scan_at
    return {
        "id": repo.id,
        "provider": repo.provider,
        "owner": repo.owner,
        "name": repo.name,
        "fullName": repo.fullName,
        "status": repo.status,
        "branches": [b.branch for b in repo.branches],
        "lastScanAt": last_scan_at,
        "lastScanDurationMs": last_scan.durationMs if last_scan else None,
        "lastScanBranch": last_scan.branch if last_scan else None,
        "createdAt": repo.createdAt,
        "updatedAt": repo.updatedAt,
    }


def _count_committed_imports_for_scan(repository_id: str, scan_id: str) -> int:
    jobs = _REPO_IMPORT_JOB_STORE.get(repository_id, [])
    return sum(1 for job in jobs if job.scanId == scan_id and job.state == "committed")


def _build_scan_report_totals_json(
    repository_id: str,
    scan_id: str,
    classified_files: Sequence[RepositoryFileRecord],
    *,
    scan_failed: bool,
) -> Dict[str, int]:
    if scan_failed:
        return {
            "discovered": 0,
            "importable": 0,
            "imported": 0,
            "failing": 0,
            "parse_error": 0,
            "manifest_error": 0,
            "awaiting_selection": 0,
            "scanFailed": 1,
        }
    imported = _count_committed_imports_for_scan(repository_id, scan_id)
    importable = 0
    parse_error = 0
    manifest_error = 0
    awaiting = 0
    for f in classified_files:
        if not f.tracked:
            continue
        conf = f.confidence if f.confidence is not None else 0.0
        has_format = f.format is not None and (not isinstance(f.format, str) or bool(f.format.strip()))
        is_high_conf = conf >= 0.5 and has_format
        if f.status == "parse_error":
            parse_error += 1
        if f.status == "manifest_error":
            manifest_error += 1
        if is_high_conf and f.status not in ("parse_error", "manifest_error"):
            importable += 1
        if is_high_conf and f.status not in ("parse_error", "manifest_error") and not f.importEnabled:
            awaiting += 1
    failing = parse_error + manifest_error
    return {
        "discovered": len(classified_files),
        "importable": importable,
        "imported": imported,
        "failing": failing,
        "parse_error": parse_error,
        "manifest_error": manifest_error,
        "awaiting_selection": awaiting,
        "scanFailed": 0,
    }


def _scan_report_attention_score(
    totals: Dict[str, int], *, last_scan_at: str | None, now_ms: float | None = None
) -> int:
    """Derive 0–100 attention score: failures, awaiting selection, scan failure, and staleness (>7d)."""
    if now_ms is None:
        now_ms = time.time() * 1000.0
    failing = int(totals.get("failing", 0) or 0)
    awaiting = int(totals.get("awaiting_selection", 0) or 0)
    scan_failed = int(totals.get("scanFailed", 0) or 0)
    score = min(100, failing * 12 + awaiting * 6 + scan_failed * 25)
    if last_scan_at:
        parsed = _parse_iso8601(last_scan_at, "lastScanAt")
        if parsed is not None:
            days = (now_ms - parsed.timestamp() * 1000.0) / (24 * 60 * 60 * 1000.0)
            if days > 7:
                score = min(100, score + 15)
    return int(score)


def _file_record_to_report_payload(file_row: RepositoryFileRecord) -> Dict[str, Any]:
    return {
        "fileId": file_row.id,
        "path": file_row.path,
        "status": file_row.status,
        "format": file_row.format,
        "confidence": file_row.confidence,
        "importEnabled": file_row.importEnabled,
        "autoImportEnabled": file_row.autoImportEnabled,
        "tracked": file_row.tracked,
        "projectSlug": file_row.projectSlug,
        "versionStrategy": file_row.versionStrategy,
        "qualityScore": file_row.qualityScore,
        "discriminator": file_row.discriminator,
    }


def _build_report_errors(
    *,
    scan: RepositoryScanRecord | None,
    classified_files: Sequence[RepositoryFileRecord] | None,
    scan_failed: bool,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if scan_failed and scan is not None:
        out.append(
            {
                "kind": "scan",
                "path": None,
                "code": scan.errorCode,
                "message": "Scan failed",
                "errorDetail": scan.errorDetail,
            }
        )
    elif scan_failed and scan is None:
        out.append(
            {
                "kind": "scan",
                "path": None,
                "code": "scan_failed",
                "message": "Scan failed",
                "errorDetail": None,
            }
        )
    for f in sorted(classified_files or [], key=lambda r: (r.path or "").lower()):
        if f.status not in {"parse_error", "manifest_error"}:
            continue
        detail = (f.discriminator or "").strip() or None
        if f.status == "parse_error":
            title = "Parse error"
        else:
            title = "Manifest error"
        out.append(
            {
                "kind": "file",
                "path": f.path,
                "code": f.status,
                "message": detail or title,
                "errorDetail": detail,
            }
        )
    return out


def _build_payload_json(
    classified_files: Sequence[RepositoryFileRecord] | None,
) -> List[Dict[str, Any]]:
    if not classified_files:
        return []
    rows = list(classified_files)
    rows.sort(key=lambda r: (r.path or "").lower())
    return [_file_record_to_report_payload(f) for f in rows]


def _append_scan_report_row(
    repository_id: str,
    scan_id: str,
    *,
    generated_at: str,
    classified_files: Sequence[RepositoryFileRecord] | None,
    scan_failed: bool,
    scan: RepositoryScanRecord | None = None,
) -> None:
    raw_totals = _build_scan_report_totals_json(
        repository_id, scan_id, classified_files or [], scan_failed=scan_failed
    )
    t_int: Dict[str, int] = {k: int(v) for k, v in raw_totals.items()}
    attention = _scan_report_attention_score(t_int, last_scan_at=generated_at)
    errors_json = _build_report_errors(
        scan=scan,
        classified_files=classified_files,
        scan_failed=scan_failed,
    )
    row = {
        "id": str(uuid4()),
        "scanId": scan_id,
        "repositoryId": repository_id,
        "generatedAt": generated_at,
        "totalsJson": {
            "discovered": int(raw_totals.get("discovered", 0)),
            "importable": int(raw_totals.get("importable", 0)),
            "imported": int(raw_totals.get("imported", 0)),
            "failing": int(raw_totals.get("failing", 0)),
            "parseError": int(raw_totals.get("parse_error", 0)),
            "manifestError": int(raw_totals.get("manifest_error", 0)),
            "awaitingSelection": int(raw_totals.get("awaiting_selection", 0)),
            "scanFailed": bool(int(raw_totals.get("scanFailed", 0))),
        },
        "attentionScore": attention,
        "payloadJson": _build_payload_json(classified_files),
        "errorsJson": errors_json,
    }
    bucket = _REPO_SCAN_REPORT_STORE.setdefault(repository_id, [])
    bucket.append(row)
    if len(bucket) > 200:
        bucket[:] = bucket[-200:]
    _REPO_LATEST_REPORT_TOTALS[repository_id] = row.get("totalsJson") or {}
    try:
        _rollup_tid = _find_tenant_id_for_repository(repository_id)
    except ValueError:
        return
    _refresh_repository_corpus_rollup_unsafe(_rollup_tid)


def _refresh_repository_corpus_rollup_unsafe(tenant_id: str) -> Dict[str, Any]:
    """Recompute per-tenant corpus stats for the dashboard. Caller must hold _STORE_LOCK."""
    tenant_repos = list(_REPO_STORE.get(tenant_id, {}).values())
    repositories_tracked = len(tenant_repos)
    importable_specs = 0
    awaiting_selection = 0
    parse_errors = 0
    manifest_errors = 0
    for repo in tenant_repos:
        tj = _REPO_LATEST_REPORT_TOTALS.get(repo.id)
        if isinstance(tj, dict):
            importable_specs += int(tj.get("importable", 0) or 0)
            awaiting_selection += int(tj.get("awaitingSelection", 0) or 0)
            parse_errors += int(tj.get("parseError", 0) or 0)
            manifest_errors += int(tj.get("manifestError", 0) or 0)
    payload: Dict[str, Any] = {
        "repositoriesTracked": repositories_tracked,
        "importableSpecs": importable_specs,
        "awaitingSelection": awaiting_selection,
        "parseErrors": parse_errors,
        "manifestErrors": manifest_errors,
        "refreshedAt": _utc_now_iso(),
    }
    _REPO_CORPUS_ROLLUP[tenant_id] = payload
    return payload


def get_repository_corpus_rollup(tenant_id: str) -> Dict[str, Any]:
    """Return tenant corpus stats, computing and caching the roll-up on first use."""
    with _STORE_LOCK:
        if tenant_id in _REPO_CORPUS_ROLLUP:
            return dict(_REPO_CORPUS_ROLLUP[tenant_id])
        return dict(_refresh_repository_corpus_rollup_unsafe(tenant_id))


def _reports_for_repository_newest_first(repository_id: str) -> List[Dict[str, Any]]:
    with _STORE_LOCK:
        rlist = [r for r in _REPO_SCAN_REPORT_STORE.get(repository_id, []) if isinstance(r, dict)]
    return sorted(
        rlist,
        key=lambda r: (r.get("generatedAt", ""), r.get("id", "")),
        reverse=True,
    )


def _get_report_row_by_id(repository_id: str, report_id: str) -> Dict[str, Any] | None:
    with _STORE_LOCK:
        for row in _REPO_SCAN_REPORT_STORE.get(repository_id, []):
            if isinstance(row, dict) and str(row.get("id")) == report_id:
                return row
    return None


def _coerce_report_totals_for_delta(t: Dict[str, Any]) -> Dict[str, int]:
    if not t:
        return {
            "discovered": 0,
            "importable": 0,
            "imported": 0,
            "failing": 0,
            "parseError": 0,
            "manifestError": 0,
            "awaitingSelection": 0,
            "scanFailed": 0,
        }
    sf = 1 if bool(t.get("scanFailed")) else 0
    return {
        "discovered": int(t.get("discovered", 0) or 0),
        "importable": int(t.get("importable", 0) or 0),
        "imported": int(t.get("imported", 0) or 0),
        "failing": int(t.get("failing", 0) or 0),
        "parseError": int(t.get("parseError", 0) or 0),
        "manifestError": int(t.get("manifestError", 0) or 0),
        "awaitingSelection": int(t.get("awaitingSelection", 0) or 0),
        "scanFailed": sf,
    }


def _totals_delta_map(left: Dict[str, int], right: Dict[str, int]) -> Dict[str, int]:
    all_keys = sorted(set(left) | set(right))
    return {k: int(left.get(k, 0)) - int(right.get(k, 0)) for k in all_keys}


def _file_paths_in_payload_row(row: Dict[str, Any]) -> set[str]:
    pl = row.get("payloadJson")
    if not isinstance(pl, list):
        return set()
    return {str(x.get("path", "")) for x in pl if isinstance(x, dict) and x.get("path")}


def _scan_metadata_for_report(repository_id: str, scan_id: str) -> RepositoryScanReportMetadata | None:
    with _STORE_LOCK:
        history = _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
    for s in history:
        if s.id == scan_id:
            return RepositoryScanReportMetadata(
                commitSha=s.commitSha,
                trigger=s.trigger,
                startedAt=s.startedAt,
                finishedAt=s.finishedAt,
                status=s.status,
            )
    return None


def _build_compare_to_previous(
    repository_id: str, current: Dict[str, Any], ordered_newest_first: List[Dict[str, Any]]
) -> RepositoryScanReportCompareToPrevious | None:
    cur_id = str(current.get("id", ""))
    for idx, row in enumerate(ordered_newest_first):
        if str(row.get("id")) == cur_id and idx + 1 < len(ordered_newest_first):
            other = ordered_newest_first[idx + 1]
            t0 = _coerce_report_totals_for_delta(
                other.get("totalsJson") if isinstance(other.get("totalsJson"), dict) else {}
            )
            t1 = _coerce_report_totals_for_delta(
                current.get("totalsJson") if isinstance(current.get("totalsJson"), dict) else {}
            )
            delta = _totals_delta_map(t1, t0)
            p0 = _file_paths_in_payload_row(other)
            p1 = _file_paths_in_payload_row(current)
            return RepositoryScanReportCompareToPrevious(
                otherReportId=str(other.get("id")),
                totalsDelta=delta,
                filePathsAdded=len(p1 - p0),
                filePathsRemoved=len(p0 - p1),
                filePathsInBoth=len(p0 & p1),
            )
    return None


def _build_scan_report_detail(
    repository_id: str, row: Dict[str, Any], *, ordered: List[Dict[str, Any]]
) -> RepositoryScanReportDetailResponse:
    totals = row.get("totalsJson")
    if not isinstance(totals, dict):
        totals = {}
    pl = row.get("payloadJson")
    payload: List[Dict[str, Any]] = pl if isinstance(pl, list) else []
    er = row.get("errorsJson")
    errors = [dict(x) for x in er if isinstance(x, dict)] if isinstance(er, list) else []
    scan_id = str(row.get("scanId", ""))
    meta = _scan_metadata_for_report(repository_id, scan_id) if scan_id else None
    other = _build_compare_to_previous(repository_id, row, ordered)
    prev_id: str | None = str(other.otherReportId) if other is not None else None
    return RepositoryScanReportDetailResponse(
        id=str(row.get("id", "")),
        scanId=scan_id,
        repositoryId=str(row.get("repositoryId", "")),
        generatedAt=str(row.get("generatedAt", "")),
        attentionScore=int(row.get("attentionScore", 0) or 0),
        totals=dict(totals),
        payload=payload,
        errors=errors,
        scan=meta,
        previousReportId=prev_id,
        compareToPrevious=other,
    )


def _append_audit_row(
    tenant_id: str,
    repository_id: str,
    event_type: RepositoryAuditEvent,
    *,
    actor_id: str | None,
    detail: Dict[str, Any] | None = None,
    outcome: Literal["success", "failure"] = "success",
) -> Dict[str, Any]:
    """Append an audit row to the in-memory store and return it.

    This function is safe to call while holding ``_STORE_LOCK`` because it
    performs no I/O.  Pass the returned dict to :func:`_persist_audit_row`
    *after* releasing the lock to write the row to the database.
    """
    created_at = _utc_now_iso()
    normalized_actor_id = actor_id if actor_id else _SYSTEM_ACTOR_ID
    payload = dict(detail or {})
    row: Dict[str, Any] = {
        "id": str(uuid4()),
        "tenantId": tenant_id,
        "repositoryId": repository_id,
        "eventType": event_type,
        "actorId": normalized_actor_id,
        "detail": payload,
        "outcome": outcome,
        "createdAt": created_at,
    }
    _REPO_AUDIT_STORE.append(row)
    return row


def _persist_audit_row(row: Dict[str, Any]) -> None:
    """Persist a previously-built audit row to the database.

    Must be called **outside** ``_STORE_LOCK`` to avoid blocking other
    repository operations on slow DB connections.  All DB failures are
    swallowed so that audit persistence is always best-effort.
    """
    try:
        # System-originated repository events do not have a backing user row.
        # Persist them with a NULL actor_id to satisfy workflow_audit FK rules.
        actor_id = row.get("actorId")
        persisted_actor_id = None if actor_id == _SYSTEM_ACTOR_ID else actor_id
        db.insert_workflow_audit(
            tenant_id=row["tenantId"],
            project_id=None,
            version_id=None,
            action=row["eventType"],
            outcome=row["outcome"],
            actor_id=persisted_actor_id,
            detail={
                **row["detail"],
                "repositoryId": row["repositoryId"],
            },
        )
    except Exception:
        pass


def _resolve_actor_id(auth_data: Dict[str, Any] | None) -> str:
    if auth_data:
        raw_user_id = auth_data.get("user_id")
        if isinstance(raw_user_id, str):
            try:
                return str(UUID(raw_user_id))
            except ValueError:
                pass
    return _SYSTEM_ACTOR_ID


def _extract_auth_scopes(auth_data: Dict[str, Any]) -> set[str]:
    raw_scopes = auth_data.get("scopes")
    if isinstance(raw_scopes, str):
        return {token for token in raw_scopes.split() if token}
    if isinstance(raw_scopes, list):
        return {str(scope).strip() for scope in raw_scopes if str(scope).strip()}
    raw_scope = auth_data.get("scope")
    if isinstance(raw_scope, str):
        return {token for token in raw_scope.split() if token}
    return set()


def _require_repository_scope(auth_data: Dict[str, Any], required_scope: str) -> None:
    scopes = _extract_auth_scopes(auth_data)
    if required_scope not in scopes:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "REPOSITORY_SCOPE_REQUIRED",
                "message": f"Missing required scope: {required_scope}",
            },
        )


def _derive_repository_spec_status(
    file_row: RepositoryFileRecord,
    latest_import_job: RepositoryImportJobRecord | None,
) -> RepositorySpecSelectionStatus:
    if file_row.status == "mapping_required":
        return "mapping_required"
    if latest_import_job is not None and latest_import_job.state == "pending_review":
        return "importing"
    if latest_import_job is not None and latest_import_job.state == "committed":
        return "imported"
    if file_row.status == "parse_error":
        return "parse_error"
    if file_row.status == "manifest_error":
        return "manifest_error"
    if file_row.status == "unchanged_checksum":
        return "unchanged_checksum"
    return "not_imported"


def _latest_import_jobs_by_path(repository_id: str, branch: str) -> Dict[str, RepositoryImportJobRecord]:
    jobs = [job for job in _REPO_IMPORT_JOB_STORE.get(repository_id, []) if job.branch == branch]
    jobs.sort(key=lambda item: _to_sort_key(item.createdAt, item.id), reverse=True)
    by_path: Dict[str, RepositoryImportJobRecord] = {}
    for job in jobs:
        path = str(job.diffSnapshot.get("path") or "").strip()
        if not path:
            continue
        if path not in by_path:
            by_path[path] = job
    return by_path


def _build_repository_spec_record(
    file_row: RepositoryFileRecord,
    branch: str,
    latest_import_job: RepositoryImportJobRecord | None,
) -> RepositorySpecRecord:
    status = _derive_repository_spec_status(file_row, latest_import_job)
    last_imported_version_id: str | None = None
    last_imported_at: str | None = None
    if latest_import_job is not None and latest_import_job.state == "committed":
        last_imported_version_id = latest_import_job.targetVersionId
        last_imported_at = latest_import_job.createdAt
    sj = file_row.settingsJson or {}
    mapping_kind = sj.get("mappingConflictKind") if isinstance(sj.get("mappingConflictKind"), str) else None
    return RepositorySpecRecord(
        fileId=file_row.id,
        repositoryId=file_row.repositoryId,
        scanId=file_row.scanId,
        branch=branch,
        path=file_row.path,
        format=file_row.format,
        confidence=file_row.confidence,
        discriminator=file_row.discriminator,
        status=status,
        importEnabled=file_row.importEnabled,
        autoImportEnabled=file_row.autoImportEnabled,
        projectSlug=file_row.projectSlug,
        versionStrategy=file_row.versionStrategy,
        mappingConflictKind=mapping_kind,
        lastImportedVersionId=last_imported_version_id,
        lastImportedAt=last_imported_at,
        createdAt=file_row.createdAt,
    )


def _selection_invariant_violation(message: str) -> None:
    raise HTTPException(
        status_code=400,
        detail={"code": _REPOSITORY_SELECTION_ERROR_CODE, "message": message},
    )


def _apply_selection_update(
    file_row: RepositoryFileRecord,
    *,
    import_enabled: bool | None,
    auto_import_enabled: bool | None,
    selection_actor_id: str | None = None,
) -> Tuple[RepositoryFileRecord, List[Dict[str, Any]]]:
    if import_enabled is None and auto_import_enabled is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "INVALID_INPUT", "message": "Provide importEnabled and/or autoImportEnabled"},
        )
    if import_enabled is False and auto_import_enabled is True:
        _selection_invariant_violation(
            "autoImportEnabled cannot be true when importEnabled is false"
        )

    next_import_enabled = file_row.importEnabled if import_enabled is None else import_enabled
    next_auto_import_enabled = file_row.autoImportEnabled if auto_import_enabled is None else auto_import_enabled

    if import_enabled is False:
        next_auto_import_enabled = False
    if next_auto_import_enabled and not next_import_enabled:
        _selection_invariant_violation(
            "autoImportEnabled cannot be true when importEnabled is false"
        )

    changes: List[Dict[str, Any]] = []
    if file_row.importEnabled != next_import_enabled:
        changes.append(
            {
                "field": "import_enabled",
                "before": file_row.importEnabled,
                "after": next_import_enabled,
            }
        )
    if file_row.autoImportEnabled != next_auto_import_enabled:
        changes.append(
            {
                "field": "auto_import_enabled",
                "before": file_row.autoImportEnabled,
                "after": next_auto_import_enabled,
            }
        )
    if not changes:
        return file_row, changes
    extra: Dict[str, Any] = {
        "importEnabled": next_import_enabled,
        "autoImportEnabled": next_auto_import_enabled,
    }
    if any(c.get("field") == "import_enabled" for c in changes) and selection_actor_id:
        extra["importSelectionActorId"] = selection_actor_id
    return file_row.model_copy(update=extra), changes


def _build_repository_source_uri(repository_id: str, path: str, branch: str, commit_sha: str) -> str:
    normalized_path = path.lstrip("/")
    return f"repo://{repository_id}/{normalized_path}@{branch}/{commit_sha}"


def _normalize_slug(raw: str | None) -> str | None:
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if not lowered:
        return None
    normalized = _SLUG_SANITIZER.sub("-", lowered).strip("-")
    return normalized or None


def _short_sha(commit_sha: str) -> str:
    normalized = _VERSION_SHA_SANITIZER.sub("-", commit_sha.strip().lower()).strip("-")
    return (normalized[:12] if normalized else "unknown")


def _build_version_id_for_commit(commit_sha: str, created_at: datetime) -> str:
    return f"{created_at.strftime('%Y%m%d')}-{_short_sha(commit_sha)}"


def _coerce_tenant_admin_flag(auth_data: Dict[str, Any]) -> bool:
    if bool(auth_data.get("is_tenant_admin")) or bool(auth_data.get("tenant_admin")):
        return True
    roles = auth_data.get("roles")
    if isinstance(roles, list):
        normalized_roles = {str(role).strip().lower() for role in roles}
        if "tenant_admin" in normalized_roles or "tenant-administrator" in normalized_roles:
            return True
    return False


def _is_manifest_project_auto_create_enabled(auth_data: Dict[str, Any]) -> bool:
    containers = (
        auth_data.get("featureFlags"),
        auth_data.get("feature_flags"),
        auth_data.get("flags"),
    )
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in _MANIFEST_PROJECT_AUTO_CREATE_FLAG_KEYS:
            if container.get(key) is True:
                return True
    return False


def _manifest_project_slug_by_path(repository_id: str) -> Dict[str, str]:
    tenant_id = _find_tenant_id_for_repository(repository_id)
    repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
    if repository is None:
        return {}
    manifest_outcome = parse_repo_manifest(repository.manifest)
    return manifest_project_slug_map_from_manifest(manifest_outcome.manifest)


ProjectMappingConflictKind = Literal[
    "PROJECT_SLUG_TAKEN",
    "VERSION_STRATEGY_MISMATCH",
    "MANIFEST_PROJECT_AMBIGUOUS",
    "RBAC_NO_PROJECT_CREATE",
]


def _evaluate_project_mapping_conflict(
    *,
    tenant_id: str,
    repository_id: str,
    file_row: RepositoryFileRecord,
    manifest_project_slug_by_path: Dict[str, str],
    manifest_duplicate_paths: bool,
) -> ProjectMappingConflictKind | None:
    """Return a typed conflict when auto-import cannot safely bind project/version (REPO-12.2)."""
    if manifest_duplicate_paths:
        return "MANIFEST_PROJECT_AMBIGUOUS"

    normalized_slug = _normalize_slug(file_row.projectSlug)
    if normalized_slug is None:
        return None

    tenant_projects = _REPO_PROJECT_STORE.setdefault(tenant_id, {})
    existing = tenant_projects.get(normalized_slug)

    policy = _REPO_IMPORT_POLICY_STORE.get(repository_id, {})
    allow_auto_create = bool(policy.get("allowManifestProjectAutoCreate"))

    manifest_slug = manifest_project_slug_by_path.get(file_row.path)

    if manifest_slug is not None and manifest_slug == normalized_slug:
        if existing is None and not allow_auto_create:
            return "RBAC_NO_PROJECT_CREATE"

    if existing is not None:
        evs = existing.defaultVersionStrategy
        fvs = file_row.versionStrategy
        if (
            isinstance(evs, str)
            and evs.strip()
            and isinstance(fvs, str)
            and fvs.strip()
            and evs.strip().lower() != fvs.strip().lower()
        ):
            return "VERSION_STRATEGY_MISMATCH"

        if allow_auto_create and manifest_slug == normalized_slug:
            if existing.origin == "manual":
                return "PROJECT_SLUG_TAKEN"
            if existing.origin == "manifest_auto" and (
                existing.createdFromRepositoryId is None
                or existing.createdFromRepositoryId != repository_id
            ):
                return "PROJECT_SLUG_TAKEN"

    return None


def _park_file_mapping_required(
    file_row: RepositoryFileRecord,
    *,
    kind: ProjectMappingConflictKind,
) -> RepositoryFileRecord:
    sj = dict(file_row.settingsJson or {})
    sj["mappingConflictKind"] = kind
    sj["preMappingScanStatus"] = file_row.status
    return file_row.model_copy(
        update={
            "status": "mapping_required",
            "settingsJson": sj,
            "discriminator": kind,
        }
    )


def _tenant_project_slug_exists(tenant_id: str, slug: str) -> bool:
    if slug in _REPO_PROJECT_STORE.get(tenant_id, {}):
        return True
    try:
        hit = db.get_project_by_slug(slug, tenant_id)
        return bool(hit)
    except Exception:
        _logger.exception(
            "Failed to check whether project slug exists; failing closed",
            extra={"tenant_id": tenant_id, "project_slug": slug},
        )
        return True


def _ensure_project_for_scan_file(
    *,
    tenant_id: str,
    repository_id: str,
    file_row: RepositoryFileRecord,
    manifest_project_slug_by_path: Dict[str, str],
) -> RepositoryResolvedProjectRecord | None:
    normalized_project_slug = _normalize_slug(file_row.projectSlug)
    if normalized_project_slug is None:
        return None
    tenant_projects = _REPO_PROJECT_STORE.setdefault(tenant_id, {})
    existing = tenant_projects.get(normalized_project_slug)
    if existing is not None:
        return existing

    policy = _REPO_IMPORT_POLICY_STORE.get(repository_id, {})
    allow_auto_create = bool(policy.get("allowManifestProjectAutoCreate"))
    manifest_slug = manifest_project_slug_by_path.get(file_row.path)
    if not allow_auto_create or manifest_slug != normalized_project_slug:
        return None

    now = _utc_now_iso()
    vs_raw = file_row.versionStrategy
    vs_norm = vs_raw.strip().lower() if isinstance(vs_raw, str) and vs_raw.strip() else None
    created = RepositoryResolvedProjectRecord(
        id=str(uuid4()),
        tenantId=tenant_id,
        slug=normalized_project_slug,
        name=normalized_project_slug.replace("-", " ").title(),
        createdAt=now,
        origin="manifest_auto",
        createdFromRepositoryId=repository_id,
        defaultVersionStrategy=vs_norm,
    )
    tenant_projects[normalized_project_slug] = created
    return created


def _ensure_commit_sha_version(
    *,
    tenant_id: str,
    project_slug: str,
    commit_sha: str,
    repository_id: str,
    branch: str,
    path: str,
    content_checksum: str,
    content_algo: str,
    imported_at: str,
) -> RepositoryResolvedVersionRecord:
    normalized_sha = commit_sha.strip().lower()
    tenant_versions = _REPO_VERSION_STORE.setdefault(tenant_id, {})
    project_versions = tenant_versions.setdefault(project_slug, {})
    existing = project_versions.get(normalized_sha)
    if existing is not None:
        return existing

    now_dt = datetime.now(timezone.utc)
    effective_checksum = content_checksum.strip().lower()
    effective_algo = content_algo.strip().lower()
    effective_imported_at = imported_at.strip()
    record = RepositoryResolvedVersionRecord(
        id=str(uuid4()),
        tenantId=tenant_id,
        projectSlug=project_slug,
        commitSha=commit_sha,
        versionId=_build_version_id_for_commit(commit_sha, now_dt),
        metadata={
            "repositorySource": {
                "repositoryId": repository_id,
                "branch": branch,
                "commitSha": commit_sha,
                "path": path,
                "contentChecksum": effective_checksum,
                "contentAlgo": effective_algo,
                "importedAt": effective_imported_at,
            }
        },
        createdAt=now_dt.isoformat(),
    )
    project_versions[normalized_sha] = record
    return record


def _build_diff_snapshot(file_row: RepositoryFileRecord) -> Dict[str, Any]:
    return {
        "path": file_row.path,
        "status": file_row.status,
        "blobSha": file_row.blobSha,
        "contentAlgo": file_row.contentAlgo,
        "contentChecksum": file_row.contentChecksum,
        "format": file_row.format,
        "tracked": file_row.tracked,
    }


def _schema_name_from_path(path: str) -> str:
    sanitized = re.sub(r"[^a-zA-Z0-9]+", "_", path.strip("/"))
    sanitized = sanitized.strip("_")
    # Truncate to keep schema names at a reasonable display length.
    return sanitized[:64] if sanitized else "repo_sync"


def _coerce_conflict_kinds(raw_kinds: Any) -> List[ImportConflictKind]:
    allowed: set[str] = {
        "duplicate_schema",
        "property_conflict",
        "reference_conflict",
        "type_mismatch",
        "semantic_conflict",
    }
    if not isinstance(raw_kinds, list):
        return []
    kinds: List[ImportConflictKind] = []
    for raw in raw_kinds:
        if isinstance(raw, str) and raw in allowed and raw not in kinds:
            kinds.append(raw)
    return kinds


def _derive_import_conflicts(
    *,
    file_row: RepositoryFileRecord,
    operation: ImportJobOperation,
    settings_json: Dict[str, Any],
) -> List[Dict[str, Any]]:
    configured_conflicts = settings_json.get("simulatedConflicts")
    if isinstance(configured_conflicts, list):
        conflicts: List[Dict[str, Any]] = []
        for item in configured_conflicts:
            if not isinstance(item, dict):
                continue
            schema_name = item.get("schemaName")
            if not isinstance(schema_name, str) or not schema_name.strip():
                continue
            kinds = _coerce_conflict_kinds(item.get("kinds"))
            if not kinds:
                continue
            message = item.get("message")
            detail = item.get("detail")
            conflicts.append(
                {
                    "schemaName": schema_name.strip(),
                    "kinds": kinds,
                    "message": message.strip() if isinstance(message, str) and message.strip() else "Conflict detected",
                    "detail": detail.strip() if isinstance(detail, str) and detail.strip() else None,
                }
            )
        return conflicts

    if operation != "import" or file_row.status != "modified":
        return []
    schema_name = _schema_name_from_path(file_row.path)
    return [
        {
            "schemaName": schema_name,
            "kinds": ["duplicate_schema"],
            "message": "Existing draft class and discovered schema both changed.",
            "detail": f"Resolve '{schema_name}' before promotion.",
        }
    ]


def _build_import_job_event_log(
    *,
    file_row: RepositoryFileRecord,
    operation: ImportJobOperation,
    state: ImportJobStatus,
    conflicts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = [
        {
            "type": "repository.sync.job_dispatched",
            "at": file_row.createdAt,
            "path": file_row.path,
            "operation": operation,
            "state": state,
        }
    ]
    if conflicts:
        events.append(
            {
                "type": "repository.sync.conflicts_detected",
                "at": file_row.createdAt,
                "taxonomy": "import_pipeline",
                "resolver": "import_conflict_resolver",
                "conflicts": conflicts,
            }
        )
    return events


def _build_repository_sync_change_report_model(file_row: RepositoryFileRecord) -> Dict[str, Any]:
    schema_name = _schema_name_from_path(file_row.path)
    baseline_openapi: Dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": "Repository Sync Baseline", "version": "0.0.0"},
        "paths": {},
        "components": {"schemas": {}},
    }
    candidate_openapi: Dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {"title": "Repository Sync Candidate", "version": "0.0.0"},
        "paths": {},
        "components": {"schemas": {}},
    }

    baseline_payload = {
        "type": "object",
        "properties": {"status": {"type": "string", "const": "baseline"}},
    }
    candidate_payload = {
        "type": "object",
        "properties": {"status": {"type": "string", "const": "candidate"}},
    }

    if file_row.status == "new":
        candidate_openapi["components"]["schemas"][schema_name] = candidate_payload
    elif file_row.status == "removed":
        baseline_openapi["components"]["schemas"][schema_name] = baseline_payload
    elif file_row.status == "modified":
        baseline_openapi["components"]["schemas"][schema_name] = baseline_payload
        candidate_openapi["components"]["schemas"][schema_name] = candidate_payload
    else:
        baseline_openapi["components"]["schemas"][schema_name] = baseline_payload
        candidate_openapi["components"]["schemas"][schema_name] = baseline_payload

    return build_change_report(baseline_openapi, candidate_openapi)


def _preview_target_version_id_for_dry_run(commit_sha: str, created_at_iso: str) -> str:
    created_at = _parse_iso8601(created_at_iso, "createdAt")
    if created_at is None:
        created_at = datetime.now(timezone.utc)
    return _build_version_id_for_commit(commit_sha, created_at)


def _resolve_target_project_slug_for_dry_run(
    *,
    tenant_id: str,
    repository_id: str,
    file_row: RepositoryFileRecord,
    manifest_project_slug_by_path: Dict[str, str],
) -> str | None:
    normalized_project_slug = _normalize_slug(file_row.projectSlug)
    if normalized_project_slug is None:
        return None
    tenant_projects = _REPO_PROJECT_STORE.get(tenant_id, {})
    if normalized_project_slug in tenant_projects:
        return normalized_project_slug

    policy = _REPO_IMPORT_POLICY_STORE.get(repository_id, {})
    allow_auto_create = bool(policy.get("allowManifestProjectAutoCreate"))
    manifest_slug = manifest_project_slug_by_path.get(file_row.path)
    if allow_auto_create and manifest_slug == normalized_project_slug:
        return normalized_project_slug
    return None


def _persist_repository_import_revision_db(
    *,
    tenant_id: str,
    repository_id: str,
    scan_branch: str,
    commit_sha: str,
    file_row: RepositoryFileRecord,
    target_semantic_version_id: str,
    target_project_slug: str,
) -> Dict[str, str]:
    """Insert ODB revision + repository_file tracking for a committed repository import (#2936)."""
    out: Dict[str, str] = {}
    checksum = _normalize_content_checksum(file_row.contentChecksum)
    if not checksum:
        return out
    slug = _normalize_slug(target_project_slug)
    if not slug:
        return out
    try:
        project = db.get_project_by_slug(slug, tenant_id)
        if not project:
            return out
        project_id = str(project.get("id", "")).strip()
        if not project_id:
            return out
        imported_at = _utc_now_iso()
        cs_norm = commit_sha.strip().lower()
        payload = {
            "repositoryId": repository_id,
            "branch": scan_branch,
            "path": file_row.path,
            "commitSha": cs_norm,
            "contentChecksum": checksum,
            "contentAlgo": "sha256",
            "importedAt": imported_at,
        }
        normalized, err = validate_repository_source_payload(payload)
        if err or not normalized:
            return out
        tip, branch_row = db.resolve_push_head_for_repository_import(project_id, tenant_id)
        base = tip or ""
        parent_version_id = tip if tip else None
        version_row, _ = db.create_version_push_transaction(
            project_id=project_id,
            tenant_id=tenant_id,
            creator_id=None,
            version_id=target_semantic_version_id,
            description="Repository import",
            change_log=None,
            commit_author=None,
            commit_message=f"Auto-import {file_row.path}",
            external_ref=None,
            parent_version_id=parent_version_id,
            source_version_id=None,
            branch_row=branch_row,
            client_base_revision_id=base,
            repository_source=normalized,
            repository_file_import=(file_row.id, checksum, repository_id),
        )
        rid = str(version_row.get("id", "")).strip()
        if rid:
            out["versionId"] = rid
            out["projectId"] = project_id
        return out
    except Exception:
        return out


def _latest_repository_source_checksum_for_file(
    *,
    tenant_id: str,
    repository_id: str,
    file_row: RepositoryFileRecord,
) -> str | None:
    project_slug = _normalize_slug(file_row.projectSlug)
    if project_slug is None:
        return None
    try:
        project = db.get_project_by_slug(project_slug, tenant_id)
        if not project:
            return None
        project_id = project.get("id")
        if not isinstance(project_id, str) or not project_id.strip():
            return None
        return db.get_latest_repository_source_checksum_for_project(
            tenant_id,
            repository_id,
            file_row.path,
            project_id,
        )
    except Exception:
        # Best-effort optimization; scan completion should not fail on lookup issues.
        return None


def _precompute_latest_checksums(
    *,
    tenant_id: str,
    repository_id: str,
    scan_files: List[RepositoryFileRecord],
    force: bool,
) -> Dict[str, str | None]:
    """Pre-fetch the latest stored contentChecksum for each modified tracked file.

    Must be called **outside** ``_STORE_LOCK`` as it performs blocking DB lookups.
    Returns a mapping of file path -> latest stored checksum (or None when unavailable).
    Caches per-slug project_id to avoid redundant ``get_project_by_slug`` calls per scan.
    """
    if force:
        return {}
    project_id_cache: Dict[str, str | None] = {}
    result: Dict[str, str | None] = {}
    for file_row in scan_files:
        if file_row.status != "modified" or not file_row.tracked:
            continue
        if _normalize_content_checksum(file_row.contentChecksum) is None:
            continue
        project_slug = _normalize_slug(file_row.projectSlug)
        if project_slug is None:
            result[file_row.path] = None
            continue
        try:
            if project_slug not in project_id_cache:
                project = db.get_project_by_slug(project_slug, tenant_id)
                raw_id = project.get("id") if project else None
                project_id_cache[project_slug] = (
                    raw_id if isinstance(raw_id, str) and raw_id.strip() else None
                )
            project_id = project_id_cache[project_slug]
            if project_id is None:
                result[file_row.path] = None
                continue
            result[file_row.path] = db.get_latest_repository_source_checksum_for_project(
                tenant_id,
                repository_id,
                file_row.path,
                project_id,
            )
        except Exception:
            # Best-effort optimization; scan completion should not fail on lookup issues.
            result[file_row.path] = None
    return result


def _prune_import_now_idempotency() -> None:
    now = time.monotonic()
    for key, (_job_id, t0) in list(_REPO_IMPORT_NOW_IDEMPOTENCY.items()):
        if now - t0 > 30.0:
            _REPO_IMPORT_NOW_IDEMPOTENCY.pop(key, None)


def _import_now_idempotency_lookup(repository_id: str, file_id: str, branch: str) -> str | None:
    _prune_import_now_idempotency()
    rec = _REPO_IMPORT_NOW_IDEMPOTENCY.get((repository_id, file_id, branch))
    if rec is None:
        return None
    return rec[0]


def _import_now_idempotency_store(repository_id: str, file_id: str, branch: str, import_job_id: str) -> None:
    _prune_import_now_idempotency()
    _REPO_IMPORT_NOW_IDEMPOTENCY[(repository_id, file_id, branch)] = (import_job_id, time.monotonic())


def _materialize_repository_dry_run_import_job(
    *,
    tenant_id: str,
    repository_id: str,
    scan_id: str,
    branch: str,
    commit_sha: str,
    file_row: RepositoryFileRecord,
    actor_id: str,
    source_kind: RepositoryImportJobSourceKind,
) -> tuple[RepositoryImportJobRecord, List[Dict[str, Any]]]:
    """Build and persist a dry-run repository import job + change report (REPO-8.3 / 9.5)."""
    repository_jobs = _REPO_IMPORT_JOB_STORE.setdefault(repository_id, [])
    manifest_project_slug_by_path = _manifest_project_slug_by_path(repository_id)
    operation: ImportJobOperation = "import"
    promote: ImportJobPromotion = file_row.promote if file_row.promote in {"auto", "manual"} else "manual"
    settings_json: Dict[str, Any] = dict(file_row.settingsJson or {})
    if settings_json.get("onBreakingChange") == "block":
        promote = "manual"
        settings_json["requiresExplicitApproval"] = True
    if file_row.status == "removed":
        operation = "removal"
        promote = "manual"
        settings_json["requiresExplicitApproval"] = True

    source_uri = _build_repository_source_uri(repository_id, file_row.path, branch, commit_sha)
    forced_failure = settings_json.get("forceImportFailure")
    failure_message: str | None = None
    if isinstance(forced_failure, str) and forced_failure.strip():
        failure_message = forced_failure.strip()
    elif forced_failure is True:
        failure_message = "forced import failure for test coverage"

    state: ImportJobStatus = "pending_review"
    if failure_message:
        state = "failed"
    elif promote == "auto":
        state = "committed"

    target_project_slug: str | None = None
    target_version_id: str | None = None
    if file_row.versionStrategy == "commit-sha":
        resolved_project_slug = _resolve_target_project_slug_for_dry_run(
            tenant_id=tenant_id,
            repository_id=repository_id,
            file_row=file_row,
            manifest_project_slug_by_path=manifest_project_slug_by_path,
        )
        if resolved_project_slug is not None:
            target_project_slug = resolved_project_slug
            target_version_id = _preview_target_version_id_for_dry_run(commit_sha, file_row.createdAt)

    change_report = RepositorySyncChangeReportRecord(
        id=str(uuid4()),
        sourceKind="repository_sync",
        repositoryId=repository_id,
        importJobId="",
        scanId=scan_id,
        changeModelJson=_build_repository_sync_change_report_model(file_row),
        createdAt=file_row.createdAt,
    )
    conflict_records = _derive_import_conflicts(
        file_row=file_row,
        operation=operation,
        settings_json=settings_json,
    )
    event_log = _build_import_job_event_log(
        file_row=file_row,
        operation=operation,
        state=state,
        conflicts=conflict_records,
    )

    import_job = RepositoryImportJobRecord(
        id=str(uuid4()),
        repositoryId=repository_id,
        repositoryFileId=file_row.id,
        scanId=scan_id,
        branch=branch,
        sourceType="git",
        sourceKind=source_kind,
        sourceUri=source_uri,
        operation=operation,
        format=file_row.format,
        settingsJson=settings_json,
        dryRun=True,
        state=state,
        diffSnapshot=_build_diff_snapshot(file_row),
        conflictRecords=conflict_records,
        eventLog=event_log,
        errorDetail=failure_message,
        targetProjectSlug=target_project_slug,
        targetVersionId=target_version_id,
        changeReportId=change_report.id,
        createdAt=file_row.createdAt,
    )
    change_report.importJobId = import_job.id
    repository_jobs.insert(0, import_job)
    _REPO_CHANGE_REPORT_STORE.setdefault(repository_id, []).insert(0, change_report)
    file_row.lastImportJobId = import_job.id
    persist_meta: Dict[str, str] = {}
    if import_job.state == "committed" and not failure_message:
        c0 = _normalize_content_checksum(file_row.contentChecksum)
        file_row.lastImportedContentChecksum = c0
        file_row.staleMismatchAt = None
        if (
            source_kind in _IMPORT_WITH_PROVENANCE_KINDS
            and (file_row.versionStrategy or "").strip().lower() == "commit-sha"
            and target_project_slug
            and target_version_id
        ):
            persist_meta = _persist_repository_import_revision_db(
                tenant_id=tenant_id,
                repository_id=repository_id,
                scan_branch=branch,
                commit_sha=commit_sha,
                file_row=file_row,
                target_semantic_version_id=target_version_id,
                target_project_slug=target_project_slug,
            )

    pending_audit_rows: List[Dict[str, Any]] = []
    if failure_message:
        file_row.status = "parse_error"
        file_row.discriminator = failure_message
        pending_audit_rows.append(_append_audit_row(
            tenant_id,
            repository_id,
            "repository.sync_failed",
            actor_id=actor_id,
            outcome="failure",
            detail={
                "scanId": scan_id,
                "importJobId": import_job.id,
                "path": file_row.path,
                "operation": operation,
                "error": failure_message,
            },
        ))
    elif promote == "auto":
        pending_audit_rows.append(_append_audit_row(
            tenant_id,
            repository_id,
            "repository.sync_committed",
            actor_id=actor_id,
            detail={
                "scanId": scan_id,
                "importJobId": import_job.id,
                "path": file_row.path,
                "operation": operation,
                "promotion": promote,
            },
        ))
    else:
        pending_audit_rows.append(_append_audit_row(
            tenant_id,
            repository_id,
            "repository.sync_pending_review",
            actor_id=actor_id,
            detail={
                "scanId": scan_id,
                "importJobId": import_job.id,
                "path": file_row.path,
                "operation": operation,
                "promotion": promote,
            },
        ))
    if source_kind in _IMPORT_WITH_PROVENANCE_KINDS:
        auto_detail: Dict[str, Any] = {
            "scanId": scan_id,
            "repositoryId": repository_id,
            "branch": branch,
            "path": file_row.path,
            "commitSha": commit_sha,
            "fileId": file_row.id,
            "projectSlug": file_row.projectSlug,
            "versionStrategy": file_row.versionStrategy,
            "importJobId": import_job.id,
            "actorId": actor_id,
        }
        cs = _normalize_content_checksum(file_row.contentChecksum)
        if cs:
            auto_detail["contentChecksumShort"] = _short_checksum(cs)
        if persist_meta.get("projectId"):
            auto_detail["projectId"] = persist_meta["projectId"]
        if persist_meta.get("versionId"):
            auto_detail["versionId"] = persist_meta["versionId"]
        pending_audit_rows.append(
            _append_audit_row(
                tenant_id,
                repository_id,
                "repository.auto_imported",
                actor_id=actor_id,
                detail=auto_detail,
            )
        )
    repo_rec = _REPO_STORE.get(tenant_id, {}).get(repository_id)
    repo_name = repo_rec.fullName if repo_rec is not None else repository_id
    emit_repository_import_notifications(
        tenant_id=tenant_id,
        repository_id=repository_id,
        repository_full_name=repo_name,
        import_selection_actor_id=file_row.importSelectionActorId,
        repository_file_id=file_row.id,
        import_job_id=import_job.id,
        source_kind=source_kind,
        state=import_job.state,
        change_model=change_report.changeModelJson,
        conflict_records=import_job.conflictRecords,
        change_report_id=import_job.changeReportId,
    )
    return import_job, pending_audit_rows


def _dispatch_import_jobs_for_scan(
    *,
    tenant_id: str,
    repository_id: str,
    scan_id: str,
    branch: str,
    commit_sha: str,
    scan_files: List[RepositoryFileRecord],
    actor_id: str,
    force: bool,
    diff_summary: Dict[str, int],
    precomputed_checksums: Dict[str, str | None] | None = None,
) -> List[Dict[str, Any]]:
    pending_audit_rows: List[Dict[str, Any]] = []
    checksums = precomputed_checksums or {}
    with _repository_dispatch_advisory_lock(repository_id):
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        manifest_obj = parse_repo_manifest(repository.manifest).manifest if repository else None
        manifest_duplicate_paths = manifest_duplicate_spec_paths(manifest_obj)
        manifest_slug_map = manifest_project_slug_map_from_manifest(manifest_obj)

        for idx, file_row in enumerate(scan_files):
            if file_row.status not in {"new", "modified", "removed"}:
                continue
            if not file_row.tracked:
                continue

            if not file_row.importEnabled:
                if file_row.status != "removed":
                    file_row.status = "discovered"
                continue

            if not file_row.autoImportEnabled:
                if file_row.status != "removed":
                    file_row.status = "ready_to_promote"
                continue

            if file_row.status == "modified" and not force:
                current_checksum = _normalize_content_checksum(file_row.contentChecksum)
                if current_checksum is not None:
                    latest_checksum = checksums.get(file_row.path)
                    if latest_checksum == current_checksum:
                        file_row.status = "unchanged_checksum"
                        diff_summary["modified"] = max(0, int(diff_summary.get("modified", 0)) - 1)
                        diff_summary["skipped_unchanged_by_checksum"] = int(
                            diff_summary.get("skipped_unchanged_by_checksum", 0)
                        ) + 1
                        pending_audit_rows.append(
                            _append_audit_row(
                                tenant_id,
                                repository_id,
                                "repository.scan.skipped_checksum",
                                actor_id=actor_id,
                                detail={
                                    "scanId": scan_id,
                                    "path": file_row.path,
                                    "contentChecksumShort": _short_checksum(current_checksum),
                                },
                            )
                        )
                        continue

            if file_row.status != "removed":
                conflict = _evaluate_project_mapping_conflict(
                    tenant_id=tenant_id,
                    repository_id=repository_id,
                    file_row=file_row,
                    manifest_project_slug_by_path=manifest_slug_map,
                    manifest_duplicate_paths=manifest_duplicate_paths,
                )
                if conflict is not None:
                    scan_files[idx] = _park_file_mapping_required(file_row, kind=conflict)
                    pending_audit_rows.append(
                        _append_audit_row(
                            tenant_id,
                            repository_id,
                            "repository.spec.mapping_required",
                            actor_id=actor_id,
                            detail={
                                "scanId": scan_id,
                                "fileId": file_row.id,
                                "path": file_row.path,
                                "conflictKind": conflict,
                            },
                        )
                    )
                    continue

            _created_job, materialize_audits = _materialize_repository_dry_run_import_job(
                tenant_id=tenant_id,
                repository_id=repository_id,
                scan_id=scan_id,
                branch=branch,
                commit_sha=commit_sha,
                file_row=file_row,
                actor_id=actor_id,
                source_kind="repository_auto_import",
            )
            pending_audit_rows.extend(materialize_audits)
    return pending_audit_rows


def _list_poll_targets_for_tenant(tenant_id: str) -> List[Dict[str, str]]:
    poll_targets: List[Dict[str, str]] = []
    for repository in _REPO_STORE.get(tenant_id, {}).values():
        if repository.status in {"archived", "paused"}:
            continue
        for branch in _REPO_BRANCH_STORE.get(repository.id, repository.branches):
            poll_targets.append({"repositoryId": repository.id, "branch": branch.branch})
    return poll_targets


def _find_import_job_for_repository(repository_id: str, import_job_id: str) -> RepositoryImportJobRecord | None:
    jobs = _REPO_IMPORT_JOB_STORE.get(repository_id, [])
    for job in jobs:
        if job.id == import_job_id:
            return job
    return None


def _find_change_report_for_import_job(repository_id: str, import_job_id: str) -> RepositorySyncChangeReportRecord | None:
    for report in _REPO_CHANGE_REPORT_STORE.get(repository_id, []):
        if report.importJobId == import_job_id:
            return report
    return None


_RECENT_IMPORT_ATTENTION_SOURCE_KINDS: frozenset[str] = frozenset(
    {"git", "repository_sync", "repository_auto_import", "repository_manual_import"}
)


def _import_job_created_within_recent_window(job: RepositoryImportJobRecord, cutoff_utc: datetime) -> bool:
    dt = _parse_iso8601(job.createdAt, "createdAt")
    if dt is None:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    cu = cutoff_utc if cutoff_utc.tzinfo else cutoff_utc.replace(tzinfo=timezone.utc)
    return dt >= cu


def _openapi_warnings_count(change_model: Dict[str, Any] | None) -> int:
    if not isinstance(change_model, dict):
        return 0
    w = change_model.get("warnings")
    return len(w) if isinstance(w, list) else 0


def _import_job_matches_recent_attention_filters(
    job: RepositoryImportJobRecord,
    change_model: Dict[str, Any] | None,
    cutoff_utc: datetime,
) -> bool:
    sk = str(job.sourceKind or "")
    if sk not in _RECENT_IMPORT_ATTENTION_SOURCE_KINDS:
        return False
    if not _import_job_created_within_recent_window(job, cutoff_utc):
        return False
    breaking, _additive = _count_change_report_categories(change_model)
    openapi_warn = _openapi_warnings_count(change_model)
    conflict_n = len(job.conflictRecords or [])
    if job.state == "failed":
        return True
    if job.state == "pending_review":
        return True
    if breaking > 0:
        return True
    if openapi_warn > 0:
        return True
    if conflict_n > 0:
        return True
    return False


def _recent_import_attention_reason(job: RepositoryImportJobRecord, change_model: Dict[str, Any] | None) -> Tuple[str, str]:
    """Return (reasonKind, primaryReason) for dashboard row copy."""
    if job.state == "failed":
        return ("failed", "failed")
    if job.state == "pending_review":
        return ("pending_review", "awaiting review")
    breaking, _a = _count_change_report_categories(change_model)
    if breaking > 0:
        label = "breaking change" if breaking == 1 else "breaking changes"
        return ("breaking", f"{breaking} {label}")
    c = len(job.conflictRecords or [])
    if c > 0:
        return ("conflict", f"{c} conflict" if c == 1 else f"{c} conflicts")
    ow = _openapi_warnings_count(change_model)
    if ow > 0:
        return ("warnings", f"{ow} warnings")
    return ("other", "needs review")


def collect_recent_import_attention_rows(
    tenant_id: str,
    *,
    dismissed_import_job_ids: Set[str],
    limit: int,
) -> List[Dict[str, Any]]:
    """Aggregate recent repository import jobs needing attention (REPO-11.3 / #2943).

    Reads the same in-memory import job store as sync-history; filters match the
    issue spec (source kinds, 7-day window, failed / pending review / breaking /
    OpenAPI warnings / conflicts).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    triples: List[Tuple[RepositoryRecord, RepositoryImportJobRecord, Dict[str, Any] | None]] = []
    with _STORE_LOCK:
        tenant_map = _REPO_STORE.get(tenant_id, {})
        for repo in tenant_map.values():
            for job in _REPO_IMPORT_JOB_STORE.get(repo.id, []):
                if job.id in dismissed_import_job_ids:
                    continue
                report = _find_change_report_for_import_job(repo.id, job.id)
                cm: Dict[str, Any] | None = dict(report.changeModelJson) if report is not None else None
                if not _import_job_matches_recent_attention_filters(job, cm, cutoff):
                    continue
                triples.append((repo, job, cm))

    triples.sort(key=lambda t: _to_sort_key(t[1].createdAt, t[1].id), reverse=True)
    triples = triples[: max(0, int(limit))]

    out: List[Dict[str, Any]] = []
    for repo, job, cm in triples:
        project_label = job.targetProjectSlug or "—"
        version_label = "—"
        if job.targetVersionId:
            try:
                vr = db.get_version_for_tenant(tenant_id, job.targetVersionId)
                if vr:
                    version_label = str(vr.get("version_id") or "—")
                    pn = vr.get("project_name")
                    ps = vr.get("project_slug")
                    if isinstance(pn, str) and pn.strip():
                        project_label = pn.strip()
                    elif isinstance(ps, str) and ps.strip():
                        project_label = ps.strip()
            except Exception:
                version_label = "draft"

        reason_kind, reason_text = _recent_import_attention_reason(job, cm)
        cid = (job.changeReportId or "").strip()
        if cid:
            change_path = (
                f"/ade/dashboard/repositories/{repo.id}?tab=sync&changeReportId="
                f"{urllib_parse.quote(cid, safe='')}"
            )
        else:
            change_path = f"/ade/dashboard/repositories/{repo.id}?tab=sync"

        out.append(
            {
                "importJobId": job.id,
                "repositoryId": repo.id,
                "repositoryFullName": repo.fullName,
                "projectName": project_label,
                "versionLabel": version_label,
                "state": job.state,
                "reasonKind": reason_kind,
                "primaryReason": reason_text,
                "createdAt": job.createdAt,
                "changeReportPath": change_path,
            }
        )
    return out


def _find_repository_file_row(
    repository_id: str,
    file_id: str,
) -> Tuple[RepositoryFileRecord, RepositoryScanRecord] | None:
    """Find the ``RepositoryFileRecord`` for ``file_id`` and the scan that owns it.

    Walks the per-repository scan history newest-first; spec detail lookups
    almost always target the latest scan, so this short-circuits quickly.
    """
    scans = _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
    for scan in scans:
        for file_row in _REPO_SCAN_FILE_HISTORY_STORE.get(scan.id, []):
            if file_row.id == file_id:
                return file_row, scan
    return None


def _build_spec_import_summary(
    *,
    job: RepositoryImportJobRecord,
    repository_id: str,
) -> RepositorySpecImportSummary:
    change_report = _find_change_report_for_import_job(repository_id, job.id)
    change_model = change_report.changeModelJson if change_report is not None else None
    summary = derive_lint_summary(job=job.model_dump(), change_model=change_model)
    return RepositorySpecImportSummary(
        id=job.id,
        state=job.state,
        sourceKind=job.sourceKind,
        operation=job.operation,
        branch=job.branch,
        createdAt=job.createdAt,
        conflictCount=len(job.conflictRecords or []),
        targetVersionId=job.targetVersionId,
        targetProjectSlug=job.targetProjectSlug,
        changeReportId=job.changeReportId,
        lintSummary=RepositorySpecLintSummary(**summary.to_payload()),
    )


def _list_recent_imports_for_path(
    repository_id: str,
    branch: str,
    path: str,
    *,
    limit: int,
) -> List[RepositoryImportJobRecord]:
    matched: List[RepositoryImportJobRecord] = []
    for job in _REPO_IMPORT_JOB_STORE.get(repository_id, []):
        if job.branch != branch:
            continue
        snapshot_path = str(job.diffSnapshot.get("path") or "").strip()
        if snapshot_path != path:
            continue
        matched.append(job)
    matched.sort(key=lambda item: _to_sort_key(item.createdAt, item.id), reverse=True)
    return matched[: max(1, limit)]


def _fetch_file_content_bytes(
    *,
    repository: RepositoryRecord,
    file_row: RepositoryFileRecord,
    branch: str,
) -> bytes:
    """Return raw bytes for ``file_row``.

    Test environments seed ``_REPO_FILE_CONTENT_STORE`` directly so unit
    tests don't have to stub GitHub. In production we hit the GitHub
    Contents API (the same URL we already use for scans) and decode the
    base64 payload.
    """
    with _STORE_LOCK:
        seeded = _REPO_FILE_CONTENT_STORE.get((repository.id, file_row.id))
    if seeded is not None:
        return seeded

    access_token = _load_linked_account_access_token(repository.linkedAccountId)
    owner = urllib_parse.quote(repository.owner, safe="")
    name = urllib_parse.quote(repository.name, safe="")
    branch_ref = urllib_parse.quote(branch, safe="")
    encoded_path = "/".join(urllib_parse.quote(part, safe="") for part in file_row.path.strip("/").split("/") if part)
    payload = _github_api_get_json(
        f"https://api.github.com/repos/{owner}/{name}/contents/{encoded_path}?ref={branch_ref}",
        access_token,
    )
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub Contents API returned malformed payload")
    encoding = str(payload.get("encoding") or "").lower()
    if encoding == "base64":
        raw = str(payload.get("content") or "").replace("\n", "")
        try:
            return base64.b64decode(raw)
        except (binascii.Error, ValueError) as exc:
            raise RuntimeError("GitHub Contents API returned invalid base64") from exc
    if encoding == "":
        # Some shapes return raw text on the `content` field directly.
        return str(payload.get("content") or "").encode("utf-8")
    raise RuntimeError(f"Unsupported GitHub content encoding: {encoding!r}")


def _seed_repository_file_content_for_tests(
    repository_id: str,
    file_id: str,
    content: bytes,
) -> None:
    """Seed in-memory file bytes so REPO-9.6 tests don't need GitHub stubs."""
    with _STORE_LOCK:
        _REPO_FILE_CONTENT_STORE[(repository_id, file_id)] = content


def _looks_like_text_bytes(payload: bytes) -> bool:
    """Heuristic: declare the bytes safe for an inline UTF-8 preview."""
    if not payload:
        return True
    if b"\x00" in payload[:8192]:
        return False
    try:
        payload.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


@router.post("/{tenant_slug}", status_code=201, response_model=RegisterRepositoryResponse)
async def register_repository(
    tenant_slug: str,
    request: RepositoryRegisterRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RegisterRepositoryResponse:
    tenant_id = auth_data["tenant_id"]
    actor_id = _resolve_actor_id(auth_data)

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

    _audit_token_row: Dict[str, Any] | None = None
    _audit_registered_row: Dict[str, Any] | None = None
    with _STORE_LOCK:
        tenant_repos = _REPO_STORE.setdefault(tenant_id, {})
        _REPO_BRANCH_STORE[repository.id] = list(normalized_branches)
        _REPO_SCAN_STORE[repository.id] = [timeline_entry]
        _REPO_FILE_STORE[repository.id] = initial_file_rows
        _REPO_SCAN_HISTORY_STORE[repository.id] = [initial_scan]
        _REPO_SCAN_FILE_HISTORY_STORE[initial_scan.id] = initial_scan_files
        _REPO_CREDENTIAL_REF_STORE[repository.id] = [{"linkedAccountId": request.linkedAccountId}]
        _REPO_IMPORT_POLICY_STORE[repository.id] = {
            "allowManifestProjectAutoCreate": _coerce_tenant_admin_flag(auth_data)
            and _is_manifest_project_auto_create_enabled(auth_data),
        }
        tenant_repos[repository.id] = repository
        _refresh_repository_corpus_rollup_unsafe(tenant_id)
        _audit_token_row = _append_audit_row(
            tenant_id,
            repository_id,
            "repository.token_resolved",
            actor_id=actor_id,
            detail={
                "provider": repository.provider,
                "linkedAccountId": request.linkedAccountId,
            },
        )
        _audit_registered_row = _append_audit_row(
            tenant_id,
            repository_id,
            "repository.registered",
            actor_id=actor_id,
            detail={
                "provider": repository.provider,
                "fullName": repository.fullName,
                "branchCount": len(normalized_branches),
            },
        )

    if _audit_token_row is not None:
        _persist_audit_row(_audit_token_row)
    if _audit_registered_row is not None:
        _persist_audit_row(_audit_registered_row)
    _recompute_repository_attention(tenant_id, repository_id)
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


def _last_scan_effective_time(raw: str | None) -> float:
    if not raw:
        return 0.0
    parsed = _parse_iso8601(raw, "lastScanAt")
    if parsed is None:
        return 0.0
    return parsed.timestamp() * 1000.0


def _is_scan_timestamp_stale(last_scan_at: str | None, *, now_ms: float | None = None) -> bool:
    if not last_scan_at:
        return False
    if now_ms is None:
        now_ms = time.time() * 1000.0
    return now_ms - _last_scan_effective_time(last_scan_at) > 7 * 24 * 60 * 60 * 1000.0


@router.get("/{tenant_slug}/scan-reports", response_model=RepositoryScanReportListResponse)
async def list_repository_scan_reports(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    provider: str = Query("all", pattern="^(all|github|gitlab|bitbucket)$"),
    status: str = Query("all", pattern="^(all|importable|imported|failing|awaiting|stale)$"),
    q: str = Query(""),
    page: int = Query(1, ge=1),
    pageSize: int = Query(25, ge=1, le=100),
) -> RepositoryScanReportListResponse:
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = auth_data["tenant_id"]
    now_ms = time.time() * 1000.0
    qn = (q or "").strip().lower()
    with _STORE_LOCK:
        tenant_repos = list(_REPO_STORE.get(tenant_id, {}).values())
    rows: List[RepositoryScanReportListItem] = []
    for repo in tenant_repos:
        if provider != "all" and repo.provider != provider:
            continue
        if qn:
            blob = f"{repo.fullName} {repo.name} {repo.owner} {repo.id}".lower()
            if qn not in blob:
                continue
        last_scan = _get_repository_last_scan(repo.id)
        last_scan_at: str | None = None
        if last_scan is not None:
            last_scan_at = (last_scan.finishedAt or last_scan.startedAt or last_scan.createdAt) or None
        last_scan_id = last_scan.id if last_scan is not None else None
        with _STORE_LOCK:
            rlist = list(_REPO_SCAN_REPORT_STORE.get(repo.id, []))
        latest: Dict[str, Any] | None = max(rlist, key=lambda r: r["generatedAt"]) if rlist else None
        last_report_id: str | None = None
        if isinstance(latest, dict) and latest.get("id"):
            last_report_id = str(latest["id"])
        totals = None
        attention = 0
        if latest is not None:
            tj = latest.get("totalsJson")
            if isinstance(tj, dict):
                totals = dict(tj)
            attention = int(latest.get("attentionScore", 0) or 0)
        elif last_scan_at:
            attention = _scan_report_attention_score(
                {"failing": 0, "awaiting_selection": 0, "scanFailed": 0},
                last_scan_at=last_scan_at,
                now_ms=now_ms,
            )
        stale = _is_scan_timestamp_stale(last_scan_at, now_ms=now_ms)
        if status == "importable":
            if not totals or int(totals.get("importable", 0) or 0) < 1:
                continue
        elif status == "imported":
            if not totals or int(totals.get("imported", 0) or 0) < 1:
                continue
        elif status == "failing":
            if not totals:
                continue
            perr = int(totals.get("parseError", 0) or 0)
            merr = int(totals.get("manifestError", 0) or 0)
            fail = int(totals.get("failing", 0) or 0) or perr + merr
            if fail < 1 and not bool(totals.get("scanFailed")):
                continue
        elif status == "awaiting":
            if not totals or int(totals.get("awaitingSelection", 0) or 0) < 1:
                continue
        elif status == "stale":
            if not stale:
                continue
        rows.append(
            RepositoryScanReportListItem(
                repositoryId=repo.id,
                fullName=repo.fullName,
                provider=repo.provider,
                owner=repo.owner,
                name=repo.name,
                branchCount=len(repo.branches),
                lastScanAt=last_scan_at,
                lastScanId=last_scan_id,
                lastReportId=last_report_id,
                totals=totals,
                attentionScore=attention,
                stale=stale,
            )
        )

    rows.sort(
        key=lambda item: (item.attentionScore, _last_scan_effective_time(item.lastScanAt or "")),
        reverse=True,
    )
    total = len(rows)
    off = (page - 1) * pageSize
    page_items = rows[off : off + pageSize]
    return RepositoryScanReportListResponse(
        items=page_items,
        total=total,
        page=page,
        pageSize=pageSize,
    )


def _repositories_for_scan_report_export(
    tenant_id: str, *, provider: str, status: str, q: str
) -> list[RepositoryRecord]:
    """Repositories matching the tenant scan-report list (same as ``list_repository_scan_reports``)."""
    now_ms = time.time() * 1000.0
    qn = (q or "").strip().lower()
    with _STORE_LOCK:
        tenant_repos = list(_REPO_STORE.get(tenant_id, {}).values())
    out: list[tuple[RepositoryRecord, int, str]] = []
    for repo in tenant_repos:
        if provider != "all" and repo.provider != provider:
            continue
        if qn:
            blob = f"{repo.fullName} {repo.name} {repo.owner} {repo.id}".lower()
            if qn not in blob:
                continue
        last_scan = _get_repository_last_scan(repo.id)
        last_scan_at: str | None = None
        if last_scan is not None:
            last_scan_at = (last_scan.finishedAt or last_scan.startedAt or last_scan.createdAt) or None
        with _STORE_LOCK:
            rlist = list(_REPO_SCAN_REPORT_STORE.get(repo.id, []))
        latest: Dict[str, Any] | None = max(rlist, key=lambda r: r["generatedAt"]) if rlist else None
        totals: Dict[str, Any] | None = None
        attention = 0
        if latest is not None:
            tj = latest.get("totalsJson")
            if isinstance(tj, dict):
                totals = dict(tj)
            attention = int(latest.get("attentionScore", 0) or 0)
        elif last_scan_at:
            attention = _scan_report_attention_score(
                {"failing": 0, "awaiting_selection": 0, "scanFailed": 0},
                last_scan_at=last_scan_at,
                now_ms=now_ms,
            )
        stale = _is_scan_timestamp_stale(last_scan_at, now_ms=now_ms)
        if status == "importable":
            if not totals or int(totals.get("importable", 0) or 0) < 1:
                continue
        elif status == "imported":
            if not totals or int(totals.get("imported", 0) or 0) < 1:
                continue
        elif status == "failing":
            if not totals:
                continue
            perr = int(totals.get("parseError", 0) or 0)
            merr = int(totals.get("manifestError", 0) or 0)
            fail = int(totals.get("failing", 0) or 0) or perr + merr
            if fail < 1 and not bool(totals.get("scanFailed")):
                continue
        elif status == "awaiting":
            if not totals or int(totals.get("awaitingSelection", 0) or 0) < 1:
                continue
        elif status == "stale":
            if not stale:
                continue
        out.append((repo, attention, last_scan_at or ""))
    out.sort(
        key=lambda t: (t[1], _last_scan_effective_time(t[2] or "")),
        reverse=True,
    )
    return [t[0] for t in out]


def _export_scan_window_epoch_bounds(
    w_from: str | None, w_to: str | None
) -> tuple[float | None, float | None, bool]:
    if not w_from and not w_to:
        return None, None, False
    a = _parse_iso8601(w_from, "scan_window.from") if w_from and str(w_from).strip() else None
    b = _parse_iso8601(w_to, "scan_window.to") if w_to and str(w_to).strip() else None
    if w_from and str(w_from).strip() and a is None:
        raise ValueError("invalid scan window from")
    if w_to and str(w_to).strip() and b is None:
        raise ValueError("invalid scan window to")
    from_ms = a.timestamp() * 1000.0 if a is not None else None
    to_ms = b.timestamp() * 1000.0 if b is not None else None
    return from_ms, to_ms, True


def _export_reports_to_include(
    repository_id: str, *, from_ms: float | None, to_ms: float | None, has_window: bool
) -> list[Dict[str, Any]]:
    rows = _reports_for_repository_newest_first(repository_id)
    if not has_window:
        return [rows[0]] if rows else []
    picked: list[Dict[str, Any]] = []
    for row in rows:
        ga = row.get("generatedAt")
        p = _parse_iso8601(str(ga), "generatedAt") if ga else None
        if p is None:
            continue
        t = p.timestamp() * 1000.0
        if from_ms is not None and t < from_ms:
            continue
        if to_ms is not None and t > to_ms:
            continue
        picked.append(row)
    return picked


def _get_scan_by_id_for_repository(
    repository_id: str, scan_id: str
) -> Optional[RepositoryScanRecord]:
    with _STORE_LOCK:
        history = list(_REPO_SCAN_HISTORY_STORE.get(repository_id, []))
    for s in history:
        if s.id == scan_id:
            return s
    return None


def _get_file_in_scan_by_id(
    repository_id: str, scan_id: str, file_id: str
) -> Optional[RepositoryFileRecord]:
    with _STORE_LOCK:
        f_list = list(_REPO_SCAN_FILE_HISTORY_STORE.get(scan_id, []))
    for f in f_list:
        if f.id == file_id:
            return f
    return None


def _export_attention_reasons(
    file_row: RepositoryFileRecord | None, spec: RepositorySpecRecord, *, report_repo_stale: bool
) -> str:
    parts: list[str] = []
    if report_repo_stale:
        parts.append("repository_stale")
    parts.append(f"spec:{spec.status}")
    if (
        file_row is not None
        and not file_row.importEnabled
        and (file_row.confidence or 0) >= 0.5
        and file_row.tracked
        and file_row.status not in ("parse_error", "manifest_error", "removed")
    ):
        parts.append("awaiting_selection")
    seen: set[str] = set()
    out: list[str] = []
    for r in parts:
        r2 = (r or "").strip()
        if r2 and r2 not in seen:
            seen.add(r2)
            out.append(r2)
    return ";".join(out)


def count_scan_report_export_row_candidates(
    tenant_id: str,
    *,
    provider: str = "all",
    status: str = "all",
    search: str = "",
    scan_from: str | None = None,
    scan_to: str | None = None,
) -> int:
    try:
        f_ms, t_ms, has_w = _export_scan_window_epoch_bounds(scan_from, scan_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    repos = _repositories_for_scan_report_export(
        tenant_id, provider=provider, status=status, q=search
    )
    n = 0
    for repo in repos:
        for report in _export_reports_to_include(
            repo.id, from_ms=f_ms, to_ms=t_ms, has_window=has_w
        ):
            pl = report.get("payloadJson")
            if not isinstance(pl, list):
                continue
            n += sum(1 for p in pl if isinstance(p, dict))
    return n


def iter_scan_report_export_rows(
    tenant_id: str,
    *,
    provider: str = "all",
    status: str = "all",
    search: str = "",
    scan_from: str | None = None,
    scan_to: str | None = None,
) -> Iterator[dict[str, Any]]:
    try:
        f_ms, t_ms, has_w = _export_scan_window_epoch_bounds(scan_from, scan_to)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    now_ms = time.time() * 1000.0
    repos = _repositories_for_scan_report_export(
        tenant_id, provider=provider, status=status, q=search
    )
    for repo in repos:
        ls0 = _get_repository_last_scan(repo.id)
        lsa0: str | None = (
            (ls0.finishedAt or ls0.startedAt or ls0.createdAt) if ls0 is not None else None
        ) or None
        report_repo_stale = _is_scan_timestamp_stale(lsa0, now_ms=now_ms) if lsa0 else False
        for report in _export_reports_to_include(
            repo.id, from_ms=f_ms, to_ms=t_ms, has_window=has_w
        ):
            report_id = str(report.get("id", ""))
            scan_id = str(report.get("scanId", ""))
            scan = _get_scan_by_id_for_repository(repo.id, scan_id) if scan_id else None
            branch = (scan.branch if scan is not None else None) or (
                repo.branches[0].branch if repo.branches else ""
            )
            scanned_at = (scan.finishedAt or scan.startedAt or str(report.get("generatedAt", "")) or "") if scan is not None else str(report.get("generatedAt", ""))
            if not branch:
                continue
            j_by = _latest_import_jobs_by_path(repo.id, branch)
            pl2 = report.get("payloadJson")
            if not isinstance(pl2, list):
                continue
            for pitem in pl2:
                if not isinstance(pitem, dict):
                    continue
                fid = str(pitem.get("fileId", ""))
                frow = _get_file_in_scan_by_id(repo.id, scan_id, fid) if fid and scan_id else None
                if frow is not None:
                    job = j_by.get(frow.path)
                    spec = _build_repository_spec_record(frow, branch, job)
                else:
                    _VALID_SPEC_STATUSES = {
                        "importing", "imported", "parse_error", "manifest_error",
                        "not_imported", "unchanged_checksum", "mapping_required",
                    }
                    raw_status = pitem.get("status")
                    spec_status: RepositorySpecSelectionStatus = (
                        raw_status if raw_status in _VALID_SPEC_STATUSES else "not_imported"
                    )
                    spec = RepositorySpecRecord(
                        fileId=fid,
                        repositoryId=repo.id,
                        scanId=scan_id,
                        branch=branch,
                        path=str(pitem.get("path", "")),
                        format=str(pitem.get("format", "")) or None
                        if pitem.get("format")
                        else None,
                        confidence=float(pitem.get("confidence"))
                        if pitem.get("confidence") is not None
                        else None,
                        discriminator=None,
                        status=spec_status,
                        importEnabled=bool(pitem.get("importEnabled")),
                        autoImportEnabled=bool(pitem.get("autoImportEnabled")),
                        projectSlug=None,
                        versionStrategy=None,
                        mappingConflictKind=None,
                        lastImportedVersionId=None,
                        lastImportedAt=None,
                        createdAt=report.get("generatedAt", "") or "",
                    )
                att_s = _export_attention_reasons(frow, spec, report_repo_stale=report_repo_stale)
                chk = frow.contentChecksum if frow is not None else None
                vers = spec.lastImportedVersionId or ""
                yield {
                    "repository": repo.fullName,
                    "provider": repo.provider,
                    "branch": branch,
                    "scan_id": scan_id,
                    "scanned_at": str(scanned_at or ""),
                    "path": str(pitem.get("path", "")) if frow is None else frow.path,
                    "format": (frow.format or "") if frow is not None else (str(pitem.get("format") or "") or ""),
                    "confidence": frow.confidence
                    if frow is not None and frow.confidence is not None
                    else pitem.get("confidence"),
                    "status": spec.status,
                    "content_checksum": (chk or "") if frow is not None else str(pitem.get("contentChecksum") or ""),
                    "last_imported_version": vers,
                    "attention_reasons": att_s,
                    "reportId": report_id,
                    "payload": dict(pitem),
                }


@router.get(
    "/{tenant_slug}/{repository_id}/scan-reports",
    response_model=RepositoryPerRepoScanReportListResponse,
)
async def list_per_repository_scan_reports(
    tenant_slug: str,
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryPerRepoScanReportListResponse:
    _ = tenant_slug
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = auth_data["tenant_id"]
    _find_repository_for_tenant(tenant_id, repository_id)
    rows = _reports_for_repository_newest_first(repository_id)
    items: List[RepositoryPerRepoScanReportListItem] = []
    for row in rows:
        tj = row.get("totalsJson")
        if not isinstance(tj, dict):
            continue
        items.append(
            RepositoryPerRepoScanReportListItem(
                id=str(row.get("id", "")),
                scanId=str(row.get("scanId", "")),
                generatedAt=str(row.get("generatedAt", "")),
                attentionScore=int(row.get("attentionScore", 0) or 0),
                totals=dict(tj),
            )
        )
    return RepositoryPerRepoScanReportListResponse(
        items=items,
        total=len(items),
    )


@router.get("/{tenant_slug}/{repository_id}/scan-reports/latest")
async def redirect_to_latest_per_repository_scan_report(
    tenant_slug: str,
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RedirectResponse:
    _ = tenant_slug
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = auth_data["tenant_id"]
    _find_repository_for_tenant(tenant_id, repository_id)
    rows = _reports_for_repository_newest_first(repository_id)
    if not rows:
        raise HTTPException(
            status_code=404, detail="No materialized scan reports for this repository yet"
        )
    first = rows[0]
    rid = str(first.get("id", ""))
    target = f"/v1/repositories/{tenant_slug}/{repository_id}/scan-reports/{rid}"
    return RedirectResponse(url=target, status_code=302)


@router.get(
    "/{tenant_slug}/{repository_id}/scan-reports/{left_report_id}/diff/{right_report_id}",
    response_model=RepositoryScanReportDiffResponse,
)
async def diff_per_repository_scan_reports(
    tenant_slug: str,
    repository_id: str,
    left_report_id: str,
    right_report_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryScanReportDiffResponse:
    _ = tenant_slug
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = auth_data["tenant_id"]
    _find_repository_for_tenant(tenant_id, repository_id)
    _validate_uuid(left_report_id, "leftReportId")
    _validate_uuid(right_report_id, "rightReportId")
    l_row = _get_report_row_by_id(repository_id, left_report_id)
    r_row = _get_report_row_by_id(repository_id, right_report_id)
    if l_row is None or r_row is None:
        raise HTTPException(
            status_code=404, detail="One or both scan report rows were not found in this repository"
        )
    lt = l_row.get("totalsJson") if isinstance(l_row.get("totalsJson"), dict) else {}
    rt = r_row.get("totalsJson") if isinstance(r_row.get("totalsJson"), dict) else {}
    left_int = _coerce_report_totals_for_delta(lt)
    right_int = _coerce_report_totals_for_delta(rt)
    delta = _totals_delta_map(left_int, right_int)
    p_l = _file_paths_in_payload_row(l_row)
    p_r = _file_paths_in_payload_row(r_row)
    return RepositoryScanReportDiffResponse(
        left=RepositoryScanReportPairTotals(
            id=str(l_row.get("id", "")),
            generatedAt=str(l_row.get("generatedAt", "")),
            scanId=str(l_row.get("scanId", "")),
            totals=dict(lt),
        ),
        right=RepositoryScanReportPairTotals(
            id=str(r_row.get("id", "")),
            generatedAt=str(r_row.get("generatedAt", "")),
            scanId=str(r_row.get("scanId", "")),
            totals=dict(rt),
        ),
        totalsDelta=delta,
        filePathsOnlyInLeft=sorted(p_l - p_r),
        filePathsOnlyInRight=sorted(p_r - p_l),
        filePathsInBoth=len(p_l & p_r),
    )


@router.get(
    "/{tenant_slug}/{repository_id}/scan-reports/{scan_report_id}",
    response_model=RepositoryScanReportDetailResponse,
)
async def get_per_repository_scan_report(
    tenant_slug: str,
    repository_id: str,
    scan_report_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryScanReportDetailResponse:
    _ = tenant_slug
    if scan_report_id == "latest":
        raise HTTPException(
            status_code=400, detail="Use /scan-reports/latest for the latest snapshot redirect"
        )
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = auth_data["tenant_id"]
    _find_repository_for_tenant(tenant_id, repository_id)
    _validate_uuid(scan_report_id, "scanReportId")
    row = _get_report_row_by_id(repository_id, scan_report_id)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"Scan report not found: {scan_report_id}"
        )
    ordered = _reports_for_repository_newest_first(repository_id)
    return _build_scan_report_detail(repository_id, row, ordered=ordered)


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


@router.get(
    "/{tenant_slug}/{repository_id}/attention",
    response_model=RepositoryAttentionDetailResponse,
    summary="Per-repository attention detail with file paths (REPO-11.4 / #2952).",
)
async def get_repository_attention_detail(
    tenant_slug: str,
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryAttentionDetailResponse:
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    _ = tenant_slug
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    tenant_id = str(auth_data["tenant_id"])
    ctx = _attention_compute_input_for_repository(tenant_id, repository_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Repository not found: {repository_id}")
    _now_dt, now_iso, inp, prev = ctx
    rsn, ocnt, score, reason_paths = compute_attention_detail(inp)
    reasons_list = sorted(rsn)
    items = [RepositoryAttentionReasonDetail(reason=r, paths=reason_paths.get(r, [])) for r in reasons_list]
    last_change = str(prev.get("lastChangeAt") or now_iso) if prev else now_iso
    return RepositoryAttentionDetailResponse(
        reasons=reasons_list,
        items=items,
        openCount=ocnt,
        attentionScore=score,
        lastChangeAt=last_change,
        refreshedAt=_now_iso(),
    )


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
    actor_id = _resolve_actor_id(auth_data)
    _audit_row: Dict[str, Any] | None = None
    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail=f"Repository not found: {repository_id}")

        now = _utc_now_iso()
        repository.status = "archived"
        repository.archivedAt = now
        repository.updatedAt = now
        _audit_row = _append_audit_row(
            tenant_id,
            repository_id,
            "repository.archived",
            actor_id=actor_id,
            detail={"status": repository.status},
        )
    if _audit_row is not None:
        _persist_audit_row(_audit_row)
    return repository


@router.post("/{tenant_slug}/{repository_id}/unarchive", response_model=RepositoryRecord)
async def unarchive_repository(
    tenant_slug: str,
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryRecord:
    tenant_id = auth_data["tenant_id"]
    actor_id = _resolve_actor_id(auth_data)
    _audit_row: Dict[str, Any] | None = None
    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail=f"Repository not found: {repository_id}")

        repository.status = "healthy"
        repository.archivedAt = None
        repository.updatedAt = _utc_now_iso()
        _audit_row = _append_audit_row(
            tenant_id,
            repository_id,
            "repository.unarchived",
            actor_id=actor_id,
            detail={"status": repository.status},
        )
    if _audit_row is not None:
        _persist_audit_row(_audit_row)
    return repository


@router.post("/{tenant_slug}/{repository_id}/pause", response_model=RepositoryRecord)
async def pause_repository(
    tenant_slug: str,
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryRecord:
    tenant_id = auth_data["tenant_id"]
    actor_id = _resolve_actor_id(auth_data)
    _audit_row: Dict[str, Any] | None = None
    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail=f"Repository not found: {repository_id}")
        now = _utc_now_iso()
        repository.status = "paused"
        repository.updatedAt = now
        _REPO_AUTO_PAUSED.discard(repository_id)
        _audit_row = _append_audit_row(
            tenant_id,
            repository_id,
            "repository.paused",
            actor_id=actor_id,
            detail={"status": repository.status},
        )
    if _audit_row is not None:
        _persist_audit_row(_audit_row)
    _recompute_repository_attention(tenant_id, repository_id)
    return repository


@router.post("/{tenant_slug}/{repository_id}/auto-pause", response_model=RepositoryRecord)
async def auto_pause_repository(
    tenant_slug: str,
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryRecord:
    tenant_id = auth_data["tenant_id"]
    actor_id = _resolve_actor_id(auth_data)
    _audit_row: Dict[str, Any] | None = None
    with _STORE_LOCK:
        repository = _REPO_STORE.get(tenant_id, {}).get(repository_id)
        if repository is None:
            raise HTTPException(status_code=404, detail=f"Repository not found: {repository_id}")
        now = _utc_now_iso()
        repository.status = "paused"
        repository.updatedAt = now
        _REPO_AUTO_PAUSED.add(repository_id)
        _audit_row = _append_audit_row(
            tenant_id,
            repository_id,
            "repository.auto_paused",
            actor_id=actor_id,
            detail={"status": repository.status},
        )
    if _audit_row is not None:
        _persist_audit_row(_audit_row)
    _recompute_repository_attention(tenant_id, repository_id)
    return repository


@router.delete("/{tenant_slug}/{repository_id}", status_code=204)
async def delete_repository(
    tenant_slug: str,
    repository_id: str,
    request: RepositoryDeleteRequest = Body(...),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    tenant_id = auth_data["tenant_id"]
    actor_id = _resolve_actor_id(auth_data)
    _audit_row: Dict[str, Any] | None = None
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
        _REPO_SCAN_REPORT_STORE.pop(repository_id, None)
        _REPO_LATEST_REPORT_TOTALS.pop(repository_id, None)
        _REPO_ATTENTION.pop(repository_id, None)
        _REPO_AUTO_PAUSED.discard(repository_id)
        _refresh_repository_corpus_rollup_unsafe(tenant_id)
        _audit_row = _append_audit_row(
            tenant_id,
            repository_id,
            "repository.removed",
            actor_id=actor_id,
            detail={"fullName": repository.fullName},
        )

    if _audit_row is not None:
        _persist_audit_row(_audit_row)
    if "PYTEST_CURRENT_TEST" not in os.environ:
        try:
            db.delete_repository_attention_row(repository_id)
        except Exception:
            pass
    return Response(status_code=204)


@router.get("/{tenant_slug}/{repository_id}/scans", response_model=RepositoryScanPage)
async def list_repository_scans(
    tenant_slug: str,
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


@router.get("/{tenant_slug}/{repository_id}/scans/{scan_id}", response_model=RepositoryScanRecord)
async def get_repository_scan(
    tenant_slug: str,
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


@router.get("/{tenant_slug}/{repository_id}/scans/{scan_id}/files", response_model=RepositoryScanFilePage)
async def list_repository_scan_files(
    tenant_slug: str,
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


@router.get("/{tenant_slug}/{repository_id}/specs", response_model=RepositorySpecPage)
async def list_repository_specs(
    tenant_slug: str,
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    branch: str | None = Query(default=None),
    status: RepositorySpecSelectionStatus | None = Query(default=None),
    search: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    limit: int = Query(default=_DEFAULT_SCAN_PAGE_SIZE, ge=1, le=_MAX_SCAN_PAGE_SIZE),
    cursor: str | None = Query(default=None),
) -> RepositorySpecPage:
    tenant_id = auth_data["tenant_id"]
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    cursor_key: Tuple[datetime, str] | None = None
    if cursor:
        cursor_dt, cursor_id = _decode_cursor(cursor)
        cursor_key = (cursor_dt, cursor_id)

    normalized_branch = (branch or "").strip()
    normalized_search = (search or "").strip().lower()

    with _STORE_LOCK:
        repository = _find_repository_for_tenant(tenant_id, repository_id)
        effective_branch = normalized_branch
        if not effective_branch:
            if not repository.branches:
                raise HTTPException(status_code=400, detail="Repository has no branch configuration")
            effective_branch = repository.branches[0].branch

        scans = _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
        _TERMINAL_SCAN_STATUSES = {"complete", "skipped_unchanged"}
        latest_scan = next(
            (scan for scan in scans if scan.branch == effective_branch and scan.status in _TERMINAL_SCAN_STATUSES),
            None,
        )
        if latest_scan is None:
            raise HTTPException(status_code=404, detail=f"No scan found for branch: {effective_branch}")

        files = list(_REPO_SCAN_FILE_HISTORY_STORE.get(latest_scan.id, []))
        latest_jobs = _latest_import_jobs_by_path(repository_id, effective_branch)

    filtered: List[RepositorySpecRecord] = []
    for file_row in files:
        if file_row.status == "removed":
            continue
        spec_row = _build_repository_spec_record(
            file_row,
            effective_branch,
            latest_jobs.get(file_row.path),
        )
        if min_confidence is not None:
            row_confidence = spec_row.confidence
            if row_confidence is None or row_confidence < min_confidence:
                continue
        if status is not None and spec_row.status != status:
            continue
        if normalized_search and normalized_search not in spec_row.path.lower():
            continue
        row_dt = _parse_iso8601(spec_row.createdAt, "createdAt")
        if row_dt is None:
            continue
        if cursor_key is not None and (row_dt, spec_row.fileId) >= cursor_key:
            continue
        filtered.append(spec_row)

    filtered.sort(key=lambda item: _to_sort_key(item.createdAt, item.fileId), reverse=True)
    page_rows = filtered[: limit + 1]
    has_more = len(page_rows) > limit
    page_items = page_rows[:limit]
    next_cursor = None
    if has_more and page_items:
        tail = page_items[-1]
        next_cursor = _encode_cursor(tail.createdAt, tail.fileId)

    return RepositorySpecPage(items=page_items, limit=limit, nextCursor=next_cursor)


@router.patch(
    "/{tenant_slug}/{repository_id}/specs/{file_id}",
    response_model=RepositorySpecRecord,
)
async def update_repository_spec_selection(
    tenant_slug: str,
    repository_id: str,
    file_id: str,
    request: RepositorySpecUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositorySpecRecord:
    tenant_id = auth_data["tenant_id"]
    actor_id = _resolve_actor_id(auth_data)
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_WRITE)
    _validate_uuid(file_id, "fileId")

    audits_to_persist: List[Dict[str, Any]] = []
    with _STORE_LOCK:
        _find_repository_for_tenant(tenant_id, repository_id)
        out_row: RepositoryFileRecord | None = None
        out_branch: str | None = None
        for scan in _REPO_SCAN_HISTORY_STORE.get(repository_id, []):
            file_list = _REPO_SCAN_FILE_HISTORY_STORE.get(scan.id, [])
            for idx, file_row in enumerate(file_list):
                if file_row.id != file_id:
                    continue
                updated, changes = _apply_selection_update(
                    file_row,
                    import_enabled=request.importEnabled,
                    auto_import_enabled=request.autoImportEnabled,
                    selection_actor_id=actor_id if actor_id != _SYSTEM_ACTOR_ID else None,
                )
                file_list[idx] = updated
                out_row = updated
                out_branch = scan.branch
                for change in changes:
                    audits_to_persist.append(
                        _append_audit_row(
                            tenant_id,
                            repository_id,
                            "repository.spec.selection_changed",
                            actor_id=actor_id,
                            detail={
                                "path": file_row.path,
                                "before": change["before"],
                                "after": change["after"],
                                "actorId": actor_id,
                                "field": change["field"],
                                "source": "api",
                            },
                        )
                    )
                break
            if out_row is not None:
                break
        if out_row is None or out_branch is None:
            raise HTTPException(status_code=404, detail=f"Repository file not found: {file_id}")
        latest_job = _latest_import_jobs_by_path(repository_id, out_branch).get(out_row.path)
        out_spec = _build_repository_spec_record(out_row, out_branch, latest_job)

    for row in audits_to_persist:
        _persist_audit_row(row)
    _recompute_repository_attention(tenant_id, repository_id)
    return out_spec


@router.patch(
    "/{tenant_slug}/{repository_id}/specs/{file_id}/mapping",
    response_model=RepositorySpecRecord,
)
async def resolve_repository_spec_mapping(
    tenant_slug: str,
    repository_id: str,
    file_id: str,
    request: RepositorySpecMappingResolveRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositorySpecRecord:
    """Resolve REPO-12.2 project-mapping conflicts and retry auto-import."""
    tenant_id = auth_data["tenant_id"]
    actor_id = _resolve_actor_id(auth_data)
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_WRITE)
    _validate_uuid(file_id, "fileId")

    audits_to_persist: List[Dict[str, Any]] = []
    out_spec: RepositorySpecRecord | None = None

    with _STORE_LOCK:
        repository = _find_repository_for_tenant(tenant_id, repository_id)
        if not repository.branches:
            raise HTTPException(status_code=400, detail="Repository has no branch configuration")

        requested_branch = (request.branch or "").strip()
        if not requested_branch:
            effective_branch = repository.branches[0].branch
        else:
            if not any(branch.branch == requested_branch for branch in repository.branches):
                raise HTTPException(
                    status_code=404,
                    detail=f"Branch {requested_branch!r} is not configured for this repository",
                )
            effective_branch = requested_branch

        _TERMINAL = {"complete", "skipped_unchanged"}
        scans = _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
        latest_scan: RepositoryScanRecord | None = next(
            (scan for scan in scans if scan.branch == effective_branch and scan.status in _TERMINAL),
            None,
        )
        if latest_scan is None:
            raise HTTPException(status_code=404, detail=f"No completed scan for branch: {effective_branch}")

        file_list = _REPO_SCAN_FILE_HISTORY_STORE.get(latest_scan.id, [])
        file_idx: int | None = None
        working_row: RepositoryFileRecord | None = None
        for idx, row in enumerate(file_list):
            if row.id == file_id:
                file_idx = idx
                working_row = row
                break
        if working_row is None or file_idx is None:
            raise HTTPException(status_code=404, detail=f"Repository file not found: {file_id}")

        if working_row.status != "mapping_required":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "SPEC_NOT_MAPPING_REQUIRED",
                    "message": "This spec is not awaiting project mapping.",
                },
            )

        if request.decision == "defer":
            audits_to_persist.append(
                _append_audit_row(
                    tenant_id,
                    repository_id,
                    "repository.spec.mapping_resolved",
                    actor_id=actor_id,
                    detail={
                        "path": working_row.path,
                        "fileId": file_id,
                        "decision": "defer",
                        "actorId": actor_id,
                    },
                )
            )
            latest_job = _latest_import_jobs_by_path(repository_id, effective_branch).get(working_row.path)
            out_spec = _build_repository_spec_record(working_row, effective_branch, latest_job)
        else:
            next_row: RepositoryFileRecord
            if request.decision == "map_existing":
                slug_norm = _normalize_slug(request.projectSlug)
                if slug_norm is None:
                    raise HTTPException(
                        status_code=400,
                        detail={"code": "INVALID_SLUG", "message": "projectSlug is required for map_existing"},
                    )
                if not _tenant_project_slug_exists(tenant_id, slug_norm):
                    raise HTTPException(
                        status_code=400,
                        detail={"code": "PROJECT_NOT_FOUND", "message": "Unknown project slug for this tenant"},
                    )
                vs_choice = request.versionStrategy
                raw_row_vs = working_row.versionStrategy
                vs_norm = (
                    vs_choice.strip().lower()
                    if isinstance(vs_choice, str) and vs_choice.strip()
                    else (
                        raw_row_vs.strip().lower()
                        if isinstance(raw_row_vs, str) and raw_row_vs.strip()
                        else "commit-sha"
                    )
                )
                next_row = working_row.model_copy(
                    update={
                        "projectSlug": slug_norm,
                        "versionStrategy": vs_norm,
                    }
                )
            elif request.decision == "create_new":
                slug_norm = _normalize_slug(request.projectSlug)
                if slug_norm is None:
                    raise HTTPException(
                        status_code=400,
                        detail={"code": "INVALID_SLUG", "message": "projectSlug is required for create_new"},
                    )
                vs_choice = request.versionStrategy
                if not isinstance(vs_choice, str) or not vs_choice.strip():
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "code": "VERSION_STRATEGY_REQUIRED",
                            "message": "versionStrategy is required for create_new",
                        },
                    )
                vs_norm = vs_choice.strip().lower()
                if _tenant_project_slug_exists(tenant_id, slug_norm):
                    raise HTTPException(
                        status_code=409,
                        detail={"code": "SLUG_TAKEN", "message": "A project with this slug already exists"},
                    )
                now_iso = _utc_now_iso()
                created_proj = RepositoryResolvedProjectRecord(
                    id=str(uuid4()),
                    tenantId=tenant_id,
                    slug=slug_norm,
                    name=slug_norm.replace("-", " ").title(),
                    createdAt=now_iso,
                    origin="mapped",
                    createdFromRepositoryId=repository_id,
                    defaultVersionStrategy=vs_norm,
                )
                _REPO_PROJECT_STORE.setdefault(tenant_id, {})[slug_norm] = created_proj
                next_row = working_row.model_copy(
                    update={
                        "projectSlug": slug_norm,
                        "versionStrategy": vs_norm,
                    }
                )
            else:
                raise HTTPException(status_code=400, detail="Invalid mapping decision")

            sj = dict(next_row.settingsJson or {})
            pre_st = sj.pop("preMappingScanStatus", None)
            sj.pop("mappingConflictKind", None)
            restored_status: RepositoryFileStatus
            if isinstance(pre_st, str) and pre_st in {
                "new",
                "modified",
                "unchanged",
                "unchanged_checksum",
                "discovered",
                "ready_to_promote",
            }:
                restored_status = pre_st  # type: ignore[assignment]
            else:
                restored_status = "modified"
            next_row = next_row.model_copy(
                update={"status": restored_status, "settingsJson": sj or None, "discriminator": None}
            )

            commit_sha = latest_scan.commitSha
            if not (isinstance(commit_sha, str) and commit_sha.strip()):
                raise HTTPException(status_code=500, detail="Repository scan is missing a commit reference for import dispatch.")

            new_job, job_audits = _materialize_repository_dry_run_import_job(
                tenant_id=tenant_id,
                repository_id=repository_id,
                scan_id=latest_scan.id,
                branch=effective_branch,
                commit_sha=commit_sha.strip(),
                file_row=next_row,
                actor_id=actor_id,
                source_kind="repository_auto_import",
            )
            file_list[file_idx] = next_row
            audits_to_persist.extend(job_audits)
            audits_to_persist.append(
                _append_audit_row(
                    tenant_id,
                    repository_id,
                    "repository.spec.mapping_resolved",
                    actor_id=actor_id,
                    detail={
                        "path": next_row.path,
                        "fileId": file_id,
                        "decision": request.decision,
                        "projectSlug": next_row.projectSlug,
                        "versionStrategy": next_row.versionStrategy,
                        "importJobId": new_job.id,
                        "actorId": actor_id,
                    },
                )
            )
            latest_job = _latest_import_jobs_by_path(repository_id, effective_branch).get(next_row.path)
            out_spec = _build_repository_spec_record(next_row, effective_branch, latest_job)

    if out_spec is None:
        raise HTTPException(status_code=500, detail="Mapping resolution failed")

    for row in audits_to_persist:
        _persist_audit_row(row)
    _recompute_repository_attention(tenant_id, repository_id)
    return out_spec


@router.post(
    "/{tenant_slug}/{repository_id}/specs/{file_id}:importNow",
    status_code=202,
    response_model=RepositorySpecImportNowResponse,
    responses={202: {"model": RepositorySpecImportNowResponse}},
)
async def import_repository_spec_now(
    tenant_slug: str,
    repository_id: str,
    file_id: str,
    request: RepositorySpecImportNowRequest = Body(...),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> JSONResponse:
    """Dispatch a one-shot dry-run import for the latest scan snapshot (REPO-9.5)."""
    tenant_id = auth_data["tenant_id"]
    actor_id = _resolve_actor_id(auth_data)
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_WRITE)
    _validate_uuid(file_id, "fileId")

    with _STORE_LOCK:
        repository = _find_repository_for_tenant(tenant_id, repository_id)
        if not repository.branches:
            raise HTTPException(status_code=400, detail="Repository has no branch configuration")

        requested_branch = (request.branch or "").strip()
        if not requested_branch:
            effective_branch = repository.branches[0].branch
        else:
            if not any(branch.branch == requested_branch for branch in repository.branches):
                raise HTTPException(
                    status_code=404,
                    detail=f"Branch {requested_branch!r} is not configured for this repository",
                )
            effective_branch = requested_branch

        _TERMINAL = {"complete", "skipped_unchanged"}
        scans = _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
        latest_scan: RepositoryScanRecord | None = next(
            (scan for scan in scans if scan.branch == effective_branch and scan.status in _TERMINAL),
            None,
        )
        if latest_scan is None:
            raise HTTPException(
                status_code=404,
                detail=f"No completed scan for branch: {effective_branch}",
            )
        file_list = _REPO_SCAN_FILE_HISTORY_STORE.get(latest_scan.id, [])
        file_row: RepositoryFileRecord | None = next(
            (row for row in file_list if row.id == file_id),
            None,
        )
        if file_row is None:
            raise HTTPException(status_code=404, detail=f"Repository file not found: {file_id}")
        if file_row.status == "removed":
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "SPEC_REMOVED",
                    "message": "This path was removed in the latest scan; re-import is not available.",
                },
            )
        if not file_row.tracked:
            raise HTTPException(
                status_code=400,
                detail={"code": "SPEC_NOT_TRACKED", "message": "This path is not tracked in the scan manifest."},
            )
        if not file_row.importEnabled:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "IMPORT_NOT_ENABLED",
                    "message": "import_enabled is false; enable import for this spec before using Import Now.",
                },
            )

        dup_id = _import_now_idempotency_lookup(repository_id, file_id, effective_branch)
        if dup_id is not None:
            return JSONResponse(
                status_code=202,
                content=RepositorySpecImportNowResponse(importJobId=dup_id).model_dump(),
            )

    assert file_row is not None
    if not request.force:
        current_checksum = _normalize_content_checksum(file_row.contentChecksum)
        if current_checksum is not None:
            try:
                latest_checksum = _latest_repository_source_checksum_for_file(
                    tenant_id=tenant_id,
                    repository_id=repository_id,
                    file_row=file_row,
                )
            except Exception:
                latest_checksum = None
            if latest_checksum is not None and latest_checksum == current_checksum:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "IMPORT_UNCHANGED_CHECKSUM",
                        "message": "No import dispatched; file content matches the last imported snapshot (re-run with force: true to bypass).",
                    },
                )

    with _STORE_LOCK:
        dup_id2 = _import_now_idempotency_lookup(repository_id, file_id, effective_branch)
        if dup_id2 is not None:
            return JSONResponse(
                status_code=202,
                content=RepositorySpecImportNowResponse(importJobId=dup_id2).model_dump(),
            )

        _TERMINAL2 = {"complete", "skipped_unchanged"}
        latest_scan2 = next(
            (
                scan
                for scan in _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
                if scan.branch == effective_branch and scan.status in _TERMINAL2
            ),
            None,
        )
        if latest_scan2 is None or latest_scan2.id != latest_scan.id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "REPOSITORY_STALE",
                    "message": "The repository scan changed; refresh and try again.",
                },
            )
        file_list2 = _REPO_SCAN_FILE_HISTORY_STORE.get(latest_scan2.id, [])
        file_idx = next(
            (idx for idx, row in enumerate(file_list2) if row.id == file_id),
            None,
        )
        if file_idx is None:
            raise HTTPException(status_code=404, detail=f"Repository file not found: {file_id}")
        working_row = file_list2[file_idx]
        if not working_row.importEnabled or not working_row.tracked or working_row.status == "removed":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "REPOSITORY_STALE",
                    "message": "The spec state changed; refresh and try again.",
                },
            )

        commit_sha = latest_scan2.commitSha
        if not (isinstance(commit_sha, str) and commit_sha.strip()):
            raise HTTPException(
                status_code=500,
                detail="Repository scan is missing a commit reference for import dispatch.",
            )

        new_job, job_audits = _materialize_repository_dry_run_import_job(
            tenant_id=tenant_id,
            repository_id=repository_id,
            scan_id=latest_scan2.id,
            branch=effective_branch,
            commit_sha=commit_sha,
            file_row=working_row,
            actor_id=actor_id,
            source_kind="repository_manual_import",
        )
        _import_now_idempotency_store(repository_id, file_id, effective_branch, new_job.id)

        import_audit = _append_audit_row(
            tenant_id,
            repository_id,
            "repository.spec.import_now_triggered",
            actor_id=actor_id,
            detail={
                "path": working_row.path,
                "fileId": file_id,
                "branch": effective_branch,
                "force": request.force,
                "actorId": actor_id,
                "importJobId": new_job.id,
                "scanId": latest_scan2.id,
            },
        )
        all_audits = job_audits + [import_audit]

    for row in all_audits:
        _persist_audit_row(row)
    _recompute_repository_attention(tenant_id, repository_id)
    return JSONResponse(
        status_code=202,
        content=RepositorySpecImportNowResponse(importJobId=new_job.id).model_dump(),
    )


@router.get(
    "/{tenant_slug}/{repository_id}/specs/{file_id}/detail",
    response_model=RepositorySpecDetailResponse,
)
async def get_repository_spec_detail(
    tenant_slug: str,
    repository_id: str,
    file_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    limit: int = Query(default=5, ge=1, le=20),
) -> RepositorySpecDetailResponse:
    """Return aggregated spec-detail metadata for the drawer (REPO-9.6).

    The endpoint joins the latest scan record, the last N import jobs for
    ``(branch, path)``, and a derived lint summary. Lazy-load contract: the
    drawer only calls this when it opens, so closed-drawer rendering does
    not pay a fan-out cost.
    """
    tenant_id = auth_data["tenant_id"]
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    _validate_uuid(file_id, "fileId")

    with _STORE_LOCK:
        repository = _find_repository_for_tenant(tenant_id, repository_id)
        located = _find_repository_file_row(repository_id, file_id)
        if located is None:
            raise HTTPException(status_code=404, detail=f"Repository file not found: {file_id}")
        file_row, scan = located
        recent_jobs = _list_recent_imports_for_path(repository_id, scan.branch, file_row.path, limit=limit)
        latest_job_for_path = _latest_import_jobs_by_path(repository_id, scan.branch).get(file_row.path)
        spec_record = _build_repository_spec_record(file_row, scan.branch, latest_job_for_path)
        recent_summaries = [
            _build_spec_import_summary(job=job, repository_id=repository_id) for job in recent_jobs
        ]

        latest_non_failed = next(
            (
                job
                for job in recent_jobs
                if job.state in ("committed", "pending_review")
            ),
            None,
        )
        if latest_non_failed is not None:
            change_report = _find_change_report_for_import_job(repository_id, latest_non_failed.id)
            change_model = change_report.changeModelJson if change_report is not None else None
            lint = derive_lint_summary(job=latest_non_failed.model_dump(), change_model=change_model)
        elif recent_jobs:
            lint = derive_lint_summary(job=recent_jobs[0].model_dump(), change_model=None)
        else:
            lint = empty_lint_summary()

    web_url = provider_blob_url(
        provider=repository.provider,
        owner=repository.owner,
        name=repository.name,
        branch=scan.branch,
        path=file_row.path,
    )
    raw_url = provider_raw_url(
        provider=repository.provider,
        owner=repository.owner,
        name=repository.name,
        branch=scan.branch,
        path=file_row.path,
    )

    return RepositorySpecDetailResponse(
        spec=spec_record,
        branch=scan.branch,
        path=file_row.path,
        fullName=repository.fullName,
        provider=repository.provider,
        providerWebUrl=web_url,
        providerRawUrl=raw_url,
        recentImports=recent_summaries,
        lintSummary=RepositorySpecLintSummary(**lint.to_payload()),
    )


@router.get(
    "/{tenant_slug}/{repository_id}/specs/{file_id}/content",
    response_model=RepositorySpecContentResponse,
)
async def get_repository_spec_content(
    tenant_slug: str,
    repository_id: str,
    file_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositorySpecContentResponse:
    """Return inline file bytes for the drawer's Monaco preview (REPO-9.6).

    Files larger than ``MAX_INLINE_PREVIEW_BYTES`` (2 MB) are not inlined;
    instead the response sets ``tooLargeForPreview = true`` and exposes
    a ``providerRawUrl`` the user can download. Binary payloads return
    ``encoding='base64'`` so the UI can show a "binary file — download"
    affordance without misrendering.
    """
    tenant_id = auth_data["tenant_id"]
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_READ)
    _validate_uuid(file_id, "fileId")

    with _STORE_LOCK:
        repository = _find_repository_for_tenant(tenant_id, repository_id)
        located = _find_repository_file_row(repository_id, file_id)
        if located is None:
            raise HTTPException(status_code=404, detail=f"Repository file not found: {file_id}")
        file_row, scan = located

    raw_url = provider_raw_url(
        provider=repository.provider,
        owner=repository.owner,
        name=repository.name,
        branch=scan.branch,
        path=file_row.path,
    )

    declared_size = file_row.sizeBytes if isinstance(file_row.sizeBytes, int) else None
    if declared_size is not None and declared_size > MAX_INLINE_PREVIEW_BYTES:
        return RepositorySpecContentResponse(
            fileId=file_row.id,
            repositoryId=repository_id,
            branch=scan.branch,
            path=file_row.path,
            format=file_row.format,
            encoding="utf-8",
            content=None,
            sizeBytes=declared_size,
            truncated=False,
            tooLargeForPreview=True,
            contentChecksum=file_row.contentChecksum,
            providerRawUrl=raw_url,
            fetchedAt=_utc_now_iso(),
        )

    try:
        payload = _fetch_file_content_bytes(repository=repository, file_row=file_row, branch=scan.branch)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "PROVIDER_FETCH_FAILED", "message": str(exc)},
        ) from exc

    actual_size = len(payload)
    if actual_size > MAX_INLINE_PREVIEW_BYTES:
        return RepositorySpecContentResponse(
            fileId=file_row.id,
            repositoryId=repository_id,
            branch=scan.branch,
            path=file_row.path,
            format=file_row.format,
            encoding="utf-8",
            content=None,
            sizeBytes=actual_size,
            truncated=False,
            tooLargeForPreview=True,
            contentChecksum=file_row.contentChecksum,
            providerRawUrl=raw_url,
            fetchedAt=_utc_now_iso(),
        )

    if _looks_like_text_bytes(payload):
        text = payload.decode("utf-8")
        return RepositorySpecContentResponse(
            fileId=file_row.id,
            repositoryId=repository_id,
            branch=scan.branch,
            path=file_row.path,
            format=file_row.format,
            encoding="utf-8",
            content=text,
            sizeBytes=actual_size,
            truncated=False,
            tooLargeForPreview=False,
            contentChecksum=file_row.contentChecksum,
            providerRawUrl=raw_url,
            fetchedAt=_utc_now_iso(),
        )

    encoded = base64.b64encode(payload).decode("ascii")
    if len(encoded) > MAX_INLINE_PREVIEW_BYTES:
        return RepositorySpecContentResponse(
            fileId=file_row.id,
            repositoryId=repository_id,
            branch=scan.branch,
            path=file_row.path,
            format=file_row.format,
            encoding="utf-8",
            content=None,
            sizeBytes=actual_size,
            truncated=False,
            tooLargeForPreview=True,
            contentChecksum=file_row.contentChecksum,
            providerRawUrl=raw_url,
            fetchedAt=_utc_now_iso(),
        )

    return RepositorySpecContentResponse(
        fileId=file_row.id,
        repositoryId=repository_id,
        branch=scan.branch,
        path=file_row.path,
        format=file_row.format,
        encoding="base64",
        content=encoded,
        sizeBytes=actual_size,
        truncated=False,
        tooLargeForPreview=False,
        contentChecksum=file_row.contentChecksum,
        providerRawUrl=raw_url,
        fetchedAt=_utc_now_iso(),
    )


@router.post(
    "/{tenant_slug}/{repository_id}/specs:bulkUpdate",
    response_model=RepositorySpecBulkUpdateResponse,
)
async def bulk_update_repository_spec_selection(
    tenant_slug: str,
    repository_id: str,
    request: RepositorySpecBulkUpdateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositorySpecBulkUpdateResponse:
    tenant_id = auth_data["tenant_id"]
    actor_id = _resolve_actor_id(auth_data)
    _require_repository_scope(auth_data, _REPOSITORY_SCOPE_WRITE)

    for file_id in request.fileIds:
        _validate_uuid(file_id, "fileId")

    audits_to_persist: List[Dict[str, Any]] = []
    with _STORE_LOCK:
        _find_repository_for_tenant(tenant_id, repository_id)
        indexed_rows: Dict[str, Tuple[str, int, RepositoryFileRecord, str]] = {}
        for scan in _REPO_SCAN_HISTORY_STORE.get(repository_id, []):
            file_list = _REPO_SCAN_FILE_HISTORY_STORE.get(scan.id, [])
            for idx, file_row in enumerate(file_list):
                indexed_rows[file_row.id] = (scan.id, idx, file_row, scan.branch)

        missing_ids = [file_id for file_id in request.fileIds if file_id not in indexed_rows]
        if missing_ids:
            raise HTTPException(status_code=404, detail=f"Repository file not found: {missing_ids[0]}")

        updates: List[Tuple[str, str, int, RepositoryFileRecord, RepositoryFileRecord, List[Dict[str, Any]], str]] = []
        for file_id in request.fileIds:
            scan_id, idx, existing_row, branch_name = indexed_rows[file_id]
            updated_row, changes = _apply_selection_update(
                existing_row,
                import_enabled=request.importEnabled,
                auto_import_enabled=request.autoImportEnabled,
                selection_actor_id=actor_id if actor_id != _SYSTEM_ACTOR_ID else None,
            )
            updates.append((file_id, scan_id, idx, existing_row, updated_row, changes, branch_name))

        for _file_id, scan_id, idx, existing_row, updated_row, changes, _branch_name in updates:
            file_list = _REPO_SCAN_FILE_HISTORY_STORE.get(scan_id, [])
            file_list[idx] = updated_row
            for change in changes:
                audits_to_persist.append(
                    _append_audit_row(
                        tenant_id,
                        repository_id,
                        "repository.spec.selection_changed",
                        actor_id=actor_id,
                        detail={
                            "path": existing_row.path,
                            "before": change["before"],
                            "after": change["after"],
                            "actorId": actor_id,
                            "field": change["field"],
                            "source": "api",
                        },
                    )
                )

        latest_jobs_by_branch: Dict[str, Dict[str, RepositoryImportJobRecord]] = {}
        response_items: List[RepositorySpecRecord] = []
        changed_file_ids: set[str] = set()
        for _file_id, _scan_id, _idx, _existing_row, updated_row, changes, branch_name in updates:
            latest_jobs = latest_jobs_by_branch.get(branch_name)
            if latest_jobs is None:
                latest_jobs = _latest_import_jobs_by_path(repository_id, branch_name)
                latest_jobs_by_branch[branch_name] = latest_jobs
            if changes:
                changed_file_ids.add(updated_row.id)
            response_items.append(
                _build_repository_spec_record(updated_row, branch_name, latest_jobs.get(updated_row.path))
            )

    for row in audits_to_persist:
        _persist_audit_row(row)
    _recompute_repository_attention(tenant_id, repository_id)
    updated_count = len(changed_file_ids)
    return RepositorySpecBulkUpdateResponse(updatedCount=updated_count, items=response_items)


@router.patch(
    "/{tenant_slug}/{repository_id}/files/{file_id}/import-enabled",
    response_model=RepositoryFileRecord,
)
async def update_repository_file_import_enabled(
    tenant_slug: str,
    repository_id: str,
    file_id: str,
    request: RepositoryFileImportEnabledRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryFileRecord:
    """Toggle whether a spec path may dispatch import work (per REPO-9.1)."""
    tenant_id = auth_data["tenant_id"]
    actor_id = _resolve_actor_id(auth_data)
    _validate_uuid(file_id, "fileId")

    audit_to_persist: Dict[str, Any] | None = None
    with _STORE_LOCK:
        _find_repository_for_tenant(tenant_id, repository_id)
        out_row: RepositoryFileRecord | None = None
        for _scan in _REPO_SCAN_HISTORY_STORE.get(repository_id, []):
            file_list = _REPO_SCAN_FILE_HISTORY_STORE.get(_scan.id, [])
            for idx, file_row in enumerate(file_list):
                if file_row.id == file_id:
                    before = file_row.importEnabled
                    after = request.importEnabled
                    if before == after:
                        return file_row
                    sel_actor = (
                        actor_id if actor_id != _SYSTEM_ACTOR_ID else file_row.importSelectionActorId
                    )
                    updated = file_row.model_copy(
                        update={
                            "importEnabled": after,
                            "autoImportEnabled": file_row.autoImportEnabled if after else False,
                            "importSelectionActorId": sel_actor,
                        }
                    )
                    file_list[idx] = updated
                    out_row = updated
                    audit_to_persist = _append_audit_row(
                        tenant_id,
                        repository_id,
                        "repository.spec.selection_changed",
                        actor_id=actor_id,
                        detail={
                            "path": file_row.path,
                            "before": before,
                            "after": after,
                            "actorId": actor_id,
                            "field": "import_enabled",
                            "source": request.source,
                        },
                    )
                    break
            if out_row is not None:
                break
        if out_row is None:
            raise HTTPException(status_code=404, detail=f"Repository file not found: {file_id}")
    if audit_to_persist is not None:
        _persist_audit_row(audit_to_persist)
    _recompute_repository_attention(tenant_id, repository_id)
    return out_row


@router.patch(
    "/{tenant_slug}/{repository_id}/files/{file_id}/auto-import-enabled",
    response_model=RepositoryFileRecord,
)
async def update_repository_file_auto_import_enabled(
    tenant_slug: str,
    repository_id: str,
    file_id: str,
    request: RepositoryFileAutoImportEnabledRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryFileRecord:
    """Toggle whether a spec path is eligible for automatic import dispatch (REPO-9.2)."""
    tenant_id = auth_data["tenant_id"]
    actor_id = _resolve_actor_id(auth_data)
    _validate_uuid(file_id, "fileId")

    audit_to_persist: Dict[str, Any] | None = None
    with _STORE_LOCK:
        _find_repository_for_tenant(tenant_id, repository_id)
        out_row: RepositoryFileRecord | None = None
        for _scan in _REPO_SCAN_HISTORY_STORE.get(repository_id, []):
            file_list = _REPO_SCAN_FILE_HISTORY_STORE.get(_scan.id, [])
            for idx, file_row in enumerate(file_list):
                if file_row.id == file_id:
                    if request.autoImportEnabled and not file_row.importEnabled:
                        raise HTTPException(
                            status_code=400,
                            detail="autoImportEnabled cannot be true when importEnabled is false",
                        )
                    before = file_row.autoImportEnabled
                    after = request.autoImportEnabled
                    if before == after:
                        return file_row
                    updated = file_row.model_copy(update={"autoImportEnabled": after})
                    file_list[idx] = updated
                    out_row = updated
                    audit_to_persist = _append_audit_row(
                        tenant_id,
                        repository_id,
                        "repository.spec.selection_changed",
                        actor_id=actor_id,
                        detail={
                            "path": file_row.path,
                            "before": before,
                            "after": after,
                            "actorId": actor_id,
                            "field": "auto_import_enabled",
                            "source": request.source,
                        },
                    )
                    break
            if out_row is not None:
                break
        if out_row is None:
            raise HTTPException(status_code=404, detail=f"Repository file not found: {file_id}")
    if audit_to_persist is not None:
        _persist_audit_row(audit_to_persist)
    _recompute_repository_attention(tenant_id, repository_id)
    return out_row


@router.get("/{tenant_slug}/{repository_id}/sync-history", response_model=RepositoryImportJobPage)
async def list_repository_sync_history(
    tenant_slug: str,
    repository_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
    state: ImportJobStatus | None = Query(default=None),
    has_conflicts: bool | None = Query(default=None, alias="hasConflicts"),
    limit: int = Query(default=_DEFAULT_SCAN_PAGE_SIZE, ge=1, le=_MAX_SCAN_PAGE_SIZE),
    cursor: str | None = Query(default=None),
) -> RepositoryImportJobPage:
    tenant_id = auth_data["tenant_id"]
    cursor_key: Tuple[datetime, str] | None = None
    if cursor:
        cursor_dt, cursor_id = _decode_cursor(cursor)
        cursor_key = (cursor_dt, cursor_id)

    with _STORE_LOCK:
        _find_repository_for_tenant(tenant_id, repository_id)
        jobs = list(_REPO_IMPORT_JOB_STORE.get(repository_id, []))

    filtered: List[RepositoryImportJobRecord] = []
    for job in jobs:
        if state is not None and job.state != state:
            continue
        if has_conflicts is not None and (len(job.conflictRecords) > 0) != has_conflicts:
            continue
        created_dt = _parse_iso8601(job.createdAt, "createdAt")
        if created_dt is None:
            continue
        if cursor_key is not None and (created_dt, job.id) >= cursor_key:
            continue
        filtered.append(job)

    filtered.sort(key=lambda item: _to_sort_key(item.createdAt, item.id), reverse=True)
    page_rows = filtered[: limit + 1]
    has_more = len(page_rows) > limit
    page_items = page_rows[:limit]
    next_cursor = None
    if has_more and page_items:
        tail = page_items[-1]
        next_cursor = _encode_cursor(tail.createdAt, tail.id)
    return RepositoryImportJobPage(items=page_items, limit=limit, nextCursor=next_cursor)


@router.post(
    "/{tenant_slug}/{repository_id}/sync-history/{import_job_id}/resolve-conflict",
    response_model=RepositoryImportJobRecord,
)
async def resolve_repository_sync_conflict(
    tenant_slug: str,
    repository_id: str,
    import_job_id: str,
    request: RepositorySyncConflictResolutionRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryImportJobRecord:
    tenant_id = auth_data["tenant_id"]
    with _STORE_LOCK:
        _find_repository_for_tenant(tenant_id, repository_id)
        import_job = _find_import_job_for_repository(repository_id, import_job_id)
        if import_job is None:
            raise HTTPException(status_code=404, detail=f"Import job not found: {import_job_id}")
        normalized_schema_name = request.schemaName.strip()
        conflict_record = next(
            (conflict for conflict in import_job.conflictRecords if conflict.get("schemaName") == normalized_schema_name),
            None,
        )
        if conflict_record is None:
            raise HTTPException(status_code=404, detail=f"Conflict not found for schema: {normalized_schema_name}")
        canonical_conflict_kinds = list(dict.fromkeys(conflict_record.get("kinds") or []))
        import_job.eventLog.append(
            {
                "type": "repository.sync.conflict_resolved",
                "at": _utc_now_iso(),
                "schemaName": normalized_schema_name,
                "choice": request.choice,
                "conflictKinds": canonical_conflict_kinds,
                "note": request.note.strip() if request.note and request.note.strip() else None,
            }
        )
        return import_job


@router.post("/{tenant_slug}/{repository_id}/scans", response_model=RepositoryScanRecord)
async def create_repository_scan(
    tenant_slug: str,
    repository_id: str,
    request: RepositoryScanCreateRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> RepositoryScanRecord:
    tenant_id = auth_data["tenant_id"]
    actor_id = _resolve_actor_id(auth_data)
    branch_name = request.branch.strip()
    now = _utc_now_iso()
    if not branch_name:
        raise HTTPException(status_code=400, detail="branch is required")

    _audit_row: Dict[str, Any] | None = None
    with _STORE_LOCK:
        repository = _find_repository_for_tenant(tenant_id, repository_id)
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
        timeline = _REPO_SCAN_STORE.setdefault(repository_id, repository.timeline)
        if scan.status == "pending":
            repository.status = "scan_in_progress"
            timeline.insert(
                0,
                RepositoryScanTimelineEntry(
                    id=str(uuid4()),
                    type="scan",
                    status="in_progress",
                    message="Scan in progress...",
                    createdAt=now,
                ),
            )
        elif scan.status == "skipped_unchanged" and repository.status not in {"archived", "paused"}:
            repository.status = "healthy"
            timeline.insert(
                0,
                RepositoryScanTimelineEntry(
                    id=str(uuid4()),
                    type="scan",
                    status="completed",
                    message="Scan skipped (unchanged).",
                    createdAt=now,
                ),
            )
        repository.timeline = list(timeline)
        repository.updatedAt = now
        _audit_row = _append_audit_row(
            tenant_id,
            repository_id,
            "repository.polled",
            actor_id=actor_id,
            detail={
                "trigger": scan.trigger,
                "branch": branch_name,
                "force": request.force,
                "scanId": scan.id,
            },
        )
    if _audit_row is not None:
        _persist_audit_row(_audit_row)
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
        _REPO_IMPORT_JOB_STORE.clear()
        _REPO_CHANGE_REPORT_STORE.clear()
        _REPO_AUDIT_STORE.clear()
        _REPO_IMPORT_POLICY_STORE.clear()
        _REPO_PROJECT_STORE.clear()
        _REPO_VERSION_STORE.clear()
        _REPO_IMPORT_NOW_IDEMPOTENCY.clear()
        _REPO_FILE_CONTENT_STORE.clear()
        _REPO_SCAN_REPORT_STORE.clear()
        _REPO_CORPUS_ROLLUP.clear()
        _REPO_ATTENTION.clear()
        _REPO_AUTO_PAUSED.clear()
    with _DISPATCH_ADVISORY_REGISTRY_LOCK:
        _REPO_DISPATCH_ADVISORY_LOCKS.clear()
    try:
        from .repositories.scan_report_export import reset_scan_report_export_state_for_tests

        reset_scan_report_export_state_for_tests()
    except Exception:
        pass


def _complete_repository_scan_for_tests(
    repository_id: str,
    scan_id: str,
    *,
    commit_sha: str,
    files: Sequence[Dict[str, Any]],
) -> RepositoryScanRecord:
    with _STORE_LOCK:
        history = _REPO_SCAN_HISTORY_STORE.get(repository_id, [])
        scan_idx = next((idx for idx, scan in enumerate(history) if scan.id == scan_id), None)
        if scan_idx is None:
            raise ValueError(f"Scan not found: {scan_id}")

        target_scan = history[scan_idx]
        repository = _REPO_STORE.get(_find_tenant_id_for_repository(repository_id), {}).get(repository_id)
        manifest_specs_by_path: Dict[str, Any] = {}
        manifest_parsed: RepoManifest | None = None
        if repository is not None:
            manifest_outcome = parse_repo_manifest(repository.manifest)
            manifest_parsed = manifest_outcome.manifest
            if manifest_outcome.manifest is not None:
                manifest_specs_by_path = {spec.path: spec for spec in manifest_outcome.manifest.specs}
        now = _utc_now_iso()
        current_files: List[RepositoryFileRecord] = []
        for item in files:
            path_raw = item.get("path")
            if not isinstance(path_raw, str) or not path_raw.strip():
                raise ValueError("Each file must include a non-empty path")
            normalized_path = path_raw.strip()
            manifest_spec = manifest_specs_by_path.get(normalized_path)
            mapping = resolve_repository_file_mapping(normalized_path, manifest_spec)

            tracked_raw = item.get("tracked")
            tracked_value = mapping.tracked
            if tracked_raw is not None:
                if isinstance(tracked_raw, bool):
                    tracked_value = tracked_raw
                elif isinstance(tracked_raw, str):
                    if tracked_raw.lower() == "true":
                        tracked_value = True
                    elif tracked_raw.lower() == "false":
                        tracked_value = False
                    else:
                        raise ValueError(
                            f"Invalid value for 'tracked': {tracked_raw!r}; expected a boolean or 'true'/'false'"
                        )
                else:
                    raise ValueError(
                        f"Invalid type for 'tracked': {type(tracked_raw).__name__}; expected a boolean or the string 'true'/'false'"
                    )

            if manifest_spec is not None:
                tracked_value = mapping.tracked

            settings_json_raw = item.get("settingsJson")
            if settings_json_raw is not None and not isinstance(settings_json_raw, dict):
                raise ValueError("settingsJson must be an object when provided")
            settings_json_value = dict(settings_json_raw or {})
            if mapping.on_breaking_change is not None:
                settings_json_value["onBreakingChange"] = mapping.on_breaking_change
            if mapping.settings_json is not None:
                for key, value in mapping.settings_json.items():
                    settings_json_value[key] = value
            if not settings_json_value:
                settings_json_value = None
            promote_raw = item.get("promote")
            if promote_raw is not None and promote_raw not in {"auto", "manual"}:
                raise ValueError("promote must be either 'auto' or 'manual' when provided")
            if manifest_spec is not None:
                promote_value: ImportJobPromotion = mapping.promote
            elif promote_raw in {"auto", "manual"}:
                promote_value = promote_raw
            else:
                promote_value = mapping.promote

            project_slug_value = item.get("projectSlug")
            version_strategy_value = item.get("versionStrategy")
            if tracked_value:
                if project_slug_value is None or manifest_spec is not None:
                    project_slug_value = mapping.project_slug
                if version_strategy_value is None or manifest_spec is not None:
                    version_strategy_value = mapping.version_strategy
            else:
                project_slug_value = None

            content_checksum = _normalize_content_checksum(item.get("contentChecksum"))
            content_algo = _normalize_content_algo(item.get("contentAlgo"), has_checksum=content_checksum is not None)
            if "importEnabled" in item and item.get("importEnabled") is not None:
                if not isinstance(item.get("importEnabled"), bool):
                    raise ValueError("importEnabled must be a boolean when provided")
                import_enabled_value = item["importEnabled"]
            else:
                import_enabled_value = initial_import_enabled_for_path(
                    manifest=manifest_parsed,
                    spec=manifest_spec,
                )
            if "autoImportEnabled" in item and item.get("autoImportEnabled") is not None:
                if not isinstance(item.get("autoImportEnabled"), bool):
                    raise ValueError("autoImportEnabled must be a boolean when provided")
                auto_import_enabled_value = item["autoImportEnabled"]
            else:
                auto_import_enabled_value = initial_auto_import_enabled_for_path(
                    manifest=manifest_parsed,
                    spec=manifest_spec,
                )
            if not import_enabled_value:
                auto_import_enabled_value = False
            current_files.append(
                RepositoryFileRecord(
                    id=str(uuid4()),
                    repositoryId=repository_id,
                    scanId=scan_id,
                    path=normalized_path,
                    blobSha=item.get("blobSha"),
                    contentChecksum=content_checksum,
                    contentAlgo=content_algo,
                    sizeBytes=item.get("sizeBytes"),
                    format=item.get("format"),
                    confidence=item.get("confidence"),
                    discriminator=item.get("discriminator"),
                    tracked=tracked_value,
                    importEnabled=import_enabled_value,
                    autoImportEnabled=auto_import_enabled_value,
                    projectSlug=project_slug_value,
                    versionStrategy=version_strategy_value,
                    settingsJson=settings_json_value,
                    promote=promote_value,
                    status="new",
                    qualityScore=item.get("qualityScore"),
                    lastImportJobId=item.get("lastImportJobId"),
                    createdAt=now,
                )
            )

        previous_completed_scan = next(
            (
                scan
                for idx, scan in enumerate(history)
                if idx != scan_idx and scan.branch == target_scan.branch and scan.status == "complete"
            ),
            None,
        )
        previous_files: Sequence[RepositoryFileRecord] = []
        if previous_completed_scan is not None:
            previous_files = _REPO_SCAN_FILE_HISTORY_STORE.get(previous_completed_scan.id, [])

        classified_files, diff_summary = _classify_scan_files_against_previous(
            repository_id=repository_id,
            scan_id=scan_id,
            created_at=now,
            current_files=current_files,
            previous_files=previous_files,
        )
        tenant_id = _find_tenant_id_for_repository(repository_id)
        pending_audit_rows = _dispatch_import_jobs_for_scan(
            tenant_id=tenant_id,
            repository_id=repository_id,
            scan_id=scan_id,
            branch=target_scan.branch,
            commit_sha=commit_sha,
            scan_files=classified_files,
            actor_id=_SYSTEM_ACTOR_ID,
            force=_scan_force_enabled(target_scan),
            diff_summary=diff_summary,
        )
        _REPO_SCAN_FILE_HISTORY_STORE[scan_id] = classified_files

        completed_scan = target_scan.model_copy(
            update={
                "commitSha": commit_sha,
                "status": "complete",
                "finishedAt": now,
                "durationMs": 0,
                "filesSeen": len(current_files),
                "filesClassified": len(classified_files),
                "filesUnknown": 0,
                "filesFailed": 0,
                "eventLog": [
                    *target_scan.eventLog,
                    *_build_hashed_event_log_entries(classified_files, at=now),
                    {"type": "repository.scan.complete", "at": now},
                ],
                "diffSummary": diff_summary,
            }
        )
        history[scan_idx] = completed_scan
        pending_audit_rows.append(_append_audit_row(
            tenant_id,
            repository_id,
            "repository.scanned",
            actor_id=_SYSTEM_ACTOR_ID,
            detail={
                "scanId": completed_scan.id,
                "branch": completed_scan.branch,
                "trigger": completed_scan.trigger,
                "status": completed_scan.status,
                "diffSummary": completed_scan.diffSummary,
            },
        ))
        _append_scan_report_row(
            repository_id,
            completed_scan.id,
            generated_at=now,
            classified_files=classified_files,
            scan_failed=False,
            scan=completed_scan,
        )

    for _audit_row in pending_audit_rows:
        _persist_audit_row(_audit_row)
    _recompute_repository_attention(tenant_id, repository_id)
    return completed_scan


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
            diffSummary={"added": 1, "modified": 0, "removed": 0, "unchanged": 0},
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
        _REPO_IMPORT_POLICY_STORE.setdefault(repository_id, {"allowManifestProjectAutoCreate": False})


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


def _get_repository_import_jobs_for_tests(repository_id: str) -> List[RepositoryImportJobRecord]:
    with _STORE_LOCK:
        return list(_REPO_IMPORT_JOB_STORE.get(repository_id, []))


def _get_repository_change_reports_for_tests(repository_id: str) -> List[RepositorySyncChangeReportRecord]:
    with _STORE_LOCK:
        return list(_REPO_CHANGE_REPORT_STORE.get(repository_id, []))


def _build_repository_sync_change_report_for_test_status(status: RepositoryFileStatus) -> Dict[str, Any]:
    file_row = RepositoryFileRecord(
        id=str(uuid4()),
        repositoryId=str(uuid4()),
        scanId=str(uuid4()),
        path="apis/stable.yaml",
        tracked=True,
        status=status,
        createdAt=_utc_now_iso(),
    )
    return _build_repository_sync_change_report_model(file_row)


def _get_repository_resolved_versions_for_tests(tenant_id: str) -> List[RepositoryResolvedVersionRecord]:
    with _STORE_LOCK:
        tenant_versions = _REPO_VERSION_STORE.get(tenant_id, {})
        rows: List[RepositoryResolvedVersionRecord] = []
        for per_commit in tenant_versions.values():
            rows.extend(per_commit.values())
        rows.sort(key=lambda row: row.createdAt, reverse=True)
        return rows


def _list_poll_targets_for_tests(tenant_id: str) -> List[Dict[str, str]]:
    with _STORE_LOCK:
        return _list_poll_targets_for_tenant(tenant_id)


