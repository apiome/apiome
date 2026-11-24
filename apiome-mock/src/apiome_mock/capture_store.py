"""Persistence for guarded proxy captures (#4747, PMR-2.4).

The runtime's write half of the review queue: it inserts the *already redacted* record and appends
an audit row so the tenant ledger shows that recording happened at all — not only that it was
authorized.

Since #7207 (DBP-1.24) one capture is **one checkout and one transaction**: the bounded pending
count, the insert, and the audit append run together on a single connection. The version is the
``revision_id`` the compiled spec already carries, so no slug lookup is repeated.

Two rules are enforced here rather than trusted to the caller:

* **Scope.** Every statement is bound to ``tenant_id`` *and* ``versions.id``, and the insert only
  writes when that version belongs to that tenant. A capture recorded against one version can never
  be written into another's queue, and a mock serving a version the tenant does not own stores
  nothing.
* **Best effort, never fatal.** Capture is an opt-in development aid layered on the data plane. A
  database failure here degrades to "not recorded" — reported on the response and in the logs —
  and never turns a served request into a 500. :mod:`apiome_mock.capture` owns that policy.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence
from uuid import UUID

import structlog
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mock.audit import append_mock_audit_entry

__all__ = [
    "CAPTURE_AUDIT_ACTION",
    "QUEUE_FULL",
    "UNRESOLVED",
    "store_capture_exchange",
]

_log = structlog.get_logger(__name__)

#: Ledger action recorded for every stored capture. Distinct from ``mock.request`` because the two
#: answer different questions: one is "traffic was served", this is "traffic was recorded".
CAPTURE_AUDIT_ACTION = "mock.capture"

#: Count pending rows, but never more than ``cap``: the caller only needs to know whether the queue
#: is full, so the scan stops at the bound instead of counting every unreviewed row.
_COUNT_PENDING = """
    SELECT COUNT(*) AS pending FROM (
      SELECT 1
      FROM apiome.mock_capture_exchange
      WHERE version_id = %(version_id)s
        AND tenant_id = %(tenant_id)s
        AND review_state = 'pending'
        AND expires_at > CURRENT_TIMESTAMP
      LIMIT %(cap)s
    ) AS bounded
"""

#: Insert only when the version belongs to the tenant (the scope rule), in the same statement.
_INSERT_CAPTURE = """
    INSERT INTO apiome.mock_capture_exchange
      (tenant_id, version_id, upstream, allowlist_entry, policy_digest, captured_by,
       operation_key, request_method, request_path, status_code, exchange, exchange_digest,
       redactions, redaction_count, schema_valid, validation_errors, expires_at)
    SELECT
      %(tenant_id)s, v.id, %(upstream)s, %(allowlist_entry)s, %(policy_digest)s,
      %(captured_by)s, %(operation_key)s, %(method)s, %(path)s, %(status_code)s,
      %(exchange)s::jsonb, %(digest)s, %(redactions)s::jsonb, %(redaction_count)s,
      %(schema_valid)s, %(validation_errors)s::jsonb, %(expires_at)s
    FROM apiome.versions v
    INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
    WHERE v.id = %(version_id)s
      AND p.tenant_id = %(tenant_id)s
      AND v.deleted_at IS NULL
    RETURNING id
