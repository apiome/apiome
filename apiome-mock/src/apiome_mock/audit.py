"""Sampled mock traffic audit rows in the tenant access ledger (#4420, SIM-1.5)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
from typing import Any
from uuid import UUID

import structlog
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_log = structlog.get_logger(__name__)

_MOCK_AUDIT_ACTION = "mock.request"


async def insert_mock_access_audit(
    pool: AsyncConnectionPool,
    *,
    tenant_id: UUID,
    client_ip: str,
    project_slug: str,
    version_label: str,
    method: str,
    path: str,
    status_code: int,
    api_key_id: UUID | None = None,
) -> None:
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                """
                SELECT entry_hash FROM apiome.access_audit
                WHERE tenant_id = %s::uuid
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (tenant_id,),
            )
            prev_row = await cur.fetchone()
            prev_hash = prev_row["entry_hash"] if prev_row else None

            detail: dict[str, Any] = {
                "projectSlug": project_slug,
                "versionLabel": version_label,
                "method": method.upper(),
                "path": path,
                "statusCode": status_code,
                "clientIp": client_ip,
            }
            if api_key_id is not None:
                detail["apiKeyId"] = str(api_key_id)
            detail_json = json.dumps(detail, sort_keys=True, default=str)
            target = f"{project_slug}/{version_label} {method.upper()} {path}"
            payload = "|".join(
                [
                    prev_hash or "",
                    str(tenant_id),
                    client_ip,
                    _MOCK_AUDIT_ACTION,
                    target,
                    detail_json,
                ]
            )
            entry_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            await cur.execute(
                """
                INSERT INTO apiome.access_audit
                  (tenant_id, actor_label, action, target, source, detail, prev_hash, entry_hash)
                VALUES (%s::uuid, %s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    tenant_id,
                    client_ip,
                    _MOCK_AUDIT_ACTION,
                    target,
                    "mock",
                    detail_json,
                    prev_hash,
                    entry_hash,
                ),
            )
        await conn.commit()


def schedule_mock_access_audit(
    pool: AsyncConnectionPool,
    *,
    tenant_id: UUID,
    client_ip: str,
    project_slug: str,
    version_label: str,
    method: str,
    path: str,
    status_code: int,
    sample_rate: float,
    api_key_id: UUID | None = None,
) -> None:
    """Record a sampled mock hit to ``access_audit`` (best-effort, async)."""
    if sample_rate <= 0.0:
        return
    if sample_rate < 1.0 and random.random() >= sample_rate:
        return

    async def _run() -> None:
        try:
            await insert_mock_access_audit(
                pool,
                tenant_id=tenant_id,
                client_ip=client_ip,
                project_slug=project_slug,
                version_label=version_label,
                method=method,
                path=path,
                status_code=status_code,
                api_key_id=api_key_id,
            )
        except Exception:
            _log.warning(
                "mock_access_audit_insert_failed",
                tenant_id=str(tenant_id),
                project_slug=project_slug,
                version_label=version_label,
                exc_info=True,
            )

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        _log.debug(
            "mock_access_audit_skip_no_event_loop",
            tenant_id=str(tenant_id),
            project_slug=project_slug,
            version_label=version_label,
        )
