"""Observability control-plane persistence — UXE-3.4 (private-suite#2476).

Exercises :mod:`app.slate_insights_store` against a scripted fake connection, following the
``test_slate_functions_store.py`` precedent exactly. No live Postgres: this asserts the SQL these
functions emit, the parameters they do *not* pass, and the transaction discipline around both.

Five properties get the most attention, because each fails silently:

* **Nothing here can claim a measurement.** ``basis``, ``edge_attached``, ``billable``,
  ``stream_state``, ``events_delivered``, ``last_delivery_state``, ``delivery_state`` and
  ``enforced`` are SQL literals with no parameter behind them. The tests assert this twice: once
  against the emitted statement text, and once against the *signature*, because a literal a caller
  can override by keyword is not a literal. That second assertion is the real one — it is the
  difference between "today's callers pass the honest value" and "no caller can pass a dishonest
  one".
* **The policy version is a compare-and-set, not a read-then-write.** Two operators shortening
  retention during one incident is the normal case, and the second must be refused.
* **Redaction happens inside the store.** A redaction the caller could skip is a redaction that
  will eventually be skipped, and live tail exists specifically to put reader traffic in front of
  a person.
* **Retention is derived, never defaulted to forever.** Every request-data insert passes a
  ``retain_until``, and it comes from the lane's policy so that shortening retention actually
  shortens it.
* **Residency lanes are a path, not a list.** An alphabetical ordering would put cache storage
  before ingress, which reads as a claim about where requests go.

One detail of the fake is worth stating, because the scripts below depend on it: ``execute``
queues its scripted result and ``fetchone``/``fetchall`` take from the front of that queue, so a
statement that executes without fetching (the residency INSERTs, the span INSERTs) consumes the
*next* script slot. The sequences here are written accordingly.
"""

from __future__ import annotations

import inspect
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence

import pytest

from app.slate_insights import EVIDENCE_KEYS, RESIDENCY_STAGES, SPAN_ATTRIBUTE_KEYS
from app.slate_insights_store import (
    SlateInsightPolicyConflictError,
    SlateInsightStoreError,
    acknowledge_budget_alert,
    append_audit,
    bump_policy_version,
    close_tail_session,
    delete_budget,
    delete_export,
    delete_synthetic_check,
    ensure_policy,
    ensure_residency_lanes,
    get_policy,
    get_trace,
    list_audit,
    list_budget_alerts,
    list_budgets,
    list_exports,
    list_logs,
    list_metric_series,
    list_residency_lanes,
    list_synthetic_checks,
    list_synthetic_results,
    list_tail_sessions,
    list_traces,
    list_usage,
    open_tail_session,
    record_budget_alert,
    record_log,
    record_metric_point,
    record_synthetic_result,
    record_trace,
    record_usage,
    update_policy,
    upsert_budget,
    upsert_export,
    upsert_residency_lane,
    upsert_synthetic_check,
)

TENANT = "11111111-1111-1111-1111-111111111111"
SITE = "22222222-2222-2222-2222-222222222222"
ENV = "33333333-3333-3333-3333-333333333333"
RELEASE = "44444444-4444-4444-4444-444444444444"
CHECK_ID = "55555555-5555-5555-5555-555555555555"
BUDGET = "66666666-6666-6666-6666-666666666666"
ALERT = "77777777-7777-7777-7777-777777777777"
EXPORT = "88888888-8888-8888-8888-888888888888"
SESSION = "99999999-9999-9999-9999-999999999999"
TRACE_ROW_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"

TRACE_ID = "a" * 32
WINDOW_START = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
WINDOW_END = datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc)
FROZEN_NOW = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)


