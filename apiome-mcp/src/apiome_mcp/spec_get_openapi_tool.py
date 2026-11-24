"""MCP ``spec.get_openapi`` tool: full generated OpenAPI 3.1 JSON by revision id (#3016).

Also the one place the spec tools build a revision's document (DBP-1.22, #7205):

* :func:`build_spec_get_openapi_response` — the whole document, for ``spec.get_openapi``,
  ``spec.export_yaml``, ``spec.describe_operation`` and ``spec.describe_component``;
* :func:`build_spec_part_response` — a value derived from the document that needs only some of
  its rows: the operation index (``spec.list_operations``) and the component names
  (``spec.list_components``).

Every call runs one resolve statement, which authorizes the caller and returns the revision's
freshness. The built value is then served from :data:`~apiome_mcp.spec_document_cache.DOCUMENT_CACHE`
(no further statement) or built from a fixed number of statements
(:func:`~apiome_mcp.spec_openapi_loaders.load_openapi_inputs`) and cached.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from uuid import UUID

from app.openapi_generator import generate_openapi_spec
from fastmcp.exceptions import NotFoundError, ToolError
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_access_audit import schedule_mcp_private_access_audit
from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.settings import get_settings
from apiome_mcp.spec_authorization import (
    build_authorized_spec_sql_predicate,
    build_mcp_scope_sql_predicate,
)
from apiome_mcp.spec_document_cache import DOCUMENT_CACHE, compact_json_size
from apiome_mcp.spec_openapi_loaders import OpenApiPart, load_openapi_inputs

_GET_OPENAPI_QUERY_ANONYMOUS = """
    SELECT
      s.id,
      t.slug AS tenant_slug,
      p.slug AS project_slug,
      v.version_id AS version_label,
      p.description AS project_description,
      v.metadata,
      v.updated_at AS version_updated_at,
      v.content_stamp,
      'public'::text AS spec_visibility
    FROM apiome.mcp_v_public_specs s
    INNER JOIN apiome.versions v ON v.id = s.id AND v.deleted_at IS NULL
    INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
    INNER JOIN apiome.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL AND t.enabled IS TRUE
    WHERE s.id = %(spec_id)s::uuid
    LIMIT 1
"""

_GET_OPENAPI_QUERY_AUTHENTICATED = """
SELECT id, tenant_slug, project_slug, version_label, project_description, metadata,
       version_updated_at, content_stamp, spec_visibility
