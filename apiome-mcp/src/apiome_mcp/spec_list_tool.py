"""MCP ``spec.list`` tool: paginated specs — public catalog plus private rows when authed (#3005, #3011).

Pages on the stored ``versions.mcp_listed_at`` (DBP-1.22, #7205): see :mod:`apiome_mcp.spec_listing_sql`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.cursor_codec import (
    clamp_page_limit,
    cursor_timestamp,
    decode_cursor_payload,
    encode_cursor_payload,
    utc,
)
from apiome_mcp.mcp_access_audit import schedule_mcp_private_access_audit_batch
from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.spec_authorization import (
    build_authorized_spec_sql_predicate,
    build_mcp_scope_sql_predicate,
)
from apiome_mcp.spec_listing_sql import LISTED_PROJECT, PAGE_COLUMNS, Where, listed_version, page_with_tags

CURSOR_VERSION = 1
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


class InvalidSpecListCursorError(ValueError):
    """Raised when ``cursor`` cannot be decoded or fails validation."""


def encode_spec_list_cursor(updated_at: datetime, spec_id: UUID) -> str:
    """Return a stable URL-safe cursor (versioned JSON, base64url without ``=`` padding)."""
    u = utc(updated_at)
    payload = {
        "v": CURSOR_VERSION,
        "i": str(spec_id),
        "u": u.isoformat().replace("+00:00", "Z"),
    }
    return encode_cursor_payload(payload)


def decode_spec_list_cursor(raw: str | None) -> tuple[datetime, UUID] | None:
    """Decode ``cursor`` into ``(updated_at, id)`` or ``None`` when absent."""
    obj = decode_cursor_payload(raw, tool="spec.list", version=CURSOR_VERSION, error=InvalidSpecListCursorError)
    if obj is None:
        return None

    u_raw = obj.get("u")
    i_raw = obj.get("i")
    if not isinstance(u_raw, str) or not isinstance(i_raw, str):
        raise InvalidSpecListCursorError("Invalid spec.list cursor (missing fields).")

    parsed_at = cursor_timestamp(u_raw, tool="spec.list", error=InvalidSpecListCursorError)

    try:
        parsed_id = UUID(i_raw.strip())
    except ValueError as exc:
        raise InvalidSpecListCursorError("Invalid spec.list cursor (bad id).") from exc

    return (utc(parsed_at), parsed_id)


def _clamp_limit(limit: int | None) -> int:
    return clamp_page_limit(limit, default=DEFAULT_PAGE_SIZE, maximum=MAX_PAGE_SIZE)


def _parse_optional_uuid(label: str, raw: str | None) -> UUID | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return UUID(str(raw).strip())
    except ValueError as exc:
        raise ValueError(f"Invalid {label}: expected a UUID.") from exc


def _row_out(row: dict[str, Any]) -> dict[str, Any]:
    tags = row["tags"]
    if tags is None:
        tag_list: list[str] = []
    else:
        tag_list = [str(t) for t in list(tags)]

    ua = row["updated_at"]
    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "project_id": str(row["project_id"]),
        "title": row["title"],
        "version": row["version"],
        "description": row["description"],
        "tags": tag_list,
        "updated_at": utc(ua).isoformat().replace("+00:00", "Z"),
    }


_ORDER = "updated_at DESC, id DESC"
_OUTPUT_COLUMNS = (
    "page.id, page.tenant_id, page.project_id, page.title, page.version, page.description, page.updated_at"
)


def _branch(
    visibility: Literal["public", "private"],
    *,
    access: tuple[str, list[Any]] | None,
    tenant: UUID | None,
    project: UUID | None,
    cursor: tuple[datetime, UUID] | None,
    limit: int,
    with_visibility: bool,
) -> tuple[str, list[Any]]:
    """One visibility's page: listable revisions in list order, after the cursor, limited.

    Args:
        visibility: Which revisions.
        access: The caller's scope / authorization predicate and its parameters (aliases ``p`` and
            ``v``), or ``None`` for an anonymous caller.
        tenant: Optional ``tenant_id`` filter.
        project: Optional ``project_id`` filter.
        cursor: ``(updated_at, id)`` of the last row of the previous page, if any.
        limit: Rows to return.
        with_visibility: Add a ``spec_visibility`` column (the authenticated statement).

    Returns:
        ``(sql, params)``.
    """
    where = Where(listed_version(visibility), LISTED_PROJECT)
    if access is not None:
        where.add(access[0], *access[1])
    where.add_if(tenant, "p.tenant_id = %s")
    where.add_if(project, "v.project_id = %s")
    if cursor is not None:
        where.add("(v.mcp_listed_at, v.id) < (%s, %s)", cursor[0], cursor[1])
    columns = PAGE_COLUMNS + (f", '{visibility}'::text AS spec_visibility" if with_visibility else "")
    sql = f"""
  SELECT {columns}
  FROM apiome.versions v
  INNER JOIN apiome.projects p ON p.id = v.project_id
  WHERE {where.sql}
  ORDER BY v.mcp_listed_at DESC, v.id DESC
  LIMIT %s"""
    return sql, [*where.params, limit]


def build_spec_list_query(
    *,
    auth_ctx: McpAuthContext | None,
    tenant: UUID | None,
    project: UUID | None,
    cursor: tuple[datetime, UUID] | None,
    limit: int,
) -> tuple[str, list[Any]]:
    """The ``spec.list`` statement for a caller: one page, then that page's tags.

    Anonymous callers read the public branch. Authenticated callers read the public branch
    filtered by key scope and the private branch for their own tenant; each branch returns its
    first ``limit`` rows after the cursor, so their merge holds the page's first ``limit`` rows.

    Args:
        auth_ctx: The authenticated caller, or ``None``.
        tenant: Optional ``tenant_id`` filter.
        project: Optional ``project_id`` filter.
        cursor: ``(updated_at, id)`` of the last row already returned, if any.
        limit: Rows to fetch (the page size plus one, to tell whether more exist).

    Returns:
        ``(sql, params)``.
    """
    if auth_ctx is None:
        page_sql, params = _branch(
            "public", access=None, tenant=tenant, project=project, cursor=cursor, limit=limit, with_visibility=False
        )
        return page_with_tags(page_sql, columns=_OUTPUT_COLUMNS, order_by=_ORDER), params

    public_sql, public_params = _branch(
        "public",
        access=build_mcp_scope_sql_predicate(auth_ctx, tenant_column="p.tenant_id", project_column="v.project_id"),
        tenant=tenant,
        project=project,
        cursor=cursor,
        limit=limit,
        with_visibility=True,
    )
    try:
        key_tenant: UUID | None = UUID(str(auth_ctx.tenant_id).strip())
    except ValueError:
        key_tenant = None
    if key_tenant is None or (tenant is not None and tenant != key_tenant):
        # No private revision can match: the key has no tenant, or the filter names another one.
        return page_with_tags(public_sql, columns=_OUTPUT_COLUMNS + ", page.spec_visibility", order_by=_ORDER), (
            public_params
        )
    private_sql, private_params = _branch(
        "private",
        access=build_authorized_spec_sql_predicate(
            auth_ctx,
            tenant_column="p.tenant_id",
            project_column="v.project_id",
            visibility_column="v.visibility",
        ),
        # Private revisions are the key's own tenant's. The authorization predicate says so inside
        # an OR; stating it as a plain equality lets the planner start from that tenant's projects.
        tenant=key_tenant,
        project=project,
        cursor=cursor,
        limit=limit,
        with_visibility=True,
    )
    page_sql = f"""
  SELECT * FROM (
    ({public_sql}
    )
    UNION ALL
    ({private_sql}
    )
  ) AS merged
  ORDER BY {_ORDER}
  LIMIT %s"""
    statement = page_with_tags(page_sql, columns=_OUTPUT_COLUMNS + ", page.spec_visibility", order_by=_ORDER)
    return statement, [*public_params, *private_params, limit]


async def build_spec_list_response(
    pool: AsyncConnectionPool,
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    auth_ctx: McpAuthContext | None = None,
    private_access_audit_tool: str = "spec.list",
) -> dict[str, Any]:
    """Return ``items``, ``has_more``, and ``next_cursor``.

    Anonymous callers see published public specs only. Authenticated callers get the
    same response shape with public rows filtered by key scope plus in-scope private
    revisions for their tenant (see #3011). One statement, whose cost is that of one page.
    """
    tenant = _parse_optional_uuid("tenant_id", tenant_id)
    project = _parse_optional_uuid("project_id", project_id)
    lim = _clamp_limit(limit)
    decoded = decode_spec_list_cursor(cursor)

    if auth_ctx is not None and auth_ctx.scope.deny_all:
        return {"items": [], "has_more": False, "next_cursor": None}

    query, exec_params = build_spec_list_query(
        auth_ctx=auth_ctx, tenant=tenant, project=project, cursor=decoded, limit=lim + 1
    )

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, exec_params)
            rows = await cur.fetchall()

    has_more = len(rows) > lim
    page = rows[:lim]

    if auth_ctx is not None:
        private_spec_ids = [str(r["id"]) for r in page if r.get("spec_visibility") == "private"]
        if private_spec_ids:
            schedule_mcp_private_access_audit_batch(
                pool,
                key_id=auth_ctx.key_id,
                tool=private_access_audit_tool,
                spec_ids=private_spec_ids,
            )

    items = [_row_out(r) for r in page]

    next_cursor: str | None = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_spec_list_cursor(last["updated_at"], last["id"])

    return {
        "items": items,
        "has_more": has_more,
        "next_cursor": next_cursor,
    }
