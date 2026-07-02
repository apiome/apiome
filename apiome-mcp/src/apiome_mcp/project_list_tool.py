"""MCP ``project.list`` tool: distinct projects with cursor pagination."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.spec_authorization import (
    build_authorized_spec_sql_predicate,
    build_mcp_scope_sql_predicate,
)

CURSOR_VERSION = 1
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


class InvalidProjectListCursorError(ValueError):
    """Raised when ``cursor`` cannot be decoded or fails validation."""


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _b64url_pad(s: str) -> str:
    return s + "=" * ((4 - len(s) % 4) % 4)


def encode_project_list_cursor(updated_at: datetime, tenant_id: UUID, project_id: UUID) -> str:
    """Return a stable URL-safe cursor (versioned JSON, base64url without ``=`` padding)."""
    u = _utc(updated_at)
    payload = {
        "v": CURSOR_VERSION,
        "u": u.isoformat().replace("+00:00", "Z"),
        "e": str(tenant_id),
        "p": str(project_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_project_list_cursor(raw: str | None) -> tuple[datetime, UUID, UUID] | None:
    """Decode ``cursor`` into ``(updated_at, tenant_id, project_id)`` or ``None`` when absent."""
    if raw is None:
        return None
    if not raw.strip():
        raise InvalidProjectListCursorError("Invalid project.list cursor (empty value).")
    try:
        blob = base64.urlsafe_b64decode(_b64url_pad(raw.strip()))
        obj = json.loads(blob.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, binascii.Error) as exc:
        raise InvalidProjectListCursorError("Invalid project.list cursor (malformed encoding).") from exc

    if not isinstance(obj, dict):
        raise InvalidProjectListCursorError("Invalid project.list cursor (expected JSON object).")

    ver = obj.get("v")
    if ver != CURSOR_VERSION:
        raise InvalidProjectListCursorError(f"Unsupported project.list cursor version: {ver!r}.")

    u_raw = obj.get("u")
    e_raw = obj.get("e")
    p_raw = obj.get("p")
    if not isinstance(u_raw, str) or not isinstance(e_raw, str) or not isinstance(p_raw, str):
        raise InvalidProjectListCursorError("Invalid project.list cursor (missing fields).")

    iso = u_raw.replace("Z", "+00:00")
    try:
        parsed_at = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise InvalidProjectListCursorError("Invalid project.list cursor (bad timestamp).") from exc

    if parsed_at.tzinfo is None:
        raise InvalidProjectListCursorError("Invalid project.list cursor (timestamp must include timezone offset).")

    try:
        tenant_uuid = UUID(e_raw.strip())
        project_uuid = UUID(p_raw.strip())
    except ValueError as exc:
        raise InvalidProjectListCursorError("Invalid project.list cursor (bad uuid).") from exc

    return (_utc(parsed_at), tenant_uuid, project_uuid)


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE_SIZE
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}.")
    return min(limit, MAX_PAGE_SIZE)


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
        "updated_at": _utc(ua).isoformat().replace("+00:00", "Z"),
    }


_PROJECT_LIST_ANONYMOUS = """
WITH agg AS (
  SELECT tenant_id, project_id, MAX(title) AS title, MAX(updated_at) AS updated_at
  FROM apiome.mcp_v_public_specs
  WHERE (%(tenant)s::uuid IS NULL OR tenant_id = %(tenant)s::uuid)
    AND (%(project)s::uuid IS NULL OR project_id = %(project)s::uuid)
  GROUP BY tenant_id, project_id
)
SELECT tenant_id, project_id, title, updated_at
FROM agg
WHERE (
  %(cur_ts)s::timestamptz IS NULL
  OR (
    updated_at < %(cur_ts)s::timestamptz
    OR (
      updated_at = %(cur_ts)s::timestamptz
      AND tenant_id < %(cur_te)s::uuid
    )
    OR (
      updated_at = %(cur_ts)s::timestamptz
      AND tenant_id = %(cur_te)s::uuid
      AND project_id < %(cur_pr)s::uuid
    )
  )
)
ORDER BY updated_at DESC, tenant_id DESC, project_id DESC
LIMIT %(lim)s
"""

# Positional %%s — filled via str.format with scope/auth fragments from spec_authorization.
_PROJECT_LIST_AUTHENTICATED = """
WITH merged AS (
  SELECT ps.tenant_id, ps.project_id, ps.title, ps.updated_at
  FROM apiome.mcp_v_public_specs AS ps
  WHERE (%s::uuid IS NULL OR ps.tenant_id = %s::uuid)
    AND (%s::uuid IS NULL OR ps.project_id = %s::uuid)
    AND ({public_scope})

  UNION ALL

  SELECT p.tenant_id, v.project_id, p.name AS title,
         GREATEST(
           v.updated_at,
           p.updated_at,
           COALESCE(tg.max_tag_updated_at, '-infinity'::timestamptz)
         ) AS updated_at
  FROM apiome.versions v
  INNER JOIN apiome.projects p ON p.id = v.project_id
  LEFT JOIN LATERAL (
    SELECT max(vt.updated_at) AS max_tag_updated_at
    FROM apiome.version_tags vt
    WHERE vt.version_id = v.id AND vt.project_id = v.project_id
  ) tg ON TRUE
  WHERE v.deleted_at IS NULL
    AND p.deleted_at IS NULL
    AND v.enabled IS TRUE
    AND p.enabled IS TRUE
    AND v.published IS TRUE
    AND v.visibility = 'private'::apiome.visibility_type
    AND ({private_auth})
    AND (%s::uuid IS NULL OR p.tenant_id = %s::uuid)
    AND (%s::uuid IS NULL OR v.project_id = %s::uuid)
),
agg AS (
  SELECT tenant_id, project_id, MAX(title) AS title, MAX(updated_at) AS updated_at
  FROM merged
  GROUP BY tenant_id, project_id
)
SELECT tenant_id, project_id, title, updated_at
FROM agg
WHERE (
  %s::timestamptz IS NULL
  OR (
    updated_at < %s::timestamptz
    OR (
      updated_at = %s::timestamptz
      AND tenant_id < %s::uuid
    )
    OR (
      updated_at = %s::timestamptz
      AND tenant_id = %s::uuid
      AND project_id < %s::uuid
    )
  )
)
ORDER BY updated_at DESC, tenant_id DESC, project_id DESC
LIMIT %s
"""


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
    cur_ts = decoded[0] if decoded else None
    cur_te = decoded[1] if decoded else None
    cur_pr = decoded[2] if decoded else None

    if auth_ctx is not None and auth_ctx.scope.deny_all:
        return {"items": [], "has_more": False, "next_cursor": None}

    if auth_ctx is None:
        params: dict[str, Any] = {
            "tenant": tenant,
            "project": project,
            "cur_ts": cur_ts,
            "cur_te": cur_te,
            "cur_pr": cur_pr,
            "lim": lim + 1,
        }
        query = _PROJECT_LIST_ANONYMOUS
        exec_params: dict[str, Any] | tuple[Any, ...] = params
    else:
        public_scope_sql, public_scope_params = build_mcp_scope_sql_predicate(
            auth_ctx,
            tenant_column="ps.tenant_id",
            project_column="ps.project_id",
        )
        private_auth_sql, private_auth_params = build_authorized_spec_sql_predicate(
            auth_ctx,
            tenant_column="p.tenant_id",
            project_column="v.project_id",
            visibility_column="v.visibility",
        )
        query = _PROJECT_LIST_AUTHENTICATED.format(
            public_scope=public_scope_sql,
            private_auth=private_auth_sql,
        )
        exec_params = (
            tenant,
            tenant,
            project,
            project,
            *public_scope_params,
            *private_auth_params,
            tenant,
            tenant,
            project,
            project,
            cur_ts,
            cur_ts,
            cur_ts,
            cur_te,
            cur_ts,
            cur_te,
            cur_pr,
            lim + 1,
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
