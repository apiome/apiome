"""Load canonical API models from Postgres for multi-protocol mock serving (SIM-4.4).

One statement on one pooled connection; the canonical model is rebuilt in a worker thread after the
connection is back in the pool (#7208, DBP-1.25).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import UUID

from app.canonical_model import ApiParadigm, CanonicalApi
from app.catalog_conversion import build_conversion_source
from app.conversion_job import ConversionError
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mock.api_key import ValidatedApiKey
from apiome_mock.spec_loader import (
    FRESHNESS_COLUMNS,
    MockAccessStatus,
    SpecStamp,
    _fetch_access_row,
    row_is_private_mode,
    spec_stamp_from_row,
)

_RESOLVE_PUBLISHED_SOURCE = f"""
    SELECT
      v.id AS version_record_id,
      p.id,
      p.slug AS project_slug,
      v.version_id AS version_label,
      v.updated_at,
      v.source_format,
      v.protocol,
      v.format_metadata,
      v.source_tool_versions AS tool_versions,
      p.metadata,
      v.mock_settings,
      t.slug AS tenant_slug,
      {FRESHNESS_COLUMNS}
    FROM apiome.versions v
    INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
    INNER JOIN apiome.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL AND t.enabled IS TRUE
    INNER JOIN apiome.mcp_v_public_specs s ON s.id = v.id
    WHERE t.slug = %(tenant)s
      AND p.slug = %(project)s
      AND v.version_id = %(version)s
      AND v.deleted_at IS NULL
      AND v.mock_enabled IS TRUE
    LIMIT 1
"""

_RESOLVE_DRAFT_SOURCE = f"""
    SELECT
      v.id AS version_record_id,
      p.id,
      p.slug AS project_slug,
      v.version_id AS version_label,
      v.updated_at,
      v.source_format,
      v.protocol,
      v.format_metadata,
      v.source_tool_versions AS tool_versions,
      p.metadata,
      v.mock_settings,
      t.slug AS tenant_slug,
      {FRESHNESS_COLUMNS}
    FROM apiome.versions v
    INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
    INNER JOIN apiome.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL AND t.enabled IS TRUE
    WHERE t.slug = %(tenant)s
      AND p.slug = %(project)s
      AND v.version_id = %(version)s
      AND v.deleted_at IS NULL
      AND v.published IS FALSE
      AND v.mock_enabled IS TRUE
      AND COALESCE(v.mock_settings->>'mode', '') = 'private'
    LIMIT 1
"""


@dataclass(frozen=True)
class LoadedCanonicalSpec:
    """A canonical API model resolved for mock serving."""

    revision_id: UUID
    tenant_slug: str
    project_slug: str
    version_label: str
    updated_at: datetime
    api: CanonicalApi
    source_format: str | None
    mock_settings: Any = None
    """The version's raw ``mock_settings`` (scenarios, chaos, fixture packs, ``graphql``; #5729)."""
    freshness: SpecStamp | None = None
    """The stamp the model was built from (#7208, DBP-1.25); the cache revalidates against it.
    ``None`` means an expired entry is reloaded."""

    @property
    def cache_key(self) -> tuple[str, str, str]:
        return (self.tenant_slug, self.project_slug, self.version_label)

    @property
    def paradigm(self) -> ApiParadigm:
        return self.api.paradigm


def _build_canonical_from_row(row: dict[str, Any]) -> CanonicalApi:
    item: dict[str, Any] = {
        "id": str(row["id"]),
        "slug": row.get("project_slug"),
        "source_format": row.get("source_format"),
        "protocol": row.get("protocol"),
        "format_metadata": row.get("format_metadata"),
        "tool_versions": row.get("tool_versions"),
        "metadata": row.get("metadata"),
    }
    source = build_conversion_source(item, source_version_id=str(row["version_record_id"]))
    return source.api


async def load_canonical_spec(
    pool: AsyncConnectionPool,
    *,
    tenant: str,
    project: str,
    version: str,
    api_key: ValidatedApiKey | None = None,
    access_row: Mapping[str, Any] | None = None,
) -> LoadedCanonicalSpec | None:
    """Resolve slug coordinates and rebuild the canonical model from captured source.

    Args:
        pool: Database pool.
        tenant: Tenant slug.
        project: Project slug.
        version: Version label.
        api_key: The caller's validated key (required for a private draft).
        access_row: The access row the caller already fetched; read from the access cache when
            omitted.

    Returns:
        The loaded model, or ``None`` when the version is not mockable or its source cannot be
        converted.
    """
    if access_row is None:
        access_row = await _fetch_access_row(pool, tenant=tenant, project=project, version=version)
    if access_row is None or not access_row.get("mock_enabled"):
        return None

    published = bool(access_row.get("published"))
    if published:
        query = _RESOLVE_PUBLISHED_SOURCE
    else:
        if api_key is None or not row_is_private_mode(access_row):
            return None
        query = _RESOLVE_DRAFT_SOURCE

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, {"tenant": tenant, "project": project, "version": version})
            row = await cur.fetchone()
            if row is None:
                return None

    try:
        api = await asyncio.to_thread(_build_canonical_from_row, row)
    except ConversionError:
        return None

    updated_at = row["updated_at"]
    if not isinstance(updated_at, datetime):
        raise TypeError("expected versions.updated_at to be a datetime")

    return LoadedCanonicalSpec(
        revision_id=row["version_record_id"],
        tenant_slug=str(row["tenant_slug"]),
        project_slug=str(row["project_slug"]),
        version_label=str(row["version_label"]),
        updated_at=updated_at,
        api=api,
        source_format=row.get("source_format"),
        mock_settings=row.get("mock_settings", access_row.get("mock_settings")),
        freshness=spec_stamp_from_row(row, id_column="version_record_id"),
    )


async def get_canonical_access_status(
    pool: AsyncConnectionPool,
    *,
    tenant: str,
    project: str,
    version: str,
    api_key: ValidatedApiKey | None = None,
) -> MockAccessStatus:
    """Return whether canonical mock serving is allowed for the slug coordinates."""
    from apiome_mock.spec_loader import get_mock_access_status

    return await get_mock_access_status(
        pool,
        tenant=tenant,
        project=project,
        version=version,
        api_key=api_key,
    )
