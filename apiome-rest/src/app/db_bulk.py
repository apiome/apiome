"""Multi-row writes for apiome-rest (DBP-1.2, #7185).

``cursor.executemany`` sends one statement per row; a 1,000-row write is 1,000 round trips. The
two helpers here send one statement per page instead:

* :func:`bulk_insert` — ``INSERT … VALUES (…), (…), …`` built by ``psycopg2.extras.execute_values``,
  ``page_size`` rows per statement, with an optional ``ON CONFLICT`` clause and ``RETURNING``.
* :func:`bulk_upsert` — ``INSERT … SELECT * FROM unnest(%s::t1[], %s::t2[], …) ON CONFLICT …``:
  one statement whose size does not grow with the row count (each column is one array
  parameter), for upserts where every column's SQL type is known.

Both run on a cursor the caller owns, so they join the caller's transaction; ``Database`` wraps
them in :meth:`~app.database.Database.bulk_insert` / :meth:`~app.database.Database.bulk_upsert`,
which commit on their own. Table and column names are quoted with ``psycopg2.sql`` and must be
plain identifiers (``schema.table`` or ``table``); values are always parameters.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from psycopg2 import sql
from psycopg2.extras import execute_values

__all__ = ["bulk_insert", "bulk_upsert", "DEFAULT_PAGE_SIZE"]

#: Rows per ``INSERT`` statement when the caller does not say.
DEFAULT_PAGE_SIZE = 1000

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
#: SQL types an :func:`bulk_upsert` column may be cast to: a name, optional ``(n[,m])``, no arrays.
_SQL_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_ .]*(\(\s*\d+(\s*,\s*\d+)?\s*\))?$")


def _identifier(name: str, what: str) -> str:
    """Check one plain SQL identifier.

    Raises:
        ValueError: ``name`` is not a plain identifier.
    """
    if not isinstance(name, str) or not _IDENTIFIER.match(name):
        raise ValueError(f"{what} {name!r} is not a plain SQL identifier")
    return name


def _table(table: str) -> sql.Composable:
    """``schema.table`` or ``table`` as a quoted identifier.

    Raises:
        ValueError: ``table`` has more than two parts or a part is not a plain identifier.
    """
    parts = str(table).split(".")
    if len(parts) > 2:
        raise ValueError(f"table {table!r} must be 'table' or 'schema.table'")
    return sql.Identifier(*[_identifier(part, "table name part") for part in parts])


def _columns(columns: Sequence[str]) -> sql.Composable:
    """A parenthesised, quoted column list.

    Raises:
        ValueError: There are no columns, a name repeats, or one is not a plain identifier.
    """
    names = [_identifier(column, "column") for column in columns]
    if not names:
        raise ValueError("a bulk write needs at least one column")
    if len(set(names)) != len(names):
        raise ValueError("a bulk write names a column twice")
    return sql.SQL(", ").join(sql.Identifier(name) for name in names)


def _returning(returning: Optional[Sequence[str]]) -> sql.Composable:
    """`` RETURNING a, b`` for the given columns, or nothing."""
    if not returning:
        return sql.SQL("")
    return sql.SQL(" RETURNING ") + _columns(returning)


def _rows(rows: Sequence[Sequence[Any]], width: int) -> List[Tuple[Any, ...]]:
    """The rows as tuples, each checked to have one value per column.

    Raises:
        ValueError: A row's length differs from the column count.
    """
    out: List[Tuple[Any, ...]] = []
    for index, row in enumerate(rows):
        values = tuple(row)
        if len(values) != width:
            raise ValueError(f"row {index} has {len(values)} values for {width} columns")
        out.append(values)
    return out


def bulk_insert(
    cursor: Any,
    table: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    returning: Optional[Sequence[str]] = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    on_conflict: Optional[str] = None,
    template: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Insert ``rows`` into ``table`` with one statement per ``page_size`` rows.

    Example::

        bulk_insert(cur, "apiome.tags", ["id", "name"], [(1, "a"), (2, "b")], returning=["id"])

    Args:
        cursor: An open cursor; the insert joins its connection's transaction.
        table: ``schema.table`` or ``table``.
        columns: The columns each row fills, in row order.
        rows: One sequence of values per row.
        returning: Columns to return for every inserted row (all pages, in order).
        page_size: Rows per statement (``>= 1``).
        on_conflict: SQL appended after ``VALUES`` verbatim, e.g.
            ``"ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name"``. It is trusted code, never
            user input.
        template: The ``execute_values`` row template, e.g. ``"(%s::uuid, %s)"``, when a column
            needs a cast; defaults to one ``%s`` per column.

    Returns:
        The ``returning`` rows as dicts (empty without ``returning``).

    Raises:
        ValueError: A bad identifier, a row of the wrong width, or ``page_size < 1``.
    """
    if int(page_size) < 1:
        raise ValueError("page_size must be at least 1")
    values = _rows(rows, len(columns))
    if not values:
        return []
    statement = sql.SQL("INSERT INTO {table} ({columns}) VALUES %s{conflict}{returning}").format(
        table=_table(table),
        columns=_columns(columns),
        conflict=sql.SQL(" " + on_conflict.strip()) if on_conflict else sql.SQL(""),
        returning=_returning(returning),
    )
    query = statement.as_string(cursor)
    if not returning:
        execute_values(cursor, query, values, template=template, page_size=int(page_size))
        return []
    found = execute_values(cursor, query, values, template=template, page_size=int(page_size), fetch=True)
    return [dict(row) if not isinstance(row, dict) else row for row in found]


