"""The one paging convention for list endpoints (DBP-1.13, #7196).

Every growing list pages the same way:

* ``limit`` — page size, at most :data:`MAX_PAGE_LIMIT`.
* ``cursor`` — an opaque token from the previous page's ``next_cursor``. It names the last row
  the caller saw, so the next page is an index range scan that costs the same on page 1 and on
  page 1,000 (``OFFSET`` reads and discards every skipped row).
* ``has_more`` / ``next_cursor`` — found by reading ``limit + 1`` rows, never by counting.
* ``include_total`` — off by default. When on, the count stops at :data:`TOTAL_CAP`.
* ``offset`` — still accepted where it existed before, deprecated, at most :data:`MAX_OFFSET`.

Endpoints that answer with a bare JSON array keep their body and carry the same two facts in
the :data:`HAS_MORE_HEADER` and :data:`NEXT_CURSOR_HEADER` response headers.

A cursor is urlsafe base64 over a small JSON object. ``{"t": <ISO timestamp>, "i": <id>}`` is the
``(timestamp, id)`` form most lists use (and the form the audit endpoints have always issued);
``{"k": [...]}`` carries any other sort key.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Callable, Dict, Generic, List, Optional, Sequence, Tuple, TypeVar

from fastapi import HTTPException, Query, Response

__all__ = [
    "DEFAULT_PAGE_LIMIT",
    "HAS_MORE_HEADER",
    "MAX_OFFSET",
    "MAX_PAGE_LIMIT",
    "MAX_REVISION_PAGE_LIMIT",
    "NEXT_CURSOR_HEADER",
    "TOTAL_CAP",
    "InvalidCursor",
    "Page",
    "capped_count_sql",
    "clamp_limit",
    "cursor_query",
    "decode_key_cursor",
    "decode_time_id_cursor",
    "encode_key_cursor",
    "encode_time_id_cursor",
    "include_total_query",
    "keyset_after",
    "keyset_before",
    "limit_query",
    "offset_query",
    "page_of",
    "parse_key_cursor",
    "parse_time_id_cursor",
    "set_page_headers",
    "time_id_key",
]

#: The page size used when the caller names none.
DEFAULT_PAGE_LIMIT = 50
#: The hard maximum page size of every list endpoint.
MAX_PAGE_LIMIT = 200
#: The maximum page size of the lists that hold one revision's parts (its classes, its paths):
#: clients read these whole, so the page is large enough that most revisions fit in one.
MAX_REVISION_PAGE_LIMIT = 1000
#: The deepest ``offset`` a deprecated offset request may ask for.
MAX_OFFSET = 10_000
#: ``include_total`` stops counting here; a total equal to the cap means "at least this many".
TOTAL_CAP = 10_000
#: Response header of bare-array lists: ``true`` when another page exists.
HAS_MORE_HEADER = "X-Has-More"
#: Response header of bare-array lists: the cursor of the next page, when there is one.
NEXT_CURSOR_HEADER = "X-Next-Cursor"

_MAX_CURSOR_LENGTH = 2048

T = TypeVar("T")


class InvalidCursor(ValueError):  # noqa: N818 - a refusal, named for what it refuses
    """The cursor is not one this service issued for this list."""


@dataclass(frozen=True)
class Page(Generic[T]):
    """One page of a keyset-paginated list.

    Attributes:
        items: The rows of this page, at most the requested limit.
        has_more: Whether a further page exists.
        next_cursor: The cursor of the next page; ``None`` on the last page.
    """

    items: List[T]
    has_more: bool
    next_cursor: Optional[str]


def clamp_limit(
    limit: Optional[int], *, default: int = DEFAULT_PAGE_LIMIT, maximum: int = MAX_PAGE_LIMIT
) -> int:
    """Resolve a requested page size against the server's bounds.

    Args:
        limit: The requested size; ``None`` for the default.
        default: The size used when none is requested.
        maximum: The largest size allowed.

    Returns:
        A size in ``[1, maximum]``.
    """
    if limit is None:
        return max(1, min(int(default), int(maximum)))
    return max(1, min(int(limit), int(maximum)))


# --------------------------------------------------------------------------------------------
# Cursor tokens
# --------------------------------------------------------------------------------------------


def _jsonable(value: Any) -> Any:
    """Turn one sort-key value into something JSON can carry.

    Args:
        value: A column value (timestamp, UUID, number, string, ``None``).

    Returns:
        The value as a JSON scalar.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


def _encode(payload: Dict[str, Any]) -> str:
    """Serialise a cursor payload.

    Args:
        payload: The JSON object to carry.

    Returns:
        Unpadded urlsafe base64.
    """
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(token: Any) -> Dict[str, Any]:
    """Read a cursor payload back.

    Args:
        token: The cursor as the caller sent it.

    Returns:
        The JSON object it carries.

    Raises:
        InvalidCursor: The token is empty, too long, not base64, or not a JSON object.
    """
    text = str(token or "").strip()
    if not text:
        raise InvalidCursor("empty cursor")
    if len(text) > _MAX_CURSOR_LENGTH:
        raise InvalidCursor("cursor too long")
    try:
        data = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise InvalidCursor("invalid base64") from exc
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidCursor("invalid json") from exc
    if not isinstance(payload, dict):
        raise InvalidCursor("cursor must be a JSON object")
    return payload


