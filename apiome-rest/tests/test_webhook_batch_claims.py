"""The webhook queues' batch claims (DBP-1.18, #7201): ordered branches, one batch, tenant skips."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import psycopg2.extensions

from app.database import Database

_TENANT = "550e8400-e29b-41d4-a716-446655440000"


class _Cursor:
    def __init__(self, answers: List[List[Dict[str, Any]]]) -> None:
        self.answers = answers
        self.calls: List[tuple] = []
        self._last: List[Dict[str, Any]] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.calls.append((sql, params))
        self._last = self.answers.pop(0) if self.answers else []

    def fetchall(self) -> List[Dict[str, Any]]:
        return self._last

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self._last[0] if self._last else None


class _Conn:
    autocommit = True
    closed = False

    class info:  # noqa: N801 - mirrors psycopg2's attribute
        transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE

    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, *args: Any, **kwargs: Any) -> _Cursor:
        return self._cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _db(monkeypatch: Any, answers: List[List[Dict[str, Any]]]) -> tuple:
    cursor = _Cursor(answers)
    conn = _Conn(cursor)
    db = Database()
    monkeypatch.setattr(db, "connect", lambda: conn)
    return db, cursor, conn


def _run(run_id: str) -> Dict[str, Any]:
    return {"id": run_id, "tenant_id": _TENANT, "payload": memoryview(b"{}"), "signature": "sha256=00"}


def test_export_claim_takes_stale_attempts_first_then_due_runs_up_to_one_batch(monkeypatch) -> None:
    db, cursor, conn = _db(monkeypatch, [[_run("stale-1")], [_run("due-1"), _run("due-2")]])
    runs = db.claim_due_export_webhook_deliveries(limit=3, exclude_tenant_ids=[_TENANT, "not-a-uuid"])
    assert [r["id"] for r in runs] == ["stale-1", "due-1", "due-2"]
    assert runs[0]["payload"] == b"{}"
    (stale_sql, stale_params), (due_sql, due_params) = cursor.calls
    # Two ordered range scans, each on its own partial index — no OR, no COALESCE sort.
    assert "status = 'delivering'" in stale_sql and "ORDER BY updated_at ASC" in stale_sql
    assert "status IN ('pending', 'retrying')" in due_sql and "ORDER BY next_attempt_at ASC" in due_sql
    for sql in (stale_sql, due_sql):
        assert "COALESCE" not in sql
        assert "FOR UPDATE SKIP LOCKED" in sql
        assert "NOT (tenant_id = ANY(%s::uuid[]))" in sql
    assert stale_params == (600, [_TENANT], 3)
    # The due branch asks only for what is left of the batch.
    assert due_params == ([_TENANT], 2)
    assert conn.commits == 1


def test_export_claim_skips_the_due_branch_when_stale_attempts_fill_the_batch(monkeypatch) -> None:
    db, cursor, _conn = _db(monkeypatch, [[_run("s1"), _run("s2")]])
    assert len(db.claim_due_export_webhook_deliveries(limit=2)) == 2
    assert len(cursor.calls) == 1


def test_the_single_claim_is_a_one_row_batch(monkeypatch) -> None:
    db, cursor, _conn = _db(monkeypatch, [[], []])
    assert db.claim_next_due_export_webhook_delivery() is None
    assert cursor.calls[0][1][-1] == 1


def test_push_claim_is_one_statement_for_a_batch_skipping_saturated_tenants(monkeypatch) -> None:
    rows = [{"event_id": "e1", "tenant_id": _TENANT}, {"event_id": "e2", "tenant_id": _TENANT}]
    db, cursor, conn = _db(monkeypatch, [rows])
    assert db.claim_due_push_webhook_deliveries(limit=50, exclude_tenant_ids=[_TENANT]) == rows
    ((sql, params),) = cursor.calls
    assert "FOR UPDATE OF e SKIP LOCKED" in sql
    assert "NOT (e.tenant_id = ANY(%s::uuid[]))" in sql
    assert "ORDER BY e.next_retry_at ASC" in sql
    assert params[1:] == ([_TENANT], 50)
    assert conn.commits == 1


def test_push_single_claim_still_returns_one_row_or_none(monkeypatch) -> None:
    db, _cursor, conn = _db(monkeypatch, [[]])
    assert db.get_next_due_push_webhook_delivery() is None
    assert conn.rollbacks == 1
