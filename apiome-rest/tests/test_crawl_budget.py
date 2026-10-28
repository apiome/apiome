"""Crawl budget primitives and the crawl checkpoint store (MFI-31.4, #4401).

Pure: a fake clock for the rate limiter, a recording fake for the checkpoint SQL.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from app.crawl_budget import (
    ERROR_CLASS_BUDGET,
    BudgetLimits,
    CrawlBudget,
    CrawlBudgetExceededError,
    CrawlMeter,
    CrawlState,
    HostRateLimiter,
    budget_from_scope,
    load_crawl_state,
    save_crawl_state,
    validate_budget_scope,
)
from app.refresh_source import RefreshSourceError

LIMITS = BudgetLimits(
    default=CrawlBudget(requests_per_second=10.0, max_requests=100, max_pages=5, max_bytes=1000),
    ceiling=CrawlBudget(requests_per_second=50.0, max_requests=1000, max_pages=50, max_bytes=10_000),
)
_MIGRATION = "apiome-db/scripts/V335__connector_crawl_state_4401.sql"


class _NoWait(HostRateLimiter):
    def __init__(self) -> None:
        super().__init__(1.0)

    def wait(self, host: str) -> None:
        del host


def _meter(**changes: Any) -> CrawlMeter:
    budget = budget_from_scope(changes, LIMITS)
    return CrawlMeter(budget, limiter=_NoWait())


# --- scope ---------------------------------------------------------------------------------


def test_defaults_apply_when_the_scope_sets_nothing():
    assert budget_from_scope({}, LIMITS) == LIMITS.default


def test_scope_values_are_read_and_clamped_to_the_ceiling():
    budget = budget_from_scope({"maxRequests": 50, "requestsPerSecond": 2.5, "maxBytes": 99_999}, LIMITS)
    assert (budget.max_requests, budget.requests_per_second, budget.max_bytes) == (50, 2.5, 10_000)
    assert budget.as_dict() == {"requestsPerSecond": 2.5, "maxRequests": 50, "maxPages": 5, "maxBytes": 10_000}


@pytest.mark.parametrize(
    "scope,message",
    [
        ({"maxRequests": 0}, "maxRequests must be a whole number above 0 and at most 1000"),
        ({"maxRequests": 1001}, "at most 1000"),
        ({"maxPages": 2.5}, "maxPages must be a whole number"),
        ({"maxBytes": True}, "maxBytes"),
        ({"requestsPerSecond": "fast"}, "requestsPerSecond must be a number above 0 and at most 50"),
        ({"requestsPerSecond": 51}, "at most 50"),
    ],
)
def test_out_of_range_scope_values_are_refused(scope, message):
    with pytest.raises(ValueError, match=message):
        validate_budget_scope(scope, LIMITS)


def test_valid_scope_values_pass():
    validate_budget_scope({"maxRequests": 1000, "maxPages": 1, "maxBytes": 1, "requestsPerSecond": 0.5}, LIMITS)


# --- meter ---------------------------------------------------------------------------------


def test_the_request_budget_refuses_the_next_request_and_exhausts_the_meter():
    meter = _meter(maxRequests=2)
    meter.claim_request("a")
    meter.claim_request("a")
    with pytest.raises(CrawlBudgetExceededError) as exc:
        meter.claim_request("a")
    assert isinstance(exc.value, RefreshSourceError)
    assert (exc.value.error_class, exc.value.dimension) == (ERROR_CLASS_BUDGET, "requests")
    assert meter.exhausted and meter.requests == 2 and meter.requests_left == 0


def test_the_byte_budget_lets_the_current_response_through_and_refuses_the_next_request():
    meter = _meter(maxBytes=100)
    meter.claim_request("a")
    meter.add_bytes(150)
    assert meter.exhausted_by == "bytes"
    with pytest.raises(CrawlBudgetExceededError) as exc:
        meter.claim_request("a")
    assert exc.value.dimension == "bytes"
    assert meter.requests == 1


def test_the_page_budget_ends_the_listing_but_not_the_requests():
    meter = _meter(maxPages=1)
    meter.claim_page()
    with pytest.raises(CrawlBudgetExceededError) as exc:
        meter.claim_page()
    assert exc.value.dimension == "pages"
    assert not meter.exhausted
    meter.claim_request("a")  # syncing what was listed goes on
    assert meter.report() == {
        "requests": 1,
        "pages": 1,
        "bytes": 0,
        "budget": {"requestsPerSecond": 10.0, "maxRequests": 100, "maxPages": 1, "maxBytes": 1000},
        "exhaustedBy": None,
        "pageBudgetReached": True,
    }


def test_the_rate_limiter_spaces_requests_per_host():
    now = [0.0]
    slept: List[float] = []

    def sleep(delay: float) -> None:
        slept.append(delay)
        now[0] += delay

    meter = CrawlMeter(LIMITS.default, limiter=HostRateLimiter(4.0, clock=lambda: now[0], sleep=sleep))
    for _ in range(3):
        meter.claim_request("sr.example")
    meter.claim_request("other.example")
    assert slept == [0.25, 0.25]  # the second and third request to one host; the other host is free


# --- checkpoint ----------------------------------------------------------------------------


class _RecordingDb:
    def __init__(self, rows: List[Dict[str, Any]] | None = None) -> None:
        self.calls: List[Tuple[str, Any]] = []
        self.rows = rows or []

    def execute_query(self, query: str, params: Any = None) -> List[Dict[str, Any]]:
        self.calls.append((" ".join(query.split()), params))
        return self.rows


def test_no_checkpoint_reads_as_empty():
    db = _RecordingDb()
    assert load_crawl_state(db, "c-1") == CrawlState()
    assert "FROM apiome.catalog_connector_crawl_state WHERE connector_id = %s::uuid" in db.calls[0][0]


def test_a_checkpoint_round_trips():
    when = datetime(2026, 10, 28, 6, 0, tzinfo=timezone.utc)
    state = CrawlState(
        cursor="orders-value", pass_started_at=when, watermark=4211, probe_supported=True, extra={"k": 1}
    )
    db = _RecordingDb()
    save_crawl_state(db, "c-1", state)
    sql, params = db.calls[0]
    assert "ON CONFLICT (connector_id) DO UPDATE SET" in sql
    assert params[:6] == ("c-1", "orders-value", when, None, 4211, True)
    assert json.loads(params[6]) == {"k": 1}

    loaded = load_crawl_state(
        _RecordingDb(
            [
                {
                    "cursor": "orders-value",
                    "pass_started_at": when,
                    "last_full_pass_at": None,
                    "watermark": 4211,
                    "probe_supported": True,
                    "extra": {"k": 1},
                }
            ]
        ),
        "c-1",
    )
    assert loaded == state
    assert loaded.with_changes(cursor=None).cursor is None


def test_the_migration_creates_the_checkpoint_table():
    sql = (Path(__file__).resolve().parents[2] / _MIGRATION).read_text()
    assert "CREATE TABLE IF NOT EXISTS apiome.catalog_connector_crawl_state" in sql
    assert "REFERENCES apiome.catalog_connectors(id) ON DELETE CASCADE" in sql
    for column in ("cursor", "pass_started_at", "last_full_pass_at", "watermark", "probe_supported", "extra"):
        assert f"    {column} " in sql
