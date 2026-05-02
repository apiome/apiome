"""MCP ``spec.list`` tool: paginated public specs from ``odb.mcp_v_public_specs`` (#3005)."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

CURSOR_VERSION = 1
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


class InvalidSpecListCursorError(ValueError):
    """Raised when ``cursor`` cannot be decoded or fails validation."""


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def encode_spec_list_cursor(updated_at: datetime, spec_id: UUID) -> str:
    """Return a stable URL-safe cursor (versioned JSON, base64url without ``=`` padding)."""
    u = _utc(updated_at)
    payload = {
        "v": CURSOR_VERSION,
        "i": str(spec_id),
        "u": u.isoformat().replace("+00:00", "Z"),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_pad(s: str) -> str:
    return s + "=" * ((4 - len(s) % 4) % 4)


def decode_spec_list_cursor(raw: str | None) -> tuple[datetime, UUID] | None:
    """Decode ``cursor`` into ``(updated_at, id)`` or ``None`` when absent."""
    if raw is None:
        return None
    if not raw.strip():
        raise InvalidSpecListCursorError("Invalid spec.list cursor (empty value).")
    try:
        blob = base64.urlsafe_b64decode(_b64url_pad(raw.strip()))
        obj = json.loads(blob.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, binascii.Error) as exc:
        raise InvalidSpecListCursorError("Invalid spec.list cursor (malformed encoding).") from exc

    if not isinstance(obj, dict):
        raise InvalidSpecListCursorError("Invalid spec.list cursor (expected JSON object).")

    ver = obj.get("v")
    if ver != CURSOR_VERSION:
        raise InvalidSpecListCursorError(f"Unsupported spec.list cursor version: {ver!r}.")

    u_raw = obj.get("u")
    i_raw = obj.get("i")
    if not isinstance(u_raw, str) or not isinstance(i_raw, str):
        raise InvalidSpecListCursorError("Invalid spec.list cursor (missing fields).")

    iso = u_raw.replace("Z", "+00:00")
    try:
        parsed_at = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise InvalidSpecListCursorError("Invalid spec.list cursor (bad timestamp).") from exc

    if parsed_at.tzinfo is None:
        raise InvalidSpecListCursorError("Invalid spec.list cursor (timestamp must include timezone offset).")

    try:
        parsed_id = UUID(i_raw.strip())
    except ValueError as exc:
        raise InvalidSpecListCursorError("Invalid spec.list cursor (bad id).") from exc

    return (_utc(parsed_at), parsed_id)


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
        "updated_at": _utc(ua).isoformat().replace("+00:00", "Z"),
    }


_LIST_QUERY = """
    SELECT id, tenant_id, project_id, title, version, description, tags, updated_at
    FROM odb.mcp_v_public_specs
    WHERE (%(tenant)s::uuid IS NULL OR tenant_id = %(tenant)s::uuid)
      AND (%(project)s::uuid IS NULL OR project_id = %(project)s::uuid)
      AND (
        %(cur_ts)s::timestamptz IS NULL
        OR (updated_at, id) < (%(cur_ts)s::timestamptz, %(cur_id)s::uuid)
      )
    ORDER BY updated_at DESC, id DESC
    LIMIT %(lim)s
"""


async def build_spec_list_response(
    pool: AsyncConnectionPool,
    *,
    tenant_id: str | None = None,
    project_id: str | None = None,
    limit: int | None = None,
    cursor: str | None = None,
) -> dict[str, Any]:
    """Return ``items``, ``has_more``, and ``next_cursor`` for public specs."""
    tenant = _parse_optional_uuid("tenant_id", tenant_id)
    project = _parse_optional_uuid("project_id", project_id)
    lim = _clamp_limit(limit)
    decoded = decode_spec_list_cursor(cursor)
    cur_ts = decoded[0] if decoded else None
    cur_id = decoded[1] if decoded else None

    params: dict[str, Any] = {
        "tenant": tenant,
        "project": project,
        "cur_ts": cur_ts,
        "cur_id": cur_id,
        "lim": lim + 1,
    }

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_LIST_QUERY, params)
            rows = await cur.fetchall()

    has_more = len(rows) > lim
    page = rows[:lim]
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
