"""A declared list ordering yields its SQL window, its cursors and its pages (DBP-1.13, #7196)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.keyset_lists import ListOrder, SortColumn, by_name, newest_first
from tests.keyset_paging_fakes import ordered_rows

TEAMS = by_name("teams", "t.name", "t.id")
RUNS = newest_first("runs", "r.created_at", "r.id")
A, B, C = (f"00000000-0000-4000-8000-00000000000{n}" for n in (1, 2, 3))
ROWS = [{"name": "alpha", "id": A}, {"name": "beta", "id": B}, {"name": "beta", "id": C}]


def test_no_limit_and_no_cursor_reads_the_whole_list():
    assert TEAMS.window(None, None) == ("", [], "", [])
    assert TEAMS.order_by == "t.name ASC, t.id ASC"


def test_a_window_continues_after_the_cursor_and_limits():
    after_sql, after_params, limit_sql, limit_params = TEAMS.window(3, ["beta", B])
    assert after_sql == " AND ((t.name > %s) OR (t.name = %s AND t.id > %s::uuid))"
    assert after_params == ["beta", "beta", B]
    assert (limit_sql, limit_params) == (" LIMIT %s", [3])


def test_newest_first_walks_downwards():
    stamp = datetime(2026, 11, 22, tzinfo=timezone.utc)
    after_sql, after_params, _, _ = RUNS.window(2, [stamp, A])
    assert "r.created_at < %s::timestamptz" in after_sql and "r.id < %s::uuid" in after_sql
    assert after_params == [stamp, stamp, A]
    assert RUNS.order_by == "r.created_at DESC, r.id DESC"


def test_a_page_issues_a_cursor_the_same_list_reads_back():
    page = TEAMS.page(ROWS, 2)
    assert [row["id"] for row in page.items] == [A, B] and page.has_more
    assert TEAMS.parse(page.next_cursor) == ["beta", B]
    last = TEAMS.page(ROWS[2:], 2)
    assert not last.has_more and last.next_cursor is None


def test_a_cursor_is_built_from_objects_as_well_as_mappings():
    assert TEAMS.cursor_of(SimpleNamespace(name="beta", id=B)) == TEAMS.cursor_of(ROWS[1])


def test_no_cursor_is_the_first_page_and_a_foreign_or_broken_one_is_a_400():
    assert TEAMS.parse(None) is None and TEAMS.parse("  ") is None
    other = ListOrder("other", TEAMS.columns)
    for token in ("not-a-cursor", other.cursor_of(ROWS[0]), RUNS.cursor_of({"created_at": "x", "id": A})):
        with pytest.raises(HTTPException) as refused:
            TEAMS.parse(token)
        assert refused.value.status_code == 400


def test_a_timestamp_cursor_round_trips_as_a_datetime():
    stamp = datetime(2026, 11, 22, 9, 30, tzinfo=timezone.utc)
    assert RUNS.parse(RUNS.cursor_of({"created_at": stamp, "id": A})) == [stamp, A]


def test_the_fake_accessor_pages_like_the_query():
    fetch = ordered_rows(TEAMS, ROWS)
    assert fetch("tenant") == ROWS
    assert fetch("tenant", limit=2) == ROWS[:2]
    assert fetch("tenant", limit=2, cursor=TEAMS.parse(TEAMS.cursor_of(ROWS[1]))) == ROWS[2:]


def test_a_nullable_leading_column_keeps_its_nulls_last():
    order = ListOrder(
        "runs-finished",
        (
            SortColumn("finished_at", "time", ("finished_at",), descending=True, nullable=True),
            SortColumn("id", "uuid", ("id",), descending=True),
        ),
    )
    after_sql, after_params, _, _ = order.window(1, [None, A])
    assert after_sql == " AND ((finished_at IS NULL AND id < %s::uuid))"
    assert after_params == [A]