class FakeCursor:
    """Records every statement and replays scripted results in order."""

    def __init__(self, conn: "FakeConnection") -> None:
        self.conn = conn

    def execute(self, query: str, params: Sequence[Any] = ()) -> None:
        self.conn.statements.append((" ".join(query.split()), tuple(params)))
        self.conn._advance()

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self.conn._take()

    def fetchall(self) -> List[Dict[str, Any]]:
        value = self.conn._take()
        return value if isinstance(value, list) else ([] if value is None else [value])

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class FakeConnection:
    """A psycopg2-shaped connection whose results are scripted per statement."""

    cursor_class = FakeCursor

    def __init__(self, results: Optional[List[Any]] = None) -> None:
        self.results = list(results or [])
        self.statements: List[tuple] = []
        self.commits = 0
        self.rollbacks = 0
        self._pending: List[Any] = []

    def _advance(self) -> None:
        if self.results:
            self._pending.append(self.results.pop(0))

    def _take(self) -> Any:
        return self._pending.pop(0) if self._pending else None

    def cursor(self) -> FakeCursor:
        return self.cursor_class(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class ExplodingCursor(FakeCursor):
    """Records the statement, then fails the way a constraint violation would."""

    def execute(self, query: str, params: Sequence[Any] = ()) -> None:
        self.conn.statements.append((" ".join(query.split()), tuple(params)))
        if len(self.conn.statements) > self.conn.fail_after:
            raise RuntimeError("constraint violation")
        self.conn._advance()


class ExplodingConnection(FakeConnection):
    """A connection whose statements fail once ``fail_after`` of them have succeeded."""

    cursor_class = ExplodingCursor

    def __init__(self, results: Optional[List[Any]] = None, fail_after: int = 0) -> None:
        super().__init__(results)
        self.fail_after = fail_after


class FakeDb:
    """Minimal ``_DbLike`` returning one connection."""

    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def connect(self) -> FakeConnection:
        return self._conn


def db_with(*results: Any) -> tuple[FakeDb, FakeConnection]:
    """Build a fake database whose statements return ``results`` in order."""
    conn = FakeConnection(list(results))
    return FakeDb(conn), conn


def exploding_db() -> tuple[FakeDb, ExplodingConnection]:
    """Build a fake database on which every statement raises."""
    conn = ExplodingConnection()
    return FakeDb(conn), conn


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> datetime:
    """Pin ``_now`` so a retention window is an exact timedelta rather than an approximate one."""
    monkeypatch.setattr("app.slate_insights_store._now", lambda: FROZEN_NOW)
    return FROZEN_NOW


def policy_row(**overrides: Any) -> Dict[str, Any]:
    """An observability policy row."""
    base = {
        "id": "policy-1",
        "tenant_id": TENANT,
        "site_id": SITE,
        "environment_id": ENV,
        "telemetry_enabled": False,
        "policy_version": 3,
        "edge_attached": False,
        "metric_retention_days": 90,
        "log_retention_days": 14,
        "trace_retention_days": 7,
        "default_sample_rate": 0.05,
        "max_tail_sample_rate": 0.01,
        "max_tail_events_per_sec": 100,
        "privacy_threshold": 10,
        "retention_waiver_reason": None,
    }
    base.update(overrides)
    return base


def policy_values(**overrides: Any) -> Dict[str, Any]:
    """Column values for a policy write."""
    base = {
        "telemetry_enabled": True,
        "metric_retention_days": 60,
        "log_retention_days": 21,
        "trace_retention_days": 5,
        "default_sample_rate": 0.1,
        "max_tail_sample_rate": 0.01,
        "max_tail_events_per_sec": 50,
        "privacy_threshold": 12,
        "retention_waiver_reason": None,
    }
    base.update(overrides)
    return base


def lane_values(**overrides: Any) -> Dict[str, Any]:
    """Column values for a residency lane write."""
    base = {
        "stage": "ingress",
        "residency_class": "in-region-only",
        "regions": ["eu-west"],
        "uncovered_sentence": "Nothing is in the request path, so this is a declared intent.",
        "residency_waiver_reason": None,
    }
    base.update(overrides)
    return base


def lane_row(stage: str, **overrides: Any) -> Dict[str, Any]:
    """A stored residency lane row."""
    base = dict(lane_values(stage=stage), id=f"lane-{stage}", enforced=False)
    base.update(overrides)
    return base


def default_lanes() -> List[Dict[str, Any]]:
    """One default lane per stage, as :func:`app.slate_insights.default_residency_lanes` gives."""
    return [lane_values(stage=stage) for stage in RESIDENCY_STAGES]


def export_values(**overrides: Any) -> Dict[str, Any]:
    """Column values for an export destination write."""
    base = {
        "label": "Vendor collector",
        "endpoint": "https://otlp.example.com/v1/traces",
        "protocol": "http/protobuf",
        "signals": ["traces"],
        "header_secret_ref": "otlp-auth",
        "enabled": True,
    }
    base.update(overrides)
    return base


def budget_values(**overrides: Any) -> Dict[str, Any]:
    """Column values for a budget write."""
    base = {
        "label": "Delivery monthly",
        "service": "delivery",
        "period": "monthly",
        "amount": 500.0,
        "currency": "USD",
        "alert_thresholds": [0.5, 0.8],
        "notify_channel_ref": "ops-alerts",
        "enabled": True,
    }
    base.update(overrides)
    return base


def alert_values(**overrides: Any) -> Dict[str, Any]:
    """Column values for a budget alert write."""
    base = {
        "budget_id": BUDGET,
        "threshold": 0.8,
        "observed_amount": 412.5,
        "budget_amount": 500.0,
        "currency": "USD",
        "period_start": date(2026, 7, 1),
        "period_end": date(2026, 7, 31),
    }
    base.update(overrides)
    return base


def session_values(**overrides: Any) -> Dict[str, Any]:
    """A planned live tail session, as :func:`app.slate_insights.plan_live_tail` gives."""
    base = {
        "sample_rate": 0.01,
        "max_events_per_sec": 25,
        "redaction_allowlist": list(EVIDENCE_KEYS),
        "filter_expression": "status>=500",
        "reason": "Investigating the checkout 500s",
    }
    base.update(overrides)
    return base


def keywords_of(function: Any) -> set:
    """Every keyword a caller could pass to ``function``."""
    return set(inspect.signature(function).parameters)


class TestHonestyLiteralsOnMetrics:
    """Nothing observed this lane, and the statement says so rather than the argument."""

    def test_a_metric_point_is_written_as_modelled_and_unattached(self) -> None:
        db, conn = db_with({"id": "metric-1"})
        record_metric_point(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            metric_family="request",
            metric_key="p95_ms",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            value=142.0,
            sample_count=5,
        )
        query, _ = conn.statements[0]
        assert "'modelled', FALSE" in query
        assert "INSERT INTO apiome.slate_insight_metric_series" in query

    def test_the_metric_basis_is_not_reachable_from_the_parameters(self) -> None:
        db, conn = db_with({"id": "metric-1"})
        record_metric_point(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            metric_family="request",
            metric_key="p95_ms",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            value=142.0,
            sample_count=5,
            suppressed=True,
        )
        _, params = conn.statements[0]
        assert "modelled" not in params
        assert False not in params, "edge_attached is a literal; suppressed is the only boolean"

    def test_no_argument_can_make_a_metric_point_claim_an_observation(self) -> None:
        """The honesty enforcement point: the dishonest values are not reachable from any call."""
        keywords = keywords_of(record_metric_point)
        assert "basis" not in keywords
        assert "edge_attached" not in keywords

    def test_a_suppressed_point_is_written_with_no_value_at_all(self) -> None:
        db, conn = db_with({"id": "metric-1"})
        record_metric_point(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            metric_family="security",
            metric_key="blocked",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            value=7.0,
            suppressed=True,
        )
        _, params = conn.statements[0]
        assert 7.0 not in params, "a suppressed row that kept its number invites a future misread"
        assert True in params

    def test_a_negative_sample_count_is_floored_rather_than_stored(self) -> None:
        db, conn = db_with({"id": "metric-1"})
        record_metric_point(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            metric_family="cache",
            metric_key="hit_ratio",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            value=0.9,
            sample_count=-5,
        )
        assert -5 not in conn.statements[0][1]

    def test_a_metric_write_commits_once(self) -> None:
        db, conn = db_with({"id": "metric-1"})
        record_metric_point(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            metric_family="origin",
            metric_key="errors",
            window_start=WINDOW_START,
            window_end=WINDOW_END,
            value=1.0,
        )
        assert conn.commits == 1
        assert conn.rollbacks == 0


class TestHonestyLiteralsOnLogs:
    """A log line that claimed to be edge-observed would be a fabricated capture."""

    def test_a_log_line_is_written_as_modelled_and_unattached(self) -> None:
        db, conn = db_with({"id": "log-1"})
        record_log(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            level="warn",
            source="origin",
            message="Upstream slow",
            evidence={"path": "/checkout"},
        )
        query, _ = conn.statements[0]
        assert "'modelled', FALSE" in query

    def test_the_log_basis_is_not_reachable_from_the_parameters(self) -> None:
        db, conn = db_with({"id": "log-1"})
        record_log(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            level="warn",
            source="origin",
            message="Upstream slow",
            evidence={"path": "/checkout"},
        )
        _, params = conn.statements[0]
        assert "modelled" not in params
        assert False not in params

    def test_no_argument_can_make_a_log_line_claim_an_observation(self) -> None:
        keywords = keywords_of(record_log)
        assert "basis" not in keywords
        assert "edge_attached" not in keywords


class TestHonestyLiteralsOnTraces:
    """An empty waterfall reads as a fast request, so a trace must never overstate its provenance."""

    def test_a_trace_is_written_as_modelled_and_unattached(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=142,
            route="/checkout",
            status_code=200,
            sample_rate=0.5,
        )
        query, _ = conn.statements[0]
        assert "'modelled', FALSE" in query

    def test_the_trace_basis_is_not_reachable_from_the_parameters(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=142,
            route="/checkout",
            status_code=200,
            sample_rate=0.5,
        )
        _, params = conn.statements[0]
        assert "modelled" not in params
        assert False not in params

    def test_no_argument_can_make_a_trace_claim_an_observation(self) -> None:
        keywords = keywords_of(record_trace)
        assert "basis" not in keywords
        assert "edge_attached" not in keywords


class TestHonestyLiteralsOnSyntheticResults:
    """No probe ran, so the row says what a probe would report, not what one saw."""

    def test_a_synthetic_result_is_written_as_modelled_and_unattached(self) -> None:
        db, conn = db_with({"id": "result-1"})
        record_synthetic_result(
            db,
            tenant_id=TENANT,
            check_id=CHECK_ID,
            environment_id=ENV,
            outcome="healthy",
            status_code=200,
            latency_ms=42,
        )
        query, _ = conn.statements[0]
        assert "'modelled', FALSE" in query

    def test_the_synthetic_basis_is_not_reachable_from_the_parameters(self) -> None:
        db, conn = db_with({"id": "result-1"})
        record_synthetic_result(
            db,
            tenant_id=TENANT,
            check_id=CHECK_ID,
            environment_id=ENV,
            outcome="healthy",
            status_code=200,
            latency_ms=42,
        )
        _, params = conn.statements[0]
        assert "modelled" not in params
        assert False not in params

    def test_no_argument_can_make_a_synthetic_result_claim_a_probe_run(self) -> None:
        keywords = keywords_of(record_synthetic_result)
        assert "basis" not in keywords
        assert "edge_attached" not in keywords

    def test_an_annotation_is_a_parameter_because_it_is_an_operator_judgement(self) -> None:
        """The distinction: what happened is a literal, what a person concluded is a parameter."""
        db, conn = db_with({"id": "result-1"})
        record_synthetic_result(
            db,
            tenant_id=TENANT,
            check_id=CHECK_ID,
            environment_id=ENV,
            outcome="degraded",
            status_code=200,
            latency_ms=980,
            release_id=RELEASE,
            annotation_kind="post-promotion-regression",
            annotation_note="p95 doubled after promotion",
        )
        _, params = conn.statements[0]
        assert "post-promotion-regression" in params
        assert "p95 doubled after promotion" in params


class TestHonestyLiteralsOnUsage:
    """A modelled cost presented as a charge is not an estimate but an invented invoice."""

    def test_a_usage_record_is_written_as_modelled_unbillable_and_unattached(self) -> None:
        db, conn = db_with({"id": "usage-1"})
        record_usage(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            service="delivery",
            usage_date=date(2026, 7, 19),
            quantity=1200.0,
            unit="requests",
            amount=3.5,
            included_quantity=1.0,
            overage_quantity=2.0,
        )
        query, _ = conn.statements[0]
        assert "'modelled', FALSE, FALSE" in query

    def test_the_usage_basis_and_billable_flag_are_not_reachable_from_the_parameters(self) -> None:
        db, conn = db_with({"id": "usage-1"})
        record_usage(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            service="delivery",
            usage_date=date(2026, 7, 19),
            quantity=1200.0,
            unit="requests",
            amount=3.5,
            included_quantity=1.0,
            overage_quantity=2.0,
        )
        _, params = conn.statements[0]
        assert "modelled" not in params
        assert False not in params

    def test_no_argument_can_make_a_usage_record_billable(self) -> None:
        keywords = keywords_of(record_usage)
        assert "basis" not in keywords
        assert "billable" not in keywords
        assert "edge_attached" not in keywords

    def test_cache_savings_are_absent_from_the_column_list_entirely(self) -> None:
        """V190 permits the column only on a metered row, and nothing meters these lanes."""
        db, conn = db_with({"id": "usage-1"})
        record_usage(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            service="delivery",
            usage_date=date(2026, 7, 19),
            quantity=1200.0,
            unit="requests",
            amount=3.5,
        )
        query, _ = conn.statements[0]
        assert "cache_savings_amount" not in query

    def test_there_is_no_cache_savings_keyword_to_pass_either(self) -> None:
        """A parameter that can only ever legally be NULL is an invitation to pass something else."""
        assert "cache_savings_amount" not in keywords_of(record_usage)

    def test_a_forecast_is_kept_in_its_own_column_rather_than_summed_into_the_total(self) -> None:
        db, conn = db_with({"id": "usage-1"})
        record_usage(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            service="delivery",
            usage_date=date(2026, 7, 19),
            quantity=1200.0,
            unit="requests",
            amount=3.5,
            forecast_amount=110.0,
        )
        query, params = conn.statements[0]
        assert "forecast_amount" in query
        assert 110.0 in params
        assert 3.5 in params

    def test_a_currency_is_normalized_to_upper_case(self) -> None:
        db, conn = db_with({"id": "usage-1"})
        record_usage(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            service="build",
            usage_date=date(2026, 7, 19),
            quantity=3.0,
            unit="minutes",
            amount=1.0,
            currency="usd",
        )
        assert "USD" in conn.statements[0][1]

    def test_a_repeated_day_updates_rather_than_duplicating(self) -> None:
        db, conn = db_with({"id": "usage-1"})
        record_usage(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            service="build",
            usage_date=date(2026, 7, 19),
            quantity=3.0,
            unit="minutes",
            amount=1.0,
        )
        assert "ON CONFLICT (environment_id, service, usage_date) DO UPDATE" in conn.statements[0][0]


class TestHonestyLiteralsOnTailSessions:
    """A session can be requested and refused, but never attached and never delivering."""

    def test_a_tail_session_is_written_as_requested_with_nothing_delivered(self) -> None:
        db, conn = db_with({"id": SESSION})
        open_tail_session(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            session=session_values(),
            actor_name="ken@example.com",
            actor_key="user-1",
        )
        query, _ = conn.statements[0]
        assert "'requested'" in query
        assert "0," in query, "events_delivered is a literal zero"
        assert "FALSE" in query

    def test_the_stream_state_is_not_reachable_from_the_parameters(self) -> None:
        db, conn = db_with({"id": SESSION})
        open_tail_session(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            session=session_values(),
            actor_name="ken@example.com",
            actor_key="user-1",
        )
        _, params = conn.statements[0]
        assert "requested" not in params
        assert "attached" not in params
        assert 0 not in params, "events_delivered and edge_attached are both literals"
        assert False not in params

    def test_no_argument_can_attach_a_tail_or_claim_a_delivery(self) -> None:
        keywords = keywords_of(open_tail_session)
        assert "stream_state" not in keywords
        assert "events_delivered" not in keywords
        assert "edge_attached" not in keywords

    def test_the_allowlist_in_force_is_stored_on_the_row(self) -> None:
        """A capture reviewed a year later is checked against the redaction it ran under."""
        db, conn = db_with({"id": SESSION})
        open_tail_session(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            session=session_values(redaction_allowlist=["path", "method"]),
            actor_name="ken@example.com",
            actor_key="user-1",
        )
        query, params = conn.statements[0]
        assert "redaction_allowlist" in query
        assert ["path", "method"] in params

    def test_the_reason_for_opening_a_tail_is_recorded(self) -> None:
        db, conn = db_with({"id": SESSION})
        open_tail_session(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            session=session_values(),
            actor_name="ken@example.com",
            actor_key="user-1",
        )
        assert "Investigating the checkout 500s" in conn.statements[0][1]

    def test_closing_a_session_does_not_write_a_delivery_count(self) -> None:
        """The one path by which this module could otherwise claim a stream it never had."""
        db, conn = db_with({"id": SESSION, "stream_state": "closed"})
        close_tail_session(db, tenant_id=TENANT, environment_id=ENV, session_id=SESSION)
        query, _ = conn.statements[0]
        assert "events_delivered" not in query
        assert "stream_state = 'closed'" in query

    def test_closing_a_session_has_no_events_delivered_keyword_either(self) -> None:
        assert "events_delivered" not in keywords_of(close_tail_session)

    def test_closing_a_session_that_does_not_exist_raises(self) -> None:
        db, conn = db_with(None)
        with pytest.raises(SlateInsightStoreError) as excinfo:
            close_tail_session(db, tenant_id=TENANT, environment_id=ENV, session_id=SESSION)
        assert excinfo.value.code == "session_not_found"

    def test_sessions_are_newest_first_and_clamped(self) -> None:
        db, conn = db_with([])
        list_tail_sessions(db, tenant_id=TENANT, environment_id=ENV, limit=9999)
        query, params = conn.statements[0]
        assert "ORDER BY started_at DESC" in query
        assert params[-1] == 200


class TestHonestyLiteralsOnExports:
    """A destination that read 'delivered' would assert an arrival nobody made."""

    def test_an_export_is_written_as_never_attempted_and_unattached(self) -> None:
        db, conn = db_with({"id": EXPORT})
        upsert_export(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            export=export_values(),
            actor_name="ken@example.com",
            actor_key="user-1",
        )
        query, _ = conn.statements[0]
        assert "'never-attempted', FALSE" in query

    def test_the_delivery_state_is_not_reachable_from_the_parameters(self) -> None:
        db, conn = db_with({"id": EXPORT})
        upsert_export(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            export=export_values(),
            actor_name="ken@example.com",
            actor_key="user-1",
        )
        _, params = conn.statements[0]
        assert "never-attempted" not in params
        assert "delivered" not in params
        assert False not in params, "enabled is True here, so any FALSE would be edge_attached"

    def test_no_argument_can_claim_an_export_arrived(self) -> None:
        keywords = keywords_of(upsert_export)
        assert "last_delivery_state" not in keywords
        assert "edge_attached" not in keywords

    def test_an_export_stores_a_secret_reference_rather_than_a_header_value(self) -> None:
        db, conn = db_with({"id": EXPORT})
        upsert_export(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            export=export_values(),
            actor_name="ken@example.com",
            actor_key="user-1",
        )
        query, params = conn.statements[0]
        assert "header_secret_ref" in query
        assert "header_value" not in query
        assert "otlp-auth" in params

    def test_re_writing_a_destination_by_label_updates_rather_than_duplicating(self) -> None:
        db, conn = db_with({"id": EXPORT})
        upsert_export(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            export=export_values(),
            actor_name="ken@example.com",
            actor_key="user-1",
        )
        assert "ON CONFLICT (environment_id, label) DO UPDATE" in conn.statements[0][0]

    def test_an_export_that_cannot_be_written_raises(self) -> None:
        db, _ = db_with(None)
        with pytest.raises(SlateInsightStoreError) as excinfo:
            upsert_export(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                export=export_values(),
                actor_name="a",
                actor_key="a",
            )
        assert excinfo.value.code == "export_not_found"

    def test_deleting_a_destination_returns_it_so_the_audit_can_name_it(self) -> None:
        db, conn = db_with({"id": EXPORT, "label": "Vendor collector"})
        deleted = delete_export(db, tenant_id=TENANT, environment_id=ENV, export_id=EXPORT)
        assert deleted["label"] == "Vendor collector"
        assert conn.statements[0][0].startswith("DELETE FROM apiome.slate_insight_otlp_exports")

    def test_deleting_a_destination_that_is_not_there_raises(self) -> None:
        db, conn = db_with(None)
        with pytest.raises(SlateInsightStoreError) as excinfo:
            delete_export(db, tenant_id=TENANT, environment_id=ENV, export_id=EXPORT)
        assert excinfo.value.code == "export_not_found"
        assert conn.rollbacks == 0, "a DELETE that matched nothing is not an error to unwind"

    def test_destinations_are_listed_by_label(self) -> None:
        db, conn = db_with([])
        list_exports(db, tenant_id=TENANT, environment_id=ENV)
        assert "ORDER BY label" in conn.statements[0][0]


class TestHonestyLiteralsOnBudgetAlerts:
    """'You have exceeded your budget' reads as a statement of fact, so its basis must be stated."""

    def test_an_alert_is_written_as_modelled_undispatched_and_unattached(self) -> None:
        db, conn = db_with({"id": ALERT})
        record_budget_alert(db, tenant_id=TENANT, environment_id=ENV, alert=alert_values())
        query, _ = conn.statements[0]
        assert "'modelled', 'not-dispatched', FALSE" in query

    def test_the_alert_basis_and_delivery_state_are_not_reachable_from_the_parameters(self) -> None:
        db, conn = db_with({"id": ALERT})
        record_budget_alert(db, tenant_id=TENANT, environment_id=ENV, alert=alert_values())
        _, params = conn.statements[0]
        assert "modelled" not in params
        assert "not-dispatched" not in params
        assert False not in params

    def test_no_argument_can_claim_an_alert_was_dispatched(self) -> None:
        keywords = keywords_of(record_budget_alert)
        assert "basis" not in keywords
        assert "delivery_state" not in keywords
        assert "edge_attached" not in keywords

    def test_a_scheduler_retry_writes_nothing_and_returns_none(self) -> None:
        """A wall of duplicates teaches operators to ignore the one that mattered."""
        db, conn = db_with(None)
        assert (
            record_budget_alert(db, tenant_id=TENANT, environment_id=ENV, alert=alert_values())
            is None
        )
        assert "ON CONFLICT (budget_id, threshold, period_start) DO NOTHING" in conn.statements[0][0]
        assert conn.commits == 1, "a no-op re-fire is still a completed transaction"

    def test_a_first_fire_returns_the_written_row(self) -> None:
        db, _ = db_with({"id": ALERT, "threshold": 0.8})
        written = record_budget_alert(
            db, tenant_id=TENANT, environment_id=ENV, alert=alert_values()
        )
        assert written is not None
        assert written["threshold"] == 0.8

    def test_the_threshold_and_both_amounts_are_recorded_together(self) -> None:
        db, conn = db_with({"id": ALERT})
        record_budget_alert(db, tenant_id=TENANT, environment_id=ENV, alert=alert_values())
        _, params = conn.statements[0]
        assert 0.8 in params
        assert 412.5 in params
        assert 500.0 in params

    def test_acknowledging_an_alert_writes_the_person_and_the_time_together(self) -> None:
        db, conn = db_with({"id": ALERT})
        acknowledge_budget_alert(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            alert_id=ALERT,
            actor_name="ken@example.com",
            actor_key="user-1",
        )
        query, params = conn.statements[0]
        assert "acknowledged_at" in query
        assert "acknowledged_by_actor_name" in query
        assert "acknowledged_by_actor_key" in query
        assert "user-1" in params

    def test_acknowledging_an_alert_that_does_not_exist_raises(self) -> None:
        db, _ = db_with(None)
        with pytest.raises(SlateInsightStoreError) as excinfo:
            acknowledge_budget_alert(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                alert_id=ALERT,
                actor_name="a",
                actor_key="a",
            )
        assert excinfo.value.code == "alert_not_found"


class TestHonestyLiteralsOnResidencyLanes:
    """A stage's placement is a declared intent, not an active control."""

    def test_a_residency_lane_is_written_as_unenforced(self) -> None:
        db, conn = db_with(lane_row("ingress"))
        upsert_residency_lane(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            lane=lane_values(),
            actor_name="ken@example.com",
            actor_key="user-1",
        )
        query, params = conn.statements[0]
        assert "FALSE" in query
        assert False not in params
        assert "enforced" in query

    def test_no_argument_can_mark_a_residency_stage_enforced(self) -> None:
        assert "enforced" not in keywords_of(upsert_residency_lane)

    def test_the_default_lanes_are_written_unenforced_too(self) -> None:
        db, conn = db_with([lane_row(stage) for stage in RESIDENCY_STAGES])
        ensure_residency_lanes(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            defaults=default_lanes(),
            actor_name="ken@example.com",
            actor_key="user-1",
        )
        insert = conn.statements[0]
        assert "enforced" in insert[0]
        assert "FALSE" in insert[0]
        assert False not in insert[1]

    def test_ensure_lanes_has_no_enforced_keyword_either(self) -> None:
        assert "enforced" not in keywords_of(ensure_residency_lanes)

    def test_a_lane_write_carries_the_sentence_saying_what_is_not_covered(self) -> None:
        db, conn = db_with(lane_row("ingress"))
        upsert_residency_lane(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            lane=lane_values(),
            actor_name="a",
            actor_key="a",
        )
        query, params = conn.statements[0]
        assert "uncovered_sentence" in query
        assert lane_values()["uncovered_sentence"] in params

    def test_an_unrestricted_class_carries_its_waiver_reason(self) -> None:
        db, conn = db_with(lane_row("cache-storage"))
        upsert_residency_lane(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            lane=lane_values(
                stage="cache-storage",
                residency_class="unrestricted",
                residency_waiver_reason="latency",
            ),
            actor_name="a",
            actor_key="a",
        )
        params = conn.statements[0][1]
        assert "unrestricted" in params
        assert "latency" in params

    def test_a_lane_that_cannot_be_written_raises(self) -> None:
        db, _ = db_with(None)
        with pytest.raises(SlateInsightStoreError) as excinfo:
            upsert_residency_lane(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                lane=lane_values(),
                actor_name="a",
                actor_key="a",
            )
        assert excinfo.value.code == "lane_not_found"


class TestResidencyLanesAreAPath:
    """All six or none, in the order a request actually travels."""

    def test_all_six_stages_are_inserted(self) -> None:
        db, conn = db_with([lane_row(stage) for stage in RESIDENCY_STAGES])
        ensure_residency_lanes(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            defaults=default_lanes(),
            actor_name="a",
            actor_key="a",
        )
        inserts = [
            s for s in conn.statements if "INSERT INTO apiome.slate_residency_lanes" in s[0]
        ]
        assert len(inserts) == 6
        written = [s[1][2] for s in inserts]
        assert written == list(RESIDENCY_STAGES)

    def test_creating_the_lanes_twice_writes_nothing_the_second_time(self) -> None:
        db, conn = db_with([lane_row(stage) for stage in RESIDENCY_STAGES])
        ensure_residency_lanes(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            defaults=default_lanes(),
            actor_name="a",
            actor_key="a",
        )
        insert = conn.statements[0][0]
        assert "ON CONFLICT (environment_id, stage) DO NOTHING" in insert

    def test_creating_the_lanes_commits_once_for_all_six(self) -> None:
        db, conn = db_with([lane_row(stage) for stage in RESIDENCY_STAGES])
        ensure_residency_lanes(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            defaults=default_lanes(),
            actor_name="a",
            actor_key="a",
        )
        assert conn.commits == 1, "five stages and a rollback would be worse than none"

    def test_creating_the_lanes_returns_them_all(self) -> None:
        db, _ = db_with([lane_row(stage) for stage in RESIDENCY_STAGES])
        lanes = ensure_residency_lanes(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            defaults=default_lanes(),
            actor_name="a",
            actor_key="a",
        )
        assert [lane["stage"] for lane in lanes] == list(RESIDENCY_STAGES)

    def test_lanes_are_ordered_along_the_request_path_not_alphabetically(self) -> None:
        """Alphabetical would put cache-storage before ingress, which is a claim about routing."""
        db, conn = db_with([])
        list_residency_lanes(db, tenant_id=TENANT, environment_id=ENV)
        query, _ = conn.statements[0]
        assert "ORDER BY array_position(" in query
        assert (
            "ARRAY['ingress','tls-termination','decrypted-processing','cache-storage', "
            "'function-execution','log-data-storage']::TEXT[], stage)" in query
        )
        assert "ORDER BY stage" not in query

    def test_the_ordering_array_lists_ingress_first_and_log_storage_last(self) -> None:
        db, conn = db_with([])
        list_residency_lanes(db, tenant_id=TENANT, environment_id=ENV)
        query, _ = conn.statements[0]
        ordering = query.split("array_position(", 1)[1]
        assert ordering.index("'ingress'") < ordering.index("'cache-storage'")
        assert ordering.index("'cache-storage'") < ordering.index("'log-data-storage'")

    def test_the_ordering_array_matches_the_shared_stage_catalog(self) -> None:
        db, conn = db_with([])
        list_residency_lanes(db, tenant_id=TENANT, environment_id=ENV)
        query, _ = conn.statements[0]
        for stage in RESIDENCY_STAGES:
            assert f"'{stage}'" in query


class TestPolicyLifecycle:
    """A lane with no row is a lane at the safe defaults, not a lane in error."""

    def test_an_existing_policy_is_returned_without_writing(self) -> None:
        db, conn = db_with(policy_row())
        result = ensure_policy(
            db,
            tenant_id=TENANT,
            site_id=SITE,
            environment_id=ENV,
            actor_name="a",
            actor_key="a",
        )
        assert result["policy_version"] == 3
        assert conn.commits == 0, "a read must not write"

    def test_a_missing_policy_is_created_at_the_shipped_defaults(self) -> None:
        db, conn = db_with(None, policy_row(policy_version=0, telemetry_enabled=False))
        result = ensure_policy(
            db,
            tenant_id=TENANT,
            site_id=SITE,
            environment_id=ENV,
            actor_name="a",
            actor_key="a",
        )
        assert result["policy_version"] == 0
        insert = conn.statements[1][0]
        assert "INSERT INTO apiome.slate_insight_policies" in insert
        assert conn.commits == 1

    def test_the_created_policy_names_no_retention_so_v190_supplies_it(self) -> None:
        db, conn = db_with(None, policy_row(policy_version=0))
        ensure_policy(
            db,
            tenant_id=TENANT,
            site_id=SITE,
            environment_id=ENV,
            actor_name="a",
            actor_key="a",
        )
        insert = conn.statements[1][0]
        assert "metric_retention_days" not in insert
        assert "log_retention_days" not in insert
        assert "trace_retention_days" not in insert

    def test_a_concurrent_first_read_re_reads_rather_than_raising(self) -> None:
        db, conn = db_with(None, None, policy_row())
        result = ensure_policy(
            db,
            tenant_id=TENANT,
            site_id=SITE,
            environment_id=ENV,
            actor_name="a",
            actor_key="a",
        )
        assert result["policy_version"] == 3
        assert "ON CONFLICT (environment_id) DO NOTHING" in conn.statements[1][0]

    def test_a_policy_that_cannot_be_read_after_insert_raises(self) -> None:
        db, _ = db_with(None, None, None)
        with pytest.raises(SlateInsightStoreError) as excinfo:
            ensure_policy(
                db,
                tenant_id=TENANT,
                site_id=SITE,
                environment_id=ENV,
                actor_name="a",
                actor_key="a",
            )
        assert excinfo.value.code == "policy_not_found"

    def test_creating_a_policy_writes_edge_attached_as_a_literal_false(self) -> None:
        db, conn = db_with(None, policy_row())
        ensure_policy(
            db,
            tenant_id=TENANT,
            site_id=SITE,
            environment_id=ENV,
            actor_name="a",
            actor_key="a",
        )
        query, params = conn.statements[1]
        assert "FALSE" in query
        assert False not in params

    def test_a_policy_write_never_names_edge_attached(self) -> None:
        """It is not an operator setting but a statement about whether a collector exists."""
        db, conn = db_with(policy_row())
        update_policy(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            policy=policy_values(),
            actor_name="a",
            actor_key="a",
        )
        assert "edge_attached" not in conn.statements[0][0]

    def test_a_policy_write_carries_every_retention_column(self) -> None:
        db, conn = db_with(policy_row())
        update_policy(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            policy=policy_values(),
            actor_name="a",
            actor_key="a",
        )
        query, params = conn.statements[0]
        for column in (
            "metric_retention_days",
            "log_retention_days",
            "trace_retention_days",
            "privacy_threshold",
            "retention_waiver_reason",
        ):
            assert column in query
        assert 60 in params and 21 in params and 5 in params

    def test_a_policy_write_on_a_lane_with_no_row_raises(self) -> None:
        db, conn = db_with(None)
        with pytest.raises(SlateInsightStoreError) as excinfo:
            update_policy(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                policy=policy_values(),
                actor_name="a",
                actor_key="a",
            )
        assert excinfo.value.code == "policy_not_found"
        assert conn.commits == 1, "the statement itself succeeded; it simply matched nothing"

    def test_a_policy_write_is_scoped_to_the_tenant_as_well_as_the_lane(self) -> None:
        db, conn = db_with(policy_row())
        update_policy(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            policy=policy_values(),
            actor_name="a",
            actor_key="a",
        )
        query, params = conn.statements[0]
        assert "WHERE tenant_id = %s::uuid AND environment_id = %s::uuid" in query
        assert TENANT in params


class TestOptimisticConcurrency:
    """Two operators changing retention during one incident is the normal case."""

    def test_the_version_bump_is_a_conditional_update(self) -> None:
        db, conn = db_with({"policy_version": 4})
        assert bump_policy_version(db, environment_id=ENV, expected_policy_version=3) == 4
        query, params = conn.statements[0]
        assert "policy_version = policy_version + 1" in query
        assert "WHERE environment_id = %s::uuid AND policy_version = %s" in query
        assert 3 in params

    def test_a_successful_bump_commits(self) -> None:
        db, conn = db_with({"policy_version": 4})
        bump_policy_version(db, environment_id=ENV, expected_policy_version=3)
        assert conn.commits == 1
        assert conn.rollbacks == 0

    def test_a_stale_expected_version_raises_rather_than_overwriting(self) -> None:
        db, conn = db_with(None, {"policy_version": 9})
        with pytest.raises(SlateInsightPolicyConflictError) as excinfo:
            bump_policy_version(db, environment_id=ENV, expected_policy_version=3)
        assert excinfo.value.expected_policy_version == 3
        assert excinfo.value.actual_policy_version == 9
        assert excinfo.value.environment_id == ENV

    def test_a_refused_edit_rolls_back_and_leaves_nothing_behind(self) -> None:
        db, conn = db_with(None, {"policy_version": 9})
        with pytest.raises(SlateInsightPolicyConflictError):
            bump_policy_version(db, environment_id=ENV, expected_policy_version=3)
        assert conn.rollbacks == 1
        assert conn.commits == 0

    def test_a_conflict_on_a_lane_with_no_policy_reports_no_actual_version(self) -> None:
        db, _ = db_with(None, None)
        with pytest.raises(SlateInsightPolicyConflictError) as excinfo:
            bump_policy_version(db, environment_id=ENV, expected_policy_version=1)
        assert excinfo.value.actual_policy_version is None

    def test_the_conflict_sentence_tells_the_operator_to_re_read(self) -> None:
        db, _ = db_with(None, {"policy_version": 9})
        with pytest.raises(SlateInsightPolicyConflictError) as excinfo:
            bump_policy_version(db, environment_id=ENV, expected_policy_version=3)
        message = str(excinfo.value)
        assert "expected version 3" in message
        assert "found 9" in message

    def test_a_failing_bump_rolls_back(self) -> None:
        db, conn = exploding_db()
        with pytest.raises(RuntimeError):
            bump_policy_version(db, environment_id=ENV, expected_policy_version=3)
        assert conn.rollbacks == 1
        assert conn.commits == 0


class TestRedactionHappensInTheStore:
    """A redaction the caller could skip is a redaction that will eventually be skipped."""

    def test_a_cookie_in_log_evidence_never_reaches_the_parameters(self) -> None:
        db, conn = db_with({"id": "log-1"})
        record_log(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            level="error",
            source="request",
            message="Checkout failed",
            evidence={"cookie": "session=abc", "path": "/checkout"},
        )
        encoded = next(
            p for p in conn.statements[0][1] if isinstance(p, str) and p.startswith("{")
        )
        assert "session=abc" not in encoded
        assert "cookie" not in encoded
        assert "/checkout" in encoded

    def test_an_authorization_header_in_log_evidence_never_reaches_the_parameters(self) -> None:
        db, conn = db_with({"id": "log-1"})
        record_log(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            level="error",
            source="security",
            message="Blocked",
            evidence={"authorization": "Bearer abc", "outcome": "blocked"},
        )
        encoded = next(
            p for p in conn.statements[0][1] if isinstance(p, str) and p.startswith("{")
        )
        assert "Bearer" not in encoded
        assert "authorization" not in encoded
        assert "blocked" in encoded

    def test_every_allowed_log_key_survives(self) -> None:
        db, conn = db_with({"id": "log-1"})
        record_log(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            level="info",
            source="cache",
            message="Hit",
            evidence={key: "x" for key in EVIDENCE_KEYS},
        )
        encoded = next(
            p for p in conn.statements[0][1] if isinstance(p, str) and p.startswith("{")
        )
        for key in EVIDENCE_KEYS:
            assert key in encoded

    def test_a_cookie_in_a_span_attribute_never_reaches_the_parameters(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=142,
            route="/checkout",
            spans=[
                {
                    "span_id": "b" * 16,
                    "name": "origin-fetch",
                    "component": "origin",
                    "start_offset_ms": 4,
                    "duration_ms": 90,
                    "attributes": {"cookie": "session=abc", "route": "/checkout"},
                }
            ],
        )
        span_statement = next(
            s for s in conn.statements if "slate_insight_trace_spans" in s[0]
        )
        encoded = next(
            p for p in span_statement[1] if isinstance(p, str) and p.startswith("{")
        )
        assert "session=abc" not in encoded
        assert "cookie" not in encoded
        assert "/checkout" in encoded

    def test_a_span_attribute_outside_the_span_allowlist_is_dropped(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=10,
            route="/x",
            spans=[
                {
                    "span_id": "b" * 16,
                    "name": "n",
                    "component": "origin",
                    "attributes": {"durationMs": "90", "route": "/x"},
                }
            ],
        )
        span_statement = next(
            s for s in conn.statements if "slate_insight_trace_spans" in s[0]
        )
        encoded = next(
            p for p in span_statement[1] if isinstance(p, str) and p.startswith("{")
        )
        assert "durationMs" not in encoded, "the span allowlist is narrower than the log one"
        assert "route" in encoded

    def test_the_span_allowlist_is_the_shared_one_rather_than_a_local_copy(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=10,
            route="/x",
            spans=[
                {
                    "span_id": "b" * 16,
                    "name": "n",
                    "component": "origin",
                    "attributes": {key: "x" for key in SPAN_ATTRIBUTE_KEYS},
                }
            ],
        )
        span_statement = next(
            s for s in conn.statements if "slate_insight_trace_spans" in s[0]
        )
        encoded = next(
            p for p in span_statement[1] if isinstance(p, str) and p.startswith("{")
        )
        for key in SPAN_ATTRIBUTE_KEYS:
            assert key in encoded

    def test_a_span_with_no_attributes_writes_an_empty_object(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=10,
            route="/x",
            spans=[{"span_id": "b" * 16, "name": "n", "component": "origin"}],
        )
        span_statement = next(
            s for s in conn.statements if "slate_insight_trace_spans" in s[0]
        )
        assert "{}" in span_statement[1]


class TestTraceAndSpansAreOneTransaction:
    """A trace whose spans failed to land renders as a fast request rather than as missing data."""

    def test_the_trace_and_every_span_are_written_before_a_single_commit(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=142,
            route="/checkout",
            spans=[
                {"span_id": "b" * 16, "name": "edge", "component": "request"},
                {"span_id": "c" * 16, "name": "origin", "component": "origin"},
            ],
        )
        kinds = [s[0] for s in conn.statements]
        assert "INSERT INTO apiome.slate_insight_traces" in kinds[0]
        assert sum("slate_insight_trace_spans" in k for k in kinds) == 2
        assert conn.commits == 1
        assert conn.rollbacks == 0

    def test_a_failure_rolls_the_trace_and_its_spans_back_together(self) -> None:
        db, conn = exploding_db()
        with pytest.raises(RuntimeError):
            record_trace(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                trace_id=TRACE_ID,
                started_at=WINDOW_START,
                duration_ms=142,
                route="/checkout",
                spans=[{"span_id": "b" * 16, "name": "edge", "component": "request"}],
            )
        assert conn.rollbacks == 1
        assert conn.commits == 0

    def test_the_spans_reference_the_written_trace_row_rather_than_the_w3c_id(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=142,
            route="/checkout",
            spans=[{"span_id": "b" * 16, "name": "edge", "component": "request"}],
        )
        span_statement = next(
            s for s in conn.statements if "slate_insight_trace_spans" in s[0]
        )
        assert TRACE_ROW_ID in span_statement[1]

    def test_a_duplicate_trace_writes_no_spans_at_all(self) -> None:
        """ON CONFLICT DO NOTHING returned nothing, so there is no row for spans to hang from."""
        db, conn = db_with(None)
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=142,
            route="/checkout",
            spans=[{"span_id": "b" * 16, "name": "edge", "component": "request"}],
        )
        assert not any("slate_insight_trace_spans" in s[0] for s in conn.statements)
        assert "ON CONFLICT (environment_id, trace_id) DO NOTHING" in conn.statements[0][0]

    def test_a_duplicate_span_within_a_trace_is_ignored(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=1,
            route="/x",
            spans=[{"span_id": "b" * 16, "name": "edge", "component": "request"}],
        )
        span_statement = next(
            s for s in conn.statements if "slate_insight_trace_spans" in s[0]
        )
        assert "ON CONFLICT (trace_id, span_id) DO NOTHING" in span_statement[0]

    def test_a_negative_span_offset_is_floored(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=1,
            route="/x",
            spans=[
                {
                    "span_id": "b" * 16,
                    "name": "edge",
                    "component": "request",
                    "start_offset_ms": -4,
                    "duration_ms": -9,
                }
            ],
        )
        span_statement = next(
            s for s in conn.statements if "slate_insight_trace_spans" in s[0]
        )
        assert -4 not in span_statement[1]
        assert -9 not in span_statement[1]

    def test_a_span_defaults_to_an_ok_status(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=1,
            route="/x",
            spans=[{"span_id": "b" * 16, "name": "edge", "component": "request"}],
        )
        span_statement = next(
            s for s in conn.statements if "slate_insight_trace_spans" in s[0]
        )
        assert "ok" in span_statement[1]

    def test_a_trace_is_read_back_with_its_spans_in_waterfall_order(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID, "trace_id": TRACE_ID}, [{"name": "edge"}])
        result = get_trace(db, tenant_id=TENANT, environment_id=ENV, trace_id=TRACE_ID)
        assert result["trace"]["trace_id"] == TRACE_ID
        assert result["spans"] == [{"name": "edge"}]
        assert "ORDER BY start_offset_ms, name" in conn.statements[1][0]

    def test_reading_a_trace_that_does_not_exist_raises(self) -> None:
        db, _ = db_with(None)
        with pytest.raises(SlateInsightStoreError) as excinfo:
            get_trace(db, tenant_id=TENANT, environment_id=ENV, trace_id=TRACE_ID)
        assert excinfo.value.code == "trace_not_found"


