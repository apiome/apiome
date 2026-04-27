#!/usr/bin/env python3
"""
REPO-8.4 / #2947.

Backfill script for historical repository scan data:
- Hash tracked repository files missing content checksums.
- Migrate legacy versions.metadata.repositorySource into versions.repository_source.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID, RFC_4122

import httpx
import psycopg2
from psycopg2.extras import Json, RealDictCursor

# Ensure project root is on path so app modules can be imported from scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from app.config import settings
from app.repositories.tree_walker import hash_streamed_bytes

_DEFAULT_BATCH_SIZE = 500
_DEFAULT_GITHUB_REQUESTS_PER_SECOND = 2.0
_CONTENT_CHECKSUM_SHORT_LEN = 12
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_CHECKSUM_RE = re.compile(r"^[0-9a-f]{64}$")
_ISO_8601_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


class BackfillError(RuntimeError):
    """Typed script-level error for deterministic exits."""


@dataclass(frozen=True)
class FileChecksumCandidate:
    file_id: str
    tenant_id: str
    repository_id: str
    provider: str
    owner: str
    name: str
    path: str
    blob_sha: str
    linked_account_id: str | None
    access_token: str | None


@dataclass(frozen=True)
class VersionSourceCandidate:
    version_id: str
    metadata: dict[str, Any]


@dataclass
class BackfillReport:
    rows_hashed: int = 0
    rows_reused: int = 0
    rows_failed: int = 0
    versions_migrated: int = 0
    versions_rejected: int = 0
    file_failures: list[dict[str, Any]] = field(default_factory=list)
    version_rejections: list[dict[str, Any]] = field(default_factory=list)


class CredentialRateLimiter:
    """Per-credential request budget gate."""

    def __init__(self, requests_per_second: float) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be > 0")
        self._min_interval_sec = 1.0 / requests_per_second
        self._next_allowed_by_key: dict[str, float] = {}

    def wait(self, key: str) -> None:
        now = time.monotonic()
        next_allowed = self._next_allowed_by_key.get(key, now)
        if now < next_allowed:
            time.sleep(next_allowed - now)
            now = time.monotonic()
        self._next_allowed_by_key[key] = now + self._min_interval_sec


def _short_checksum(checksum: str) -> str:
    return checksum[:_CONTENT_CHECKSUM_SHORT_LEN]


def _normalize_uuid(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    candidate = raw.strip().lower()
    if not candidate:
        return None
    try:
        parsed = UUID(candidate)
        if parsed.variant != RFC_4122:
            return None
        if parsed.version not in (1, 2, 3, 4, 5):
            return None
        return str(parsed)
    except ValueError:
        return None


def _normalize_non_empty_str(raw: Any, *, max_length: int, field_name: str) -> tuple[str | None, str | None]:
    if not isinstance(raw, str):
        return None, f"{field_name} must be a string"
    value = raw.strip()
    if not value:
        return None, f"{field_name} must not be empty"
    if len(value) > max_length:
        return None, f"{field_name} exceeds max length {max_length}"
    return value, None


def validate_repository_source_payload(payload: Any) -> tuple[dict[str, str] | None, str | None]:
    """
    Validate legacy metadata.repositorySource payload against REPO-8.2 constraints.
    Returns normalized payload on success.
    """
    if not isinstance(payload, dict):
        return None, "repositorySource must be a JSON object"

    required = {
        "repositoryId",
        "branch",
        "path",
        "commitSha",
        "contentChecksum",
        "contentAlgo",
        "importedAt",
    }
    missing = sorted(key for key in required if key not in payload)
    if missing:
        return None, f"repositorySource missing required fields: {', '.join(missing)}"

    repository_id = _normalize_uuid(payload.get("repositoryId"))
    if repository_id is None:
        return None, "repositoryId must be a valid UUID"

    branch, branch_error = _normalize_non_empty_str(payload.get("branch"), max_length=256, field_name="branch")
    if branch_error:
        return None, branch_error

    path, path_error = _normalize_non_empty_str(payload.get("path"), max_length=1024, field_name="path")
    if path_error:
        return None, path_error

    commit_sha, commit_error = _normalize_non_empty_str(payload.get("commitSha"), max_length=64, field_name="commitSha")
    if commit_error:
        return None, commit_error
    commit_sha = commit_sha.lower()
    if not _COMMIT_SHA_RE.fullmatch(commit_sha):
        return None, "commitSha must be a 40-64 char lowercase hex string"

    checksum, checksum_error = _normalize_non_empty_str(
        payload.get("contentChecksum"), max_length=64, field_name="contentChecksum"
    )
    if checksum_error:
        return None, checksum_error
    checksum = checksum.lower()
    if not _CHECKSUM_RE.fullmatch(checksum):
        return None, "contentChecksum must be a 64-char lowercase hex string"

    algo, algo_error = _normalize_non_empty_str(payload.get("contentAlgo"), max_length=16, field_name="contentAlgo")
    if algo_error:
        return None, algo_error
    algo = algo.lower()
    if algo != "sha256":
        return None, "contentAlgo must be 'sha256'"

    imported_at, imported_at_error = _normalize_non_empty_str(
        payload.get("importedAt"), max_length=64, field_name="importedAt"
    )
    if imported_at_error:
        return None, imported_at_error
    if not _ISO_8601_TS_RE.fullmatch(imported_at):
        return None, "importedAt must be an ISO 8601 timestamp string"

    normalized = {
        "repositoryId": repository_id,
        "branch": branch,
        "path": path,
        "commitSha": commit_sha,
        "contentChecksum": checksum,
        "contentAlgo": algo,
        "importedAt": imported_at,
    }
    return normalized, None


def _fetch_github_blob_checksum(
    *,
    client: httpx.Client,
    owner: str,
    name: str,
    blob_sha: str,
    access_token: str,
) -> str:
    url = f"https://api.github.com/repos/{owner}/{name}/git/blobs/{blob_sha}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.raw",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    with client.stream("GET", url, headers=headers, timeout=30.0) as response:
        if response.status_code >= 400:
            body = response.text
            raise BackfillError(
                f"GitHub blob fetch failed for {owner}/{name}@{blob_sha}: "
                f"status={response.status_code} body={body[:300]}"
            )
        hashed = hash_streamed_bytes(response.iter_bytes(chunk_size=64 * 1024))
    return hashed.checksum


def _count_reused_rows(conn: psycopg2.extensions.connection) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)::bigint AS cnt
            FROM odb.repository_file
            WHERE tracked = TRUE
              AND content_checksum IS NOT NULL
            """
        )
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def _iter_checksum_candidates(
    conn: psycopg2.extensions.connection,
    *,
    batch_size: int,
) -> Iterable[list[FileChecksumCandidate]]:
    last_seen_id: str | None = None
    while True:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    rf.id::text AS file_id,
                    r.tenant_id::text AS tenant_id,
                    r.id::text AS repository_id,
                    r.provider::text AS provider,
                    r.owner,
                    r.name,
                    rf.path,
                    rf.blob_sha,
                    cred.linked_account_id::text AS linked_account_id,
                    cred.access_token
                FROM odb.repository_file rf
                JOIN odb.repository r ON r.id = rf.repository_id
                LEFT JOIN LATERAL (
                    SELECT eap.id AS linked_account_id, eap.access_token
                    FROM odb.repository_credential_ref rcr
                    JOIN odb.external_auth_providers eap ON eap.id = rcr.linked_account_id
                    WHERE rcr.repository_id = r.id
                    ORDER BY rcr.created_at ASC
                    LIMIT 1
                ) cred ON TRUE
                WHERE rf.tracked = TRUE
                  AND rf.content_checksum IS NULL
                  AND rf.blob_sha IS NOT NULL
                  AND (%s::uuid IS NULL OR rf.id > %s::uuid)
                ORDER BY rf.id
                LIMIT %s
                """,
                (last_seen_id, last_seen_id, batch_size),
            )
            rows = cursor.fetchall()

        if not rows:
            return

        batch: list[FileChecksumCandidate] = []
        for row in rows:
            batch.append(
                FileChecksumCandidate(
                    file_id=str(row["file_id"]),
                    tenant_id=str(row["tenant_id"]),
                    repository_id=str(row["repository_id"]),
                    provider=str(row["provider"]),
                    owner=str(row["owner"]),
                    name=str(row["name"]),
                    path=str(row["path"]),
                    blob_sha=str(row["blob_sha"]),
                    linked_account_id=row.get("linked_account_id"),
                    access_token=row.get("access_token"),
                )
            )
        yield batch
        last_seen_id = batch[-1].file_id


def _backfill_file_checksums(
    conn: psycopg2.extensions.connection,
    *,
    report: BackfillReport,
    batch_size: int,
    limiter: CredentialRateLimiter,
) -> None:
    with httpx.Client() as client:
        for batch in _iter_checksum_candidates(conn, batch_size=batch_size):
            for candidate in batch:
                if candidate.provider != "github":
                    report.rows_failed += 1
                    report.file_failures.append(
                        {
                            "fileId": candidate.file_id,
                            "repositoryId": candidate.repository_id,
                            "path": candidate.path,
                            "error": f"unsupported provider: {candidate.provider}",
                        }
                    )
                    continue

                if not candidate.access_token or not candidate.access_token.strip():
                    report.rows_failed += 1
                    report.file_failures.append(
                        {
                            "fileId": candidate.file_id,
                            "repositoryId": candidate.repository_id,
                            "path": candidate.path,
                            "error": "missing linked account access token",
                        }
                    )
                    continue

                limiter.wait(candidate.linked_account_id or f"{candidate.repository_id}:fallback")
                try:
                    checksum = _fetch_github_blob_checksum(
                        client=client,
                        owner=candidate.owner,
                        name=candidate.name,
                        blob_sha=candidate.blob_sha,
                        access_token=candidate.access_token.strip(),
                    )
                except Exception as exc:
                    report.rows_failed += 1
                    report.file_failures.append(
                        {
                            "fileId": candidate.file_id,
                            "repositoryId": candidate.repository_id,
                            "path": candidate.path,
                            "error": str(exc),
                        }
                    )
                    continue

                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE odb.repository_file
                        SET content_checksum = %s,
                            content_algo = 'sha256'
                        WHERE id = %s::uuid
                          AND content_checksum IS NULL
                        """,
                        (checksum, candidate.file_id),
                    )
                    updated = cursor.rowcount

                    if updated == 1:
                        cursor.execute(
                            """
                            INSERT INTO odb.workflow_audit
                              (tenant_id, project_id, version_id, action, outcome, actor_id, detail)
                            VALUES
                              (%s::uuid, NULL, NULL, 'repository.scan.backfilled', 'success', NULL, %s::jsonb)
                            """,
                            (
                                candidate.tenant_id,
                                json.dumps(
                                    {
                                        "repositoryId": candidate.repository_id,
                                        "path": candidate.path,
                                        "content_checksum_short": _short_checksum(checksum),
                                    }
                                ),
                            ),
                        )
                        report.rows_hashed += 1
                    else:
                        # Concurrent writer or previously completed row.
                        report.rows_reused += 1

            conn.commit()


