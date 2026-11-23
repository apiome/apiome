"""Multi-column keyset paging: the ordering, its cursor and its predicate (DBP-1.13, #7196).

:mod:`app.keyset_columns` serves the lists whose order is not ``(timestamp DESC, id DESC)``: a
caller-chosen sort, mixed directions, a nullable leading column. These tests pin the three things
derived from one tuple of :class:`SortColumn`: the ``ORDER BY``, the cursor after a row, and the
``WHERE`` predicate that continues the list. The predicate's row selection was checked against
PostgreSQL itself (every row of a 24-row table as the cursor, four orderings); what is asserted
here is the SQL it emits and the cursors it refuses.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.keyset_columns import (
    SortColumn,
    decode_columns_cursor,
    encode_columns_cursor,
    keyset_after_columns,
    order_by_sql,
)
from app.keyset_pagination import InvalidCursor, encode_key_cursor

_ID = "990e8400-e29b-41d4-a716-446655440001"

_NAME_THEN_ID = (
    SortColumn("t.name", "text", ("name",)),
    SortColumn("t.id", "uuid", ("id",)),
)
_NEWEST_FIRST = (
    SortColumn("COALESCE(t.used_at, t.made_at)", "time", ("used_at", "made_at"), descending=True),
    SortColumn("t.id", "uuid", ("id",)),
)
_NULLABLE_LEAD = (
    SortColumn("t.owner", "text", ("owner",), nullable=True),
    SortColumn("t.id", "uuid", ("id",)),
)
_NULLS_FIRST = (
    SortColumn("t.stale", "bool", ("stale",)),
    SortColumn("t.pointer", "text", ("pointer",), nullable=True, nulls_first=True),
    SortColumn("t.rank", "int", ("rank",)),
)


def test_the_order_by_spells_each_columns_direction_and_null_placement():
    assert order_by_sql(_NAME_THEN_ID) == "t.name ASC, t.id ASC"
    assert order_by_sql(_NEWEST_FIRST) == "COALESCE(t.used_at, t.made_at) DESC, t.id ASC"
    assert order_by_sql(_NULLABLE_LEAD) == "t.owner ASC NULLS LAST, t.id ASC"
    assert order_by_sql(_NULLS_FIRST) == "t.stale ASC, t.pointer ASC NULLS FIRST, t.rank ASC"


def test_no_cursor_adds_no_predicate():
    assert keyset_after_columns(_NAME_THEN_ID, None) == ("", [])


def test_an_ascending_order_expands_lexicographically():
    sql, params = keyset_after_columns(_NAME_THEN_ID, ["Orders", _ID])
    assert sql == " AND ((t.name > %s) OR (t.name = %s AND t.id > %s::uuid))"
    assert params == ["Orders", "Orders", _ID]


def test_a_descending_column_continues_downwards():
    stamp = datetime(2026, 11, 22, tzinfo=timezone.utc)
    sql, params = keyset_after_columns(_NEWEST_FIRST, [stamp, _ID])
    assert "(COALESCE(t.used_at, t.made_at) < %s::timestamptz)" in sql
    assert "COALESCE(t.used_at, t.made_at) = %s::timestamptz AND t.id > %s::uuid" in sql
    assert params == [stamp, stamp, _ID]


def test_a_nullable_column_keeps_its_null_rows_after_a_value():
    sql, params = keyset_after_columns(_NULLABLE_LEAD, ["payments", _ID])
    assert "((t.owner > %s OR t.owner IS NULL))" in sql
    assert params == ["payments", "payments", _ID]


def test_a_null_cursor_value_is_matched_with_is_null_not_equals():
    sql, params = keyset_after_columns(_NULLABLE_LEAD, [None, _ID])
    # Nothing sorts after NULL in a NULLS LAST column; only the id can break the tie.
    assert sql == " AND ((t.owner IS NULL AND t.id > %s::uuid))"
    assert params == [_ID]


def test_a_nulls_first_column_puts_every_value_after_its_nulls():
    sql, params = keyset_after_columns(_NULLS_FIRST, [False, None, 3])
    assert "(t.stale > %s::boolean)" in sql
    assert "(t.stale = %s::boolean AND t.pointer IS NOT NULL)" in sql
    assert "(t.stale = %s::boolean AND t.pointer IS NULL AND t.rank > %s::bigint)" in sql
    assert params == [False, False, False, 3]
    assert sql.count("%s") == len(params)

    sql, params = keyset_after_columns(_NULLS_FIRST, [True, "/a", 3])
    # A value in a NULLS FIRST column never re-admits the NULL rows already served.
    assert "t.pointer > %s)" in sql and "t.pointer IS NULL" not in sql
    assert sql.count("%s") == len(params)


def test_a_cursor_round_trips_and_coalesces_like_the_sql_does():
    stamp = datetime(2026, 11, 22, 12, 30, tzinfo=timezone.utc)
    token = encode_columns_cursor("recent", _NEWEST_FIRST, {"used_at": None, "made_at": stamp, "id": _ID})
    assert decode_columns_cursor(token, "recent", _NEWEST_FIRST) == [stamp, _ID]

    token = encode_columns_cursor("edges", _NULLS_FIRST, {"stale": False, "pointer": None, "rank": 0})
    assert decode_columns_cursor(token, "edges", _NULLS_FIRST) == [False, None, 0]


@pytest.mark.parametrize(
    "token",
    [
        "not-a-cursor",
        encode_key_cursor(["name", "Orders"]),  # too few values
        encode_key_cursor(["other", "Orders", _ID]),  # issued for a different ordering
        encode_key_cursor(["name", None, _ID]),  # NULL in a column that cannot be NULL
        encode_key_cursor(["name", 7, _ID]),  # a number where text sorts
        encode_key_cursor(["name", "Orders", "not-a-uuid"]),
        encode_key_cursor(["name", "Or\x00ders", _ID]),
    ],
)
def test_a_cursor_that_does_not_fit_the_ordering_is_refused(token):
    with pytest.raises(InvalidCursor):
        decode_columns_cursor(token, "name", _NAME_THEN_ID)


@pytest.mark.parametrize(
    "columns,values",
    [
        (_NEWEST_FIRST, ["yesterday", _ID]),
        (_NEWEST_FIRST, ["2026-11-22T00:00:00", _ID]),  # no timezone
        (_NULLS_FIRST, ["false", None, 1]),  # text where a boolean sorts
        (_NULLS_FIRST, [False, None, True]),  # a boolean where an integer sorts
        (_NULLS_FIRST, [False, None, 1.5]),
    ],
)
def test_a_cursor_value_of_the_wrong_type_is_refused(columns, values):
    with pytest.raises(InvalidCursor):
        decode_columns_cursor(encode_key_cursor(["tag", *values]), "tag", columns)