class TestRetentionIsWritten:
    """Indefinite retention of request data is a liability rather than a feature."""

    def test_a_log_line_retains_for_the_policys_log_window(self, frozen_now: datetime) -> None:
        db, conn = db_with({"id": "log-1"})
        record_log(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            level="info",
            source="request",
            message="m",
            evidence={},
            policy=policy_row(log_retention_days=3),
        )
        moments = [p for p in conn.statements[0][1] if isinstance(p, datetime)]
        at, retain_until = moments
        assert retain_until - at == timedelta(days=3)

    def test_a_log_line_with_no_policy_falls_back_to_v190s_own_default(
        self, frozen_now: datetime
    ) -> None:
        db, conn = db_with({"id": "log-1"})
        record_log(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            level="info",
            source="request",
            message="m",
            evidence={},
        )
        moments = [p for p in conn.statements[0][1] if isinstance(p, datetime)]
        assert moments[1] - moments[0] == timedelta(days=14)

    def test_a_trace_retains_for_the_policys_trace_window(self, frozen_now: datetime) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=FROZEN_NOW,
            duration_ms=1,
            route="/x",
            policy=policy_row(trace_retention_days=2),
        )
        moments = [p for p in conn.statements[0][1] if isinstance(p, datetime)]
        assert moments[-1] - FROZEN_NOW == timedelta(days=2)

    def test_a_trace_with_no_policy_falls_back_to_seven_days(self, frozen_now: datetime) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=FROZEN_NOW,
            duration_ms=1,
            route="/x",
        )
        moments = [p for p in conn.statements[0][1] if isinstance(p, datetime)]
        assert moments[-1] - FROZEN_NOW == timedelta(days=7)

    def test_a_synthetic_result_retains_for_the_metric_window(self, frozen_now: datetime) -> None:
        db, conn = db_with({"id": "result-1"})
        record_synthetic_result(
            db,
            tenant_id=TENANT,
            check_id=CHECK_ID,
            environment_id=ENV,
            outcome="healthy",
            policy=policy_row(metric_retention_days=30),
        )
        moments = [p for p in conn.statements[0][1] if isinstance(p, datetime)]
        assert moments[1] - moments[0] == timedelta(days=30)

    def test_a_synthetic_result_with_no_policy_falls_back_to_ninety_days(
        self, frozen_now: datetime
    ) -> None:
        db, conn = db_with({"id": "result-1"})
        record_synthetic_result(
            db,
            tenant_id=TENANT,
            check_id=CHECK_ID,
            environment_id=ENV,
            outcome="healthy",
        )
        moments = [p for p in conn.statements[0][1] if isinstance(p, datetime)]
        assert moments[1] - moments[0] == timedelta(days=90)

    def test_a_tail_session_retains_for_the_log_window(self, frozen_now: datetime) -> None:
        db, conn = db_with({"id": SESSION})
        open_tail_session(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            session=session_values(),
            actor_name="a",
            actor_key="a",
            policy=policy_row(log_retention_days=9),
        )
        moments = [p for p in conn.statements[0][1] if isinstance(p, datetime)]
        assert moments[1] - moments[0] == timedelta(days=9)

    def test_every_request_data_insert_names_retain_until(self) -> None:
        db, conn = db_with({"id": "log-1"})
        record_log(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            level="info",
            source="request",
            message="m",
            evidence={},
        )
        assert "retain_until" in conn.statements[0][0]

        db, conn = db_with({"id": TRACE_ROW_ID})
        record_trace(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            trace_id=TRACE_ID,
            started_at=WINDOW_START,
            duration_ms=1,
            route="/x",
        )
        assert "retain_until" in conn.statements[0][0]

        db, conn = db_with({"id": "result-1"})
        record_synthetic_result(
            db, tenant_id=TENANT, check_id=CHECK_ID, environment_id=ENV, outcome="healthy"
        )
        assert "retain_until" in conn.statements[0][0]

        db, conn = db_with({"id": SESSION})
        open_tail_session(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            session=session_values(),
            actor_name="a",
            actor_key="a",
        )
        assert "retain_until" in conn.statements[0][0]

    def test_a_zero_retention_in_the_policy_is_ignored_in_favour_of_the_fallback(
        self, frozen_now: datetime
    ) -> None:
        """V190 forbids a non-positive window, so a corrupt policy must not produce one here."""
        db, conn = db_with({"id": "log-1"})
        record_log(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            level="info",
            source="request",
            message="m",
            evidence={},
            policy=policy_row(log_retention_days=0),
        )
        moments = [p for p in conn.statements[0][1] if isinstance(p, datetime)]
        assert moments[1] - moments[0] == timedelta(days=14)

    def test_a_boolean_masquerading_as_a_retention_is_ignored(self, frozen_now: datetime) -> None:
        db, conn = db_with({"id": "log-1"})
        record_log(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            level="info",
            source="request",
            message="m",
            evidence={},
            policy=policy_row(log_retention_days=True),
        )
        moments = [p for p in conn.statements[0][1] if isinstance(p, datetime)]
        assert moments[1] - moments[0] == timedelta(days=14)

    def test_the_audit_table_is_written_without_retention(self) -> None:
        """The record that a capture happened outlives the capture."""
        db, conn = db_with({"id": "audit-1"})
        append_audit(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            actor_name="ken@example.com",
            actor_key="user-1",
            subject_kind="live-tail",
            summary="Live tail opened",
        )
        assert "retain_until" not in conn.statements[0][0]


