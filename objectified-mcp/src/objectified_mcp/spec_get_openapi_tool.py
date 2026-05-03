"""MCP ``spec.get_openapi`` tool: full generated OpenAPI 3.1 JSON by revision id (#3016)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app.openapi_generator import generate_openapi_spec
from fastmcp.exceptions import NotFoundError, ToolError
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from objectified_mcp.mcp_access_audit import schedule_mcp_private_access_audit
from objectified_mcp.mcp_auth import McpAuthContext
from objectified_mcp.settings import get_settings
from objectified_mcp.spec_authorization import (
    build_authorized_spec_sql_predicate,
    build_mcp_scope_sql_predicate,
)
from objectified_mcp.spec_openapi_loaders import fetch_openapi_generation_inputs_async

_GET_OPENAPI_QUERY_ANONYMOUS = """
    SELECT
      s.id,
      t.slug AS tenant_slug,
      p.slug AS project_slug,
      v.version_id AS version_label,
      p.description AS project_description,
      v.metadata,
      'public'::text AS spec_visibility
    FROM odb.mcp_v_public_specs s
    INNER JOIN odb.versions v ON v.id = s.id AND v.deleted_at IS NULL
    INNER JOIN odb.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
    INNER JOIN odb.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL AND t.enabled IS TRUE
    WHERE s.id = %(spec_id)s::uuid
    LIMIT 1
"""

_GET_OPENAPI_QUERY_AUTHENTICATED = """
SELECT id, tenant_slug, project_slug, version_label, project_description, metadata, spec_visibility
FROM (
  SELECT
    s.id,
    t.slug AS tenant_slug,
    p.slug AS project_slug,
    v.version_id AS version_label,
    p.description AS project_description,
    v.metadata,
    'public'::text AS spec_visibility
  FROM odb.mcp_v_public_specs s
  INNER JOIN odb.versions v ON v.id = s.id AND v.deleted_at IS NULL
  INNER JOIN odb.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
  INNER JOIN odb.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL AND t.enabled IS TRUE
  WHERE s.id = %s::uuid
    AND ({public_scope})

  UNION ALL

  SELECT
    v.id,
    tn.slug AS tenant_slug,
    p.slug AS project_slug,
    v.version_id AS version_label,
    p.description AS project_description,
    v.metadata,
    'private'::text AS spec_visibility
  FROM odb.versions v
  INNER JOIN odb.projects p ON p.id = v.project_id
  INNER JOIN odb.tenants tn ON tn.id = p.tenant_id
  WHERE v.id = %s::uuid
    AND v.deleted_at IS NULL
    AND p.deleted_at IS NULL
    AND v.enabled IS TRUE
    AND p.enabled IS TRUE
    AND tn.deleted_at IS NULL
    AND tn.enabled IS TRUE
    AND v.published IS TRUE
    AND v.visibility = 'private'::odb.visibility_type
    AND ({private_auth})
) AS merged
LIMIT 1
"""


def _parse_spec_id(raw: str) -> UUID:
    s = str(raw).strip()
    if not s:
        raise ValueError("spec_id is required.")
    try:
        return UUID(s)
    except ValueError as exc:
        raise ValueError("Invalid spec_id: expected a UUID.") from exc


def _project_description(row: dict[str, Any]) -> str | None:
    d = row.get("project_description")
    if d is None:
        return None
    t = str(d).strip()
    return t if t else None


async def build_spec_get_openapi_response(
    pool: AsyncConnectionPool,
    *,
    spec_id: str,
    auth_ctx: McpAuthContext | None = None,
    apply_json_payload_cap: bool = True,
    private_access_audit_tool: str = "spec.get_openapi",
) -> dict[str, Any]:
    """Return OpenAPI 3.1 document dict for ``spec_id``, or raise ``NotFoundError`` / ``ToolError``.

    When ``apply_json_payload_cap`` is False, skip the compact JSON byte limit (used by YAML export,
    which applies its own UTF-8 cap). ``private_access_audit_tool`` names the tool stored when a private
    revision is returned to an authenticated caller.
    """
    sid = _parse_spec_id(spec_id)

    if auth_ctx is not None and auth_ctx.scope.deny_all:
        raise NotFoundError("Unknown or non-public spec.")

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            if auth_ctx is None:
                await cur.execute(_GET_OPENAPI_QUERY_ANONYMOUS, {"spec_id": sid})
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
                query = _GET_OPENAPI_QUERY_AUTHENTICATED.format(
                    public_scope=public_scope_sql,
                    private_auth=private_auth_sql,
                )
                exec_params = (sid, *public_scope_params, sid, *private_auth_params)
                await cur.execute(query, exec_params)
            row = await cur.fetchone()

        if row is None:
            raise NotFoundError("Unknown or non-public spec.")

        classes, all_properties, paths_data, security_rows, server_rows = await fetch_openapi_generation_inputs_async(
            conn,
            sid,
        )

    if auth_ctx is not None and row.get("spec_visibility") == "private":
        schedule_mcp_private_access_audit(
            pool,
            key_id=auth_ctx.key_id,
            tool=private_access_audit_tool,
            spec_id=str(row["id"]),
        )

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

    if apply_json_payload_cap:
        settings = get_settings()
        encoded = json.dumps(spec, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(encoded) > settings.openapi_max_json_bytes:
            raise ToolError(
                f"OpenAPI document exceeds server limit ({settings.openapi_max_json_bytes} bytes); "
                "this condition corresponds to HTTP 413 Payload Too Large."
            )

    return spec
