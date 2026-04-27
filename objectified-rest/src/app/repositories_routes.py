"""
Repository registration endpoints (REPO-1.4).

Provides tenant-scoped endpoints to register source-code repositories and
trigger an initial scan job.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple
from uuid import UUID, uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from .auth import validate_authentication
from .database import db
from .openapi_change_report import build_change_report
from .repositories.manifest import parse_repo_manifest, resolve_repository_file_mapping

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
    "unchanged_checksum",
    "modified",
    "removed",
    "parse_error",
    "manifest_error",
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
    projectSlug: str | None = None
    versionStrategy: str | None = None
    settingsJson: Dict[str, Any] | None = None
    promote: ImportJobPromotion | None = None
    status: RepositoryFileStatus
    qualityScore: int | None = None
    lastImportJobId: str | None = None
    createdAt: str


class RepositoryImportJobRecord(BaseModel):
    id: str
    repositoryId: str
    repositoryFileId: str
    scanId: str
    branch: str
    sourceType: Literal["git"]
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


class RepositoryResolvedProjectRecord(BaseModel):
    id: str
    tenantId: str
    slug: str
    name: str
    createdAt: str


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
_STORE_LOCK = Lock()
_SYSTEM_ACTOR_ID = "00000000-0000-0000-0000-000000000000"

RepositoryAuditEvent = Literal[
    "repository.registered",
    "repository.scanned",
    "repository.scan.skipped_checksum",
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
]

_DEFAULT_SCAN_PAGE_SIZE = 50
_MAX_SCAN_PAGE_SIZE = 200
_CONTENT_CHECKSUM_ALGO = "sha256"
_CONTENT_CHECKSUM_SHORT_LEN = 12
_SLUG_SANITIZER = re.compile(r"[^a-z0-9]+")
_VERSION_SHA_SANITIZER = re.compile(r"[^a-z0-9]+")
_MANIFEST_PROJECT_AUTO_CREATE_FLAG_KEYS = (
    "repoManifestProjectAutoCreate",
    "repo_manifest_project_auto_create",
)


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
    if manifest_outcome.manifest is None:
        return {}
    manifest_map: Dict[str, str] = {}
    for spec in manifest_outcome.manifest.specs:
        normalized_slug = _normalize_slug(spec.project)
        if normalized_slug is None:
            continue
        manifest_map[spec.path] = normalized_slug
    return manifest_map


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
    created = RepositoryResolvedProjectRecord(
        id=str(uuid4()),
        tenantId=tenant_id,
        slug=normalized_project_slug,
        name=normalized_project_slug.replace("-", " ").title(),
        createdAt=now,
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
    repository_jobs = _REPO_IMPORT_JOB_STORE.setdefault(repository_id, [])
    manifest_project_slug_by_path = _manifest_project_slug_by_path(repository_id)
    pending_audit_rows: List[Dict[str, Any]] = []
    checksums = precomputed_checksums or {}
    for file_row in scan_files:
        if file_row.status not in {"new", "modified", "removed"}:
            continue
        if not file_row.tracked:
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
        _audit_row = _append_audit_row(
            tenant_id,
            repository_id,
            "repository.paused",
            actor_id=actor_id,
            detail={"status": repository.status},
        )
    if _audit_row is not None:
        _persist_audit_row(_audit_row)
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
        _audit_row = _append_audit_row(
            tenant_id,
            repository_id,
            "repository.auto_paused",
            actor_id=actor_id,
            detail={"status": repository.status},
        )
    if _audit_row is not None:
        _persist_audit_row(_audit_row)
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
        _audit_row = _append_audit_row(
            tenant_id,
            repository_id,
            "repository.removed",
            actor_id=actor_id,
            detail={"fullName": repository.fullName},
        )

    if _audit_row is not None:
        _persist_audit_row(_audit_row)
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
        if repository is not None:
            manifest_outcome = parse_repo_manifest(repository.manifest)
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

    for _audit_row in pending_audit_rows:
        _persist_audit_row(_audit_row)
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