class TestWritesRollBackOnFailure:
    """Every write unwinds itself; none leaves half a change behind."""

    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(
                lambda db: record_metric_point(
                    db,
                    tenant_id=TENANT,
                    environment_id=ENV,
                    metric_family="request",
                    metric_key="p95_ms",
                    window_start=WINDOW_START,
                    window_end=WINDOW_END,
                    value=1.0,
                ),
                id="record_metric_point",
            ),
            pytest.param(
                lambda db: record_log(
                    db,
                    tenant_id=TENANT,
                    environment_id=ENV,
                    level="info",
                    source="request",
                    message="m",
                    evidence={},
                ),
                id="record_log",
            ),
            pytest.param(
                lambda db: record_synthetic_result(
                    db,
                    tenant_id=TENANT,
                    check_id=CHECK_ID,
                    environment_id=ENV,
                    outcome="healthy",
                ),
                id="record_synthetic_result",
            ),
            pytest.param(
                lambda db: record_usage(
                    db,
                    tenant_id=TENANT,
                    environment_id=ENV,
                    service="delivery",
                    usage_date=date(2026, 7, 19),
                    quantity=1.0,
                    unit="requests",
                    amount=1.0,
                ),
                id="record_usage",
            ),
            pytest.param(
                lambda db: record_budget_alert(
                    db, tenant_id=TENANT, environment_id=ENV, alert=alert_values()
                ),
                id="record_budget_alert",
            ),
            pytest.param(
                lambda db: open_tail_session(
                    db,
                    tenant_id=TENANT,
                    environment_id=ENV,
                    session=session_values(),
                    actor_name="a",
                    actor_key="a",
                ),
                id="open_tail_session",
            ),
            pytest.param(
                lambda db: close_tail_session(
                    db, tenant_id=TENANT, environment_id=ENV, session_id=SESSION
                ),
                id="close_tail_session",
            ),
            pytest.param(
                lambda db: upsert_export(
                    db,
                    tenant_id=TENANT,
                    environment_id=ENV,
                    export=export_values(),
                    actor_name="a",
                    actor_key="a",
                ),
                id="upsert_export",
            ),
            pytest.param(
                lambda db: delete_export(
                    db, tenant_id=TENANT, environment_id=ENV, export_id=EXPORT
                ),
                id="delete_export",
            ),
            pytest.param(
                lambda db: upsert_synthetic_check(
                    db,
                    tenant_id=TENANT,
                    environment_id=ENV,
                    check={"label": "Home"},
                    actor_name="a",
                    actor_key="a",
                ),
                id="upsert_synthetic_check",
            ),
            pytest.param(
                lambda db: delete_synthetic_check(
                    db, tenant_id=TENANT, environment_id=ENV, check_id=CHECK_ID
                ),
                id="delete_synthetic_check",
            ),
            pytest.param(
                lambda db: upsert_budget(
                    db,
                    tenant_id=TENANT,
                    environment_id=ENV,
                    budget=budget_values(),
                    actor_name="a",
                    actor_key="a",
                ),
                id="upsert_budget",
            ),
            pytest.param(
                lambda db: delete_budget(
                    db, tenant_id=TENANT, environment_id=ENV, budget_id=BUDGET
                ),
                id="delete_budget",
            ),
            pytest.param(
                lambda db: acknowledge_budget_alert(
                    db,
                    tenant_id=TENANT,
                    environment_id=ENV,
                    alert_id=ALERT,
                    actor_name="a",
                    actor_key="a",
                ),
                id="acknowledge_budget_alert",
            ),
            pytest.param(
                lambda db: upsert_residency_lane(
                    db,
                    tenant_id=TENANT,
                    environment_id=ENV,
                    lane=lane_values(),
                    actor_name="a",
                    actor_key="a",
                ),
                id="upsert_residency_lane",
            ),
            pytest.param(
                lambda db: ensure_residency_lanes(
                    db,
                    tenant_id=TENANT,
                    environment_id=ENV,
                    defaults=default_lanes(),
                    actor_name="a",
                    actor_key="a",
                ),
                id="ensure_residency_lanes",
            ),
            pytest.param(
                lambda db: update_policy(
                    db,
                    tenant_id=TENANT,
                    environment_id=ENV,
                    policy=policy_values(),
                    actor_name="a",
                    actor_key="a",
                ),
                id="update_policy",
            ),
            pytest.param(
                lambda db: append_audit(
                    db,
                    tenant_id=TENANT,
                    environment_id=ENV,
                    actor_name="a",
                    actor_key="a",
                    subject_kind="policy",
                    summary="s",
                ),
                id="append_audit",
            ),
        ],
    )
    def test_a_failing_write_rolls_back_and_never_commits(self, call: Any) -> None:
        db, conn = exploding_db()
        with pytest.raises(RuntimeError):
            call(db)
        assert conn.rollbacks == 1
        assert conn.commits == 0

    def test_a_failing_policy_creation_rolls_back(self) -> None:
        """The read that precedes it is not in the transaction; the INSERT that follows it is."""
        conn = ExplodingConnection([None], fail_after=1)
        db = FakeDb(conn)
        with pytest.raises(RuntimeError):
            ensure_policy(
                db,
                tenant_id=TENANT,
                site_id=SITE,
                environment_id=ENV,
                actor_name="a",
                actor_key="a",
            )
        assert conn.rollbacks == 1
        assert conn.commits == 0


