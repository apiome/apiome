"""One declared ordering per keyset-paged list (DBP-1.13, #7196).

:mod:`app.keyset_columns` derives a cursor, its check and the continuing predicate from a tuple of
sort columns. A :class:`ListOrder` names such a tuple once, next to the query it orders, so the
accessor and the route cannot disagree about it::

    TEAMS_ORDER = ListOrder("teams", (
        SortColumn("t.name", "text", ("name",)),
        SortColumn("t.id", "uuid", ("id",)),
    ))

    # accessor — ``limit=None`` reads the whole list (internal callers)
    after_sql, after_params, limit_sql, limit_params = TEAMS_ORDER.window(limit, cursor)
    sql = f"SELECT … WHERE t.tenant_id = %s{after_sql} ORDER BY {TEAMS_ORDER.order_by}{limit_sql}"

    # route
    rows = list_teams(tenant_id, limit=limit + 1, cursor=TEAMS_ORDER.parse(cursor))
    page = TEAMS_ORDER.page(rows, limit)

The columns must spell the query's ``ORDER BY`` exactly and end in a unique column.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

from fastapi import HTTPException

from .keyset_columns import (
    SortColumn,
    decode_columns_cursor,
    encode_columns_cursor,
    keyset_after_columns,
    order_by_sql,
)
from .keyset_pagination import InvalidCursor, Page, page_of

__all__ = ["ListOrder", "SortColumn", "newest_first", "by_name"]


@dataclass(frozen=True)
class ListOrder:
    """The ordering of one keyset-paged list.

    Attributes:
        tag: Names the list; a cursor is only accepted back by the list that issued it.
        columns: The ``ORDER BY`` columns, in order, ending in a unique one.
    """

    tag: str
    columns: Tuple[SortColumn, ...]

    @property
    def order_by(self) -> str:
        """The ``ORDER BY`` list (without the keyword)."""
        return order_by_sql(self.columns)

    def window(
        self, limit: Optional[int], cursor: Optional[Sequence[Any]]
    ) -> Tuple[str, List[Any], str, List[Any]]:
        """The continuation predicate and the ``LIMIT`` of one read.

        Args:
            limit: Rows to read; ``None`` reads the whole list.
            cursor: The values from :meth:`parse`, or ``None`` for the first page.

        Returns:
            ``(after_sql, after_params, limit_sql, limit_params)``. ``after_sql`` is ``" AND (…)"``
            or empty and belongs in the ``WHERE`` clause; ``limit_sql`` is ``" LIMIT %s"`` or empty.
        """
        after_sql, after_params = keyset_after_columns(self.columns, cursor)
        if limit is None:
            return after_sql, after_params, "", []
        return after_sql, after_params, " LIMIT %s", [int(limit)]

    def cursor_of(self, row: Any) -> str:
        """The cursor that continues the list after ``row`` (a mapping, or an object with the fields)."""
        if not isinstance(row, Mapping):
            row = {
                field: getattr(row, field, None)
                for column in self.columns
                for field in column.fields
            }
        return encode_columns_cursor(self.tag, self.columns, row)

    def decode(self, token: Any) -> List[Any]:
        """Read a cursor this list issued.

        Raises:
            InvalidCursor: The token is malformed or belongs to another list.
        """
        return decode_columns_cursor(token, self.tag, self.columns)

    def parse(self, token: Optional[str]) -> Optional[List[Any]]:
        """Route-side :meth:`decode`: no cursor is fine, a bad one is a ``400``.

        Args:
            token: The ``cursor`` query parameter, or ``None``.

        Returns:
            The sort values of the last row already seen, or ``None`` when no cursor was sent.

        Raises:
            HTTPException: ``400`` for a malformed cursor.
        """
        if token is None or not str(token).strip():
            return None
        try:
            return self.decode(token)
        except InvalidCursor as exc:
            raise HTTPException(status_code=400, detail=f"Invalid cursor: {exc}") from exc

    def page(self, rows: Sequence[Any], limit: int) -> Page[Any]:
        """Cut a ``limit + 1`` read down to a page."""
        return page_of(rows, limit, self.cursor_of)


def newest_first(
    tag: str,
    timestamp_sql: str = "created_at",
    id_sql: str = "id",
    *,
    timestamp_field: str = "created_at",
    id_field: str = "id",
    id_kind: str = "uuid",
) -> ListOrder:
    """A ``<timestamp> DESC, <id> DESC`` ordering.

    Args:
        tag: Names the list.
        timestamp_sql: The timestamp column as the query names it. Trusted SQL.
        id_sql: The id column as the query names it. Trusted SQL.
        timestamp_field: The row key holding the timestamp.
        id_field: The row key holding the id.
        id_kind: ``uuid``, ``text`` or ``int``.

    Returns:
        The ordering.
    """
    return ListOrder(
        tag,
        (
            SortColumn(timestamp_sql, "time", (timestamp_field,), descending=True),
            SortColumn(id_sql, id_kind, (id_field,), descending=True),
        ),
    )


def by_name(
    tag: str,
    name_sql: str = "name",
    id_sql: str = "id",
    *,
    name_field: str = "name",
    id_field: str = "id",
    id_kind: str = "uuid",
) -> ListOrder:
    """A ``<name> ASC, <id> ASC`` ordering.

    Args:
        tag: Names the list.
        name_sql: The name expression as the query's ``ORDER BY`` spells it. Trusted SQL.
        id_sql: The id column as the query names it. Trusted SQL.
        name_field: The row key holding the name expression's value.
        id_field: The row key holding the id.
        id_kind: ``uuid``, ``text`` or ``int``.

    Returns:
        The ordering.
    """
    return ListOrder(
        tag,
        (
            SortColumn(name_sql, "text", (name_field,)),
            SortColumn(id_sql, id_kind, (id_field,)),
        ),
    )