def encode_time_id_cursor(timestamp: Any, row_id: Any) -> str:
    """The cursor after a row of a ``(timestamp, id)``-ordered list.

    Args:
        timestamp: The row's sort timestamp (a ``datetime``, or its ISO text).
        row_id: The row's id, the tie-breaker.

    Returns:
        The opaque cursor.
    """
    return _encode({"t": _jsonable(timestamp), "i": str(row_id)})


def decode_time_id_cursor(token: Any) -> Tuple[datetime, str]:
    """Read a ``(timestamp, id)`` cursor.

    Args:
        token: The cursor as the caller sent it.

    Returns:
        ``(timestamp, id)``; the timestamp is timezone-aware.

    Raises:
        InvalidCursor: The token is malformed, or its timestamp has no timezone.
    """
    payload = _decode(token)
    stamp, row_id = payload.get("t"), payload.get("i")
    if not isinstance(stamp, str) or not isinstance(row_id, str) or not row_id:
        raise InvalidCursor("cursor missing t or i")
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidCursor("bad timestamp") from exc
    if parsed.tzinfo is None:
        raise InvalidCursor("cursor timestamp missing timezone info")
    return parsed, row_id


def encode_key_cursor(values: Sequence[Any]) -> str:
    """The cursor after a row of a list ordered by any other key.

    Args:
        values: The row's sort-key values, in ``ORDER BY`` order.

    Returns:
        The opaque cursor.
    """
    return _encode({"k": [_jsonable(value) for value in values]})


def decode_key_cursor(token: Any, size: int) -> List[Any]:
    """Read a sort-key cursor.

    Args:
        token: The cursor as the caller sent it.
        size: How many key values the list's ordering has.

    Returns:
        The key values, in ``ORDER BY`` order.

    Raises:
        InvalidCursor: The token is malformed or carries a different number of values.
    """
    values = _decode(token).get("k")
    if not isinstance(values, list) or len(values) != size:
        raise InvalidCursor("cursor does not match this list")
    if any(isinstance(value, (dict, list)) for value in values):
        raise InvalidCursor("cursor does not match this list")
    return values


def parse_time_id_cursor(token: Optional[str]) -> Optional[Tuple[datetime, str]]:
    """Route-side :func:`decode_time_id_cursor`: no cursor is fine, a bad one is a ``400``.

    Args:
        token: The ``cursor`` query parameter, or ``None``.

    Returns:
        ``(timestamp, id)``, or ``None`` when no cursor was sent.

    Raises:
        HTTPException: ``400`` for a malformed cursor.
    """
    if token is None or not str(token).strip():
        return None
    try:
        return decode_time_id_cursor(token)
    except InvalidCursor as exc:
        raise HTTPException(status_code=400, detail=f"Invalid cursor: {exc}") from exc


def parse_key_cursor(token: Optional[str], size: int) -> Optional[List[Any]]:
    """Route-side :func:`decode_key_cursor`: no cursor is fine, a bad one is a ``400``.

    Args:
        token: The ``cursor`` query parameter, or ``None``.
        size: How many key values the list's ordering has.

    Returns:
        The key values, or ``None`` when no cursor was sent.

    Raises:
        HTTPException: ``400`` for a malformed cursor.
    """
    if token is None or not str(token).strip():
        return None
    try:
        return decode_key_cursor(token, size)
    except InvalidCursor as exc:
        raise HTTPException(status_code=400, detail=f"Invalid cursor: {exc}") from exc


# --------------------------------------------------------------------------------------------
# SQL fragments
# --------------------------------------------------------------------------------------------


def keyset_before(
    timestamp_sql: str,
    id_sql: str,
    cursor: Optional[Tuple[Any, Any]],
    *,
    id_cast: str = "::uuid",
) -> Tuple[str, List[Any]]:
    """The predicate that continues a ``<timestamp> DESC, <id> DESC`` list after a cursor.

    A row-value comparison, so PostgreSQL walks the ``(…, timestamp DESC, id DESC)`` index from
    the cursor position instead of filtering.

    Args:
        timestamp_sql: The timestamp column as the query names it (``n.created_at``).
        id_sql: The id column as the query names it (``n.id``). Trusted SQL, never caller input.
        cursor: ``(timestamp, id)`` from :func:`decode_time_id_cursor`, or ``None`` for page one.
        id_cast: The cast applied to the id parameter (``""`` for a text key).

    Returns:
        ``(sql, params)``: ``" AND (…) < (…)"`` with its parameters, or ``("", [])`` without a
        cursor.
    """
    if cursor is None:
        return "", []
    stamp, row_id = cursor
    return f" AND ({timestamp_sql}, {id_sql}) < (%s, %s{id_cast})", [stamp, row_id]