class TestSyntheticChecks:
    """The stored check is what a modelled result is computed against."""

    def test_a_check_write_carries_every_column_the_surface_shows(self) -> None:
        db, conn = db_with({"id": CHECK_ID})
        upsert_synthetic_check(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            check={
                "label": "Home",
                "target_path": "/",
                "method": "GET",
                "regions": ["eu-west"],
                "interval_seconds": 60,
                "expected_status": 200,
                "latency_budget_ms": 800,
                "enabled": True,
            },
            actor_name="a",
            actor_key="a",
        )
        query, params = conn.statements[0]
        for column in (
            "target_path",
            "regions",
            "interval_seconds",
            "expected_status",
            "latency_budget_ms",
        ):
            assert column in query
        assert 800 in params

    def test_a_check_defaults_to_disabled(self) -> None:
        """Enabling a probe is an operator decision, not a side effect of creating one."""
        db, conn = db_with({"id": CHECK_ID})
        upsert_synthetic_check(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            check={"label": "Home"},
            actor_name="a",
            actor_key="a",
        )
        assert False in conn.statements[0][1]

    def test_a_check_that_cannot_be_written_raises(self) -> None:
        db, _ = db_with(None)
        with pytest.raises(SlateInsightStoreError) as excinfo:
            upsert_synthetic_check(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                check={"label": "Home"},
                actor_name="a",
                actor_key="a",
            )
        assert excinfo.value.code == "check_not_found"

    def test_deleting_a_check_that_is_not_there_raises(self) -> None:
        db, _ = db_with(None)
        with pytest.raises(SlateInsightStoreError) as excinfo:
            delete_synthetic_check(db, tenant_id=TENANT, environment_id=ENV, check_id=CHECK_ID)
        assert excinfo.value.code == "check_not_found"

    def test_checks_are_listed_by_label(self) -> None:
        db, conn = db_with([])
        list_synthetic_checks(db, tenant_id=TENANT, environment_id=ENV)
        assert "ORDER BY label" in conn.statements[0][0]


