"""Keyset paging for lists whose ordering is not ``(timestamp DESC, id DESC)`` (DBP-1.13, #7196).

:mod:`app.keyset_pagination` covers the common newest-first list with one row-value comparison.
Some lists sort by a caller-chosen column, mix ascending and descending columns, or lead with a
nullable one; a row-value comparison cannot express those. This module describes such an ordering
as a tuple of :class:`SortColumn` and derives everything else from it: the cursor after a row,
the check of a cursor a caller sends back, and the ``WHERE`` predicate that continues the list.

The columns must spell the list's ``ORDER BY`` exactly (same expressions, same directions, ending
in a unique column); the predicate is only correct against that ordering.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from .keyset_pagination import InvalidCursor, decode_key_cursor, encode_key_cursor

__all__ = [
    "SortColumn",
    "decode_columns_cursor",
    "encode_columns_cursor",
    "keyset_after_columns",
    "order_by_sql",
]


@dataclass(frozen=True)
class SortColumn:
    """One column of a list ordering.

    Attributes:
        sql: The expression, spelled exactly as the ``ORDER BY`` evaluates it. An output alias
            cannot be named in ``WHERE``, so a computed column repeats its full expression.
            Trusted SQL, never caller input.
        kind: ``text``, ``uuid``, ``int``, ``float``, ``bool`` or ``time`` — picks the parameter
            cast and how a cursor value is checked.
        fields: Row keys holding the value; the first non-null one wins (mirrors a ``COALESCE``).
        descending: Whether the column sorts ``DESC``.
        nullable: Whether the expression can be ``NULL``. Its ``NULL`` rows sort last
            (PostgreSQL's default ascending, ``NULLS LAST`` descending) unless ``nulls_first``.
        nulls_first: For a nullable column, whether ``NULL`` rows sort first instead.
    """

    sql: str
    kind: str
    fields: Tuple[str, ...]
    descending: bool = False
    nullable: bool = False
    nulls_first: bool = False


_KIND_CAST = {
    "text": "",
    "uuid": "::uuid",
    "int": "::bigint",
    "float": "::double precision",
    "bool": "::boolean",
    "time": "::timestamptz",
}

_MISMATCH = "cursor does not match this list"


def order_by_sql(columns: Sequence[SortColumn]) -> str:
    """The ``ORDER BY`` list the columns describe.

    Args:
        columns: The ordering.

    Returns:
        ``a ASC, b DESC NULLS LAST, …`` — without the ``ORDER BY`` keyword.
    """
    parts: List[str] = []
    for column in columns:
        direction = "DESC" if column.descending else "ASC"
        nulls = ""
        if column.nullable:
            nulls = " NULLS FIRST" if column.nulls_first else " NULLS LAST"
        parts.append(f"{column.sql} {direction}{nulls}")
    return ", ".join(parts)


def encode_columns_cursor(tag: str, columns: Sequence[SortColumn], row: Mapping[str, Any]) -> str:
    """The cursor that continues a list after ``row``.

    Args:
        tag: Names the ordering (the sort key and direction). A cursor is only accepted back for
            the ordering it was issued under.
        columns: The ordering.
        row: The last row of the page.

    Returns:
        An opaque cursor carrying the tag and the row's sort values.
    """
    values: List[Any] = [tag]
    for column in columns:
        values.append(next((row[f] for f in column.fields if row.get(f) is not None), None))
    return encode_key_cursor(values)


def _checked(column: SortColumn, value: Any) -> Any:
    """Check one cursor value against the column it claims to belong to.

    Args:
        column: The sort column.
        value: The value the cursor carries for it.

    Returns:
        The value as the query parameter (timestamps parsed, UUIDs normalized).

    Raises:
        InvalidCursor: The value has the wrong type for the column.
    """
    if value is None:
        if column.nullable:
            return None
        raise InvalidCursor(_MISMATCH)
    if column.kind == "bool":
        if not isinstance(value, bool):
            raise InvalidCursor(_MISMATCH)
        return value
    if column.kind in ("int", "float"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise InvalidCursor(_MISMATCH)
        if column.kind == "int" and not isinstance(value, int):
            raise InvalidCursor(_MISMATCH)
        return value
    if not isinstance(value, str) or "\x00" in value:
        raise InvalidCursor(_MISMATCH)
    if column.kind == "uuid":
        try:
            return str(uuid.UUID(value))
        except ValueError as exc:
            raise InvalidCursor("bad id") from exc
    if column.kind == "time":
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise InvalidCursor("bad timestamp") from exc
        if stamp.tzinfo is None:
            raise InvalidCursor("cursor timestamp missing timezone info")
        return stamp
    return value


def decode_columns_cursor(token: Any, tag: str, columns: Sequence[SortColumn]) -> List[Any]:
    """Read a cursor for the ordering the request asked for.

    Args:
        token: The ``cursor`` query parameter.
        tag: The ordering the request names.
        columns: That ordering's columns.

    Returns:
        The sort values of the last row already seen, one per column.

    Raises:
        InvalidCursor: The token is malformed, or was issued for a different ordering.
    """
    values = decode_key_cursor(token, len(columns) + 1)
    if values[0] != tag:
        raise InvalidCursor("cursor was issued for a different sort")
    return [_checked(column, value) for column, value in zip(columns, values[1:])]


def keyset_after_columns(
    columns: Sequence[SortColumn], values: Optional[Sequence[Any]]
) -> Tuple[str, List[Any]]:
    """The predicate that continues an ordering after a cursor.

    The expanded lexicographic comparison — ``a > x OR (a = x AND b > y) OR …`` — with each
    column's own direction, and ``NULL`` sorting where the column says it does.

    Args:
        columns: The ordering.
        values: The values from :func:`decode_columns_cursor`, or ``None`` for page one.

    Returns:
        ``(sql, params)``: ``" AND (…)"`` with its parameters, or ``("", [])`` without a cursor.
    """
    if values is None:
        return "", []
    alternatives: List[str] = []
    params: List[Any] = []
    for index, column in enumerate(columns):
        value = values[index]
        if value is None and not column.nulls_first:
            # Nothing sorts after NULL in this column; only later columns can break the tie.
            continue
        parts: List[str] = []
        for earlier, seen in zip(columns[:index], values[:index]):
            if seen is None:
                parts.append(f"{earlier.sql} IS NULL")
            else:
                parts.append(f"{earlier.sql} = %s{_KIND_CAST[earlier.kind]}")
                params.append(seen)
        if value is None:
            # NULLs sort first here, so every non-NULL value comes after the cursor's NULL.
            beyond = f"{column.sql} IS NOT NULL"
        else:
            operator = "<" if column.descending else ">"
            beyond = f"{column.sql} {operator} %s{_KIND_CAST[column.kind]}"
            params.append(value)
            if column.nullable and not column.nulls_first:
                beyond = f"({beyond} OR {column.sql} IS NULL)"
        parts.append(beyond)
        alternatives.append("(" + " AND ".join(parts) + ")")
    if not alternatives:
        return " AND FALSE", []
    return " AND (" + " OR ".join(alternatives) + ")", params
