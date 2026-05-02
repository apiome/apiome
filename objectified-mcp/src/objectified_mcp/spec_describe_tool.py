"""MCP ``spec.describe`` tool: public spec metadata by revision id (#3006)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastmcp.exceptions import NotFoundError
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_DESCRIBE_QUERY = """
    SELECT
      s.id,
      s.title,
      s.version,
      s.description,
      t.slug AS owner,
      s.tags,
      s.updated_at
    FROM odb.mcp_v_public_specs s
    INNER JOIN odb.tenants t ON t.id = s.tenant_id
    WHERE s.id = %(spec_id)s::uuid
      AND t.deleted_at IS NULL
      AND t.enabled IS TRUE
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


async def build_spec_describe_response(pool: AsyncConnectionPool, *, spec_id: str) -> dict[str, Any]:
    """Return canonical public metadata for ``spec_id``, or raise ``NotFoundError``."""
    sid = _parse_spec_id(spec_id)

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_DESCRIBE_QUERY, {"spec_id": sid})
            row = await cur.fetchone()

    if row is None:
        raise NotFoundError("Unknown or non-public spec.")

    return _row_to_metadata(row)