class TestBudgets:
    """A budget is a control; the alert it produces is a claim, and only the claim is a literal."""

    def test_a_budget_write_carries_its_thresholds_as_an_array(self) -> None:
        db, conn = db_with({"id": BUDGET})
        upsert_budget(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            budget=budget_values(),
            actor_name="a",
            actor_key="a",
        )
        query, params = conn.statements[0]
        assert "%s::numeric(4,3)[]" in query
        assert [0.5, 0.8] in params

    def test_a_budget_that_cannot_be_written_raises(self) -> None:
        db, _ = db_with(None)
        with pytest.raises(SlateInsightStoreError) as excinfo:
            upsert_budget(
                db,
                tenant_id=TENANT,
                environment_id=ENV,
                budget=budget_values(),
                actor_name="a",
                actor_key="a",
            )
        assert excinfo.value.code == "budget_not_found"

    def test_deleting_a_budget_that_is_not_there_raises(self) -> None:
        db, _ = db_with(None)
        with pytest.raises(SlateInsightStoreError) as excinfo:
            delete_budget(db, tenant_id=TENANT, environment_id=ENV, budget_id=BUDGET)
        assert excinfo.value.code == "budget_not_found"

    def test_budgets_are_listed_by_label(self) -> None:
        db, conn = db_with([])
        list_budgets(db, tenant_id=TENANT, environment_id=ENV)
        assert "ORDER BY label" in conn.statements[0][0]

    def test_a_budget_stores_a_channel_reference_rather_than_an_address(self) -> None:
        db, conn = db_with({"id": BUDGET})
        upsert_budget(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            budget=budget_values(),
            actor_name="a",
            actor_key="a",
        )
        query, params = conn.statements[0]
        assert "notify_channel_ref" in query
        assert "ops-alerts" in params