"""

#: :func:`store_capture_exchange` result when the review queue already holds ``max_pending`` rows.
QUEUE_FULL = "review-queue-full"

#: :func:`store_capture_exchange` result when the version is not inside the tenant.
UNRESOLVED = "version-unresolved"


async def store_capture_exchange(
    pool: AsyncConnectionPool,
    *,
    tenant_id: UUID,
    version_id: UUID,
    project: str,
    version: str,
    max_pending: int,
    upstream: str,
    allowlist_entry: str,
    policy_digest: str,
    api_key_id: UUID | None,
    operation_key: str | None,
    method: str,
    path: str,
    status_code: int,
    record: Mapping[str, Any],
    digest: str,
    redactions: Sequence[Mapping[str, str]],
    schema_valid: bool | None,
    validation_errors: Sequence[str],
    expires_at: datetime,
) -> tuple[str | None, str | None]:
    """Store one redacted capture in the review queue and audit that it happened.

    The pending count, the insert and the audit row share one connection and one transaction: the
    queue bound and the ledger entry are exact for the row that was stored, and an audit failure
    rolls the capture back (nothing is recorded that the ledger does not show).

    The caller is responsible for the record being redacted and credential-clean; this function
    stores what it is given. The audit row carries the capture's coordinates, upstream, and
    redaction count — never any captured content.

    Args:
        pool: The runtime's database pool.
        tenant_id: Tenant that owns the capture (the caller's API key tenant).
        version_id: ``versions.id`` of the mocked revision (``CompiledSpec.revision_id``).
        project: Project slug from the URL (ledger text only).
        version: Version label from the URL (ledger text only).
        max_pending: Unreviewed captures a version may hold; at the bound nothing is stored.
        upstream: Fetched upstream URL, query string already removed.
        allowlist_entry: The allowlist entry that authorized the fetch.
        policy_digest: Digest of the capture policy in force.
        api_key_id: The API key that drove the capture.
        operation_key: The matched spec operation, when the request matched one.
        method: Request method.
        path: Request path relative to the version prefix.
        status_code: Upstream response status.
        record: The redacted ``apiome.mock.capture/v1`` document.
        digest: Content digest of that document.
        redactions: The redaction decision list.
        schema_valid: Whether the response matched the contract (``None`` when unchecked).
        validation_errors: Schema validation errors for the response.
        expires_at: When retention removes the capture.

    Returns:
        ``(capture_id, None)`` when stored, else ``(None, reason)`` with reason :data:`QUEUE_FULL`
        or :data:`UNRESOLVED`.
    """
    async with pool.connection() as conn:
        async with conn.transaction():
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    _COUNT_PENDING, {"version_id": version_id, "tenant_id": tenant_id, "cap": max_pending}
                )
                counted = await cur.fetchone()
                if counted is not None and int(counted["pending"]) >= max_pending:
                    return None, QUEUE_FULL
                await cur.execute(
                    _INSERT_CAPTURE,
                    {
                        "tenant_id": tenant_id,
                        "version_id": version_id,
                        "upstream": upstream,
                        "allowlist_entry": allowlist_entry,
                        "policy_digest": policy_digest,
                        "captured_by": api_key_id,
                        "operation_key": operation_key,
                        "method": method,
                        "path": path,
                        "status_code": status_code,
                        "exchange": json.dumps(record, sort_keys=True, default=str),
                        "digest": digest,
                        "redactions": json.dumps(list(redactions), default=str),
                        "redaction_count": len(redactions),
                        "schema_valid": schema_valid,
                        "validation_errors": json.dumps(list(validation_errors), default=str),
                        "expires_at": expires_at,
                    },
                )
                row = await cur.fetchone()
            if row is None:
                _log.warning("mock_capture_version_unresolved", project=project, version=version)
                return None, UNRESOLVED
            capture_id = str(row["id"])
            await append_mock_audit_entry(
                conn,
                tenant_id=tenant_id,
                actor_label=str(api_key_id) if api_key_id else "capture",
                action=CAPTURE_AUDIT_ACTION,
                target=f"{project}/{version} {method} {path}",
                detail={
                    "projectSlug": project,
                    "versionLabel": version,
                    "method": method,
                    "path": path,
                    "statusCode": status_code,
                    "upstream": upstream,
                    "allowlistEntry": allowlist_entry,
                    "policyDigest": policy_digest,
                    "captureId": capture_id,
                    "redactions": len(redactions),
                    "schemaValid": schema_valid,
                    "apiKeyId": str(api_key_id) if api_key_id else None,
                },
            )
    return capture_id, None
