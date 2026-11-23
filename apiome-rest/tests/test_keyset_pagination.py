"""The shared paging convention (DBP-1.13, #7196): cursors, limits, pages and headers."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.testclient import TestClient

from app import keyset_pagination as kp

STAMP = datetime(2026, 11, 22, 10, 30, 15, 123456, tzinfo=timezone.utc)
ROW_ID = "0b8f6f3e-5a0f-4c3e-9a55-0d6a6d3c9d11"


def _token(payload) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


# --- cursors ---------------------------------------------------------------------------------


def test_a_time_id_cursor_round_trips_to_the_microsecond():
    assert kp.decode_time_id_cursor(kp.encode_time_id_cursor(STAMP, ROW_ID)) == (STAMP, ROW_ID)


def test_a_time_id_cursor_is_the_format_the_audit_endpoints_always_issued():
    assert kp.decode_time_id_cursor(_token({"t": "2026-11-22T10:30:15Z", "i": ROW_ID})) == (
        datetime(2026, 11, 22, 10, 30, 15, tzinfo=timezone.utc),
        ROW_ID,
    )


def test_a_key_cursor_round_trips_its_values_in_order():
    token = kp.encode_key_cursor(["Orders API", STAMP, 7, None])
    assert kp.decode_key_cursor(token, 4) == ["Orders API", STAMP.isoformat(), 7, None]


@pytest.mark.parametrize(
    "token",
    [
        "",
        "   ",
        "not base64 !!",
        _token(["a", "list"]),
        _token({"t": "2026-11-22T10:30:15+00:00"}),
        _token({"t": "yesterday", "i": ROW_ID}),
        _token({"t": "2026-11-22T10:30:15", "i": ROW_ID}),
        _token({"t": 5, "i": ROW_ID}),
        _token({"t": "2026-11-22T10:30:15+00:00", "i": ""}),
        "A" * 3000,
    ],
)
def test_a_malformed_time_id_cursor_is_refused(token):
    with pytest.raises(kp.InvalidCursor):
        kp.decode_time_id_cursor(token)


@pytest.mark.parametrize(
    "token",
    [_token({"k": ["only-one"]}), _token({"k": "text"}), _token({"k": [{"a": 1}, 2]}), _token({})],
)
def test_a_key_cursor_for_another_list_is_refused(token):
    with pytest.raises(kp.InvalidCursor):
        kp.decode_key_cursor(token, 2)


def test_route_side_parsing_lets_no_cursor_through_and_turns_a_bad_one_into_a_400():
    assert kp.parse_time_id_cursor(None) is None
    assert kp.parse_time_id_cursor("  ") is None
    assert kp.parse_key_cursor(None, 2) is None
    assert kp.parse_time_id_cursor(kp.encode_time_id_cursor(STAMP, ROW_ID)) == (STAMP, ROW_ID)
    assert kp.parse_key_cursor(kp.encode_key_cursor(["a", 1]), 2) == ["a", 1]
    for parse in (lambda: kp.parse_time_id_cursor("???"), lambda: kp.parse_key_cursor("???", 2)):
        with pytest.raises(HTTPException) as raised:
            parse()
        assert raised.value.status_code == 400


# --- limits ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("asked", "applied"),
    [(None, 50), (1, 1), (0, 1), (-5, 1), (200, 200), (201, 200), (10_000, 200)],
)
def test_a_limit_is_clamped_to_the_hard_maximum(asked, applied):
    assert kp.clamp_limit(asked) == applied


def test_a_list_may_set_a_lower_maximum_and_its_own_default():
    assert kp.clamp_limit(None, default=500, maximum=100) == 100
    assert kp.clamp_limit(80, maximum=25) == 25


# --- SQL -------------------------------------------------------------------------------------


def test_the_first_page_adds_no_predicate():
    assert kp.keyset_before("n.created_at", "n.id", None) == ("", [])


def test_a_later_page_is_a_row_value_comparison_the_index_can_seek():
    sql, params = kp.keyset_before("n.created_at", "n.id", (STAMP, ROW_ID))
    assert sql == " AND (n.created_at, n.id) < (%s, %s::uuid)"
    assert params == [STAMP, ROW_ID]


def test_a_text_key_is_compared_without_a_uuid_cast():
    sql, _ = kp.keyset_before("l.finished_at", "l.job_id", (STAMP, "job-1"), id_cast="")
    assert sql == " AND (l.finished_at, l.job_id) < (%s, %s)"


def test_a_capped_count_stops_reading_at_the_cap():
    sql = kp.capped_count_sql("FROM apiome.notifications n WHERE n.user_id = %s")
    assert "SELECT 1 FROM apiome.notifications n WHERE n.user_id = %s LIMIT 10000" in sql
    assert sql.startswith("SELECT count(*)::int AS total FROM (")
    assert "LIMIT 25" in kp.capped_count_sql("FROM t", cap=25)


# --- pages -----------------------------------------------------------------------------------


def _rows(count):
    return [{"id": f"id-{n}", "created_at": STAMP.replace(second=n)} for n in range(count)]


def test_a_full_read_plus_one_means_another_page_and_the_cursor_names_the_last_row_kept():
    page = kp.page_of(_rows(4), 3, kp.time_id_key())
    assert [row["id"] for row in page.items] == ["id-0", "id-1", "id-2"]
    assert page.has_more is True
    assert kp.decode_time_id_cursor(page.next_cursor) == (STAMP.replace(second=2), "id-2")


@pytest.mark.parametrize("count", [0, 2, 3])
def test_a_read_that_does_not_overflow_is_the_last_page(count):
    page = kp.page_of(_rows(count), 3, kp.time_id_key())
    assert len(page.items) == count
    assert page.has_more is False and page.next_cursor is None


def test_a_cursor_can_be_built_from_other_row_fields():
    rows = [{"job_id": "j1", "finished_at": STAMP}, {"job_id": "j0", "finished_at": STAMP}]
    page = kp.page_of(rows, 1, kp.time_id_key("finished_at", "job_id"))
    assert kp.decode_time_id_cursor(page.next_cursor) == (STAMP, "j1")


# --- headers and query parameters ------------------------------------------------------------


def test_a_bare_array_list_reports_its_paging_in_headers():
    more, last = Response(), Response()
    kp.set_page_headers(more, kp.Page(items=[1], has_more=True, next_cursor="abc"))
    kp.set_page_headers(last, kp.Page(items=[1], has_more=False, next_cursor=None))
    assert more.headers[kp.HAS_MORE_HEADER] == "true"
    assert more.headers[kp.NEXT_CURSOR_HEADER] == "abc"
    assert last.headers[kp.HAS_MORE_HEADER] == "false"
    assert kp.NEXT_CURSOR_HEADER not in last.headers


def test_the_query_parameters_document_their_bounds_and_enforce_them():
    app = FastAPI()

    @app.get("/things")
    def things(
        limit: int = kp.limit_query(),
        cursor: str | None = kp.cursor_query(),
        include_total: bool = kp.include_total_query(),
        offset: int = kp.offset_query(),
    ):
        return {"limit": limit, "cursor": cursor, "include_total": include_total, "offset": offset}

    client = TestClient(app)
    assert client.get("/things").json() == {
        "limit": 50,
        "cursor": None,
        "include_total": False,
        "offset": 0,
    }
    assert client.get("/things", params={"limit": 200}).status_code == 200
    assert client.get("/things", params={"limit": 201}).status_code == 422
    assert client.get("/things", params={"limit": 0}).status_code == 422
    assert client.get("/things", params={"offset": 10_001}).status_code == 422

    parameters = {p["name"]: p for p in app.openapi()["paths"]["/things"]["get"]["parameters"]}
    assert parameters["limit"]["schema"]["maximum"] == kp.MAX_PAGE_LIMIT == 200
    assert parameters["offset"]["deprecated"] is True
    assert parameters["offset"]["schema"]["maximum"] == kp.MAX_OFFSET
    assert parameters["include_total"]["schema"]["default"] is False