def _iter_version_source_candidates(
    conn: psycopg2.extensions.connection,
    *,
    batch_size: int,
) -> Iterable[list[VersionSourceCandidate]]:
    last_seen_id: str | None = None
    while True:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT
                    v.id::text AS version_id,
                    v.metadata
                FROM odb.versions v
                JOIN odb.projects p ON p.id = v.project_id
                WHERE v.deleted_at IS NULL
                  AND p.deleted_at IS NULL
                  AND v.repository_source IS NULL
                  AND v.metadata IS NOT NULL
                  AND (v.metadata ? 'repositorySource')
                  AND (%s::uuid IS NULL OR v.id > %s::uuid)
                ORDER BY v.id
                LIMIT %s
                """,
                (last_seen_id, last_seen_id, batch_size),
            )
            rows = cursor.fetchall()

        if not rows:
            return

        batch: list[VersionSourceCandidate] = []
        for row in rows:
            metadata = row.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}
            batch.append(
                VersionSourceCandidate(
                    version_id=str(row["version_id"]),
                    metadata=metadata,
                )
            )
        yield batch
        last_seen_id = batch[-1].version_id


def _migrate_version_repository_source(
    conn: psycopg2.extensions.connection,
    *,
    report: BackfillReport,
    batch_size: int,
) -> None:
    for batch in _iter_version_source_candidates(conn, batch_size=batch_size):
        for candidate in batch:
            legacy_payload = candidate.metadata.get("repositorySource")
            normalized, validation_error = validate_repository_source_payload(legacy_payload)
            if validation_error is not None or normalized is None:
                report.versions_rejected += 1
                report.version_rejections.append(
                    {
                        "versionId": candidate.version_id,
                        "reason": validation_error or "unknown validation error",
                    }
                )
                continue

            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE odb.versions
                    SET repository_source = %s::jsonb
                    WHERE id = %s::uuid
                      AND repository_source IS NULL
                    """,
                    (Json(normalized), candidate.version_id),
                )
                if cursor.rowcount == 1:
                    report.versions_migrated += 1

        conn.commit()