def bulk_upsert(
    cursor: Any,
    table: str,
    columns: Sequence[Tuple[str, str]],
    rows: Sequence[Sequence[Any]],
    *,
    conflict_columns: Sequence[str],
    update_columns: Optional[Sequence[str]] = None,
    returning: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    """Upsert ``rows`` with one ``INSERT … SELECT FROM unnest(…)`` statement.

    Each column travels as one array parameter, so the statement text is the same for 10 rows or
    100,000 and PostgreSQL plans it once. ``unnest`` needs every column's SQL type.

    Example::

        bulk_upsert(
            cur, "apiome.tenant_repository_files",
            [("repository_id", "uuid"), ("branch", "text"), ("path", "text"), ("name", "text")],
            rows, conflict_columns=["repository_id", "branch", "path"], update_columns=["name"],
        )

    Args:
        cursor: An open cursor; the upsert joins its connection's transaction.
        table: ``schema.table`` or ``table``.
        columns: ``(name, sql_type)`` pairs, in row order; ``sql_type`` is a scalar type such as
            ``uuid``, ``text``, ``bigint``, ``timestamptz`` or ``varchar(64)``.
        rows: One sequence of values per row.
        conflict_columns: The unique key ``ON CONFLICT`` targets.
        update_columns: Columns overwritten from the new row on conflict; ``None`` means every
            column not in ``conflict_columns``; an empty list means ``DO NOTHING``.
        returning: Columns to return for every inserted or updated row.

    Returns:
        The ``returning`` rows as dicts (empty without ``returning``).

    Raises:
        ValueError: A bad identifier or type, a row of the wrong width, a conflict or update
            column that is not one of ``columns``, or a key repeated within ``rows`` that
            PostgreSQL would reject ("cannot affect row a second time") — checked up front so
            the message names the key.
    """
    names = [_identifier(name, "column") for name, _ in columns]
    types = []
    for name, sql_type in columns:
        if not isinstance(sql_type, str) or not _SQL_TYPE.match(sql_type.strip()) or "[" in sql_type:
            raise ValueError(f"column {name!r} has an unsupported SQL type {sql_type!r}")
        types.append(sql_type.strip())
    conflict = [_identifier(name, "conflict column") for name in conflict_columns]
    if not conflict or any(name not in names for name in conflict):
        raise ValueError("conflict_columns must be a non-empty subset of columns")
    if update_columns is None:
        updates = [name for name in names if name not in conflict]
    else:
        updates = [_identifier(name, "update column") for name in update_columns]
        if any(name not in names for name in updates):
            raise ValueError("update_columns must be a subset of columns")
    values = _rows(rows, len(names))
    if not values:
        return []
    key_index = [names.index(name) for name in conflict]
    seen = set()
    for row in values:
        key = tuple(row[i] for i in key_index)
        if key in seen:
            raise ValueError(f"rows repeat the conflict key {key!r}")
        seen.add(key)

    arrays = [list(column) for column in zip(*values)]
    unnest_args = sql.SQL(", ").join(
        sql.SQL("%s::") + sql.SQL(sql_type + "[]") for sql_type in types
    )
    if updates:
        action = sql.SQL("DO UPDATE SET ") + sql.SQL(", ").join(
            sql.SQL("{col} = EXCLUDED.{col}").format(col=sql.Identifier(name)) for name in updates
        )
    else:
        action = sql.SQL("DO NOTHING")
    statement = sql.SQL(
        "INSERT INTO {table} ({columns}) SELECT * FROM unnest({args}) ON CONFLICT ({conflict}) {action}{returning}"
    ).format(
        table=_table(table),
        columns=_columns(names),
        args=unnest_args,
        conflict=_columns(conflict),
        action=action,
        returning=_returning(returning),
    )
    cursor.execute(statement, arrays)
    if not returning:
        return []
    return [dict(row) if not isinstance(row, dict) else row for row in cursor.fetchall()]
