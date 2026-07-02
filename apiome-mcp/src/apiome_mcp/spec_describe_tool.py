"""MCP ``spec.describe`` tool: spec metadata by revision id (#3006, #3012)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastmcp.exceptions import NotFoundError
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_access_audit import schedule_mcp_private_access_audit
from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.spec_authorization import (
    build_authorized_spec_sql_predicate,
    build_mcp_scope_sql_predicate,
)

_DESCRIBE_QUERY_ANONYMOUS = """
    SELECT
      s.id,
      s.title,
      s.version,
      s.description,
      t.slug AS owner,
      s.tags,
      s.updated_at
    FROM apiome.mcp_v_public_specs s
    INNER JOIN apiome.tenants t ON t.id = s.tenant_id
    WHERE s.id = %(spec_id)s::uuid
      AND t.deleted_at IS NULL
      AND t.enabled IS TRUE
    LIMIT 1
"""

# Positional %%s — ``public_scope`` / ``private_auth`` fragments add their own placeholders.
_DESCRIBE_QUERY_AUTHENTICATED = """
SELECT id, title, version, description, owner, tags, updated_at, spec_visibility
FROM (
  SELECT
    s.id,
    s.title,
    s.version,
    s.description,
    t.slug AS owner,
    s.tags,
    s.updated_at,
    'public'::text AS spec_visibility
  FROM apiome.mcp_v_public_specs s
  INNER JOIN apiome.tenants t ON t.id = s.tenant_id
  WHERE s.id = %s::uuid
    AND t.deleted_at IS NULL
    AND t.enabled IS TRUE
    AND ({public_scope})

  UNION ALL

  SELECT
    v.id,
    p.name AS title,
    v.version_id AS version,
    v.description,
    tn.slug AS owner,
    COALESCE(tg.tags, ARRAY[]::TEXT[]) AS tags,
    GREATEST(v.updated_at, p.updated_at, COALESCE(tg.max_tag_updated_at, '-infinity'::timestamptz)) AS updated_at,
    'private'::text AS spec_visibility
  FROM apiome.versions v
  INNER JOIN apiome.projects p ON p.id = v.project_id
  INNER JOIN apiome.tenants tn ON tn.id = p.tenant_id
  LEFT JOIN LATERAL (
    SELECT array_agg(vt.name ORDER BY vt.name) AS tags,
           max(vt.updated_at) AS max_tag_updated_at
    FROM apiome.version_tags vt
    WHERE vt.version_id = v.id AND vt.project_id = v.project_id
  ) tg ON TRUE
  WHERE v.id = %s::uuid
    AND v.deleted_at IS NULL
    AND p.deleted_at IS NULL
    AND v.enabled IS TRUE
    AND p.enabled IS TRUE
    AND tn.deleted_at IS NULL
    AND tn.enabled IS TRUE
    AND v.published IS TRUE
    AND v.visibility = 'private'::apiome.visibility_type
    AND ({private_auth})
) AS merged
LIMIT 1
"""


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_spec_id(raw: str) -> UUID:
    s = str(raw).strip()
    if not s:
        raise ValueError("spec_id is required.")
    try:
        return UUID(s)
    except ValueError as exc:
        raise ValueError("Invalid spec_id: expected a UUID.") from exc


def _row_to_metadata(row: dict[str, Any]) -> dict[str, Any]:
    tags = row["tags"]
    if tags is None:
        tag_list: list[str] = []
    else:
        tag_list = [str(t) for t in list(tags)]

    ua = row["updated_at"]
    desc = row["description"]
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "version": row["version"],
        "description": None if desc is None else str(desc),
        "owner": str(row["owner"]),
        "tags": tag_list,
        "updated_at": _utc(ua).isoformat().replace("+00:00", "Z"),
    }


async def build_spec_describe_response(
    pool: AsyncConnectionPool,
    *,
    spec_id: str,
    auth_ctx: McpAuthContext | None = None,
) -> dict[str, Any]:
    """Return canonical metadata for ``spec_id``, or raise ``NotFoundError``.

    Anonymous callers only resolve revisions present in ``apiome.mcp_v_public_specs``.
    Authenticated callers additionally resolve in-scope private published revisions
    for their tenant (same rules as ``spec.list``, #3011).
    """
    sid = _parse_spec_id(spec_id)

    if auth_ctx is not None and auth_ctx.scope.deny_all:
        raise NotFoundError("Unknown or non-public spec.")

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            if auth_ctx is None:
                await cur.execute(_DESCRIBE_QUERY_ANONYMOUS, {"spec_id": sid})
            else:
                public_scope_sql, public_scope_params = build_mcp_scope_sql_predicate(
                    auth_ctx,
                    tenant_column="s.tenant_id",
                    project_column="s.project_id",
                )
                private_auth_sql, private_auth_params = build_authorized_spec_sql_predicate(
                    auth_ctx,
                    tenant_column="p.tenant_id",
                    project_column="v.project_id",
                    visibility_column="v.visibility",
                )
                query = _DESCRIBE_QUERY_AUTHENTICATED.format(
                    public_scope=public_scope_sql,
                    private_auth=private_auth_sql,
                )
                exec_params = (sid, *public_scope_params, sid, *private_auth_params)
                await cur.execute(query, exec_params)
            row = await cur.fetchone()

    if row is None:
        raise NotFoundError("Unknown or non-public spec.")

    if auth_ctx is not None and row.get("spec_visibility") == "private":
        schedule_mcp_private_access_audit(
            pool,
            key_id=auth_ctx.key_id,
            tool="spec.describe",
            spec_id=str(row["id"]),
        )

    return _row_to_metadata(row)