def keyset_after(
    columns_sql: Sequence[str],
    values: Optional[Sequence[Any]],
    *,
    casts: Optional[Sequence[str]] = None,
) -> Tuple[str, List[Any]]:
    """The predicate that continues an all-ascending list after a cursor.

    Args:
        columns_sql: The ``ORDER BY`` expressions, in order, as the query names them. Trusted SQL.
        values: The cursor's values for those expressions (:func:`decode_key_cursor`), or ``None``
            for page one.
        casts: A cast per value (``"::uuid"``, or ``""``); none by default.

    Returns:
        ``(sql, params)``: ``" AND (…) > (…)"`` with its parameters, or ``("", [])`` without a
        cursor.
    """
    if values is None:
        return "", []
    applied = list(casts) if casts is not None else [""] * len(columns_sql)
    placeholders = ", ".join(f"%s{cast}" for cast in applied)
    return f" AND ({', '.join(columns_sql)}) > ({placeholders})", list(values)


def capped_count_sql(from_and_where_sql: str, *, cap: int = TOTAL_CAP) -> str:
    """A count that stops reading at ``cap`` rows.

    Args:
        from_and_where_sql: ``FROM … WHERE …`` of the list being counted (its parameters are the
            caller's; this adds none).
        cap: Where to stop.

    Returns:
        A ``SELECT`` yielding one ``total`` column, never more than ``cap``.
    """
    return (
        "SELECT count(*)::int AS total FROM ("
        f"SELECT 1 {from_and_where_sql} LIMIT {int(cap)}"
        ") capped"
    )


# --------------------------------------------------------------------------------------------
# Pages
# --------------------------------------------------------------------------------------------


def time_id_key(timestamp_field: str = "created_at", id_field: str = "id") -> Callable[[Any], str]:
    """A cursor builder for rows of a ``(timestamp, id)``-ordered list.

    Args:
        timestamp_field: The row key holding the sort timestamp.
        id_field: The row key holding the id.

    Returns:
        A function from a row mapping to its cursor.
    """

    def build(row: Any) -> str:
        return encode_time_id_cursor(row[timestamp_field], row[id_field])

    return build


def page_of(rows: Sequence[T], limit: int, cursor_of: Callable[[T], str]) -> Page[T]:
    """Cut a ``limit + 1`` read down to a page.

    Args:
        rows: The rows read with ``LIMIT limit + 1``.
        limit: The page size the caller asked for.
        cursor_of: Builds the cursor that follows a row (see :func:`time_id_key`).

    Returns:
        The page; ``next_cursor`` is set only when a further row was read.
    """
    items = list(rows[:limit])
    has_more = len(rows) > limit
    next_cursor = cursor_of(items[-1]) if has_more and items else None
    return Page(items=items, has_more=has_more, next_cursor=next_cursor)


def set_page_headers(response: Response, page: Page[Any]) -> None:
    """Report a bare-array list's paging state in response headers.

    Args:
        response: The response FastAPI will send.
        page: The page being returned.
    """
    response.headers[HAS_MORE_HEADER] = "true" if page.has_more else "false"
    if page.next_cursor:
        response.headers[NEXT_CURSOR_HEADER] = page.next_cursor


# --------------------------------------------------------------------------------------------
# Query parameters (one wording across the OpenAPI document)
# --------------------------------------------------------------------------------------------


def limit_query(default: int = DEFAULT_PAGE_LIMIT, *, maximum: int = MAX_PAGE_LIMIT) -> Any:
    """The ``limit`` query parameter.

    Args:
        default: The page size when the caller names none.
        maximum: The documented hard maximum.

    Returns:
        A FastAPI ``Query`` default.
    """
    return Query(
        default=default,
        ge=1,
        le=maximum,
        description=f"Page size. At most {maximum}.",
    )


def cursor_query() -> Any:
    """The ``cursor`` query parameter.

    Returns:
        A FastAPI ``Query`` default.
    """
    return Query(
        default=None,
        max_length=_MAX_CURSOR_LENGTH,
        description=(
            "Opaque cursor from the previous page (`next_cursor`, or the `X-Next-Cursor` header). "
            "Omit for the first page."
        ),
    )


def include_total_query() -> Any:
    """The ``include_total`` query parameter.

    Returns:
        A FastAPI ``Query`` default.
    """
    return Query(
        default=False,
        description=(
            "Also count the matching rows. Off by default because counting reads every match; "
            f"the count stops at {TOTAL_CAP:,}."
        ),
    )


def offset_query() -> Any:
    """The deprecated ``offset`` query parameter.

    Returns:
        A FastAPI ``Query`` default.
    """
    return Query(
        default=0,
        ge=0,
        le=MAX_OFFSET,
        deprecated=True,
        description=(
            f"Rows to skip. Deprecated: page with `cursor` instead. At most {MAX_OFFSET:,}."
        ),
    )
