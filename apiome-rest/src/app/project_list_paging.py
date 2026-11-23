"""Keyset paging shared by the project list and the catalog list (DBP-1.13, #7196).

Both lists read ``apiome.projects p`` newest first, and with ``include_deleted`` put live rows
before soft-deleted ones. Their sort key is therefore ``[is_live, created_at, id]``, all
descending; this module owns that key so the two queries and the two routes cannot drift apart.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence, Tuple

from .keyset_pagination import encode_key_cursor

__all__ = ["PROJECT_CURSOR_SIZE", "project_keyset_sql", "project_row_cursor"]

#: How many values a project-list cursor carries (see :func:`project_row_cursor`).
PROJECT_CURSOR_SIZE = 3


def project_row_cursor(row: Mapping[str, Any]) -> str:
    """The cursor that follows one project or catalog row.

    Args:
        row: A row carrying ``deleted_at``, ``created_at`` and ``id``.

    Returns:
        The opaque cursor.
    """
    return encode_key_cursor([row.get("deleted_at") is None, row["created_at"], row["id"]])


def project_keyset_sql(
    include_deleted: bool, limit: Optional[int], cursor: Optional[Sequence[Any]]
) -> Tuple[str, str, List[Any], str, List[Any]]:
    """The ordering, continuation and limit of a ``projects p`` list.

    Args:
        include_deleted: Whether soft-deleted rows are listed (after the live ones).
        limit: Rows to read; ``None`` reads the whole list (internal callers).
        cursor: ``[is_live, created_at, id]`` of the last row already seen, or ``None``.

    Returns:
        ``(order_sql, after_sql, after_params, limit_sql, limit_params)``. ``after_sql`` is an
        ``AND …`` predicate (or empty) for the ``WHERE`` clause; the parameters go in that order
        after the query's other ``WHERE`` parameters.
    """
    order_sql = (
        "ORDER BY (p.deleted_at IS NULL) DESC, p.created_at DESC, p.id DESC"
        if include_deleted
        else "ORDER BY p.created_at DESC, p.id DESC"
    )
    after_sql, after_params = "", []
    if cursor is not None:
        is_live, created_at, project_id = cursor
        if include_deleted:
            after_sql = "AND ((p.deleted_at IS NULL), p.created_at, p.id) < (%s, %s, %s::uuid)"
            after_params = [bool(is_live), created_at, project_id]
        else:
            after_sql = "AND (p.created_at, p.id) < (%s, %s::uuid)"
            after_params = [created_at, project_id]
    limit_sql, limit_params = ("LIMIT %s", [int(limit)]) if limit is not None else ("", [])
    return order_sql, after_sql, after_params, limit_sql, limit_params
