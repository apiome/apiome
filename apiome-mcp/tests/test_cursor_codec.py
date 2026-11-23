"""The cursor envelope and page-size clamp shared by the paginated tools (apiome #7196)."""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from apiome_mcp.cursor_codec import (
    clamp_page_limit,
    cursor_timestamp,
    decode_cursor_payload,
    encode_cursor_payload,
    utc,
)
from apiome_mcp.project_list_tool import decode_project_list_cursor, encode_project_list_cursor
from apiome_mcp.spec_list_tags_tool import decode_spec_list_tags_cursor, encode_spec_list_tags_cursor
from apiome_mcp.spec_list_tool import decode_spec_list_cursor, encode_spec_list_cursor
from apiome_mcp.spec_search_tool import decode_spec_search_cursor, encode_spec_search_cursor


class _BadCursorError(ValueError):
    pass


def _decode(raw):
    return decode_cursor_payload(raw, tool="thing.list", version=1, error=_BadCursorError)


def _token(payload) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")


def test_a_payload_round_trips_and_the_token_is_stable_and_unpadded():
    token = encode_cursor_payload({"v": 1, "u": "2026-11-22T00:00:00Z", "i": "abc"})
    assert token == encode_cursor_payload({"i": "abc", "u": "2026-11-22T00:00:00Z", "v": 1})
    assert "=" not in token
    assert _decode(token) == {"v": 1, "u": "2026-11-22T00:00:00Z", "i": "abc"}


def test_no_cursor_is_the_first_page():
    assert _decode(None) is None


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("   ", "Invalid thing.list cursor (empty value)."),
        ("%%%", "Invalid thing.list cursor (malformed encoding)."),
        (_token([1, 2]), "Invalid thing.list cursor (expected JSON object)."),
        (_token({"v": 2}), "Unsupported thing.list cursor version: 2."),
        (_token({}), "Unsupported thing.list cursor version: None."),
    ],
)
def test_a_bad_envelope_raises_the_tools_own_error(raw, message):
    with pytest.raises(_BadCursorError) as raised:
        _decode(raw)
    assert str(raised.value) == message


def test_a_cursor_timestamp_is_read_in_utc_and_must_carry_an_offset():
    assert cursor_timestamp("2026-11-22T10:00:00Z", tool="t", error=_BadCursorError) == datetime(
        2026, 11, 22, 10, tzinfo=timezone.utc
    )
    assert cursor_timestamp("2026-11-22T12:00:00+02:00", tool="t", error=_BadCursorError) == datetime(
        2026, 11, 22, 10, tzinfo=timezone.utc
    )
    for bad, reason in (("yesterday", "bad timestamp"), ("2026-11-22T10:00:00", "timezone offset")):
        with pytest.raises(_BadCursorError, match=reason):
            cursor_timestamp(bad, tool="t", error=_BadCursorError)


def test_utc_treats_a_naive_datetime_as_utc_and_converts_an_aware_one():
    naive = datetime(2026, 11, 22, 10)
    assert utc(naive) == datetime(2026, 11, 22, 10, tzinfo=timezone.utc)
    aware = datetime(2026, 11, 22, 12, tzinfo=timezone(timedelta(hours=2)))
    assert utc(aware) == datetime(2026, 11, 22, 10, tzinfo=timezone.utc)


def test_a_page_limit_is_clamped_to_the_tools_maximum_and_refused_below_one():
    assert clamp_page_limit(None, default=50, maximum=100) == 50
    assert clamp_page_limit(1, default=50, maximum=100) == 1
    assert clamp_page_limit(500, default=50, maximum=100) == 100
    with pytest.raises(ValueError, match="limit must be at least 1, got 0."):
        clamp_page_limit(0, default=50, maximum=100)


def test_every_tool_still_issues_and_reads_the_cursor_it_always_did():
    from uuid import UUID

    stamp = datetime(2026, 11, 22, 10, 30, 15, 123456, tzinfo=timezone.utc)
    one, two = UUID(int=1), UUID(int=2)
    assert decode_spec_list_cursor(encode_spec_list_cursor(stamp, one)) == (stamp, one)
    assert decode_project_list_cursor(encode_project_list_cursor(stamp, one, two)) == (stamp, one, two)
    assert decode_spec_search_cursor(encode_spec_search_cursor(7, stamp, one)) == (7, stamp, one)
    assert decode_spec_list_tags_cursor(encode_spec_list_tags_cursor(3, "payments")) == (3, "payments")
    # The wire format is unchanged: a token minted before this refactor still decodes.
    legacy = _token({"v": 1, "i": str(one), "u": "2026-11-22T10:30:15.123456Z"})
    assert decode_spec_list_cursor(legacy) == (stamp, one)