class TestFilterBuilders:
    """An optional filter that appears when it was not supplied silently narrows every read."""

    def test_metric_filters_are_absent_until_supplied(self) -> None:
        db, conn = db_with([])
        list_metric_series(db, tenant_id=TENANT, environment_id=ENV)
        query, params = conn.statements[0]
        for clause in (
            "metric_family = ANY",
            "release_id = %s::uuid",
            "region = %s",
            "window_start >= %s",
            "window_end <= %s",
        ):
            assert clause not in query
        assert len(params) == 3

    def test_every_metric_filter_appears_when_supplied(self) -> None:
        db, conn = db_with([])
        list_metric_series(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            families=["request", "cache"],
            release_id=RELEASE,
            region="eu-west",
            since=WINDOW_START,
            until=WINDOW_END,
        )
        query, params = conn.statements[0]
        assert "metric_family = ANY(%s::text[])" in query
        assert "release_id = %s::uuid" in query
        assert "region = %s" in query
        assert "window_start >= %s" in query
        assert "window_end <= %s" in query
        assert ["request", "cache"] in params
        assert "eu-west" in params

    def test_metric_series_are_ordered_oldest_first_within_a_series(self) -> None:
        db, conn = db_with([])
        list_metric_series(db, tenant_id=TENANT, environment_id=ENV)
        assert "ORDER BY metric_family, metric_key, window_start" in conn.statements[0][0]

    def test_the_metric_limit_is_clamped_at_both_ends(self) -> None:
        db, conn = db_with([], [])
        list_metric_series(db, tenant_id=TENANT, environment_id=ENV, limit=99999)
        assert conn.statements[0][1][-1] == 5000
        list_metric_series(db, tenant_id=TENANT, environment_id=ENV, limit=0)
        assert conn.statements[1][1][-1] == 1

    def test_log_filters_are_absent_until_supplied(self) -> None:
        db, conn = db_with([])
        list_logs(db, tenant_id=TENANT, environment_id=ENV)
        query, params = conn.statements[0]
        for column in ("level = ", "source = ", "release_id", "trace_ref", "ILIKE"):
            assert column not in query
        assert len(params) == 3

    def test_every_log_filter_appears_when_supplied(self) -> None:
        db, conn = db_with([])
        list_logs(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            levels=["error"],
            sources=["origin"],
            release_id=RELEASE,
            region="eu-west",
            trace_ref=TRACE_ROW_ID,
            query="timeout",
        )
        query, params = conn.statements[0]
        assert "level = ANY(%s::text[])" in query
        assert "source = ANY(%s::text[])" in query
        assert "release_id = %s::uuid" in query
        assert "region = %s" in query
        assert "trace_ref = %s::uuid" in query
        assert "message ILIKE %s" in query
        assert "%timeout%" in params

    def test_logs_are_newest_first_and_clamped(self) -> None:
        db, conn = db_with([])
        list_logs(db, tenant_id=TENANT, environment_id=ENV, limit=99999)
        query, params = conn.statements[0]
        assert "ORDER BY at DESC" in query
        assert params[-1] == 1000

    def test_trace_filters_are_absent_until_supplied(self) -> None:
        db, conn = db_with([])
        list_traces(db, tenant_id=TENANT, environment_id=ENV)
        query, params = conn.statements[0]
        for column in ("release_id", "route = ", "duration_ms >="):
            assert column not in query
        assert len(params) == 3

    def test_every_trace_filter_appears_when_supplied(self) -> None:
        db, conn = db_with([])
        list_traces(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            release_id=RELEASE,
            region="eu-west",
            route="/checkout",
            min_duration_ms=500,
        )
        query, params = conn.statements[0]
        assert "release_id = %s::uuid" in query
        assert "region = %s" in query
        assert "route = %s" in query
        assert "duration_ms >= %s" in query
        assert 500 in params

    def test_a_zero_minimum_duration_is_still_a_filter(self) -> None:
        """Falsy but supplied: ``is not None`` rather than truthiness is what distinguishes them."""
        db, conn = db_with([])
        list_traces(db, tenant_id=TENANT, environment_id=ENV, min_duration_ms=0)
        assert "duration_ms >= %s" in conn.statements[0][0]

    def test_traces_are_newest_first_and_clamped(self) -> None:
        db, conn = db_with([])
        list_traces(db, tenant_id=TENANT, environment_id=ENV, limit=99999)
        query, params = conn.statements[0]
        assert "ORDER BY started_at DESC" in query
        assert params[-1] == 500

    def test_usage_filters_are_absent_until_supplied(self) -> None:
        db, conn = db_with([])
        list_usage(db, tenant_id=TENANT, environment_id=ENV)
        query, params = conn.statements[0]
        for clause in (
            "service = ANY",
            "release_id = %s::uuid",
            "region = %s",
            "usage_date >= %s",
            "usage_date <= %s",
        ):
            assert clause not in query
        assert len(params) == 3

    def test_every_usage_filter_appears_when_supplied(self) -> None:
        db, conn = db_with([])
        list_usage(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            services=["delivery"],
            release_id=RELEASE,
            region="eu-west",
            since=date(2026, 7, 1),
            until=date(2026, 7, 31),
        )
        query, params = conn.statements[0]
        assert "service = ANY(%s::text[])" in query
        assert "release_id = %s::uuid" in query
        assert "region = %s" in query
        assert "usage_date >= %s" in query
        assert "usage_date <= %s" in query
        assert date(2026, 7, 31) in params

    def test_usage_is_oldest_first_so_a_period_reads_the_way_a_chart_draws_it(self) -> None:
        db, conn = db_with([])
        list_usage(db, tenant_id=TENANT, environment_id=ENV, limit=99999)
        query, params = conn.statements[0]
        assert "ORDER BY usage_date, service" in query
        assert params[-1] == 5000

    def test_budget_alert_filters_are_absent_until_supplied(self) -> None:
        db, conn = db_with([])
        list_budget_alerts(db, tenant_id=TENANT, environment_id=ENV)
        query, params = conn.statements[0]
        assert "budget_id" not in query
        assert "acknowledged_at" not in query
        assert len(params) == 3

    def test_budget_alerts_can_be_narrowed_to_one_budget_and_to_the_unacknowledged(self) -> None:
        db, conn = db_with([])
        list_budget_alerts(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            budget_id=BUDGET,
            unacknowledged_only=True,
        )
        query, params = conn.statements[0]
        assert "budget_id = %s::uuid" in query
        assert "acknowledged_at IS NULL" in query
        assert BUDGET in params
        assert len(params) == 4, "the acknowledgement filter takes no parameter"

    def test_budget_alerts_are_newest_first_and_clamped(self) -> None:
        db, conn = db_with([])
        list_budget_alerts(db, tenant_id=TENANT, environment_id=ENV, limit=99999)
        query, params = conn.statements[0]
        assert "ORDER BY at DESC" in query
        assert params[-1] == 500

    def test_synthetic_result_filters_are_absent_until_supplied(self) -> None:
        db, conn = db_with([])
        list_synthetic_results(db, tenant_id=TENANT, environment_id=ENV)
        query, params = conn.statements[0]
        assert "check_id" not in query
        assert "annotation_kind" not in query
        assert len(params) == 3

    def test_synthetic_results_can_be_narrowed_to_the_annotated(self) -> None:
        db, conn = db_with([])
        list_synthetic_results(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            check_id=CHECK_ID,
            release_id=RELEASE,
            annotated_only=True,
        )
        query, params = conn.statements[0]
        assert "check_id = %s::uuid" in query
        assert "release_id = %s::uuid" in query
        assert "annotation_kind IS NOT NULL" in query
        assert len(params) == 5

    def test_synthetic_results_are_newest_first_and_clamped(self) -> None:
        db, conn = db_with([])
        list_synthetic_results(db, tenant_id=TENANT, environment_id=ENV, limit=99999)
        query, params = conn.statements[0]
        assert "ORDER BY at DESC" in query
        assert params[-1] == 1000

    def test_the_audit_filter_is_absent_until_supplied(self) -> None:
        db, conn = db_with([])
        list_audit(db, tenant_id=TENANT, environment_id=ENV)
        query, params = conn.statements[0]
        assert "subject_kind" not in query
        assert len(params) == 3

    def test_the_audit_can_be_narrowed_to_one_subject_kind(self) -> None:
        db, conn = db_with([])
        list_audit(db, tenant_id=TENANT, environment_id=ENV, subject_kind="live-tail")
        query, params = conn.statements[0]
        assert "subject_kind = %s" in query
        assert "live-tail" in params

    def test_the_audit_trail_is_newest_first_and_clamped(self) -> None:
        db, conn = db_with([])
        list_audit(db, tenant_id=TENANT, environment_id=ENV, limit=99999)
        query, params = conn.statements[0]
        assert "ORDER BY at DESC" in query
        assert params[-1] == 1000


