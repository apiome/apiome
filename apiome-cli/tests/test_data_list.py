"""``apiome data list --class <class>`` (CLI 10.1, #3253).

The rendering (:mod:`apiome_cli.data_view`) and the command against a mocked
``GET /v1/data/{tenant}/records``: the class given as ``<project>/<version>/<Class>`` (resolved via
``…/classes``) or as a class schema id, filters / sort / ``--include-deleted`` on the query, the
cursor (``--next``, ``--all`` following every page), ``--columns``, and snapshot tests for the table,
``--json`` and ``--ndjson`` output.

Regenerate the snapshots with ``UPDATE_SNAPSHOTS=1``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from typer.testing import CliRunner

from apiome_cli.data_record import DataInputError, check_filter, is_class_schema_id
from apiome_cli.data_view import (
    MAX_CELL_WIDTH,
    data_columns,
    format_cell,
    format_time,
    parse_columns,
    render_footer,
    render_table,
)
from apiome_cli.exit_codes import EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()
SNAPSHOTS = Path(__file__).parent / "snapshots" / "data"
UPDATE_SNAPSHOTS = os.environ.get("UPDATE_SNAPSHOTS") == "1"

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_CS = "33333333-3333-4333-8333-333333333333"
_CLASSES = "http://localhost:8000/v1/data/acme/classes?project=billing&version=1.0.0"
_RECORDS = "http://localhost:8000/v1/data/acme/records"
_ANY_RECORDS = re.compile(re.escape(_RECORDS) + r"\?.*")
_LOOKUP = {
    "success": True,
    "project": "billing",
    "version": "1.0.0",
    "published": True,
    "classes": [{"class_schema_id": _CS, "class_id": "c-1", "class_name": "Charge", "schema": {}}],
}


def _item(n: int, amount, currency: str, status: str, *, deleted: str | None = None) -> dict:
    return {
        "record_id": f"8a2f0000-0000-4000-8000-00000000000{n}",
        "created_at": f"2026-05-04T12:4{n}:00+00:00",
        "updated_at": f"2026-05-04T12:4{n}:00+00:00",
        "deleted_at": deleted,
        "data": {"amount": amount, "currency": currency, "status": status},
    }


_ITEMS = [
    _item(1, 19.99, "USD", "succeeded"),
    _item(2, 100.0, "EUR", "succeeded"),
    _item(3, 5, "USD", "failed"),
]


def _page(items, *, total=None, next_cursor=None) -> dict:
    return {
        "success": True,
        "class_schema_id": _CS,
        "total": len(items) if total is None else total,
        "limit": 50,
        "sort": "created_at",
        "next_cursor": next_cursor,
        "items": items,
    }


def _snapshot(name: str, text: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if UPDATE_SNAPSHOTS:
        SNAPSHOTS.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}; run with UPDATE_SNAPSHOTS=1"
    assert text == path.read_text(encoding="utf-8")


def _list(*args: str, cls: str = "billing/1.0.0/Charge"):
    return runner.invoke(app, ["data", "list", "--class", cls, *args], env=_ENV)


def _record_queries(httpx_mock) -> list[dict]:
    return [
        parse_qs(urlsplit(str(r.url)).query)
        for r in httpx_mock.get_requests()
        if str(r.url).startswith(_RECORDS)
    ]


def _add_records(httpx_mock, payload) -> None:
    httpx_mock.add_response(url=_ANY_RECORDS, json=payload)


# ---- rules -----------------------------------------------------------------------------------------


def test_is_class_schema_id() -> None:
    assert is_class_schema_id(_CS)
    assert is_class_schema_id(f" {_CS} ")
    assert not is_class_schema_id("billing/1.0.0/Charge")
    assert not is_class_schema_id("Charge")


def test_check_filter() -> None:
    assert check_filter("status=succeeded") == "status=succeeded"
    assert check_filter("note=") == "note="
    for bad in ("status", "=x"):
        with pytest.raises(DataInputError, match="must be key=value"):
            check_filter(bad)


def test_parse_columns() -> None:
    assert parse_columns(None) == []
    assert parse_columns(" amount, ,status ") == ["amount", "status"]


def test_data_columns_follow_first_use_or_the_request() -> None:
    items = [{"data": {"b": 1, "a": 2}}, {"data": {"c": 3, "a": 4}}, {"data": None}]
    assert data_columns(items, []) == ["b", "a", "c"]
    assert data_columns(items, ["c", "c", "zz"]) == ["c", "zz"]


@pytest.mark.parametrize(
    "value, text",
    [
        (None, ""),
        ("USD", "USD"),
        (True, "true"),
        (False, "false"),
        (19.99, "19.99"),
        (3, "3"),
        ({"k": [1, 2]}, '{"k":[1,2]}'),
        ("two\n  lines", "two lines"),
    ],
)
def test_format_cell(value, text) -> None:
    assert format_cell(value) == text


def test_format_cell_cuts_long_values() -> None:
    cut = format_cell("x" * 100)
    assert len(cut) == MAX_CELL_WIDTH and cut.endswith("…")


def test_format_time() -> None:
    assert format_time("2026-05-04T12:42:07.123+00:00") == "2026-05-04 12:42"
    assert format_time(None) == ""
    assert format_time("yesterday") == "yesterday"


def test_render_table_and_footer() -> None:
    lines = render_table(_ITEMS[:1], ["amount", "missing"], include_deleted=True)
    assert lines[0].split() == ["ID", "CREATED", "AMOUNT", "MISSING", "DELETED_AT"]
    assert lines[1].startswith("8a2f0000-0000-4000-8000-000000000001  2026-05-04 12:41  19.99")
    assert all(line == line.rstrip() for line in lines)
    assert render_footer(20, 1234, "abc") == "20 of 1,234 (use --next abc or --all)."
    assert render_footer(3, 3, None) == "3 of 3."


# ---- command: snapshots ----------------------------------------------------------------------------


def test_table_snapshot(httpx_mock) -> None:
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    _add_records(httpx_mock, _page(_ITEMS, total=1234, next_cursor="eyJvIjozfQ"))
    result = _list("--limit", "3")
    assert result.exit_code == EXIT_SUCCESS, result.output
    _snapshot("list-table", result.stdout)


def test_include_deleted_table_snapshot(httpx_mock) -> None:
    items = [*_ITEMS[:2], _item(4, 7, "USD", "succeeded", deleted="2026-05-05T09:00:00+00:00")]
    _add_records(httpx_mock, _page(items))
    result = _list("--include-deleted", "--columns", "amount,status", cls=_CS)
    assert result.exit_code == EXIT_SUCCESS, result.output
    _snapshot("list-table-deleted", result.stdout)
    assert _record_queries(httpx_mock)[0]["include_deleted"] == ["true"]


def test_json_snapshot(httpx_mock) -> None:
    _add_records(httpx_mock, _page(_ITEMS))
    result = _list("--json", cls=_CS)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout) == _ITEMS
    _snapshot("list-json", result.stdout)


def test_ndjson_snapshot(httpx_mock) -> None:
    _add_records(httpx_mock, _page(_ITEMS))
    result = _list("--ndjson", cls=_CS)
    assert result.exit_code == EXIT_SUCCESS, result.output
    lines = result.stdout.splitlines()
    assert [json.loads(line) for line in lines] == _ITEMS
    assert not result.stdout.startswith("[")
    _snapshot("list-ndjson", result.stdout)


# ---- command: query, paging ------------------------------------------------------------------------


def test_class_address_is_resolved_then_listed_with_the_query(httpx_mock) -> None:
    httpx_mock.add_response(url=_CLASSES, json=_LOOKUP)
    _add_records(httpx_mock, _page(_ITEMS[:1]))
    result = _list("--filter", "status=succeeded", "--filter", "currency=USD", "--sort", "-created_at", "--limit", "20")
    assert result.exit_code == EXIT_SUCCESS, result.output
    (query,) = _record_queries(httpx_mock)
    assert query == {
        "class_schema_id": [_CS],
        "limit": ["20"],
        "sort": ["-created_at"],
        "filter": ["status=succeeded", "currency=USD"],
    }
    assert result.stdout.rstrip().endswith("1 of 1.")


def test_a_class_schema_id_skips_the_lookup(httpx_mock) -> None:
    _add_records(httpx_mock, _page([]))
    result = _list(cls=_CS)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == f"No records in {_CS}.\n"
    assert all("/classes" not in str(r.url) for r in httpx_mock.get_requests())


def test_next_sends_the_cursor(httpx_mock) -> None:
    _add_records(httpx_mock, _page(_ITEMS[2:], total=3))
    result = _list("--next", "eyJvIjoyfQ", cls=_CS)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert _record_queries(httpx_mock)[0]["cursor"] == ["eyJvIjoyfQ"]
    assert result.stdout.rstrip().endswith("1 of 3.")


def test_all_follows_every_cursor_with_the_largest_page(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{_RECORDS}?class_schema_id={_CS}&limit=500&sort=created_at", json=_page(_ITEMS[:2], total=3, next_cursor="c2")
    )
    httpx_mock.add_response(
        url=f"{_RECORDS}?class_schema_id={_CS}&limit=500&sort=created_at&cursor=c2", json=_page(_ITEMS[2:], total=3)
    )
    result = _list("--all", "--limit", "2", cls=_CS)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert len(_record_queries(httpx_mock)) == 2
    assert result.stdout.rstrip().endswith("3 of 3.")
    assert "--next" not in result.stdout


def test_all_streams_ndjson_across_pages(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{_RECORDS}?class_schema_id={_CS}&limit=500&sort=created_at", json=_page(_ITEMS[:2], total=3, next_cursor="c2")
    )
    httpx_mock.add_response(
        url=f"{_RECORDS}?class_schema_id={_CS}&limit=500&sort=created_at&cursor=c2", json=_page(_ITEMS[2:], total=3)
    )
    result = _list("--all", "--ndjson", cls=_CS)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert [json.loads(line) for line in result.stdout.splitlines()] == _ITEMS
    assert "More records" not in result.stderr


def test_json_across_pages_is_one_array(httpx_mock) -> None:
    httpx_mock.add_response(
        url=f"{_RECORDS}?class_schema_id={_CS}&limit=500&sort=created_at", json=_page(_ITEMS[:2], total=3, next_cursor="c2")
    )
    httpx_mock.add_response(
        url=f"{_RECORDS}?class_schema_id={_CS}&limit=500&sort=created_at&cursor=c2", json=_page(_ITEMS[2:], total=3)
    )
    result = runner.invoke(app, ["--json", "data", "list", "--class", _CS, "--all"], env=_ENV)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout) == _ITEMS


def test_json_puts_the_next_cursor_on_stderr(httpx_mock) -> None:
    _add_records(httpx_mock, _page(_ITEMS[:1], total=3, next_cursor="c2"))
    result = _list("--json", cls=_CS)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert json.loads(result.stdout) == _ITEMS[:1]
    assert "More records: --next c2" in result.stderr


def test_an_empty_json_page_is_an_empty_array(httpx_mock) -> None:
    _add_records(httpx_mock, _page([]))
    result = _list("--json", cls=_CS)
    assert result.stdout == "[]\n"


# ---- command: errors ---------------------------------------------------------------------------


def test_a_stale_cursor_is_a_usage_error(httpx_mock) -> None:
    httpx_mock.add_response(
        url=_ANY_RECORDS,
        status_code=400,
        json={"detail": "Cursor does not belong to this query (class, filters, sort or include_deleted changed)"},
    )
    result = _list("--next", "stale", cls=_CS)
    assert result.exit_code == EXIT_USAGE
    assert "Cursor does not belong to this query" in result.stderr


@pytest.mark.parametrize(
    "args, message",
    [
        (["--json", "--ndjson"], "Use --json or --ndjson, not both."),
        (["--filter", "status"], "--filter 'status' must be key=value"),
    ],
)
def test_usage_errors(httpx_mock, args, message) -> None:
    result = _list(*args, cls=_CS)
    assert result.exit_code == EXIT_USAGE
    assert message in result.stderr
    assert httpx_mock.get_requests() == []


def test_a_malformed_class_is_a_usage_error(httpx_mock) -> None:
    result = _list(cls="Charge")
    assert result.exit_code == EXIT_USAGE
    assert "must be <project>/<version>/<Class>" in result.stderr


def test_limit_is_bounded(httpx_mock) -> None:
    assert _list("--limit", "501", cls=_CS).exit_code == EXIT_USAGE
    assert _list("--limit", "0", cls=_CS).exit_code == EXIT_USAGE
