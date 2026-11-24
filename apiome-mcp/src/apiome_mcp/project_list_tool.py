"""MCP ``project.list`` tool: distinct projects with cursor pagination.

Reads the per-project rollup ``apiome.mcp_project_listing`` (DBP-1.22, #7205) instead of grouping
every listed revision by project on each page.
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
from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.spec_authorization import build_mcp_scope_sql_predicate
from apiome_mcp.spec_listing_sql import LISTED_PROJECT, Where

CURSOR_VERSION = 1
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


class InvalidProjectListCursorError(ValueError):
    """Raised when ``cursor`` cannot be decoded or fails validation."""


def encode_project_list_cursor(updated_at: datetime, tenant_id: UUID, project_id: UUID) -> str:
    """Return a stable URL-safe cursor (versioned JSON, base64url without ``=`` padding)."""
    u = utc(updated_at)
    payload = {
        "v": CURSOR_VERSION,
        "u": u.isoformat().replace("+00:00", "Z"),
        "e": str(tenant_id),
        "p": str(project_id),
    }
    return encode_cursor_payload(payload)


def decode_project_list_cursor(raw: str | None) -> tuple[datetime, UUID, UUID] | None:
    """Decode ``cursor`` into ``(updated_at, tenant_id, project_id)`` or ``None`` when absent."""
    obj = decode_cursor_payload(raw, tool="project.list", version=CURSOR_VERSION, error=InvalidProjectListCursorError)
    if obj is None:
        return None

    u_raw = obj.get("u")
    e_raw = obj.get("e")
    p_raw = obj.get("p")
    if not isinstance(u_raw, str) or not isinstance(e_raw, str) or not isinstance(p_raw, str):
        raise InvalidProjectListCursorError("Invalid project.list cursor (missing fields).")

    parsed_at = cursor_timestamp(u_raw, tool="project.list", error=InvalidProjectListCursorError)

    try:
        tenant_uuid = UUID(e_raw.strip())
        project_uuid = UUID(p_raw.strip())
    except ValueError as exc:
        raise InvalidProjectListCursorError("Invalid project.list cursor (bad uuid).") from exc

    return (utc(parsed_at), tenant_uuid, project_uuid)


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
    ua = row["updated_at"]
    return {
        "tenant_id": str(row["tenant_id"]),
        "project_id": str(row["project_id"]),
        "title": row["title"],
        "updated_at": utc(ua).isoformat().replace("+00:00", "Z"),
    }


_ORDER = "updated_at DESC, tenant_id DESC, project_id DESC"


def _branch(
    stamp: Literal["public_listed_at", "listed_at"],
    *,
    access: tuple[str, list[Any]] | None,
    own_tenant: tuple[str, UUID] | None,
    tenant: UUID | None,
    project: UUID | None,
    cursor: tuple[datetime, UUID, UUID] | None,
    limit: int,
) -> tuple[str, list[Any]]:
    """One page of ``apiome.mcp_project_listing`` in list order on one of its timestamps.

    Args:
        stamp: ``public_listed_at`` (projects with a public listed revision) or ``listed_at``
            (projects with any listed revision — a key's own tenant).
        access: The caller's scope predicate and its parameters (columns ``l.tenant_id``,
            ``l.project_id``), or ``None`` for an anonymous caller.
        own_tenant: ``("=", id)`` to read only the key's tenant, ``("<>", id)`` to read every
            other tenant, ``None`` for no such split.
        tenant: Optional ``tenant_id`` filter.
        project: Optional ``project_id`` filter.
        cursor: ``(updated_at, tenant_id, project_id)`` of the last row already returned, if any.
        limit: Rows to return.

    Returns:
        ``(sql, params)``.
    """
    where = Where(f"l.{stamp} IS NOT NULL", LISTED_PROJECT)
    if own_tenant is not None:
        where.add(f"l.tenant_id {own_tenant[0]} %s", own_tenant[1])
    if access is not None:
        where.add(access[0], *access[1])
    where.add_if(tenant, "l.tenant_id = %s")
    where.add_if(project, "l.project_id = %s")
    if cursor is not None:
        where.add(f"(l.{stamp}, l.tenant_id, l.project_id) < (%s, %s, %s)", *cursor)
    sql = f"""
  SELECT l.tenant_id, l.project_id, p.name AS title, l.{stamp} AS updated_at
  FROM apiome.mcp_project_listing l
  INNER JOIN apiome.projects p ON p.id = l.project_id
  WHERE {where.sql}
  ORDER BY l.{stamp} DESC, l.tenant_id DESC, l.project_id DESC
  LIMIT %s"""
    return sql, [*where.params, limit]


def build_project_list_query(
    *,
    auth_ctx: McpAuthContext | None,
    tenant: UUID | None,
    project: UUID | None,
    cursor: tuple[datetime, UUID, UUID] | None,
    limit: int,
) -> tuple[str, list[Any]]:
    """The ``project.list`` statement for a caller, over the per-project rollup (V428).

    A project's ``updated_at`` is the newest listing timestamp of the revisions the caller may
    see: its public revisions for an anonymous caller or a key of another tenant
    (``public_listed_at``), all its listed revisions for a key of the owning tenant
    (``listed_at``). The two cases are disjoint sets of projects, so an authenticated caller's
    page is the merge of one limited read of each.

    Args:
        auth_ctx: The authenticated caller, or ``None``.
        tenant: Optional ``tenant_id`` filter.
        project: Optional ``project_id`` filter.
        cursor: ``(updated_at, tenant_id, project_id)`` of the last row already returned, if any.
        limit: Rows to fetch (the page size plus one).

    Returns:
        ``(sql, params)``.
    """
    common: dict[str, Any] = {"tenant": tenant, "project": project, "cursor": cursor, "limit": limit}
    if auth_ctx is None:
        return _branch("public_listed_at", access=None, own_tenant=None, **common)

    access = build_mcp_scope_sql_predicate(auth_ctx, tenant_column="l.tenant_id", project_column="l.project_id")
    try:
        key_tenant: UUID | None = UUID(str(auth_ctx.tenant_id).strip())
    except ValueError:
        key_tenant = None
    if key_tenant is None:
        # A key without a tenant id owns no private revisions: the public rollup is all it sees.
        return _branch("public_listed_at", access=access, own_tenant=None, **common)

    others_sql, others_params = _branch("public_listed_at", access=access, own_tenant=("<>", key_tenant), **common)
    own_sql, own_params = _branch("listed_at", access=access, own_tenant=("=", key_tenant), **common)
    sql = f"""
