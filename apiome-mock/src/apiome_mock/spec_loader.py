"""Load and compile published OpenAPI specs from Postgres (apiome-mcp read path)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from apiome_mcp.spec_openapi_loaders import fetch_openapi_generation_inputs_async
from app.mock_engine import MockOperation, extract_operations
from app.openapi_generator import generate_openapi_spec
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_RESOLVE_PUBLISHED_SPEC = """
    SELECT
      s.id,
      s.updated_at,
      t.slug AS tenant_slug,
      p.slug AS project_slug,
      v.version_id AS version_label,
      p.description AS project_description,
      v.metadata
    FROM apiome.mcp_v_public_specs s
    INNER JOIN apiome.versions v ON v.id = s.id AND v.deleted_at IS NULL
    INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
    INNER JOIN apiome.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL AND t.enabled IS TRUE
    WHERE t.slug = %(tenant)s
      AND p.slug = %(project)s
      AND v.version_id = %(version)s
    LIMIT 1
"""


def _project_description(row: dict[str, Any]) -> str | None:
    description = row.get("project_description")
    if description is None:
        return None
    text = str(description).strip()
    return text if text else None


@dataclass(frozen=True)
class CompiledSpec:
    """Routing table compiled from a published OpenAPI document."""

    revision_id: UUID
    tenant_slug: str
    project_slug: str
    version_label: str
    updated_at: datetime
    spec: dict[str, Any]
    operations: tuple[MockOperation, ...]

    @property
    def cache_key(self) -> tuple[str, str, str]:
        return (self.tenant_slug, self.project_slug, self.version_label)


async def load_compiled_spec(
    pool: AsyncConnectionPool,
    *,
    tenant: str,
    project: str,
    version: str,
) -> CompiledSpec | None:
    """Resolve a published public spec by slug coordinates and compile its routing table."""
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                _RESOLVE_PUBLISHED_SPEC,
                {"tenant": tenant, "project": project, "version": version},
            )
            row = await cur.fetchone()
            if row is None:
                return None
            revision_id = row["id"]
            inputs = await fetch_openapi_generation_inputs_async(conn, revision_id)
            classes, all_properties, paths_data, security_rows, server_rows = inputs

    spec = generate_openapi_spec(
        str(row["tenant_slug"]),
        str(row["project_slug"]),
        str(row["version_label"]),
        classes,
        all_properties,
        project_description=_project_description(row),
        version_db_id=str(row["id"]),
        revision_metadata=row.get("metadata"),
        paths_data=paths_data,
        security_scheme_rows=security_rows,
        server_rows=server_rows,
    )
    operations = tuple(extract_operations(spec))
    updated_at = row["updated_at"]
    if not isinstance(updated_at, datetime):
        raise TypeError("expected versions.updated_at to be a datetime")

    return CompiledSpec(
        revision_id=revision_id,
        tenant_slug=str(row["tenant_slug"]),
        project_slug=str(row["project_slug"]),
        version_label=str(row["version_label"]),
        updated_at=updated_at,
        spec=spec,
        operations=operations,
    )
