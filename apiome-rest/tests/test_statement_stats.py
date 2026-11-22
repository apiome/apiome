"""Per-request SQL statement counter — DBP-1.1 (#7184).

DB-free: statements are reported with :func:`app.statement_stats.record`, as
:class:`~app.statement_stats.CountingDictCursor` does for every pooled connection
(``tests/test_query_budgets_db.py`` covers the cursor on a real connection).

Pins:

* a request's statements — on the event loop or on the worker thread of a synchronous handler —
  are counted on that request only, and the access-log line carries ``db_statements`` and
  ``db_time_ms``;
* ``Server-Timing`` is sent only when ``db_statement_server_timing`` is on;
* a request above ``db_statement_warn_threshold`` logs at WARNING;
* :func:`~app.statement_stats.assert_max_queries` fails over budget and lists the statements.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import observability, statement_stats
from app.config import settings
from app.statement_stats import QueryBudgetExceededError, assert_max_queries, capture, record


class _FakeLog:
    """Stands in for the access logger: records the bound fields and the level of each line."""

    def __init__(self) -> None:
        self.lines: List[Dict[str, Any]] = []
        self._bound: Dict[str, Any] = {}

    def bind(self, **fields: Any) -> "_FakeLog":
        bound = _FakeLog()
        bound.lines = self.lines
        bound._bound = fields
        return bound

    def _emit(self, level: str, event: str) -> None:
        self.lines.append({"level": level, "event": event, **self._bound})

    def debug(self, event: str) -> None:
        self._emit("debug", event)

    def info(self, event: str) -> None:
        self._emit("info", event)

    def warning(self, event: str) -> None:
        self._emit("warning", event)

    def error(self, event: str) -> None:
        self._emit("error", event)


@pytest.fixture
def access_log(monkeypatch) -> _FakeLog:
    log = _FakeLog()
    monkeypatch.setattr(observability, "_log", log)
    return log


def _app(statements: int = 3) -> FastAPI:
    """An app behind the observability middleware whose routes 'run' ``statements`` statements."""
    app = FastAPI()
    app.add_middleware(observability.ObservabilityMiddleware)

    @app.get("/sync")
    def sync_route() -> Dict[str, Any]:
        # A synchronous handler runs on a worker thread, as most REST database work does.
        for _ in range(statements):
            record(2.0, "SELECT 1")
        return {"thread": threading.current_thread().name}

    @app.get("/async")
    async def async_route() -> Dict[str, Any]:
        for _ in range(statements):
            record(1.5, "SELECT 2")
        return {}

    @app.get("/none")
    async def no_db() -> Dict[str, Any]:
        return {}

    return app


def _line(log: _FakeLog, path_hint: int = -1) -> Dict[str, Any]:
    http = [line for line in log.lines if line["event"] == "http_request"]
    return http[path_hint]


# ───────────────────────────── middleware ─────────────────────────────


def test_a_sync_handler_statements_are_counted_on_its_request(access_log) -> None:
    client = TestClient(_app(statements=4))
    body = client.get("/sync").json()

    assert body["thread"] != threading.current_thread().name
    line = _line(access_log)
    assert line["db_statements"] == 4
    assert line["db_time_ms"] == pytest.approx(8.0)
    assert line["level"] == "info"


def test_an_async_handler_statements_are_counted(access_log) -> None:
    TestClient(_app(statements=2)).get("/async")
    assert _line(access_log)["db_statements"] == 2
    assert _line(access_log)["db_time_ms"] == pytest.approx(3.0)


def test_each_request_starts_from_zero(access_log) -> None:
    client = TestClient(_app(statements=3))
    client.get("/sync")
    client.get("/none")
    assert [line["db_statements"] for line in access_log.lines if line["event"] == "http_request"] == [3, 0]


def test_no_request_counter_outside_a_request() -> None:
    assert statement_stats.current() is None
    record(1.0)  # no request, no capture: a no-op, not an error


def test_server_timing_is_off_by_default(access_log, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_statement_server_timing", False)
    response = TestClient(_app()).get("/sync")
    assert "server-timing" not in response.headers


def test_server_timing_reports_count_and_time_when_enabled(access_log, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_statement_server_timing", True)
    response = TestClient(_app(statements=3)).get("/sync")
    assert response.headers["server-timing"] == 'db;dur=6.000;desc="3 statements"'


def test_server_timing_value_uses_the_singular_for_one_statement() -> None:
    stats = statement_stats.StatementStats()
    stats.add(1.25)
    assert observability.server_timing_value(stats) == 'db;dur=1.250;desc="1 statement"'


def test_a_request_over_the_warn_threshold_logs_a_warning(access_log, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_statement_warn_threshold", 3)
    client = TestClient(_app(statements=4))
    client.get("/sync")
    assert _line(access_log)["level"] == "warning"


def test_the_warn_threshold_is_off_at_zero(access_log, monkeypatch) -> None:
    monkeypatch.setattr(settings, "db_statement_warn_threshold", 0)
    TestClient(_app(statements=500)).get("/sync")
    assert _line(access_log)["level"] == "info"


# ───────────────────────────── capture and budgets ─────────────────────────────


def test_capture_sees_statements_of_other_threads() -> None:
    with capture() as stats:
        worker = threading.Thread(target=lambda: [record(1.0, f"SELECT {i}") for i in range(3)])
        worker.start()
        worker.join()
    assert stats.count == 3
    assert stats.statements == ["SELECT 0", "SELECT 1", "SELECT 2"]


def test_capture_sees_a_test_client_request(access_log) -> None:
    client = TestClient(_app(statements=5))
    with capture() as stats:
        client.get("/sync")
    assert stats.count == 5


def test_captures_nest_and_stop_when_closed() -> None:
    with capture() as outer:
        record(1.0)
        with capture() as inner:
            record(1.0)
        record(1.0)
    record(1.0)
    assert (outer.count, inner.count) == (3, 1)


def test_capture_keeps_a_one_line_preview_of_long_or_bytes_sql() -> None:
    with capture() as stats:
        record(1.0, b"SELECT\n   id\nFROM apiome.classes")
        record(1.0, "SELECT " + "x, " * 200)
    assert stats.statements[0] == "SELECT id FROM apiome.classes"
    assert len(stats.statements[1]) == 160 and stats.statements[1].endswith("…")


def test_a_request_keeps_no_sql_text() -> None:
    stats, token = statement_stats.begin_request()
    try:
        record(1.0, "SELECT 1")
    finally:
        statement_stats.end_request(token)
    assert stats.count == 1 and stats.statements == []


def test_assert_max_queries_passes_within_budget() -> None:
    with assert_max_queries(2) as stats:
        record(1.0)
        record(1.0)
    assert stats.count == 2


def test_assert_max_queries_fails_over_budget_and_lists_the_statements() -> None:
    with pytest.raises(QueryBudgetExceededError) as exc:
        with assert_max_queries(1, "GET /things"):
            record(1.0, "SELECT a FROM t")
            record(1.0, "SELECT b FROM t")
    message = str(exc.value)
    assert "GET /things ran 2 SQL statements; its budget is 1." in message
    assert "1. SELECT a FROM t" in message and "2. SELECT b FROM t" in message


def test_assert_max_queries_is_an_assertion_error() -> None:
    assert issubclass(QueryBudgetExceededError, AssertionError)


def test_assert_max_queries_rejects_a_negative_budget() -> None:
    with pytest.raises(ValueError):
        with assert_max_queries(-1):
            pass


def test_the_pool_opens_connections_with_the_counting_cursor() -> None:
    import inspect

    from app import database

    assert "cursor_factory=CountingDictCursor" in inspect.getsource(database.Database.connect)