class TestTenantScoping:
    """A query that forgets tenant_id passes every single-tenant test and leaks in production."""

    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(lambda db: get_policy(db, tenant_id=TENANT, environment_id=ENV), id="policy"),
            pytest.param(
                lambda db: list_residency_lanes(db, tenant_id=TENANT, environment_id=ENV),
                id="residency",
            ),
            pytest.param(
                lambda db: list_metric_series(db, tenant_id=TENANT, environment_id=ENV),
                id="metrics",
            ),
            pytest.param(lambda db: list_logs(db, tenant_id=TENANT, environment_id=ENV), id="logs"),
            pytest.param(
                lambda db: list_traces(db, tenant_id=TENANT, environment_id=ENV), id="traces"
            ),
            pytest.param(
                lambda db: list_tail_sessions(db, tenant_id=TENANT, environment_id=ENV),
                id="tail",
            ),
            pytest.param(
                lambda db: list_exports(db, tenant_id=TENANT, environment_id=ENV), id="exports"
            ),
            pytest.param(
                lambda db: list_synthetic_checks(db, tenant_id=TENANT, environment_id=ENV),
                id="checks",
            ),
            pytest.param(
                lambda db: list_synthetic_results(db, tenant_id=TENANT, environment_id=ENV),
                id="results",
            ),
            pytest.param(lambda db: list_usage(db, tenant_id=TENANT, environment_id=ENV), id="usage"),
            pytest.param(
                lambda db: list_budgets(db, tenant_id=TENANT, environment_id=ENV), id="budgets"
            ),
            pytest.param(
                lambda db: list_budget_alerts(db, tenant_id=TENANT, environment_id=ENV),
                id="alerts",
            ),
            pytest.param(lambda db: list_audit(db, tenant_id=TENANT, environment_id=ENV), id="audit"),
        ],
    )
    def test_every_read_is_tenant_scoped(self, call: Any) -> None:
        db, conn = db_with([])
        call(db)
        query, params = conn.statements[0]
        assert "tenant_id = %s::uuid" in query
        assert TENANT in params

    def test_reading_one_trace_is_scoped_to_the_tenant_and_the_lane(self) -> None:
        db, conn = db_with({"id": TRACE_ROW_ID}, [])
        get_trace(db, tenant_id=TENANT, environment_id=ENV, trace_id=TRACE_ID)
        query, _ = conn.statements[0]
        assert "tenant_id = %s::uuid AND environment_id = %s::uuid" in query


class TestAudit:
    """The record that a live tail was opened outlives the capture it took."""

    def test_an_audit_entry_names_its_subject(self) -> None:
        db, conn = db_with({"id": "audit-1"})
        append_audit(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            actor_name="ken@example.com",
            actor_key="user-1",
            subject_kind="live-tail",
            subject_id=SESSION,
            summary="Live tail opened at 1% for 25 events/sec",
        )
        query, params = conn.statements[0]
        assert "INSERT INTO apiome.slate_insight_audit" in query
        assert "Live tail opened at 1% for 25 events/sec" in params
        assert SESSION in params
        assert conn.commits == 1

    def test_an_audit_entry_with_no_detail_writes_an_empty_object(self) -> None:
        db, conn = db_with({"id": "audit-1"})
        append_audit(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            actor_name="a",
            actor_key="a",
            subject_kind="policy",
            summary="Retention shortened",
        )
        assert "{}" in conn.statements[0][1]

    def test_audit_detail_is_serialized_rather_than_passed_as_a_mapping(self) -> None:
        db, conn = db_with({"id": "audit-1"})
        append_audit(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            actor_name="a",
            actor_key="a",
            subject_kind="policy",
            summary="Retention shortened",
            detail={"log_retention_days": 7},
        )
        encoded = next(
            p for p in conn.statements[0][1] if isinstance(p, str) and p.startswith("{")
        )
        assert '"log_retention_days": 7' in encoded

    def test_an_automation_can_be_an_actor(self) -> None:
        db, conn = db_with({"id": "audit-1"})
        append_audit(
            db,
            tenant_id=TENANT,
            environment_id=ENV,
            actor_name="budget-scheduler",
            actor_key="automation-1",
            subject_kind="budget-alert",
            summary="Threshold 80% reached",
            actor_kind="automation",
        )
        assert "automation" in conn.statements[0][1]