SELECT tenant_id, project_id, title, updated_at FROM (
  ({others_sql}
  )
  UNION ALL
  ({own_sql}
  )
) AS merged
ORDER BY {_ORDER}
LIMIT %s"""
    return sql, [*others_params, *own_params, limit]


async def build_project_list_response(
    pool: AsyncConnectionPool,
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
    auth_ctx: McpAuthContext | None = None,
) -> dict[str, Any]:
    """Return ``items``, ``has_more``, and ``next_cursor`` for distinct projects.

    Each item is the latest activity timestamp across published revisions the caller
    may see (public catalog, or merged public + private when authenticated).
    """
    tenant = _parse_optional_uuid("tenant_id", tenant_id)
    project = _parse_optional_uuid("project_id", project_id)
    lim = _clamp_limit(limit)
    decoded = decode_project_list_cursor(cursor)

    if auth_ctx is not None and auth_ctx.scope.deny_all:
        return {"items": [], "has_more": False, "next_cursor": None}

    query, exec_params = build_project_list_query(
        auth_ctx=auth_ctx, tenant=tenant, project=project, cursor=decoded, limit=lim + 1
    )

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, exec_params)
            rows = await cur.fetchall()

    has_more = len(rows) > lim
    page = rows[:lim]
    items = [_row_out(r) for r in page]

    next_cursor: str | None = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_project_list_cursor(
            last["updated_at"],
            last["tenant_id"],
            last["project_id"],
        )

    return {
        "items": items,
        "has_more": has_more,
        "next_cursor": next_cursor,
    }
