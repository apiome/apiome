"""Retention for discovery jobs and Slate request data (DBP-1.18, #7201)."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from app import operational_retention_sweep as sweep
from app.database import Database


class FakeDb:
    """Records the prune calls and answers from a scripted backlog per table."""

    SLATE_RETAINED_TABLES = Database.SLATE_RETAINED_TABLES

    def __init__(self, backlog: Dict[str, int], fail: str = "") -> None:
        self.backlog = dict(backlog)
        self.fail = fail
        self.calls: List[tuple] = []

    def _take(self, table: str, limit: int) -> int:
        if table == self.fail:
            raise RuntimeError(f"{table} is broken")
        n = min(limit, self.backlog.get(table, 0))
        self.backlog[table] = self.backlog.get(table, 0) - n
        return n

    def prune_mcp_discovery_jobs(
        self, *, retention_days: int, keep_per_endpoint: int, limit: int, after: Any = None
    ) -> Dict[str, Any]:
        self.calls.append(("jobs", retention_days, keep_per_endpoint, limit, after))
        n = self._take("mcp_discovery_jobs", limit)
        page = len([c for c in self.calls if c[0] == "jobs"])
        return {"deleted": n, "scanned": n, "next": ("at", f"page-{page}") if n == limit else None}

    def purge_expired_slate_rows(self, table: str, *, limit: int) -> int:
        self.calls.append(("slate", table, limit))
        return self._take(table, limit)


def test_it_drains_each_table_in_batches() -> None:
    db = FakeDb({"mcp_discovery_jobs": 25, "slate_insight_logs": 7})
    counts = sweep.process_operational_retention_sweep(
        db,
        discovery_job_retention_days=30,
        discovery_job_keep_per_endpoint=5,
        discovery_job_batch_size=10,
        slate_batch_size=3,
    )
    assert counts["mcp_discovery_jobs"] == 25
    assert counts["slate_insight_logs"] == 7
    assert set(counts) == {"mcp_discovery_jobs", *Database.SLATE_RETAINED_TABLES}
    # 10 + 10 + 5: each window resumes after the previous one; the short window ends the loop.
    assert [c for c in db.calls if c[0] == "jobs"] == [
        ("jobs", 30, 5, 10, None),
        ("jobs", 30, 5, 10, ("at", "page-1")),
        ("jobs", 30, 5, 10, ("at", "page-2")),
    ]
    assert sweep._discovery_job_cursor is None


@pytest.fixture(autouse=True)
def _fresh_cursor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "_discovery_job_cursor", None)


def test_the_discovery_job_cursor_survives_into_the_next_tick() -> None:
    db = FakeDb({"mcp_discovery_jobs": 10_000})
    sweep.process_operational_retention_sweep(db, discovery_job_batch_size=10)
    assert sweep._discovery_job_cursor == ("at", f"page-{sweep.MAX_BATCHES_PER_TABLE}")
    sweep.process_operational_retention_sweep(db, discovery_job_batch_size=10)
    first_of_second_tick = [c for c in db.calls if c[0] == "jobs"][sweep.MAX_BATCHES_PER_TABLE]
    assert first_of_second_tick[-1] == ("at", f"page-{sweep.MAX_BATCHES_PER_TABLE}")


def test_a_large_backlog_is_spread_over_ticks() -> None:
    db = FakeDb({"slate_insight_traces": 10_000})
    counts = sweep.process_operational_retention_sweep(db, slate_batch_size=10)
    assert counts["slate_insight_traces"] == 10 * sweep.MAX_BATCHES_PER_TABLE
    assert db.backlog["slate_insight_traces"] > 0


def test_zero_retention_keeps_discovery_jobs_forever() -> None:
    db = FakeDb({"mcp_discovery_jobs": 5})
    counts = sweep.process_operational_retention_sweep(db, discovery_job_retention_days=0)
    assert counts["mcp_discovery_jobs"] == 0
    assert not [c for c in db.calls if c[0] == "jobs"]


def test_one_table_failing_does_not_stop_the_others() -> None:
    db = FakeDb({"slate_insight_logs": 2, "slate_security_events": 2}, fail="slate_insight_logs")
    counts = sweep.process_operational_retention_sweep(db, slate_batch_size=10)
    assert counts["slate_insight_logs"] == 0
    assert counts["slate_security_events"] == 2


def test_the_slate_purge_accepts_only_retained_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database()
    captured: Dict[str, Any] = {}

    def _write(sql: str, params: Any = None) -> int:
        captured["sql"], captured["params"] = sql, params
        return 0

    monkeypatch.setattr(db, "_execute_write", _write)
    db.purge_expired_slate_rows("slate_insight_logs", limit=0)
    assert "DELETE FROM apiome.slate_insight_logs" in captured["sql"]
    assert "retain_until < CURRENT_TIMESTAMP" in captured["sql"]
    assert "ORDER BY retain_until ASC" in captured["sql"]
    assert captured["params"] == (1,)
    with pytest.raises(ValueError):
        db.purge_expired_slate_rows("users; DROP TABLE x", limit=10)


def test_the_discovery_job_prune_reads_a_bounded_window_of_finished_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    db = Database()
    captured: Dict[str, Any] = {}

    def _query(sql: str, params: Any = None) -> List[Dict[str, Any]]:
        captured["sql"], captured["params"] = sql, params
        return [{"scanned": 500, "deleted": 3, "last_at": "t", "last_id": "550e8400-e29b-41d4-a716-446655440000"}]

    monkeypatch.setattr(db, "execute_query", _query)
    result = db.prune_mcp_discovery_jobs(retention_days=30, keep_per_endpoint=20, limit=500)
    assert result == {"deleted": 3, "scanned": 500, "next": ("t", "550e8400-e29b-41d4-a716-446655440000")}
    assert "j.state IN ('completed', 'failed')" in captured["sql"]
    assert "OFFSET %(skip)s LIMIT 1" in captured["sql"]
    assert "(j.created_at, j.id) >" not in captured["sql"]
    assert captured["params"] == {"days": 30, "limit": 500, "skip": 19}

    db.prune_mcp_discovery_jobs(
        retention_days=30, keep_per_endpoint=0, limit=500, after=("t", "550e8400-e29b-41d4-a716-446655440000")
    )
    assert "OFFSET" not in captured["sql"]
    assert "(j.created_at, j.id) > (%(after_at)s, %(after_id)s::uuid)" in captured["sql"]

    # A short window is the end: the caller wraps around.
    monkeypatch.setattr(
        db, "execute_query", lambda sql, params=None: [{"scanned": 2, "deleted": 2, "last_at": "t", "last_id": "x"}]
    )
    assert db.prune_mcp_discovery_jobs(retention_days=30, keep_per_endpoint=1, limit=500)["next"] is None
    assert db.prune_mcp_discovery_jobs(retention_days=0, keep_per_endpoint=1, limit=500)["deleted"] == 0