def run_backfill(
    *,
    batch_size: int,
    github_requests_per_second: float,
    error_report_path: Path,
) -> BackfillReport:
    report = BackfillReport()
    conn = psycopg2.connect(settings.effective_database_url)
    conn.autocommit = False
    try:
        report.rows_reused = _count_reused_rows(conn)
        _backfill_file_checksums(
            conn,
            report=report,
            batch_size=batch_size,
            limiter=CredentialRateLimiter(github_requests_per_second),
        )
        _migrate_version_repository_source(conn, report=report, batch_size=batch_size)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    error_report = {
        "generatedAtEpochMs": int(time.time() * 1000),
        "fileFailures": report.file_failures,
        "versionRejections": report.version_rejections,
    }
    error_report_path.parent.mkdir(parents=True, exist_ok=True)
    error_report_path.write_text(json.dumps(error_report, indent=2), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill historical repository content checksums and version repository_source tuples."
    )
    parser.add_argument("--batch-size", type=int, default=_DEFAULT_BATCH_SIZE)
    parser.add_argument("--github-rps", type=float, default=_DEFAULT_GITHUB_REQUESTS_PER_SECOND)
    parser.add_argument(
        "--error-report-path",
        type=Path,
        default=Path(__file__).resolve().with_suffix(".errors.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size < 1:
        raise SystemExit("--batch-size must be >= 1")
    if args.github_rps <= 0:
        raise SystemExit("--github-rps must be > 0")

    report = run_backfill(
        batch_size=args.batch_size,
        github_requests_per_second=args.github_rps,
        error_report_path=args.error_report_path,
    )
    print(
        json.dumps(
            {
                "rows_hashed": report.rows_hashed,
                "rows_reused": report.rows_reused,
                "rows_failed": report.rows_failed,
                "versions_migrated": report.versions_migrated,
                "versions_rejected": report.versions_rejected,
                "error_report_path": str(args.error_report_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
