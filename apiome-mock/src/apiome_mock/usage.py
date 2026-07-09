"""Daily mock usage rollups (#4420, SIM-1.5)."""

from __future__ import annotations

import asyncio
from uuid import UUID

import structlog
from psycopg_pool import AsyncConnectionPool

_log = structlog.get_logger(__name__)


async def record_mock_usage(
    pool: AsyncConnectionPool,
    *,
    tenant_id: UUID,
    project_slug: str,
    version_label: str,
) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "SELECT apiome.record_mock_usage(%s::uuid, %s, %s)",
            (tenant_id, project_slug, version_label),
        )
        await conn.commit()


def schedule_mock_usage(
    pool: AsyncConnectionPool,
    *,
    tenant_id: UUID,
    project_slug: str,
    version_label: str,
) -> None:
    """Fire-and-forget usage rollup so mock latency stays low."""

    async def _run() -> None:
        try:
            await record_mock_usage(
                pool,
                tenant_id=tenant_id,
                project_slug=project_slug,
                version_label=version_label,
            )
        except Exception:
            _log.warning(
                "mock_usage_record_failed",
                tenant_id=str(tenant_id),
                project_slug=project_slug,
                version_label=version_label,
                exc_info=True,
            )

    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        _log.debug(
            "mock_usage_skip_no_event_loop",
            tenant_id=str(tenant_id),
            project_slug=project_slug,
            version_label=version_label,
        )