FROM (
  SELECT
    s.id,
    t.slug AS tenant_slug,
    p.slug AS project_slug,
    v.version_id AS version_label,
    p.description AS project_description,
    v.metadata,
    v.updated_at AS version_updated_at,
    v.content_stamp,
    'public'::text AS spec_visibility
  FROM apiome.mcp_v_public_specs s
  INNER JOIN apiome.versions v ON v.id = s.id AND v.deleted_at IS NULL
  INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
  INNER JOIN apiome.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL AND t.enabled IS TRUE
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
    v.updated_at AS version_updated_at,
    v.content_stamp,
    'private'::text AS spec_visibility
  FROM apiome.versions v
  INNER JOIN apiome.projects p ON p.id = v.project_id
  INNER JOIN apiome.tenants tn ON tn.id = p.tenant_id
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


def _freshness(row: dict[str, Any]) -> tuple[Any, ...]:
    """Everything of the resolve row the generated document depends on (the cache key's tail)."""
    return (
        row.get("version_updated_at"),
        row.get("content_stamp"),
        str(row["tenant_slug"]),
        str(row["project_slug"]),
        str(row["version_label"]),
        _project_description(row),
    )


async def _resolve_spec_row(cur: Any, sid: UUID, auth_ctx: McpAuthContext | None) -> dict[str, Any] | None:
    """Run the resolve statement: the revision's row if the caller may read it, else ``None``."""
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
        await cur.execute(query, (sid, *public_scope_params, sid, *private_auth_params))
    row = await cur.fetchone()
    return dict(row) if row is not None else None


async def _load_spec_part(
    pool: AsyncConnectionPool,
    *,
    spec_id: str,
    auth_ctx: McpAuthContext | None,
    part: OpenApiPart,
    derive: Callable[[dict[str, Any]], Any] | None,
    private_access_audit_tool: str,
) -> tuple[Any, int]:
    """Resolve ``spec_id`` for the caller and return ``(value, compact JSON size)`` for ``part``.

    ``part="document"`` yields the OpenAPI document. Any other part yields ``derive(document)``,
    taken from the cached full document when there is one, else from a document generated from
    that part's rows only.

    Raises:
        ValueError: ``spec_id`` is empty or not a UUID.
        NotFoundError: The revision does not exist or the caller may not read it.
    """
    sid = _parse_spec_id(spec_id)

    if auth_ctx is not None and auth_ctx.scope.deny_all:
        raise NotFoundError("Unknown or non-public spec.")

    cached: tuple[Any, int] | None = None
    full: tuple[Any, int] | None = None
    inputs = None
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            row = await _resolve_spec_row(cur, sid, auth_ctx)
        if row is None:
            raise NotFoundError("Unknown or non-public spec.")

        freshness = _freshness(row)
        key = (part, row["id"], freshness)
        cached = DOCUMENT_CACHE.get(key)
        if cached is None and part != "document":
            full = DOCUMENT_CACHE.get(("document", row["id"], freshness))
        if cached is None and full is None:
            inputs = await load_openapi_inputs(conn, sid, part=part)

    if auth_ctx is not None and row.get("spec_visibility") == "private":
        schedule_mcp_private_access_audit(
            pool,
            key_id=auth_ctx.key_id,
            tool=private_access_audit_tool,
            spec_id=str(row["id"]),
        )

    if cached is not None:
        return cached
    if full is not None and derive is not None:
        # Derived from the shared document on every call: cheap, and nothing extra to keep.
        value = derive(full[0])
        return value, compact_json_size(value)

    assert inputs is not None
    value = generate_openapi_spec(
        str(row["tenant_slug"]),
        str(row["project_slug"]),
        str(row["version_label"]),
        project_description=_project_description(row),
        version_db_id=str(row["id"]),
        revision_metadata=row.get("metadata"),
        **inputs.generator_kwargs(),
    )
    if derive is not None:
        value = derive(value)
    size = compact_json_size(value)
    DOCUMENT_CACHE.put(key, value, size)
    return value, size


async def build_spec_part_response(
    pool: AsyncConnectionPool,
    *,
    spec_id: str,
    part: OpenApiPart,
    derive: Callable[[dict[str, Any]], Any],
    auth_ctx: McpAuthContext | None = None,
    private_access_audit_tool: str,
) -> Any:
    """Return ``derive(document)`` for ``spec_id``, reading only the rows ``part`` needs.

    Args:
        pool: The catalog pool.
        spec_id: The revision id.
        part: ``"operations"`` or ``"components"`` — which rows ``derive`` depends on (see
            :func:`~apiome_mcp.spec_openapi_loaders.load_openapi_inputs`).
        derive: Pure function of the OpenAPI document. Its result is cached and shared between
            calls, so callers must not mutate what they get.
        auth_ctx: The authenticated caller, or ``None`` for an anonymous one.
        private_access_audit_tool: Tool name stored when a private revision is returned.

    Returns:
        What ``derive`` returns for the revision's document.

    Raises:
        ValueError: ``spec_id`` is empty or not a UUID.
        NotFoundError: The revision does not exist or the caller may not read it.
    """
    value, _ = await _load_spec_part(
        pool,
        spec_id=spec_id,
        auth_ctx=auth_ctx,
        part=part,
        derive=derive,
        private_access_audit_tool=private_access_audit_tool,
    )
    return value


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

    The returned document is shared with the document cache: callers must not mutate it.
    """
    spec, size = await _load_spec_part(
        pool,
        spec_id=spec_id,
        auth_ctx=auth_ctx,
        part="document",
        derive=None,
        private_access_audit_tool=private_access_audit_tool,
    )

    if apply_json_payload_cap:
        settings = get_settings()
        if size > settings.openapi_max_json_bytes:
            raise ToolError(
                f"OpenAPI document exceeds server limit ({settings.openapi_max_json_bytes} bytes); "
                "this condition corresponds to HTTP 413 Payload Too Large."
            )

    return cast(dict[str, Any], spec)
